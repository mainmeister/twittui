"""Show catalog registry exports, TWiT REST API pagination, archive scraping, and episode search."""

from __future__ import annotations

from datetime import datetime
import html
import re
import time
import urllib.parse

import requests

from tiered_search import compute_match_score, rank_and_filter_episodes
from twittui._compat import api_rate_limiter, compat_attr
from twittui.cache import (
    SHOW_DATE_BOUNDS_TTL_SECONDS,
    _shows_cache_key_hash,
    episode_cache_key,
)
from twittui.config import load_twittui_dotenv
from twittui.logging_config import get_logger
from twittui.shows import (
    DEFAULT_SHOWS,
    KNOWN_SHOW_FEEDS,
    MEMBERFUL_HOST_FEEDS,
    MEMBERFUL_SHOW_FEEDS,
    SHOW_REGISTRY,
    SHOW_SEARCH_SLUGS,
    TRANSCRIPT_SLUG_MAP,
    ShowEntry,
    get_show_entry,
)

_logger = get_logger("catalog")


class CatalogMixin:
    """TWiT REST API catalog, episode pagination, archive scraping, and search mixin."""

    def fetch_shows(self):
        """Fetch shows from the TWIT API and return a list of show names."""
        def set_status(message):
            if hasattr(self, 'api_status_label'):
                self.api_status_label.text = message

        try:
            compat_attr('load_twittui_dotenv', load_twittui_dotenv)()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()

            if not app_id or not app_key:
                _logger.info("API credentials not found in settings or .env file, using default shows")
                set_status('Shows API credentials missing; using fallback show list.')
                self.show_ids = {name: sid for name, sid in compat_attr('DEFAULT_SHOWS', DEFAULT_SHOWS)}
                self.show_active = {name: None for name in self.show_ids}
                self.show_date_bounds = {name: (None, None) for name in self.show_ids}
                return sorted(self.show_ids, key=str.casefold)

            cache_key = _shows_cache_key_hash(app_id, app_key)
            if getattr(self, '_shows_cache', None) is not None:
                cached_data = self._shows_cache.get(cache_key) if isinstance(self._shows_cache, dict) else None
                if cached_data is not None:
                    self.show_ids = dict(cached_data.get('show_ids', {}))
                    self.show_active = dict(cached_data.get('show_active', {}))
                    self.show_date_bounds = dict(cached_data.get('show_date_bounds', {}))
                    return list(cached_data.get('shows', []))

            headers = {
                'Accept': 'application/json',
                'app-id': app_id,
                'app-key': app_key
            }

            url = 'https://twit.tv/api/v1.0/shows?page=1&range=1000'
            visited = set()
            show_ids = {}
            show_active = {}
            show_date_bounds = {}
            while url:
                parsed = urllib.parse.urlsplit(url)
                query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                if (parsed.scheme != 'https' or parsed.netloc != 'twit.tv' or
                        parsed.path not in ('/api/v1.0/shows', '/api/v1.0/shows/') or
                        parsed.fragment or set(query) - {'page', 'range'} or
                        ('page' in query and (len(query['page']) != 1 or not query['page'][0].isdigit() or int(query['page'][0]) < 1)) or
                        ('range' in query and (len(query['range']) != 1 or not query['range'][0].isdigit() or int(query['range'][0]) < 1))):
                    raise ValueError('Invalid shows API page link')
                page = int(query['page'][0]) if 'page' in query else 1
                if page in visited:
                    raise ValueError('Repeated shows API page link')
                visited.add(page)
                response = api_rate_limiter.get(url, headers=headers, timeout=(10, 30))
                if response.status_code != 200:
                    set_status(f'Shows API failed (HTTP {response.status_code}); using fallback show list.')
                    self.show_ids = {name: sid for name, sid in compat_attr('DEFAULT_SHOWS', DEFAULT_SHOWS)}
                    self.show_active = {name: None for name in self.show_ids}
                    self.show_date_bounds = {name: (None, None) for name in self.show_ids}
                    return sorted(self.show_ids, key=str.casefold)
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get('shows'), list):
                    raise ValueError('Invalid shows API response')
                for show in data['shows']:
                    if isinstance(show, dict) and isinstance(show.get('label'), str) and show['label'].strip():
                        name = show['label']
                        show_ids[name] = show.get('id')
                        active = show.get('active')
                        show_active[name] = active if isinstance(active, bool) else None
                        created = show.get('created')
                        show_id_str = str(show.get('id')) if show.get('id') is not None else None
                        cached = self._show_date_cache.get(show_id_str) if (show_id_str and getattr(self, '_show_date_cache', None) is not None) else None
                        if cached and cached[1] is not None:
                            bounds = (created or cached[0], cached[1])
                        else:
                            bounds = (created, None)
                        show_date_bounds[name] = bounds
                        if show_id_str and getattr(self, '_show_date_cache', None) is not None:
                            self._show_date_cache[show_id_str] = bounds
                next_link = data.get('_links', {}).get('next')
                url = urllib.parse.urljoin(url, next_link['href']) if next_link else None

            if show_ids:
                if not any(name.strip().lower() == 'triangulation' for name in show_ids):
                    show_ids['Triangulation'] = None
                    show_active['Triangulation'] = None
                    show_date_bounds['Triangulation'] = (None, None)
                self.show_ids = show_ids
                self.show_active = show_active
                self.show_date_bounds = show_date_bounds
                if not hasattr(self, '_shows_cache') or not isinstance(self._shows_cache, dict):
                    self._shows_cache = {}
                cached_shows_obj = {
                    'shows': sorted(show_ids, key=str.casefold),
                    'show_ids': dict(show_ids),
                    'show_active': dict(show_active),
                    'show_date_bounds': dict(show_date_bounds),
                }
                self._shows_cache[cache_key] = cached_shows_obj
                self._save_to_persistent_cache('shows', cache_key, cached_shows_obj)
                set_status('')
                return sorted(show_ids, key=str.casefold)

            set_status('Shows API returned no usable shows; using fallback show list.')
            self.show_ids = {name: sid for name, sid in compat_attr('DEFAULT_SHOWS', DEFAULT_SHOWS)}
            self.show_active = {name: None for name in self.show_ids}
            self.show_date_bounds = {name: (None, None) for name in self.show_ids}
            return sorted(self.show_ids, key=str.casefold)
        except Exception as e:
            _logger.warning(f"Error fetching shows: {e}")
            set_status('Shows API request failed; using fallback show list.')
            self.show_ids = {name: sid for name, sid in compat_attr('DEFAULT_SHOWS', DEFAULT_SHOWS)}
            self.show_active = {name: None for name in self.show_ids}
            self.show_date_bounds = {name: (None, None) for name in self.show_ids}
            return sorted(self.show_ids, key=str.casefold)

    def fetch_show_date_bounds(self, show_id):
        """Fetch the earliest and latest episode dates from a show's public archive."""
        if not show_id:
            return None

        show_id_str = str(show_id)
        if getattr(self, '_show_date_cache', None) is not None and show_id_str in self._show_date_cache:
            cached_bounds = self._show_date_cache[show_id_str]
            ts_map = getattr(self, '_show_date_cache_ts', None)
            is_expired = (
                isinstance(ts_map, dict)
                and show_id_str in ts_map
                and (time.time() - float(ts_map[show_id_str])) > SHOW_DATE_BOUNDS_TTL_SECONDS
            )
            if is_expired:
                self._show_date_cache.pop(show_id_str, None)
                ts_map.pop(show_id_str, None)
            elif cached_bounds and cached_bounds[0] is not None and cached_bounds[1] is not None:
                return cached_bounds

        def page_dates(page_html):
            dates = []
            pattern = r'<a\s+href="/shows/[^\"]+/episodes/\d+(?:\?[^\"]*)?"[^>]*>(.*?)</a>'
            for content in re.findall(pattern, page_html, re.IGNORECASE | re.DOTALL):
                date_match = re.search(r'<span class="date">(.*?)</span>', content, re.IGNORECASE | re.DOTALL)
                if not date_match:
                    continue
                date_text = html.unescape(re.sub(r'<[^>]+>', '', date_match.group(1))).strip()
                try:
                    dates.append(datetime.strptime(date_text, '%b %d %Y').strftime('%Y-%m-%d'))
                except ValueError:
                    continue
            return dates

        try:
            params = {'filter[shows]': str(show_id), 'page': 1}
            response = requests.get('https://twit.tv/episodes', params=params, timeout=10)
            response.raise_for_status()
            page_match = re.search(r'class="page-number-input"[^>]*\bmax="(\d+)"', response.text)
            last_page = int(page_match.group(1)) if page_match else 1
            if last_page < 1:
                return None
            newest_dates = page_dates(response.text)
            if not newest_dates:
                return None
            oldest_dates = newest_dates
            if last_page > 1:
                oldest_params = {**params, 'page': last_page}
                response = requests.get('https://twit.tv/episodes', params=oldest_params, timeout=10)
                response.raise_for_status()
                oldest_dates = page_dates(response.text)
                if not oldest_dates:
                    return None
            result = (min(oldest_dates), max(newest_dates))
            if getattr(self, '_show_date_cache', None) is not None:
                self._show_date_cache[show_id_str] = result
            if isinstance(getattr(self, '_show_date_cache_ts', None), dict):
                self._show_date_cache_ts[show_id_str] = time.time()
            self._save_to_persistent_cache('show_date_bounds', show_id_str, result)
            return result
        except (requests.RequestException, ValueError, TypeError) as e:
            _logger.warning(f"Error fetching show archive dates: {e}")
            return None

    def test_api_credentials(self, app_id: str, app_key: str) -> tuple[bool, str]:
        """Validate TWiT API Application ID and Key against TWiT REST API."""
        app_id = (app_id or '').strip()
        app_key = (app_key or '').strip()

        if not app_id or not app_key:
            return False, "Failed: Missing API Application ID or Application Key.\nPlease enter both credentials before testing."

        headers = {
            'Accept': 'application/json',
            'app-id': app_id,
            'app-key': app_key,
            'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'
        }

        try:
            resp = api_rate_limiter.get('https://twit.tv/api/v1.0/shows?page=1&range=1', headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                show_count = 0
                if isinstance(data, dict):
                    raw_count = data.get('count')
                    if raw_count is not None and str(raw_count).isdigit():
                        show_count = int(raw_count)
                    elif isinstance(data.get('shows'), list):
                        show_count = len(data['shows'])
                return True, f"Passed: TWiT API credentials verified successfully!\nVerified access to {show_count} shows on the TWiT API."
            elif resp.status_code in (401, 403):
                return False, f"Failed: TWiT API authentication rejected (HTTP {resp.status_code}).\nPlease check that your Application ID and Key are correct."
            else:
                return False, f"Failed: TWiT API returned HTTP status {resp.status_code} ({resp.reason})."
        except requests.exceptions.Timeout:
            return False, "Failed: Connection to TWiT API timed out."
        except requests.exceptions.RequestException as e:
            return False, f"Failed: Network error communicating with TWiT API: {e}"
        except Exception as e:
            _logger.warning("Error testing TWiT API credentials: %s", e, exc_info=True)
            return False, f"Failed: Error testing TWiT API credentials: {e}"

    def _episode_cache_key(self, ep):
        return episode_cache_key(ep)

    def _parse_api_episodes(self, raw_episodes):
        episodes = []
        for episode in raw_episodes:
            if not isinstance(episode, dict):
                continue
            episode_info = dict(episode)
            title = episode.get('label') or episode.get('title')
            if title:
                episode_info['title'] = title
            date = episode.get('airingDate') or episode.get('publishDate')
            if date:
                episode_info['date'] = date
            number = episode.get('episodeNumber') or episode.get('number')
            if number is not None:
                episode_info['number'] = number

            length = self.extract_duration(episode)
            if length:
                episode_info['length'] = length
                episode_info['duration'] = length

            size_val = self.extract_size(episode)
            if size_val:
                episode_info['size'] = size_val
                episode_info['file_size'] = size_val
                episode_info['enclosure_length'] = size_val

            media_url = self.extract_media_url(episode)
            if media_url:
                episode_info['media_url'] = media_url

            transcript_url = episode.get('transcript_url') or episode.get('transcript') or ''
            if transcript_url:
                episode_info['transcript_url'] = transcript_url

            episodes.append(episode_info)
        return episodes

    def fetch_episode_detail(self, episode_id):
        """Fetch full details for a single episode ID."""
        if not hasattr(self, '_episode_detail_cache') or not isinstance(self._episode_detail_cache, dict):
            self._episode_detail_cache = {}
        ep_id_str = str(episode_id)
        if ep_id_str in self._episode_detail_cache:
            return self._episode_detail_cache[ep_id_str]
        try:
            compat_attr('load_twittui_dotenv', load_twittui_dotenv)()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()
            if not app_id or not app_key:
                return None
            headers = {
                'Accept': 'application/json',
                'app-id': app_id,
                'app-key': app_key
            }
            url = f'https://twit.tv/api/v1.0/episodes/{episode_id}'
            response = api_rate_limiter.get(url, headers=headers, timeout=8)
            if response.status_code == 200:
                data = response.json()
                detail = None
                if 'episodes' in data and isinstance(data['episodes'], list) and data['episodes']:
                    detail = data['episodes'][0]
                elif 'episode' in data and isinstance(data['episode'], dict):
                    detail = data['episode']
                elif isinstance(data, dict):
                    detail = data
                if detail:
                    self._episode_detail_cache[ep_id_str] = detail
                    self._save_to_persistent_cache('episode_detail', ep_id_str, detail)
                return detail
            return None
        except Exception as e:
            _logger.warning(f"Error fetching episode details: {e}")
            return None

    def fetch_triangulation_archive(self, page):
        """Fetch one chronological page from TWiT's public Triangulation archive."""
        if not hasattr(self, '_triangulation_archive_cache') or not isinstance(self._triangulation_archive_cache, dict):
            self._triangulation_archive_cache = {}
        page_key = (int(page or 1), bool(self.is_sort_ascending()))
        if page_key in self._triangulation_archive_cache:
            archive_data = self._triangulation_archive_cache[page_key]
            self._episodes_all_loaded = archive_data.get('all_loaded', False)
            return list(archive_data.get('episodes', []))

        try:
            params = {'filter[shows]': '1663', 'page': 1}
            response = requests.get('https://twit.tv/episodes', params=params, timeout=10)
            response.raise_for_status()
            match = re.search(r'class="page-number-input"[^>]*\bmax="(\d+)"', response.text)
            if not match:
                return None
            last_page = int(match.group(1))
            page = int(page or 1)
            if page < 1 or page > last_page:
                return []
            archive_page = last_page - page + 1 if self.is_sort_ascending() else page
            if archive_page != 1:
                params['page'] = archive_page
                response = requests.get('https://twit.tv/episodes', params=params, timeout=10)
                response.raise_for_status()
            pattern = r'<a\s+href="(/shows/triangulation/episodes/(\d+)(?:\?[^\"]*)?)"[^>]*>(.*?)</a>'
            episodes = []
            for path, number, content in re.findall(pattern, response.text, re.IGNORECASE | re.DOTALL):
                date_match = re.search(r'<span class="date">(.*?)</span>\s*-\s*(.*?)\s*<br', content, re.DOTALL)
                if not date_match:
                    continue
                date_text = html.unescape(date_match.group(1)).strip()
                try:
                    date_text = datetime.strptime(date_text, '%b %d %Y').strftime('%Y-%m-%d')
                except ValueError:
                    pass
                title = html.unescape(re.sub(r'<[^>]+>', '', date_match.group(2))).strip()
                episodes.append({'number': number, 'title': title, 'date': date_text,
                                 'cleanPath': path.split('?', 1)[0]})
            if not episodes:
                return None
            self._episodes_all_loaded = page >= last_page
            result = list(reversed(episodes)) if self.is_sort_ascending() else episodes
            self._triangulation_archive_cache[page_key] = {
                'episodes': list(result),
                'all_loaded': self._episodes_all_loaded
            }
            self._save_to_persistent_cache('triangulation_archive', f"{page_key[0]}|||{1 if page_key[1] else 0}", self._triangulation_archive_cache[page_key])
            return result
        except (requests.RequestException, ValueError, TypeError) as e:
            _logger.warning(f"Error fetching Triangulation archive: {e}")
            return None

    def fetch_episodes(self, show_id, page=1, sort=None):
        """Fetch episodes for a specific show ID, with fallback to Show and Club RSS feeds."""
        if not hasattr(self, '_episodes_cache') or not isinstance(self._episodes_cache, dict):
            self._episodes_cache = {}

        show_id_key = str(show_id) if show_id is not None else ''
        page_num = int(page or 1)
        page_size = 50

        if page_num > 1 and getattr(self, '_episodes_all_loaded', False) and show_id_key in self._episodes_cache:
            if hasattr(self._episodes_cache, 'get_page') and hasattr(self._episodes_cache, 'count_episodes'):
                total_cached = self._episodes_cache.count_episodes(show_id_key)
                if total_cached > 0:
                    page_slice = self._episodes_cache.get_page(
                        show_id_key, page=page_num, page_size=page_size
                    )
                    self._episodes_from_api = True
                    self._episodes_all_loaded = (not page_slice) or (page_num * page_size) >= total_cached
                    self._episode_api_status = ''
                    return page_slice
            else:
                cached_list = self._episodes_cache.get(show_id_key, [])
                if cached_list:
                    start_idx = (page_num - 1) * page_size
                    end_idx = page_num * page_size
                    if start_idx < len(cached_list):
                        self._episodes_from_api = True
                        self._episodes_all_loaded = end_idx >= len(cached_list)
                        self._episode_api_status = ''
                        return cached_list[start_idx:end_idx]
                    self._episodes_from_api = True
                    self._episodes_all_loaded = True
                    self._episode_api_status = ''
                    return []

        if page and int(page) > 1 and getattr(self, '_episodes_all_loaded', False):
            return []
        if not page or int(page) <= 1:
            self._episodes_from_api = False
            self._episodes_all_loaded = False
            self._episode_api_status = ''
        selected_show = self._selected_show_name()
        if not selected_show and hasattr(self, 'show_ids'):
            for name, sid in self.show_ids.items():
                if str(sid) == str(show_id):
                    selected_show = name
                    break

        try:
            compat_attr('load_twittui_dotenv', load_twittui_dotenv)()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()

            if app_id and app_key and show_id and (not page or int(page) <= 1 or getattr(self, '_episodes_from_api', False)):
                headers = {
                    'Accept': 'application/json',
                    'app-id': app_id,
                    'app-key': app_key
                }

                # Always fetch and cache canonical newest-first pages unless caller
                # explicitly passes a sort parameter; UI sort selections (Date/Number/
                # Title/Length/Size asc/desc) are applied client-side in memory so sort
                # changes never misalign cache order or trigger full archive re-scans.
                if sort is None:
                    sort = '-airingDate'

                page = int(page or 1)
                page_size = 50

                defer_first_page_reconciliation = (
                    page == 1 and getattr(self, '_defer_episodes_persist', False)
                )
                cached_list = (
                    [] if defer_first_page_reconciliation
                    else self._episodes_cache.get(show_id_key, [])
                )
                cached_keys = {self._episode_cache_key(e) for e in cached_list if self._episode_cache_key(e) is not None}

                if page > 1 and cached_list and getattr(self, '_episodes_all_loaded', False):
                    start_idx = (page - 1) * page_size
                    end_idx = page * page_size
                    if start_idx < len(cached_list):
                        self._episodes_from_api = True
                        self._episodes_all_loaded = end_idx >= len(cached_list)
                        self._episode_api_status = ''
                        return cached_list[start_idx:end_idx]
                    else:
                        self._episodes_from_api = True
                        self._episodes_all_loaded = True
                        self._episode_api_status = ''
                        return []

                url = f'https://twit.tv/api/v1.0/episodes?filter[shows]={show_id}&page={page}&range={page_size}'
                if sort:
                    url += f'&sort={sort}'
                response = api_rate_limiter.get(url, headers=headers, timeout=(10, 60))

                if response.status_code == 200:
                    data = response.json()
                    if not isinstance(data, dict) or not isinstance(data.get('episodes'), list):
                        raise ValueError('Invalid episodes API response')
                    count = data.get('count')
                    episodes = self._parse_api_episodes(data.get('episodes', []))

                    self._episodes_from_api = True
                    next_link = (data.get('_links') or {}).get('next')

                    if page == 1 and cached_list:
                        fetched_pages: set[int] = {1}
                        last_fetched_page = 1
                        hit_cache = False
                        new_items = []
                        tail_new_items = []
                        seen_new_keys: set = set()
                        for ep in episodes:
                            k = self._episode_cache_key(ep)
                            if k and k in cached_keys:
                                hit_cache = True
                                continue
                            if not k or k not in seen_new_keys:
                                if hit_cache:
                                    tail_new_items.append(ep)
                                else:
                                    new_items.append(ep)
                                if k:
                                    seen_new_keys.add(k)

                        if hit_cache:
                            merged = new_items + cached_list + tail_new_items
                        else:
                            accumulated = list(new_items)
                            tail_acc = list(tail_new_items)
                            curr_page = 2
                            while next_link and not hit_cache:
                                fetched_pages.add(curr_page)
                                last_fetched_page = curr_page
                                n_url = f'https://twit.tv/api/v1.0/episodes?filter[shows]={show_id}&page={curr_page}&range={page_size}'
                                if sort:
                                    n_url += f'&sort={sort}'
                                n_resp = api_rate_limiter.get(n_url, headers=headers, timeout=(10, 60))
                                if n_resp.status_code != 200:
                                    break
                                n_data = n_resp.json()
                                if not isinstance(n_data, dict) or not isinstance(n_data.get('episodes'), list):
                                    break
                                page_eps = self._parse_api_episodes(n_data.get('episodes', []))
                                for ep in page_eps:
                                    k = self._episode_cache_key(ep)
                                    if k and k in cached_keys:
                                        hit_cache = True
                                        continue
                                    if not k or k not in seen_new_keys:
                                        if hit_cache:
                                            tail_acc.append(ep)
                                        else:
                                            accumulated.append(ep)
                                        if k:
                                            seen_new_keys.add(k)
                                next_link = (n_data.get('_links') or {}).get('next')
                                curr_page += 1

                            merged = accumulated + cached_list + tail_acc

                        seen_keys = {self._episode_cache_key(e) for e in merged if self._episode_cache_key(e) is not None}
                        total_count = int(count) if str(count).isdigit() else None
                        total_pages = (total_count + page_size - 1) // page_size if total_count is not None else None

                        if total_count is not None and len(seen_keys) < total_count:
                            for p in range(2, total_pages + 1):
                                if len(seen_keys) >= total_count:
                                    break
                                if p in fetched_pages:
                                    continue
                                fetched_pages.add(p)
                                n_url = f'https://twit.tv/api/v1.0/episodes?filter[shows]={show_id}&page={p}&range={page_size}'
                                if sort:
                                    n_url += f'&sort={sort}'
                                n_resp = api_rate_limiter.get(n_url, headers=headers, timeout=(10, 60))
                                if n_resp.status_code != 200:
                                    break
                                n_data = n_resp.json()
                                if not isinstance(n_data, dict) or not isinstance(n_data.get('episodes'), list):
                                    break
                                page_eps = self._parse_api_episodes(n_data.get('episodes', []))
                                for ep in page_eps:
                                    k = self._episode_cache_key(ep)
                                    if not k or k not in seen_keys:
                                        merged.append(ep)
                                        if k:
                                            seen_keys.add(k)
                        elif total_count is None and next_link:
                            curr_page = max(2, last_fetched_page + 1)
                            while next_link:
                                if curr_page in fetched_pages:
                                    curr_page += 1
                                    continue
                                fetched_pages.add(curr_page)
                                n_url = f'https://twit.tv/api/v1.0/episodes?filter[shows]={show_id}&page={curr_page}&range={page_size}'
                                if sort:
                                    n_url += f'&sort={sort}'
                                n_resp = api_rate_limiter.get(n_url, headers=headers, timeout=(10, 60))
                                if n_resp.status_code != 200:
                                    break
                                n_data = n_resp.json()
                                if not isinstance(n_data, dict) or not isinstance(n_data.get('episodes'), list):
                                    break
                                page_eps = self._parse_api_episodes(n_data.get('episodes', []))
                                for ep in page_eps:
                                    k = self._episode_cache_key(ep)
                                    if not k or k not in seen_keys:
                                        merged.append(ep)
                                        if k:
                                            seen_keys.add(k)
                                next_link = (n_data.get('_links') or {}).get('next')
                                curr_page += 1

                        self._episodes_cache[show_id_key] = merged
                        if not getattr(self, '_defer_episodes_persist', False):
                            self._save_to_persistent_cache('episodes', show_id_key, merged)
                        self._episodes_all_loaded = (
                            len(seen_keys) >= total_count if total_count is not None
                            else not next_link
                        )
                        self._episode_api_status = ''
                        return merged
                    else:
                        if page == 1:
                            self._episodes_cache[show_id_key] = list(episodes)
                        else:
                            curr_cached = self._episodes_cache.setdefault(show_id_key, [])
                            seen_keys = {self._episode_cache_key(e) for e in curr_cached if self._episode_cache_key(e) is not None}
                            for ep in episodes:
                                k = self._episode_cache_key(ep)
                                if not k or k not in seen_keys:
                                    curr_cached.append(ep)
                                    if k:
                                        seen_keys.add(k)

                        if not getattr(self, '_defer_episodes_persist', False):
                            self._save_to_persistent_cache('episodes', show_id_key, self._episodes_cache[show_id_key])
                        self._episodes_all_loaded = not next_link and (
                            int(count) <= page * page_size if str(count).isdigit()
                            else len(episodes) < page_size
                        )
                        self._episode_api_status = ''
                        return episodes
                self._episode_api_status = f'Episodes API failed (HTTP {response.status_code}); RSS may not contain the full archive.'
        except Exception as e:
            _logger.warning(f"Error fetching episodes from API: {e}")
            self._episode_api_status = f'Episodes API failed ({e}); RSS may not contain the full archive.'

        if page and int(page) > 1 and getattr(self, '_episodes_from_api', False):
            return []

        if selected_show.strip().lower() == 'triangulation':
            if not page or int(page) <= 1:
                self._triangulation_rss_fallback = False
            if not getattr(self, '_triangulation_rss_fallback', False):
                archive = self.fetch_triangulation_archive(page)
                if archive is not None:
                    return archive
                if page and int(page) > 1:
                    return []
                self._triangulation_rss_fallback = True

        # Fallback 1: Fetch episodes from Show's public RSS feed on feeds.twit.tv
        if selected_show:
            rss_items = self.fetch_show_rss_items(selected_show, audio_only=self.is_audio_only())
            if rss_items:
                is_asc = self.is_sort_ascending()
                if is_asc:
                    rss_items = list(reversed(rss_items))

                page_items = rss_items

                episodes = []
                for item in page_items:
                    episodes.append({
                        'title': item.get('title', ''),
                        'number': item.get('number', ''),
                        'date': item.get('date', ''),
                        'length': item.get('length') or item.get('duration', ''),
                        'duration': item.get('duration') or item.get('length', ''),
                        'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                        'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                        'enclosure_length': item.get('enclosure_length', ''),
                        'media_url': item.get('enclosure_url', ''),
                        'cleanPath': item.get('link', ''),
                        'transcript_url': item.get('transcript_url', ''),
                        'description': item.get('description', ''),
                        'summary': item.get('summary', ''),
                        'guid': item.get('guid', ''),
                        'pubDate': item.get('pubDate', '')
                    })
                if episodes:
                    self._episodes_all_loaded = True
                    return episodes

        # Fallback 2: Fetch episodes from Club TWiT RSS feed
        club_items = self.fetch_club_twit_rss_items(selected_show, audio_only=self.is_audio_only())
        if club_items:
            matching_items = []
            for item in club_items:
                title = item.get('title', '')
                if not selected_show or selected_show.lower() in title.lower() or any(w.lower() in title.lower() for w in selected_show.split() if len(w) > 3):
                    matching_items.append(item)

            is_asc = self.is_sort_ascending()
            if is_asc:
                matching_items = list(reversed(matching_items))

            page_items = matching_items

            episodes = []
            for item in page_items:
                episodes.append({
                    'title': item.get('title', ''),
                    'number': item.get('number', ''),
                    'date': item.get('date', ''),
                    'length': item.get('length') or item.get('duration', ''),
                    'duration': item.get('duration') or item.get('length', ''),
                    'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                    'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                    'enclosure_length': item.get('enclosure_length', ''),
                    'media_url': item.get('enclosure_url', ''),
                    'cleanPath': item.get('link', ''),
                    'transcript_url': item.get('transcript_url', ''),
                    'description': item.get('description', ''),
                    'summary': item.get('summary', ''),
                    'guid': item.get('guid', ''),
                    'pubDate': item.get('pubDate', '')
                })
            if episodes:
                self._episodes_all_loaded = True
                return episodes

        return []

    def search_episodes(self, query: str, show_id: str = None, show_name: str = None) -> list:
        """Search for episodes matching keywords within the selected show across API and fallback RSS feeds."""
        if not query or not query.strip():
            return []

        query_str = query.strip()
        query_lower = query_str.lower()
        query_words = [w for w in re.split(r'\s+', query_lower) if w]

        selected_show = show_name or self._selected_show_name()
        if not selected_show and hasattr(self, 'show_ids') and show_id:
            for name, sid in self.show_ids.items():
                if str(sid) == str(show_id):
                    selected_show = name
                    break

        is_all_shows = not selected_show or selected_show.lower().strip() == 'all twit.tv shows'
        results = []
        seen_keys = set()

        def add_result(ep):
            if not ep:
                return
            ep_id = ep.get('id')
            clean_path = ep.get('cleanPath')
            num = ep.get('number')
            title = ep.get('title')
            key = None
            if ep_id:
                key = f"id:{ep_id}"
            elif clean_path:
                key = f"path:{clean_path}"
            elif num or title:
                key = f"nt:{num}:{title}"

            if key and key in seen_keys:
                return
            if key:
                seen_keys.add(key)
            results.append(ep)

        # Show slug helpers for checking cleanPath or body
        slug_candidates = set()
        if selected_show:
            show_clean = selected_show.lower().strip()
            slug_candidates.add(re.sub(r'[^a-z0-9]+', '-', show_clean).strip('-'))
            slug_candidates.add(re.sub(r'[^a-z0-9]+', '', show_clean))
            # Known abbreviations and aliases (derived from unified SHOW_REGISTRY)
            if show_clean in SHOW_SEARCH_SLUGS:
                slug_candidates.update(SHOW_SEARCH_SLUGS[show_clean])

        def show_matches_cleanpath(cp: str, body: str = '') -> bool:
            if is_all_shows:
                return True
            if not cp and not body:
                return True
            cp_lower = (cp or '').lower()
            for cand in slug_candidates:
                if f"/shows/{cand}/" in cp_lower or f"/shows/{cand}" in cp_lower or f"/{cand}/" in cp_lower:
                    return True
            if selected_show and selected_show.lower() in (body or '').lower():
                return True
            return False

        # Load show RSS items to help enrich and match
        rss_items_map = {}
        show_rss_list = []
        if selected_show:
            try:
                show_rss_list = self.fetch_show_rss_items(selected_show, audio_only=self.is_audio_only())
                for r_item in (show_rss_list or []):
                    r_num = str(r_item.get('number', '')).strip()
                    if r_num:
                        rss_items_map[r_num] = r_item
                    r_title = r_item.get('title', '').strip().lower()
                    if r_title:
                        rss_items_map[r_title] = r_item
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.search_episodes', exc_info=True)

        # Tier 1: TWiT REST API Search Endpoint
        try:
            compat_attr('load_twittui_dotenv', load_twittui_dotenv)()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()

            if app_id and app_key:
                if not hasattr(self, '_api_search_cache') or not isinstance(self._api_search_cache, dict):
                    self._api_search_cache = {}
                search_cache_key = query_str.strip().lower()
                if search_cache_key in self._api_search_cache:
                    search_items = self._api_search_cache[search_cache_key]
                else:
                    headers = {
                        'Accept': 'application/json',
                        'app-id': app_id,
                        'app-key': app_key
                    }
                    encoded_query = urllib.parse.quote(query_str)
                    url = f'https://twit.tv/api/v1.0/search/{encoded_query}?range=1000000'
                    resp = api_rate_limiter.get(url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        search_items = data.get('search', [])
                        if isinstance(search_items, list):
                            self._api_search_cache[search_cache_key] = search_items
                            self._save_to_persistent_cache('api_search', search_cache_key, search_items)
                    else:
                        search_items = []

                if isinstance(search_items, list):
                    for item in search_items:
                        item_type = item.get('type')
                        if item_type and item_type != 'episode':
                            continue
                        clean_path = item.get('cleanPath', '')
                        body = item.get('body', '')
                        if not show_matches_cleanpath(clean_path, body):
                            continue

                        ep_id = item.get('id')
                        title = item.get('label') or item.get('title') or ''
                        ep_num = ''
                        if clean_path:
                            num_match = re.search(r'/episodes/(\d+)', clean_path)
                            if num_match:
                                ep_num = num_match.group(1)
                        if not ep_num and title:
                            num_match = re.search(r'\b(\d+)\b', title)
                            if num_match:
                                ep_num = num_match.group(1)

                        matched_rss = rss_items_map.get(str(ep_num).strip()) or rss_items_map.get(title.strip().lower())
                        date_val = matched_rss.get('date', '') if matched_rss else ''
                        dur_val = (matched_rss.get('length') or matched_rss.get('duration', '')) if matched_rss else ''
                        size_val = (matched_rss.get('size') or matched_rss.get('file_size') or matched_rss.get('enclosure_length', '')) if matched_rss else ''
                        media_url_val = matched_rss.get('enclosure_url', '') if matched_rss else ''

                        ep_info = {
                            'id': str(ep_id) if ep_id is not None else '',
                            'title': title,
                            'number': ep_num,
                            'cleanPath': clean_path,
                            'description': body,
                            'summary': body,
                            'date': date_val,
                            'length': dur_val,
                            'duration': dur_val,
                            'size': size_val,
                            'file_size': size_val,
                            'enclosure_length': size_val,
                            'media_url': media_url_val
                        }
                        add_result(ep_info)
        except Exception as e:
            _logger.warning(f"Error searching API: {e}")

        fuzzy_enabled = self.is_fuzzy_search_enabled()
        phonetic_enabled = self.is_phonetic_search_enabled()

        # Tier 2: Public Show RSS Feeds (feeds.twit.tv)
        if show_rss_list:
            try:
                for item in show_rss_list:
                    t = item.get('title', '')
                    d = item.get('description', '')
                    s = item.get('summary', '')
                    num = str(item.get('number', ''))
                    dur = str(item.get('length') or item.get('duration') or '')
                    sz = str(item.get('size') or item.get('file_size') or item.get('enclosure_length') or '')
                    combined = f"{t} {d} {s} {num} {dur} {sz}".lower()
                    if compute_match_score(query_str, combined, fuzzy_enabled=fuzzy_enabled, phonetic_enabled=phonetic_enabled) > 0.0:
                        ep = {
                            'title': t,
                            'number': num,
                            'date': item.get('date', ''),
                            'length': item.get('length') or item.get('duration', ''),
                            'duration': item.get('duration') or item.get('length', ''),
                            'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                            'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                            'enclosure_length': item.get('enclosure_length', ''),
                            'media_url': item.get('enclosure_url', ''),
                            'cleanPath': item.get('link', ''),
                            'description': d,
                            'summary': s,
                            'guid': item.get('guid', ''),
                            'pubDate': item.get('pubDate', '')
                        }
                        add_result(ep)
            except Exception as e:
                _logger.warning(f"Error searching show RSS: {e}")

        # Tier 3: Club TWiT RSS Feed
        try:
            club_items = self.fetch_club_twit_rss_items(selected_show, audio_only=self.is_audio_only())
            if club_items:
                for item in club_items:
                    t = item.get('title', '')
                    d = item.get('description', '')
                    s = item.get('summary', '')
                    num = str(item.get('number', ''))
                    dur = str(item.get('length') or item.get('duration') or '')
                    sz = str(item.get('size') or item.get('file_size') or item.get('enclosure_length') or '')
                    if not is_all_shows and selected_show:
                        if selected_show.lower() not in t.lower() and not any(w.lower() in t.lower() for w in selected_show.split() if len(w) > 3):
                            continue
                    combined = f"{t} {d} {s} {num} {dur} {sz}".lower()
                    if compute_match_score(query_str, combined, fuzzy_enabled=fuzzy_enabled, phonetic_enabled=phonetic_enabled) > 0.0:
                        ep = {
                            'title': t,
                            'number': num,
                            'date': item.get('date', ''),
                            'length': item.get('length') or item.get('duration', ''),
                            'duration': item.get('duration') or item.get('length', ''),
                            'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                            'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                            'enclosure_length': item.get('enclosure_length', ''),
                            'media_url': item.get('enclosure_url', ''),
                            'cleanPath': item.get('link', ''),
                            'description': d,
                            'summary': s,
                            'guid': item.get('guid', ''),
                            'pubDate': item.get('pubDate', '')
                        }
                        add_result(ep)
        except Exception as e:
            _logger.warning(f"Error searching Club TWiT RSS: {e}")

        # Tier 4: Search across currently loaded episodes if any
        if hasattr(self, 'current_episodes') and self.current_episodes:
            for ep in self.current_episodes:
                t = str(ep.get('title', ''))
                d = str(ep.get('description', ''))
                s = str(ep.get('summary', ''))
                num = str(ep.get('number', ''))
                dur = str(ep.get('length') or ep.get('duration') or ep.get('runningTime') or '')
                sz = str(ep.get('size') or ep.get('file_size') or ep.get('fileSize') or ep.get('enclosure_length') or '')
                combined = f"{t} {d} {s} {num} {dur} {sz}".lower()
                if compute_match_score(query_str, combined, fuzzy_enabled=fuzzy_enabled, phonetic_enabled=phonetic_enabled) > 0.0:
                    add_result(ep)

        # Tier 4b: Indexed SQLite FTS5 full-text search across persisted normalized episodes
        episodes_cache = getattr(self, '_episodes_cache', None)
        if episodes_cache is not None and hasattr(episodes_cache, 'search_fts'):
            try:
                target_show_id = None
                if not is_all_shows:
                    if show_id is not None and str(show_id).strip():
                        target_show_id = str(show_id).strip()
                    elif selected_show and hasattr(self, 'show_ids') and self.show_ids.get(selected_show):
                        target_show_id = str(self.show_ids[selected_show])
                fts_hits = episodes_cache.search_fts(query_str, show_id=target_show_id, limit=200)
                for ep in fts_hits:
                    add_result(ep)
            except Exception as e:
                _logger.debug("SQLite FTS5 cache search skipped: %s", e, exc_info=True)

        return rank_and_filter_episodes(results, query_str, fuzzy_enabled=fuzzy_enabled, phonetic_enabled=phonetic_enabled)
