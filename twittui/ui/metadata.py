"""Episode metadata extraction, transcript links, details modal, and hover dwell controller."""

from __future__ import annotations

import html
import os
import re
import threading
import time

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from tiered_search import find_match_context
from twittui._compat import quiet_print as print
from twittui.logging_config import get_logger
from twittui.shows import TRANSCRIPT_SLUG_MAP

_logger = get_logger("ui.metadata")


class MetadataMixin:
    """Episode details dialog, transcript resolution, and hover preview mixin for TwitTUIForm."""

    @staticmethod
    def clean_html_text(text: str) -> str:
        """Strip HTML tags and unescape HTML entities into clean plain text."""
        if not text:
            return ''
        s = str(text)
        s = re.sub(r'<\s*br\s*/?>', '\n', s, flags=re.I)
        s = re.sub(r'</\s*p\s*>', '\n\n', s, flags=re.I)
        s = re.sub(r'</\s*li\s*>', '\n', s, flags=re.I)
        s = re.sub(r'<[^>]+>', '', s)
        s = html.unescape(s)
        s = re.sub(r'\n{3,}', '\n\n', s)
        return s.strip()

    def generate_transcript_slug_candidates(self, show_name: str, ep_num: str) -> list:
        """Generate candidate transcript URL slugs for a show and episode number."""
        if not show_name or not ep_num:
            return []
        s = str(show_name).lower().strip()
        s_clean = re.sub(r'[^a-z0-9\s-]', '', s)
        ep_clean = str(ep_num).strip().lstrip('#')

        show_variants = [
            s_clean.replace(' ', '-'),
        ]
        if s_clean.startswith('this week in '):
            show_variants.append(s_clean.replace('this week in ', 'week-').replace(' ', '-'))
        if s_clean.startswith('the '):
            show_variants.append(s_clean[4:].replace(' ', '-'))

        for k, v in TRANSCRIPT_SLUG_MAP.items():
            if k in s_clean:
                show_variants = list(v) + show_variants

        seen = set()
        unique_variants = []
        for var in show_variants:
            if var and var not in seen:
                seen.add(var)
                unique_variants.append(var)

        candidates = []
        for var in unique_variants:
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-{ep_clean}-transcript")
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-episode-{ep_clean}-transcript")
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-{ep_clean}")
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-episode-{ep_clean}")
        return candidates

    def resolve_transcript_url(self, target, show_name: str = '', *, allow_guess: bool = False) -> str:
        """Resolve or extract the transcript URL for an episode target."""
        if not target:
            return ''
        ep_data = {}
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            ep_data.update(target.episode_data)
        elif isinstance(target, dict):
            if 'episode_data' in target and isinstance(target['episode_data'], dict):
                ep_data.update(target['episode_data'])
            else:
                ep_data.update(target)

        # Collect show and episode identifiers
        show = show_name or getattr(target, 'show', '') or ep_data.get('show_name') or ep_data.get('show') or ''
        if not show:
            show = self._selected_show_name()
        if isinstance(show, dict):
            show = show.get('label') or show.get('title') or ''
        show_str = str(show).strip()
        ep_title = getattr(target, 'title', '') or ep_data.get('title') or ep_data.get('label') or ''
        ep_num = getattr(target, 'episode', '') or getattr(target, 'number', '') or ep_data.get('episode') or ep_data.get('number') or ep_data.get('episodeNumber') or ep_data.get('episode_number') or ''
        if not ep_num and ep_title:
            m_num = re.search(r'\b(?:episode|ep|twis|twit|twig|tnw|mbw|sn|ww|uls|iost)?\s*#?\s*(\d{1,5})\b', ep_title, re.IGNORECASE)
            if m_num:
                ep_num = m_num.group(1)
        if not ep_num and (ep_data.get('link') or ep_data.get('cleanPath')):
            m_link = re.search(r'/episodes/(\d+)', str(ep_data.get('link') or ep_data.get('cleanPath')))
            if m_link:
                ep_num = m_link.group(1)

        # 1. Direct field on target or ep_data (with sanity check against show name)
        t_url = (getattr(target, 'transcript_url', None) or getattr(target, 'transcript', None)
                 or ep_data.get('transcript_url') or ep_data.get('transcript')
                 or ep_data.get('podcast_transcript') or ep_data.get('transcriptUrl')
                 or ep_data.get('transcript_link') or '')
        if t_url:
            t_url = str(t_url).strip()
            if t_url:
                if not t_url.startswith('http://') and not t_url.startswith('https://'):
                    t_url = f"https://twit.tv/{t_url.lstrip('/')}"
                is_mismatch = False
                if show_str and ep_num:
                    s_lower = show_str.lower()
                    u_lower = t_url.lower()
                    if 'space' in s_lower and 'space' not in u_lower and ('tech-news' in u_lower or 'google' in u_lower or 'windows' in u_lower or 'twit' in u_lower):
                        is_mismatch = True
                    elif 'google' in s_lower and 'google' not in u_lower and ('space' in u_lower or 'tech-news' in u_lower):
                        is_mismatch = True
                    elif 'tech news weekly' in s_lower and 'tech-news' not in u_lower and ('space' in u_lower or 'google' in u_lower):
                        is_mismatch = True
                if not is_mismatch:
                    return t_url

        # 2. Check matched cached RSS items for THIS specific show
        show_key = show_str.lower().strip() if show_str else ''
        if show_key:
            matching_caches = []
            for k, v in getattr(self, '_show_rss_cache', {}).items():
                if show_key in k.lower() or k.lower().startswith(show_key):
                    matching_caches.append(v)
            for cache_items in matching_caches:
                for it in (cache_items or []):
                    match_num = ep_num and str(it.get('number', '')).strip() == str(ep_num).strip()
                    match_title = ep_title and str(it.get('title', '')).strip().lower() == str(ep_title).strip().lower()
                    if (match_num or match_title) and it.get('transcript_url'):
                        t_url = str(it['transcript_url']).strip()
                        if t_url:
                            if not t_url.startswith('http://') and not t_url.startswith('https://'):
                                t_url = f"https://twit.tv/{t_url.lstrip('/')}"
                            return t_url

        # Check general caches only when title matches or show name is in link/title
        for cache_items in [getattr(self, '_club_rss_cache', [])] + list(getattr(self, '_memberful_feeds_cache', {}).values()):
            for it in (cache_items or []):
                it_title = str(it.get('title', '')).strip().lower()
                it_link = str(it.get('link', '')).strip().lower()
                match_title = ep_title and ep_title.strip().lower() == it_title
                match_num = ep_num and str(it.get('number', '')).strip() == str(ep_num).strip()
                match_show = show_key and (show_key in it_title or show_key in it_link or (show_key.replace(' ', '-') in it_link))
                if ((match_title and (not show_key or match_show)) or (match_num and match_show)) and it.get('transcript_url'):
                    t_url = str(it['transcript_url']).strip()
                    if t_url:
                        if not t_url.startswith('http://') and not t_url.startswith('https://'):
                            t_url = f"https://twit.tv/{t_url.lstrip('/')}"
                        return t_url

        # 3. Optional canonical candidate transcript URL (only when explicitly requested,
        # avoiding unverified 404 URLs on older/non-transcribed shows)
        if allow_guess and show_str and ep_num:
            candidates = self.generate_transcript_slug_candidates(show_str, str(ep_num).strip())
            if candidates:
                return candidates[0]

        return ''

    def extract_episode_metadata_fields(self, target, show_name: str = '') -> dict:
        """Extract all structured metadata fields for an episode."""
        ep_data = {}
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            ep_data.update(target.episode_data)
        elif isinstance(target, dict):
            if 'episode_data' in target and isinstance(target['episode_data'], dict):
                ep_data.update(target['episode_data'])
            else:
                ep_data.update(target)

        # Collect show name
        show = show_name or getattr(target, 'show', '') or ep_data.get('show_name') or ep_data.get('show')
        if not show:
            show = self._selected_show_name()
        if isinstance(show, dict):
            show = show.get('label') or show.get('title') or ''

        ep_title = getattr(target, 'title', '') or ep_data.get('title') or ep_data.get('label') or ''

        # Collect episode number
        ep_num = getattr(target, 'episode', '') or getattr(target, 'number', '') or ep_data.get('episode') or ep_data.get('number') or ep_data.get('episodeNumber') or ep_data.get('episode_number') or ''
        if not ep_num and ep_title:
            m_num = re.search(r'\b(?:episode|ep|twis|twit|twig|tnw|mbw|sn|ww|uls|iost)?\s*#?\s*(\d{1,5})\b', ep_title, re.IGNORECASE)
            if m_num:
                ep_num = m_num.group(1)
        if not ep_num and (ep_data.get('link') or ep_data.get('cleanPath')):
            m_link = re.search(r'/episodes/(\d+)', str(ep_data.get('link') or ep_data.get('cleanPath')))
            if m_link:
                ep_num = m_link.group(1)

        # Collect date
        ep_date = getattr(target, 'date', '') or ep_data.get('date') or ep_data.get('airingDate') or ep_data.get('publishDate') or ep_data.get('pubDate') or ''

        # Collect duration / length
        ep_dur = getattr(target, 'length', '') or getattr(target, 'duration', '') or ep_data.get('length') or ep_data.get('duration') or ep_data.get('runningTime') or ''
        if ep_dur:
            ep_dur = self.format_duration(ep_dur)

        # Collect file size
        ep_size = getattr(target, 'size', '') or getattr(target, 'file_size', '') or ep_data.get('size') or ep_data.get('file_size') or ep_data.get('enclosure_length') or ''
        if not ep_size:
            ep_size = self.extract_size(ep_data) or ''
        ep_size_formatted = self.format_file_size(ep_size) if ep_size else ''

        # Collect ID / GUID / Node ID
        ep_id = ep_data.get('id') or ep_data.get('guid') or ep_data.get('node_id') or ''

        # Collect Web Link / CleanPath
        ep_link = ep_data.get('cleanPath') or ep_data.get('link') or ep_data.get('url') or ''
        if ep_link and not str(ep_link).startswith('http'):
            ep_link = f"https://twit.tv/{str(ep_link).lstrip('/')}"

        # Collect Transcript Link / URL
        transcript_url = self.resolve_transcript_url(target, show_name=show) or ''

        # Collect Media URL
        media_url = getattr(target, 'media_url', '') or ep_data.get('media_url') or ep_data.get('enclosure_url') or ''
        if not media_url:
            media_url = self.extract_media_url(ep_data) or ''

        # Available formats
        formats = []
        for fmt_key, fmt_label in [
            ('video_hd', 'HD Video (1080p/720p)'),
            ('video_large', 'Large Video'),
            ('video_small', 'Small/Mobile Video'),
            ('video_audio', 'Audio (MP3/M4A)'),
            ('audio', 'Audio'),
            ('video_youtube', 'YouTube Stream')
        ]:
            if fmt_key in ep_data and ep_data[fmt_key]:
                formats.append(fmt_label)

        # Hosts / Guests / People
        people_list = []
        for p_key in ['hosts', 'guests', 'people', 'staff']:
            val = ep_data.get(p_key)
            if isinstance(val, list):
                for p in val:
                    if isinstance(p, dict):
                        name = p.get('label') or p.get('name') or p.get('title')
                        if name:
                            people_list.append(str(name))
                    elif isinstance(p, str) and p.strip():
                        people_list.append(p.strip())
            elif isinstance(val, str) and val.strip():
                people_list.append(val.strip())

        # Topics / Categories / Tags
        topics_list = []
        for t_key in ['topics', 'tags', 'categories']:
            val = ep_data.get(t_key)
            if isinstance(val, list):
                for t in val:
                    if isinstance(t, dict):
                        name = t.get('label') or t.get('name') or t.get('title')
                        if name:
                            topics_list.append(str(name))
                    elif isinstance(t, str) and t.strip():
                        topics_list.append(t.strip())
            elif isinstance(val, str) and val.strip():
                topics_list.append(val.strip())

        # Description / Show notes (field precedence matches tiered_search.get_episode_fields())
        desc_raw = (
            ep_data.get('description')
            or ep_data.get('summary')
            or ep_data.get('body')
            or ep_data.get('show_notes')
            or ep_data.get('notes')
            or ep_data.get('teaser')
            or ep_data.get('snippet')
            or ''
        )
        desc_clean = self.clean_html_text(desc_raw)

        # Collect Search Match Context if present or if active search filter is applied
        match_ctx = None
        if hasattr(target, '_search_match_context') and getattr(target, '_search_match_context'):
            match_ctx = getattr(target, '_search_match_context')
        elif isinstance(target, dict) and target.get('_search_match_context'):
            match_ctx = target.get('_search_match_context')
        elif hasattr(target, 'match_context') and getattr(target, 'match_context'):
            match_ctx = getattr(target, 'match_context')
        elif isinstance(target, dict) and target.get('match_context'):
            match_ctx = target.get('match_context')
        elif 'episode_data' in ep_data and isinstance(ep_data['episode_data'], dict) and ep_data['episode_data'].get('_search_match_context'):
            match_ctx = ep_data['episode_data'].get('_search_match_context')
        elif hasattr(target, 'episode_data') and hasattr(target.episode_data, '_search_match_context') and getattr(target.episode_data, '_search_match_context'):
            match_ctx = getattr(target.episode_data, '_search_match_context')

        if not match_ctx and hasattr(self, 'search_input') and self.search_input and (self.search_input.value or '').strip():
            query = self.search_input.value.strip()
            fuzzy = self.is_fuzzy_search_enabled() if hasattr(self, 'is_fuzzy_search_enabled') else True
            phonetic = self.is_phonetic_search_enabled() if hasattr(self, 'is_phonetic_search_enabled') else True
            match_ctx = find_match_context(target, query, fuzzy_enabled=fuzzy, phonetic_enabled=phonetic)

        header_title = f"Episode Details: {ep_title}" if ep_title else "Episode Details"
        if len(header_title) > 60:
            header_title = header_title[:57] + "..."

        return {
            'header_title': header_title,
            'show': show,
            'episode': ep_num,
            'title': ep_title,
            'date': ep_date,
            'duration': ep_dur,
            'size': ep_size_formatted,
            'file_size': ep_size_formatted,
            'id': ep_id,
            'link': ep_link,
            'transcript_url': transcript_url,
            'transcript': transcript_url,
            'media_url': media_url,
            'formats': formats,
            'people': people_list,
            'topics': topics_list,
            'description': desc_clean,
            'match_context': match_ctx,
            '_search_match_context': match_ctx,
            'raw_data': ep_data
        }

    def format_episode_metadata(self, target, show_name: str = '', meta=None) -> tuple[str, str]:
        """Format all available metadata for an episode into a human-readable title and description."""
        if meta is None:
            meta = self.extract_episode_metadata_fields(target, show_name=show_name)
        show = meta['show']
        ep_num = meta['episode']
        ep_title = meta['title']
        ep_date = meta['date']
        ep_dur = meta['duration']
        ep_size = meta.get('size')
        ep_id = meta['id']
        ep_link = meta['link']
        transcript_url = meta.get('transcript_url') or meta.get('transcript') or ''
        media_url = meta['media_url']
        formats = meta['formats']
        people_list = meta['people']
        topics_list = meta['topics']
        desc_clean = meta['description']

        lines = []

        match_ctx = meta.get('match_context') or meta.get('_search_match_context')
        if match_ctx:
            f_name = getattr(match_ctx, 'field_name', '') or (match_ctx.get('field_name', '') if isinstance(match_ctx, dict) else '')
            m_tier = getattr(match_ctx, 'match_tier', '') or (match_ctx.get('match_tier', '') if isinstance(match_ctx, dict) else '')
            m_snip = getattr(match_ctx, 'snippet', '') or (match_ctx.get('snippet', '') if isinstance(match_ctx, dict) else '')
            if f_name or m_tier or m_snip:
                lines.append("[🔍 Search Match]")
                if f_name:
                    lines.append(f"• Field: {f_name}")
                if m_tier:
                    lines.append(f"• Match Type: {m_tier}")
                if m_snip:
                    lines.append(f"• Snippet: {m_snip}")
                lines.append("")

        if show:
            lines.append(f"Show: {show}")
        if ep_num and str(ep_num) != 'Unknown Number':
            lines.append(f"Episode: {ep_num}")
        if ep_title and str(ep_title) != 'Unknown Title':
            lines.append(f"Title: {ep_title}")
        if ep_date and str(ep_date) != 'Unknown Date':
            lines.append(f"Date: {ep_date}")
        if ep_dur:
            lines.append(f"Duration: {ep_dur}")
        if ep_size:
            lines.append(f"Size: {ep_size}")
        if ep_id:
            lines.append(f"ID / GUID: {ep_id}")
        if ep_link:
            lines.append(f"Web Link: {ep_link}")
        if transcript_url:
            lines.append(f"Transcript: {transcript_url}")
        if media_url:
            lines.append(f"Media URL: {media_url}")
        if formats:
            lines.append(f"Available Formats: {', '.join(formats)}")
        if people_list:
            lines.append(f"Hosts / Guests: {', '.join(people_list)}")
        if topics_list:
            lines.append(f"Topics: {', '.join(topics_list)}")

        if desc_clean:
            lines.append("")
            lines.append("Description / Show Notes:")
            lines.append(desc_clean)

        return meta['header_title'], "\n".join(lines)

    @staticmethod
    def _configure_metadata_link_rows(link_rows: list, content_box=None) -> None:
        """Size metadata link labels dynamically so they are never overwritten by adjacent URL fields."""
        if not link_rows:
            return

        measured_widths = []
        for lbl, btn in link_rows:
            lbl_impl = getattr(lbl, '_impl', None)
            lbl_mod = getattr(getattr(lbl_impl, '__class__', None), '__module__', '') if lbl_impl else ''
            is_textual = lbl_mod.startswith('toga_textual')

            if not is_textual and lbl_impl is not None:
                try:
                    if hasattr(lbl_impl, 'rehint'):
                        lbl_impl.rehint()
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_metadata_link_rows', exc_info=True)

                lbl_native = getattr(lbl_impl, 'native', None)
                if lbl_native is not None:
                    try:
                        if hasattr(lbl_native, 'get_preferred_width'):
                            min_w, nat_w = lbl_native.get_preferred_width()
                            if isinstance(min_w, (int, float)) and isinstance(nat_w, (int, float)):
                                measured_widths.append(int(max(min_w, nat_w)))
                        elif hasattr(lbl_native, 'get_preferred_size'):
                            min_sz, nat_sz = lbl_native.get_preferred_size()
                            w_min = getattr(min_sz, 'width', 0)
                            w_nat = getattr(nat_sz, 'width', 0)
                            if isinstance(w_min, (int, float)) and isinstance(w_nat, (int, float)):
                                measured_widths.append(int(max(w_min, w_nat)))
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_metadata_link_rows', exc_info=True)

                intrinsic = getattr(lbl, 'intrinsic', None)
                intrinsic_w = getattr(intrinsic, 'width', None) if intrinsic is not None else None
                iw_val = getattr(intrinsic_w, 'value', intrinsic_w)
                if isinstance(iw_val, (int, float)) and not isinstance(iw_val, bool) and iw_val > 0:
                    measured_widths.append(int(iw_val))

            btn_impl = getattr(btn, '_impl', None)
            btn_mod = getattr(getattr(btn_impl, '__class__', None), '__module__', '') if btn_impl else ''
            if btn_mod.startswith('toga_gtk'):
                try:
                    from toga_gtk.libs import Pango
                    btn_native = getattr(btn_impl, 'native', None)
                    btn_child = btn_native.get_child() if btn_native is not None and hasattr(btn_native, 'get_child') else None
                    if btn_child is not None:
                        if hasattr(btn_child, 'set_xalign'):
                            btn_child.set_xalign(0.0)
                        if hasattr(btn_child, 'set_ellipsize'):
                            btn_child.set_ellipsize(Pango.EllipsizeMode.END)
                    if hasattr(btn_impl, 'rehint'):
                        btn_impl.rehint()
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_metadata_link_rows', exc_info=True)

        if measured_widths:
            aligned_width = max(measured_widths) + 8
            for lbl, _btn in link_rows:
                lbl.style.width = aligned_width

        if content_box is not None:
            try:
                content_box.refresh()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_metadata_link_rows', exc_info=True)

    def show_episode_metadata_dialog(self, target) -> None:
        """Display a popup dialog/window with all metadata for the specified episode, featuring clickable Web and Media URLs."""
        if not target:
            return

        target = self._snapshot_episode(target)
        meta = self.extract_episode_metadata_fields(target)
        self._show_episode_metadata(target, meta)

    def _show_episode_metadata(self, target, meta):
        title, message = self.format_episode_metadata(target, meta=meta)
        if not message:
            message = "No metadata available for this episode."

        def _on_closed(window=None, result=None):
            self._dialog_open = False
            self._hover_row_index = None
            self._metadata_window = None
            return True

        def _close_meta_window(widget=None):
            try:
                if getattr(self, '_metadata_window', None) is not None:
                    self._metadata_window.close()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._show_episode_metadata._close_meta_window', exc_info=True)
            _on_closed()

        def _show():
            try:
                self._dialog_open = True
                self._cancel_hover_timer()

                # If an existing metadata window is open, close it first
                if getattr(self, '_metadata_window', None) is not None:
                    try:
                        self._metadata_window.close()
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm._show_episode_metadata._show', exc_info=True)
                    self._metadata_window = None

                # Check if running under Textual TUI backend
                native_app = getattr(getattr(self, '_impl', None), 'native', None)
                is_textual = (
                    (native_app and getattr(getattr(native_app, '__class__', None), '__module__', '').startswith('toga_textual'))
                    or os.environ.get('TOGA_BACKEND') in ('toga_textual', 'textual')
                )
                if is_textual:
                    if hasattr(self, 'main_window') and self.main_window:
                        self._present_window_dialog(self.main_window, "info", title, message, on_result=_on_closed)
                    return

                # Build rich custom dialog window with clickable URLs
                win_title = meta.get('header_title') or title or "Episode Details"
                win = toga.Window(title=win_title, size=(750, 650), on_close=_on_closed)
                self._metadata_window = win

                content_box = toga.Box(style=Pack(direction=COLUMN, margin=10))

                # Search Match Summary Callout Box
                match_ctx = meta.get('match_context') or meta.get('_search_match_context')
                if match_ctx:
                    f_name = getattr(match_ctx, 'field_name', '') or (match_ctx.get('field_name', '') if isinstance(match_ctx, dict) else '')
                    m_tier = getattr(match_ctx, 'match_tier', '') or (match_ctx.get('match_tier', '') if isinstance(match_ctx, dict) else '')
                    m_snip = getattr(match_ctx, 'snippet', '') or (match_ctx.get('snippet', '') if isinstance(match_ctx, dict) else '')
                    if f_name or m_tier or m_snip:
                        match_box = toga.Box(style=Pack(direction=COLUMN, margin_bottom=8))
                        match_box.add(toga.Label("🔍 Search Match", style=Pack(font_size=11, font_weight='bold', margin_bottom=3), tooltip='Search match summary'))
                        if f_name:
                            match_box.add(toga.Label(f"• Field: {f_name}", style=Pack(margin_bottom=2), tooltip=f'Matched in {f_name}'))
                        if m_tier:
                            match_box.add(toga.Label(f"• Match Type: {m_tier}", style=Pack(margin_bottom=2), tooltip=f'Match type: {m_tier}'))
                        if m_snip:
                            match_box.add(toga.Label(f"• Snippet: {m_snip}", style=Pack(margin_bottom=2), tooltip='Matching text excerpt'))
                        content_box.add(match_box)

                # Title
                ep_title = meta.get('title') or ''
                if ep_title:
                    content_box.add(toga.Label(ep_title, style=Pack(font_size=13, font_weight='bold', margin_bottom=6), tooltip='Episode title'))

                # Metadata Key-Values
                meta_rows = []
                if meta.get('show'):
                    meta_rows.append(f"Show: {meta['show']}")
                if meta.get('episode') and str(meta['episode']) != 'Unknown Number':
                    meta_rows.append(f"Episode: {meta['episode']}")
                if meta.get('date') and str(meta['date']) != 'Unknown Date':
                    meta_rows.append(f"Date: {meta['date']}")
                if meta.get('duration'):
                    meta_rows.append(f"Duration: {meta['duration']}")
                if meta.get('size'):
                    meta_rows.append(f"Size: {meta['size']}")
                if meta.get('id'):
                    meta_rows.append(f"ID / GUID: {meta['id']}")

                for row_text in meta_rows:
                    content_box.add(toga.Label(row_text, style=Pack(margin_bottom=3), tooltip=f'Metadata: {row_text}'))

                link_rows = []

                # Web Link (Clickable)
                ep_link = meta.get('link') or ''
                if ep_link:
                    link_box = toga.Box(style=Pack(direction=ROW, margin_top=4, margin_bottom=4, align_items='center'))
                    link_label = toga.Label("Web Link:", style=Pack(font_weight='bold', margin_right=8), tooltip='Episode webpage link')
                    link_box.add(link_label)
                    link_btn = toga.Button(
                        ep_link,
                        on_press=lambda w, u=ep_link: self.open_url_in_browser(u),
                        style=Pack(flex=1),
                        tooltip=f'Open episode webpage in browser: {ep_link}'
                    )
                    link_box.add(link_btn)
                    content_box.add(link_box)
                    link_rows.append((link_label, link_btn))

                # Transcript Link (Clickable)
                transcript_url = meta.get('transcript_url') or meta.get('transcript') or ''
                if transcript_url:
                    transcript_box = toga.Box(style=Pack(direction=ROW, margin_top=4, margin_bottom=4, align_items='center'))
                    transcript_label = toga.Label("Transcript:", style=Pack(font_weight='bold', margin_right=8), tooltip='Episode transcript link')
                    transcript_box.add(transcript_label)
                    transcript_btn = toga.Button(
                        transcript_url,
                        on_press=lambda w, u=transcript_url: self.open_url_in_browser(u),
                        style=Pack(flex=1),
                        tooltip=f'Open transcript in browser: {transcript_url}'
                    )
                    transcript_box.add(transcript_btn)
                    content_box.add(transcript_box)
                    link_rows.append((transcript_label, transcript_btn))

                # Media URL (Clickable)
                media_url = meta.get('media_url') or ''
                if media_url:
                    media_box = toga.Box(style=Pack(direction=ROW, margin_top=4, margin_bottom=4, align_items='center'))
                    media_label = toga.Label("Media URL:", style=Pack(font_weight='bold', margin_right=8), tooltip='Direct media stream link')
                    media_box.add(media_label)
                    media_btn = toga.Button(
                        media_url,
                        on_press=lambda w, u=media_url: self.open_url_in_browser(u),
                        style=Pack(flex=1),
                        tooltip=f'Open media stream in browser: {media_url}'
                    )
                    media_box.add(media_btn)
                    content_box.add(media_box)
                    link_rows.append((media_label, media_btn))

                # Available Formats
                if meta.get('formats'):
                    content_box.add(toga.Label(f"Available Formats: {', '.join(meta['formats'])}", style=Pack(margin_top=3, margin_bottom=3), tooltip='Available media formats for this episode'))

                # Hosts / Guests
                if meta.get('people'):
                    content_box.add(toga.Label(f"Hosts / Guests: {', '.join(meta['people'])}", style=Pack(margin_top=3, margin_bottom=3), tooltip='Hosts and guests appearing in this episode'))

                # Topics
                if meta.get('topics'):
                    content_box.add(toga.Label(f"Topics: {', '.join(meta['topics'])}", style=Pack(margin_top=3, margin_bottom=3), tooltip='Topics discussed in this episode'))

                # Description / Show notes
                desc_text = meta.get('description') or ''
                scroll_desc_callback = None
                if desc_text:
                    content_box.add(toga.Label("Description / Show Notes:", style=Pack(font_weight='bold', margin_top=6, margin_bottom=4), tooltip='Episode description and show notes'))
                    desc_input = toga.MultilineTextInput(
                        value=desc_text,
                        readonly=True,
                        style=Pack(flex=1, height=220, margin_bottom=6),
                        tooltip='Episode description and show notes'
                    )
                    content_box.add(desc_input)

                    if match_ctx:
                        f_name = getattr(match_ctx, 'field_name', '') or (match_ctx.get('field_name', '') if isinstance(match_ctx, dict) else '')
                        char_offset = getattr(match_ctx, 'char_offset', 0) or (match_ctx.get('char_offset', 0) if isinstance(match_ctx, dict) else 0)
                        try:
                            char_offset_int = int(char_offset or 0)
                        except (TypeError, ValueError):
                            char_offset_int = 0
                        if 'description' in str(f_name).lower() and char_offset_int > 0:
                            def _scroll_desc_to_match(target_input=desc_input, target_win=win, offset=char_offset_int) -> bool:
                                try:
                                    if getattr(self, '_metadata_window', None) is not target_win:
                                        return False
                                    impl = getattr(target_input, '_impl', None)
                                    if impl is None:
                                        return False
                                    # In toga-gtk 0.5.x, native is Gtk.ScrolledWindow and native_textview is Gtk.TextView
                                    textview = getattr(impl, 'native_textview', None)
                                    if textview is None:
                                        native = getattr(impl, 'native', None)
                                        if native is not None and hasattr(native, 'get_buffer'):
                                            textview = native
                                        elif native is not None and hasattr(native, 'get_child'):
                                            child = native.get_child()
                                            if child is not None and hasattr(child, 'get_buffer'):
                                                textview = child
                                    if textview is not None and hasattr(textview, 'get_buffer'):
                                        buf = textview.get_buffer()
                                        max_chars = buf.get_char_count() if hasattr(buf, 'get_char_count') else len(desc_text)
                                        clamped = max(0, min(offset, int(max_chars)))
                                        iter_pos = buf.get_iter_at_offset(clamped)
                                        buf.place_cursor(iter_pos)
                                        scrolled = textview.scroll_to_iter(iter_pos, 0.1, True, 0.0, 0.2)
                                        if scrolled is False and hasattr(textview, 'scroll_to_mark') and hasattr(buf, 'get_insert'):
                                            textview.scroll_to_mark(buf.get_insert(), 0.1, True, 0.0, 0.2)
                                except Exception:
                                    _logger.debug("Ignored exception in %s", 'TwitTUIForm._show_episode_metadata._show._scroll_desc_to_match', exc_info=True)
                                return False

                            scroll_desc_callback = _scroll_desc_to_match

                # Bottom Action Bar
                btn_box = toga.Box(style=Pack(direction=ROW, margin_top=6, align_items='center'))
                btn_box.add(toga.Box(style=Pack(flex=1)))
                close_btn = toga.Button('Close', on_press=_close_meta_window, style=Pack(width=100), tooltip='Close episode details window')
                btn_box.add(close_btn)
                content_box.add(btn_box)

                # Top-level window layout container
                win.content = content_box
                self._configure_metadata_link_rows(link_rows, content_box)
                win.show()
                if callable(scroll_desc_callback):
                    try:
                        from gi.repository import GLib
                        GLib.idle_add(scroll_desc_callback)
                    except Exception:
                        scroll_desc_callback()

            except Exception as e:
                print(f"Error displaying custom episode metadata window ({e}), falling back to info_dialog.")
                try:
                    if hasattr(self, 'main_window') and self.main_window:
                        self._present_window_dialog(self.main_window, "info", title, message, on_result=_on_closed)
                except Exception as inner_e:
                    print(f"Error displaying fallback info_dialog: {inner_e}")
                    _on_closed()

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(_show)
            except Exception:
                _show()
        else:
            _show()

    def _cancel_hover_timer_locked(self) -> None:
        """Cancel active hover timer while holding lock."""
        if getattr(self, '_hover_timer', None) is not None:
            try:
                self._hover_timer.cancel()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._cancel_hover_timer_locked', exc_info=True)
            self._hover_timer = None

    def _cancel_hover_timer(self) -> None:
        """Cancel active hover timer and clear hovered row index."""
        if not hasattr(self, '_hover_lock'):
            self._hover_lock = threading.Lock()
        with self._hover_lock:
            self._cancel_hover_timer_locked()
            self._hover_row_index = None
            self._hover_generation = getattr(self, '_hover_generation', 0) + 1

    def _trigger_hover_metadata(self, row_idx: int) -> None:
        """Triggered after 3 seconds of continuous hover over an episode row."""
        with self._hover_lock:
            if getattr(self, '_dialog_open', False):
                return
            if self._hover_row_index != row_idx:
                return
            self._hover_timer = None

        def _show():
            try:
                if not hasattr(self, 'episodes_list') or not self.episodes_list or not self.episodes_list.data:
                    return
                if row_idx < 0 or row_idx >= len(self.episodes_list.data):
                    return
                row_item = self.episodes_list.data[row_idx]
                self.show_episode_metadata_dialog(row_item)
            except Exception as e:
                print(f"Error displaying episode metadata dialog: {e}")

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(_show)
            except RuntimeError:
                pass
        else:
            _show()

    def _on_table_motion_notify(self, widget, event) -> bool:
        """Handle mouse motion over episodes table and track 3-second hover dwell time."""
        if getattr(self, '_dialog_open', False):
            self._cancel_hover_timer()
            return False

        try:
            x, y = int(event.x), int(event.y)
            path_info = widget.get_path_at_pos(x, y)
            if path_info:
                path = path_info[0]
                indices = path.get_indices()
                if indices and len(indices) > 0:
                    row_idx = indices[0]
                    with self._hover_lock:
                        if self._hover_row_index != row_idx:
                            self._cancel_hover_timer_locked()
                            self._hover_row_index = row_idx
                            self._hover_generation = getattr(self, '_hover_generation', 0) + 1
                            self._hover_timer = threading.Timer(3.0, self._trigger_hover_metadata, args=(row_idx,))
                            self._hover_timer.daemon = True
                            self._hover_timer.start()
                    return False
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm._on_table_motion_notify', exc_info=True)

        self._cancel_hover_timer()
        return False

    def _on_table_leave_notify(self, widget, event) -> bool:
        """Cancel hover timer when mouse pointer leaves the episodes table."""
        self._cancel_hover_timer()
        return False

    def _on_textual_table_hover_row(self, row_idx: int) -> None:
        """Handle mouse hover on Textual TUI table and track 3-second hover dwell time."""
        if getattr(self, '_dialog_open', False):
            self._cancel_hover_timer()
            return
        with self._hover_lock:
            if self._hover_row_index != row_idx:
                self._cancel_hover_timer_locked()
                self._hover_row_index = row_idx
                self._hover_generation = getattr(self, '_hover_generation', 0) + 1
                self._hover_timer = threading.Timer(3.0, self._trigger_hover_metadata, args=(row_idx,))
                self._hover_timer.daemon = True
                self._hover_timer.start()

    def _setup_table_hover_events(self) -> None:
        """Set up hover tracking on the episodes table to show metadata dialog after 3 seconds."""
        if not hasattr(self, 'episodes_list') or not self.episodes_list:
            return

        # Textual TUI backend support
        self.episodes_list.on_hover_row = self._on_textual_table_hover_row
        self.episodes_list.on_hover_leave = self._cancel_hover_timer

        impl = getattr(self.episodes_list, '_impl', None)
        if not impl:
            return

        native_table = getattr(impl, 'native_table', None)
        if native_table and hasattr(native_table, 'connect'):
            if getattr(self, '_table_hover_connected', False):
                return
            try:
                from gi.repository import Gdk
                native_table.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
                native_table.connect('motion-notify-event', self._on_table_motion_notify)
                native_table.connect('leave-notify-event', self._on_table_leave_notify)
                self._table_hover_connected = True
            except Exception:
                try:
                    native_table.connect('motion-notify-event', self._on_table_motion_notify)
                    native_table.connect('leave-notify-event', self._on_table_leave_notify)
                    self._table_hover_connected = True
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm._setup_table_hover_events', exc_info=True)
