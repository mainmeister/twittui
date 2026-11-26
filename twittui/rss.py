"""Public, Club TWiT, and Memberful RSS feed fetching and item matching."""

from __future__ import annotations

import email.utils
import html
import os
import re
import urllib.parse

import requests

from twittui._compat import quiet_print as print
from twittui.logging_config import get_logger
from twittui.media import is_safe_http_url, safe_xml_fromstring
from twittui.shows import KNOWN_SHOW_FEEDS, MEMBERFUL_HOST_FEEDS, MEMBERFUL_SHOW_FEEDS

_logger = get_logger("rss")


class RssMixin:
    """RSS/Atom and Memberful feed parser mixin for TwitTUIForm."""

    def fetch_memberful_feed_items(self, feed_id: int | str) -> list:
        """Fetch and cache items from a specific Memberful feed ID."""
        fid_str = str(feed_id)
        if fid_str in self._memberful_feeds_cache:
            return self._memberful_feeds_cache[fid_str]

        feed_url = self.get_club_twit_rss_url(feed_id)
        if not feed_url:
            return []

        try:
            resp = requests.get(feed_url, headers={'User-Agent': 'TwitTUI/1.0'}, timeout=10)
            if resp.status_code == 200:
                root = safe_xml_fromstring(resp.content)
                items = []
                for item in root.findall('.//item'):
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    guid_elem = item.find('guid')
                    enclosure_elem = item.find('enclosure')
                    pubdate_elem = item.find('pubDate')

                    duration_str = ''
                    dur_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}duration')
                    if dur_elem is None:
                        dur_elem = item.find('duration')
                    if dur_elem is None:
                        for elem in item:
                            if elem.tag.endswith('duration'):
                                dur_elem = elem
                                break
                    if dur_elem is not None and dur_elem.text:
                        duration_str = self.format_duration(dur_elem.text.strip())

                    desc_elem = item.find('description')
                    summary_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}summary')
                    if summary_elem is None:
                        summary_elem = item.find('summary')
                    desc_str = ''
                    if desc_elem is not None and desc_elem.text:
                        desc_str = desc_elem.text.strip()
                    elif summary_elem is not None and summary_elem.text:
                        desc_str = summary_elem.text.strip()

                    pub_str = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ''
                    date_str = ''
                    if pub_str:
                        try:
                            dt = email.utils.parsedate_to_datetime(pub_str)
                            date_str = dt.strftime('%Y-%m-%d')
                        except Exception:
                            date_str = pub_str[:10]

                    title_str = title_elem.text.strip() if title_elem is not None and title_elem.text else ''
                    num_match = re.search(r'\b(beta\d+|\d+)\b', title_str, re.IGNORECASE)
                    ep_num = num_match.group(1) if num_match else ''

                    enc_url = enclosure_elem.attrib.get('url', '').strip() if enclosure_elem is not None else ''
                    enc_len = enclosure_elem.attrib.get('length', '').strip() if enclosure_elem is not None else ''

                    transcript_url = ''
                    transcript_elem = item.find('{https://podcastindex.org/namespace/1.0}transcript')
                    if transcript_elem is None:
                        for elem in item:
                            if elem.tag.endswith('transcript'):
                                transcript_elem = elem
                                break
                    if transcript_elem is not None:
                        transcript_url = transcript_elem.attrib.get('url', '').strip() or (transcript_elem.text.strip() if transcript_elem.text else '')

                    item_data = {
                        'title': title_str,
                        'number': ep_num,
                        'date': date_str,
                        'length': duration_str,
                        'duration': duration_str,
                        'size': enc_len,
                        'file_size': enc_len,
                        'enclosure_length': enc_len,
                        'description': desc_str,
                        'summary': desc_str,
                        'link': link_elem.text.strip() if link_elem is not None and link_elem.text else '',
                        'guid': guid_elem.text.strip() if guid_elem is not None and guid_elem.text else '',
                        'pubDate': pub_str,
                        'enclosure_url': enc_url,
                        'transcript_url': transcript_url
                    }
                    if enc_url and self.is_valid_media_url(enc_url):
                        items.append(item_data)
                self._memberful_feeds_cache[fid_str] = items
                return items
        except Exception as e:
            print(f"Error fetching Memberful RSS feed {feed_id}: {e}")

        return []

    def fetch_club_twit_rss_items(self, show_name: str = None, audio_only: bool = None) -> list:
        """Fetch and cache episode items from the Club TWiT RSS feeds relevant to the show."""
        if audio_only is None:
            audio_only = self.is_audio_only()

        feed_ids_to_fetch = []
        if show_name:
            show_key = show_name.lower().strip()
            if show_key in MEMBERFUL_SHOW_FEEDS:
                show_fids = list(MEMBERFUL_SHOW_FEEDS[show_key])
                if audio_only:
                    show_fids.reverse()
                feed_ids_to_fetch.extend(show_fids)

        # Also include default network feed and host feeds
        configured_url = os.getenv('twitcluburl') or os.getenv('TWITCLUBURL') or os.getenv('TWIT_CLUB_URL') or ''
        default_fid = 9040 if audio_only else 9041
        if '/rss/' in configured_url:
            fid_match = re.search(r'/rss/(\d+)', configured_url)
            if fid_match:
                default_fid = int(fid_match.group(1))

        if default_fid not in feed_ids_to_fetch:
            feed_ids_to_fetch.append(default_fid)

        # Fetch and accumulate items
        all_items = []
        seen_urls = set()
        for fid in feed_ids_to_fetch:
            items = self.fetch_memberful_feed_items(fid)
            for it in items:
                enc = it.get('enclosure_url')
                if enc and enc not in seen_urls:
                    seen_urls.add(enc)
                    all_items.append(it)

        if not show_name:
            self._club_rss_cache = all_items

        return all_items

    def fetch_show_rss_items(self, show_name: str, audio_only: bool = None) -> list:
        """Fetch public RSS feed items for a given show name."""
        if not show_name:
            return []

        if audio_only is None:
            audio_only = self.is_audio_only()

        show_key = show_name.lower().strip()
        cache_key = f"{show_key}_audio" if audio_only else f"{show_key}_video"
        cache_lock = getattr(self, '_cache_lock', None)
        if cache_lock is not None:
            with cache_lock:
                if cache_key in self._show_rss_cache:
                    return list(self._show_rss_cache[cache_key])
        elif cache_key in self._show_rss_cache:
            return self._show_rss_cache[cache_key]

        feed_files = list(KNOWN_SHOW_FEEDS.get(show_key, []))
        if not feed_files:
            slug = re.sub(r'[^a-zA-Z0-9]+', '', show_key)
            feed_files = [f"{slug}.xml", f"{slug}_video_hd.xml"] if audio_only else [f"{slug}_video_hd.xml", f"{slug}.xml"]
        else:
            if audio_only:
                feed_files.reverse()

        items = []
        for feed_file in feed_files:
            try:
                url = f"https://feeds.twit.tv/{feed_file}"
                resp = requests.get(url, headers={'User-Agent': 'TwitTUI/1.0'}, timeout=8)
                if resp.status_code == 200:
                    root = safe_xml_fromstring(resp.content)
                    for item in root.findall('.//item'):
                        title_elem = item.find('title')
                        link_elem = item.find('link')
                        enclosure_elem = item.find('enclosure')
                        pubdate_elem = item.find('pubDate')

                        duration_str = ''
                        dur_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}duration')
                        if dur_elem is None:
                            dur_elem = item.find('duration')
                        if dur_elem is None:
                            for elem in item:
                                if elem.tag.endswith('duration'):
                                    dur_elem = elem
                                    break
                        if dur_elem is not None and dur_elem.text:
                            duration_str = self.format_duration(dur_elem.text.strip())

                        desc_elem = item.find('description')
                        summary_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}summary')
                        if summary_elem is None:
                            summary_elem = item.find('summary')
                        desc_str = ''
                        if desc_elem is not None and desc_elem.text:
                            desc_str = desc_elem.text.strip()
                        elif summary_elem is not None and summary_elem.text:
                            desc_str = summary_elem.text.strip()

                        pub_str = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ''
                        date_str = ''
                        if pub_str:
                            try:
                                dt = email.utils.parsedate_to_datetime(pub_str)
                                date_str = dt.strftime('%Y-%m-%d')
                            except Exception:
                                date_str = pub_str[:10]

                        title_str = title_elem.text.strip() if title_elem is not None and title_elem.text else ''
                        num_match = re.search(r'\b(\d+)\b', title_str)
                        ep_num = num_match.group(1) if num_match else ''

                        enc_url = enclosure_elem.attrib.get('url', '').strip() if enclosure_elem is not None else ''
                        enc_len = enclosure_elem.attrib.get('length', '').strip() if enclosure_elem is not None else ''

                        transcript_url = ''
                        transcript_elem = item.find('{https://podcastindex.org/namespace/1.0}transcript')
                        if transcript_elem is None:
                            for elem in item:
                                if elem.tag.endswith('transcript'):
                                    transcript_elem = elem
                                    break
                        if transcript_elem is not None:
                            transcript_url = transcript_elem.attrib.get('url', '').strip() or (transcript_elem.text.strip() if transcript_elem.text else '')

                        if enc_url and self.is_valid_media_url(enc_url):
                            items.append({
                                'title': title_str,
                                'number': ep_num,
                                'date': date_str,
                                'length': duration_str,
                                'duration': duration_str,
                                'size': enc_len,
                                'file_size': enc_len,
                                'enclosure_length': enc_len,
                                'description': desc_str,
                                'summary': desc_str,
                                'link': link_elem.text.strip() if link_elem is not None and link_elem.text else '',
                                'transcript_url': transcript_url,
                                'enclosure_url': enc_url,
                                'feed_file': feed_file,
                            })
                    if items:
                        break
            except Exception as e:
                print(f"Error fetching show feed {feed_file}: {e}")

        if cache_lock is not None:
            with cache_lock:
                self._show_rss_cache[cache_key] = items
        else:
            self._show_rss_cache[cache_key] = items
        return items

    def fetch_media_from_webpage(self, clean_path_or_url: str, audio_only: bool = None) -> str | None:
        """Scrape direct media stream URL from episode webpage."""
        if not clean_path_or_url or not isinstance(clean_path_or_url, str):
            return None

        if audio_only is None:
            audio_only = self.is_audio_only()

        if not hasattr(self, '_media_webpage_cache') or not isinstance(self._media_webpage_cache, dict):
            self._media_webpage_cache = {}

        cache_key = (clean_path_or_url.strip(), bool(audio_only))
        if cache_key in self._media_webpage_cache:
            return self._media_webpage_cache[cache_key]

        clean_path = clean_path_or_url.strip()
        if clean_path.startswith('http://') or clean_path.startswith('https://'):
            url = clean_path
        else:
            url = f"https://twit.tv/{clean_path.lstrip('/')}"

        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}, timeout=8)
            if resp.status_code == 200:
                html = resp.text
                media_matches = re.findall(r'https?://[^\s\"\'<>]+\.(?:mp4|mp3|m4a|webm|ogg|m4v|aac)', html)
                res = None
                if audio_only:
                    for candidate in media_matches:
                        if self.is_valid_media_url(candidate) and self.is_audio_url(candidate):
                            res = candidate
                            break
                    if not res:
                        for candidate in media_matches:
                            if self.is_valid_media_url(candidate):
                                res = candidate
                                break
                else:
                    for candidate in media_matches:
                        if self.is_valid_media_url(candidate) and (candidate.endswith('.mp4') or 'video' in candidate or self.is_video_url(candidate)):
                            res = candidate
                            break
                    if not res:
                        for candidate in media_matches:
                            if self.is_valid_media_url(candidate):
                                res = candidate
                                break

                if not res:
                    yt_matches = re.findall(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[a-zA-Z0-9_-]+', html)
                    if yt_matches and not audio_only:
                        res = yt_matches[0]

                if res:
                    self._media_webpage_cache[cache_key] = res
                    self._save_to_persistent_cache('media_webpage', f"{clean_path_or_url.strip()}|||{1 if audio_only else 0}", res)
                return res
        except Exception as e:
            print(f"Error scraping episode webpage {url}: {e}")

        return None

    def _match_rss_item(self, item: dict, clean_path: str, ep_id: str, ep_num: str, ep_title: str, show: str) -> bool:
        """Helper to match an RSS item against episode identifiers."""
        enc_url = item.get('enclosure_url', '')
        if not enc_url or not self.is_valid_media_url(enc_url):
            return False

        item_link = item.get('link', '')
        item_title = item.get('title', '')

        # 1. Clean path matching
        if clean_path and item_link and clean_path in item_link:
            return True

        # 2. Episode ID in media URL
        if ep_id and (f"_{ep_id}-" in enc_url or f"_{ep_id}." in enc_url or f"_{ep_id}_" in enc_url or f"/{ep_id}/" in enc_url):
            return True

        # 3. Episode number matching (e.g. beta002, 1001, etc.)
        if ep_num:
            if re.search(r'\b' + re.escape(ep_num) + r'\b', item_title, re.IGNORECASE):
                if not show or show.lower() in item_title.lower() or any(w.lower() in item_title.lower() for w in show.split() if len(w) > 2):
                    return True
            if (f"_{ep_num.lower()}_" in enc_url.lower() or f"_{ep_num.lower()}-" in enc_url.lower() or f"_{ep_num.lower()}." in enc_url.lower()):
                return True

        # 4. Episode title matching
        if ep_title:
            clean_title = re.sub(r'^(?:AI Inside|TWiT\+?|Hands-On AI|[^:]+):\s*', '', ep_title, flags=re.I).strip()
            if len(clean_title) >= 4 and clean_title.lower() in item_title.lower():
                return True
            if len(ep_title) >= 4 and ep_title.lower() in item_title.lower():
                return True

        return False
