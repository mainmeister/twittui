"""Tiered, weighted search architecture for TwitTUI.

Matching Pipeline:
1. Exact Substring Match (Score: 100) - Highest Priority Display
2. Ranked Fuzzy / fzf Subsequence Score - Sorted by Match Quality (catches typos like 'ballacer' -> 'ballecer')
3. Phonetic Match (Double Metaphone) - Fallback for Phonetic Outliers
"""

import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple, Set, Optional

try:
    from rapidfuzz import fuzz as rf_fuzz
except ImportError:
    rf_fuzz = None

from double_metaphone import double_metaphone, get_phonetic_keys


@dataclass
class MatchContext:
    field_name: str = ""       # e.g., 'Description / Show Notes', 'Title', 'Hosts / Guests', 'Topics', 'Episode Number'
    matched_token: str = ""    # e.g., 'Ballecer'
    query_token: str = ""      # e.g., 'ballacer'
    match_tier: str = ""       # 'Exact Match', 'Fuzzy Match (92% similarity)', or 'Phonetic Match ("ballacer" ≈ "Ballecer")'
    snippet: str = ""          # '...Steve is away this week, so Fr. Robert Ballecer joins Leo Laporte...'
    char_offset: int = 0      # Character offset of match within the field text
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1] * (len(s2) + 1)
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row[j + 1] = min(insertions, deletions, substitutions)
        prev_row = curr_row
    return prev_row[len(s2)]


def fuzzy_ratio(s1: str, s2: str) -> float:
    """Compute normalized fuzzy similarity ratio (0.0 to 100.0)."""
    if not s1 and not s2:
        return 100.0
    if not s1 or not s2:
        return 0.0
    s1_low, s2_low = s1.lower(), s2.lower()
    if s1_low == s2_low:
        return 100.0
    if rf_fuzz is not None:
        try:
            return float(rf_fuzz.ratio(s1_low, s2_low))
        except Exception:
            pass
    dist = levenshtein_distance(s1_low, s2_low)
    total_len = len(s1_low) + len(s2_low)
    return max(0.0, ((total_len - dist) / total_len) * 100.0)


def fzf_subsequence_score(query: str, target: str) -> float:
    """Score target based on subsequence alignment with query (fzf-style).
    Returns a score between 0.0 and 100.0 (0.0 if not a subsequence).
    """
    if not query or not target:
        return 0.0
    q = query.lower()
    t = target.lower()
    if q == t:
        return 100.0
    if q in t:
        return 95.0

    q_idx = 0
    q_len = len(q)
    t_len = len(t)
    last_match = -1
    consecutive = 0
    score = 0.0

    for t_idx, ch in enumerate(t):
        if q_idx < q_len and ch == q[q_idx]:
            is_word_start = (t_idx == 0 or not t[t_idx - 1].isalnum())
            if is_word_start:
                score += 10.0

            if last_match == t_idx - 1:
                consecutive += 1
                score += 5.0 * consecutive
            else:
                consecutive = 0

            score += 10.0
            last_match = t_idx
            q_idx += 1

    if q_idx < q_len:
        return 0.0  # Not all characters found in sequence

    max_possible = (q_len * 10.0) + (10.0 * q_len) + (5.0 * q_len * (q_len - 1) / 2.0)
    if max_possible <= 0:
        return 0.0
    normalized = min(95.0, max(50.0, (score / max_possible) * 95.0))
    return normalized


def format_duration_str(val: Any) -> str:
    """Helper to convert duration to formatted string (HH:MM:SS or MM:SS)."""
    if val is None or val == '':
        return ''
    if isinstance(val, dict):
        if 'runningTime' in val and val['runningTime']:
            return format_duration_str(val['runningTime'])
        if 'duration' in val and val['duration']:
            return format_duration_str(val['duration'])
        if 'hours' in val or 'minutes' in val or 'seconds' in val:
            try:
                h = int(val.get('hours') or 0)
                m = int(val.get('minutes') or 0)
                s = int(val.get('seconds') or 0)
                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            except Exception:
                pass
        return ''
    s = str(val).strip()
    if not s:
        return ''
    if s.isdigit():
        total = int(s)
        h = total // 3600
        m = (total % 3600) // 60
        sec = total % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"
    return s


def format_file_size_str(val: Any) -> str:
    """Helper to convert size in bytes to human-readable string and byte string."""
    if val is None or val == '':
        return ''
    if isinstance(val, dict):
        for k in ['file_size', 'fileSize', 'size', 'length', 'enclosure_length', 'bytes']:
            if k in val and val[k]:
                res = format_file_size_str(val[k])
                if res:
                    return res
        return ''
    s = str(val).strip().replace(',', '')
    if not s:
        return ''
    if s.isdigit():
        num = int(s)
        if num < 1024:
            return f"{num} B ({num} bytes)"
        elif num < 1024 * 1024:
            kb = num / 1024.0
            return f"{kb:.1f} KB ({num} bytes)"
        elif num < 1024 * 1024 * 1024:
            mb = num / (1024.0 * 1024.0)
            return f"{mb:.1f} MB ({num} bytes)"
        else:
            gb = num / (1024.0 * 1024.0 * 1024.0)
            return f"{gb:.2f} GB ({num} bytes)"
    return s


def extract_searchable_text(episode: Any) -> str:
    """Extract and combine searchable text fields from an episode dict or object."""
    if not episode:
        return ""
    fields = []
    keys = (
        'title', 'label', 'description', 'summary', 'body', 'number',
        'episode', 'episodeNumber', 'show_notes', 'notes',
        'length', 'duration', 'runningTime', 'running_time',
        'size', 'file_size', 'fileSize', 'enclosure_length', 'bytes'
    )

    if isinstance(episode, dict):
        for key in keys:
            val = episode.get(key)
            if val is not None and str(val).strip():
                fields.append(str(val).strip())
                if key in ('length', 'duration', 'runningTime', 'running_time'):
                    dur_fmt = format_duration_str(val)
                    if dur_fmt and dur_fmt not in fields:
                        fields.append(dur_fmt)
                elif key in ('size', 'file_size', 'fileSize', 'enclosure_length', 'bytes'):
                    sz_fmt = format_file_size_str(val)
                    if sz_fmt and sz_fmt not in fields:
                        fields.append(sz_fmt)
        if '_embedded' in episode:
            embedded = episode.get('_embedded') or {}
            if isinstance(embedded, dict):
                for credit in embedded.get('credits', []):
                    if isinstance(credit, dict):
                        fields.append(str(credit.get('label', '')))
                        fields.append(str(credit.get('name', '')))
        if 'episode_data' in episode and isinstance(episode['episode_data'], dict):
            fields.append(extract_searchable_text(episode['episode_data']))
    else:
        for key in keys:
            val = getattr(episode, key, None)
            if val is not None and str(val).strip():
                fields.append(str(val).strip())
                if key in ('length', 'duration', 'runningTime', 'running_time'):
                    dur_fmt = format_duration_str(val)
                    if dur_fmt and dur_fmt not in fields:
                        fields.append(dur_fmt)
                elif key in ('size', 'file_size', 'fileSize', 'enclosure_length', 'bytes'):
                    sz_fmt = format_file_size_str(val)
                    if sz_fmt and sz_fmt not in fields:
                        fields.append(sz_fmt)
        if hasattr(episode, 'episode_data') and isinstance(episode.episode_data, dict):
            fields.append(extract_searchable_text(episode.episode_data))

    return " ".join(fields)


def compute_match_score(
    query: str,
    text: str,
    fuzzy_enabled: bool = True,
    phonetic_enabled: bool = True,
    min_word_threshold: float = 68.0
) -> float:
    """Evaluate candidate text against search query using tiered matching architecture.

    Returns:
        Score between 0.0 and 100.0.
        - Tier 1 (Exact Substring): 100.0
        - Tier 2 (Ranked Fuzzy / fzf Subsequence): 60.0 - 99.0
        - Tier 3 (Phonetic Match): 60.0 - 85.0
        - 0.0 if not matched.
    """
    if not query or not text:
        return 0.0

    q_clean = query.strip().lower()
    if not q_clean:
        return 0.0

    t_clean = text.strip().lower()
    if not t_clean:
        return 0.0

    q_words = [w for w in re.split(r'\s+', q_clean) if w]
    if not q_words:
        return 0.0

    # -------------------------------------------------------------
    # Tier 1: Exact Substring Match (Score: 100)
    # Highest Priority Display
    # -------------------------------------------------------------
    if all(qw in t_clean for qw in q_words):
        return 100.0

    if not fuzzy_enabled and not phonetic_enabled:
        return 0.0

    cand_words = [w for w in re.findall(r'[a-z0-9]+', t_clean) if w]
    if not cand_words:
        return 0.0

    text_phonetic = get_phonetic_keys(t_clean) if phonetic_enabled else set()

    word_scores = []
    for qw in q_words:
        # If this single query token is an exact substring of the candidate text
        if qw in t_clean:
            word_scores.append(100.0)
            continue

        best_w_score = 0.0

        # Tier 2: Fuzzy / Subsequence scoring for this query token
        if fuzzy_enabled:
            # Check direct token ratio against candidate words
            for cw in cand_words:
                r = fuzzy_ratio(qw, cw)
                if r > best_w_score:
                    best_w_score = float(r)

            # Check fzf subsequence against candidate words
            if len(qw) >= 3:
                for cw in cand_words:
                    if len(qw) <= len(cw):
                        sub_score = fzf_subsequence_score(qw, cw)
                        if sub_score > best_w_score:
                            best_w_score = max(best_w_score, sub_score)

            # Check partial ratio on full text if rapidfuzz available
            if len(qw) > 3 and rf_fuzz is not None:
                try:
                    pr = float(rf_fuzz.partial_ratio(qw, t_clean))
                    if pr > best_w_score:
                        best_w_score = max(best_w_score, pr)
                except Exception:
                    pass

        # Tier 3: Phonetic (Double Metaphone) fallback for this query token
        if phonetic_enabled and best_w_score < 75.0:
            qw_p, qw_s = double_metaphone(qw)
            if (qw_p and qw_p in text_phonetic) or (qw_s and qw_s in text_phonetic):
                phonetic_score = 80.0 if (qw_p and qw_p in text_phonetic) else 72.0
                best_w_score = max(best_w_score, phonetic_score)

        # Enforce minimum threshold per query word
        effective_threshold = min_word_threshold if len(qw) >= 4 else 80.0
        if best_w_score < effective_threshold:
            return 0.0

        word_scores.append(best_w_score)

    if not word_scores:
        return 0.0

    avg_score = sum(word_scores) / len(word_scores)
    # Tier 2 & 3 scores are ranked below exact 100.0 (capped at 99.0)
    final_score = min(99.0, max(60.0, avg_score))
    return final_score


def extract_snippet(text: str, match_pos: int, match_len: int, window: int = 50) -> str:
    """Extract a keyword-in-context (KWIC) snippet centered around matched position."""
    if not text:
        return ""
    start_idx = max(0, match_pos - window)
    end_idx = min(len(text), match_pos + match_len + window)

    # Align to word boundaries where reasonable
    if start_idx > 0:
        prev_space = text.find(' ', start_idx, min(match_pos, start_idx + 15))
        if prev_space != -1:
            start_idx = prev_space + 1
    if end_idx < len(text):
        next_space = text.rfind(' ', max(match_pos + match_len, end_idx - 15), end_idx)
        if next_space != -1:
            end_idx = next_space

    raw_snippet = text[start_idx:end_idx]
    cleaned = re.sub(r'\s+', ' ', raw_snippet).strip()

    prefix = "..." if start_idx > 0 else ""
    suffix = "..." if end_idx < len(text) else ""
    return f"{prefix}{cleaned}{suffix}"


def get_episode_fields(episode: Any) -> List[Tuple[str, str]]:
    """Extract named fields from episode for matching and context extraction."""
    fields: List[Tuple[str, str]] = []
    if not episode:
        return fields

    ep_data: Dict[str, Any] = {}
    if isinstance(episode, dict):
        if 'episode_data' in episode and isinstance(episode['episode_data'], dict):
            ep_data.update(episode['episode_data'])
        ep_data.update(episode)
    else:
        if hasattr(episode, 'episode_data') and isinstance(episode.episode_data, dict):
            ep_data.update(episode.episode_data)
        for attr in ('title', 'label', 'description', 'summary', 'body', 'number', 'episode', 'people', 'hosts', 'topics'):
            if hasattr(episode, attr):
                val = getattr(episode, attr)
                if val:
                    ep_data[attr] = val

    # 1. Title
    title = ep_data.get('title') or ep_data.get('label') or ''
    if title:
        fields.append(('Title', str(title).strip()))

    # 2. Hosts / Guests / People
    people = []
    for k in ('hosts', 'guests', 'people', 'staff'):
        val = ep_data.get(k)
        if isinstance(val, list):
            for p in val:
                if isinstance(p, dict):
                    name = p.get('label') or p.get('name') or p.get('title')
                    if name:
                        people.append(str(name))
                elif isinstance(p, str) and p.strip():
                    people.append(p.strip())
        elif isinstance(val, str) and val.strip():
            people.append(val.strip())
    if '_embedded' in ep_data and isinstance(ep_data['_embedded'], dict):
        for credit in ep_data['_embedded'].get('credits', []):
            if isinstance(credit, dict):
                lbl = credit.get('label') or credit.get('name')
                if lbl:
                    people.append(str(lbl))
    if people:
        fields.append(('Hosts / Guests', ", ".join(people)))

    # 3. Topics
    topics = []
    for k in ('topics', 'tags', 'categories'):
        val = ep_data.get(k)
        if isinstance(val, list):
            for t in val:
                if isinstance(t, dict):
                    name = t.get('label') or t.get('name') or t.get('title')
                    if name:
                        topics.append(str(name))
                elif isinstance(t, str) and t.strip():
                    topics.append(t.strip())
        elif isinstance(val, str) and val.strip():
            topics.append(val.strip())
    if topics:
        fields.append(('Topics', ", ".join(topics)))

    # 4. Description / Show Notes
    desc = ep_data.get('description') or ep_data.get('summary') or ep_data.get('body') or ep_data.get('show_notes') or ep_data.get('notes') or ep_data.get('teaser') or ep_data.get('snippet') or ''
    if desc:
        fields.append(('Description / Show Notes', str(desc).strip()))

    # 5. Episode Number
    num = ep_data.get('number') or ep_data.get('episode') or ep_data.get('episodeNumber') or ''
    if num:
        fields.append(('Episode Number', str(num).strip()))

    # 6. Length / Duration
    dur_val = ep_data.get('length') or ep_data.get('duration') or ep_data.get('runningTime') or ep_data.get('running_time')
    if dur_val:
        dur_str = format_duration_str(dur_val)
        raw_str = str(dur_val).strip()
        if dur_str:
            combined_dur = dur_str if dur_str == raw_str else f"{dur_str} {raw_str}"
            fields.append(('Length', combined_dur))
        elif raw_str:
            fields.append(('Length', raw_str))

    # 7. Size / Bytes
    size_val = ep_data.get('size') or ep_data.get('file_size') or ep_data.get('fileSize') or ep_data.get('enclosure_length') or ep_data.get('bytes')
    if size_val:
        size_str = format_file_size_str(size_val)
        raw_size_str = str(size_val).strip()
        if size_str:
            combined_size = size_str if size_str == raw_size_str else f"{size_str} {raw_size_str}"
            fields.append(('Size', combined_size))
        elif raw_size_str:
            fields.append(('Size', raw_size_str))

    return fields


def find_match_context(
    episode: Any,
    query: str,
    fuzzy_enabled: bool = True,
    phonetic_enabled: bool = True,
    min_word_threshold: float = 68.0
) -> Optional[MatchContext]:
    """Find detailed match context (field name, match type, token, snippet, char offset) for an episode."""
    if not query or not query.strip() or not episode:
        return None

    q_clean = query.strip().lower()
    q_words = [w for w in re.split(r'\s+', q_clean) if w]
    if not q_words:
        return None

    fields = get_episode_fields(episode)
    if not fields:
        return None

    # Priority 1: Exact matches across fields
    for field_label, field_text in fields:
        f_lower = field_text.lower()
        if q_clean in f_lower:
            m = re.search(re.escape(q_clean), field_text, re.IGNORECASE)
            if m:
                matched_token = field_text[m.start():m.end()]
                snippet = extract_snippet(field_text, m.start(), len(matched_token))
                return MatchContext(
                    field_name=field_label,
                    matched_token=matched_token,
                    query_token=query.strip(),
                    match_tier="Exact Match",
                    snippet=snippet,
                    char_offset=m.start(),
                    score=100.0
                )

        if all(qw in f_lower for qw in q_words):
            first_qw = q_words[0]
            m = re.search(r'\b' + re.escape(first_qw) + r'\b', field_text, re.IGNORECASE) or re.search(re.escape(first_qw), field_text, re.IGNORECASE)
            if m:
                matched_token = field_text[m.start():m.end()]
                snippet = extract_snippet(field_text, m.start(), len(matched_token))
                return MatchContext(
                    field_name=field_label,
                    matched_token=matched_token,
                    query_token=first_qw,
                    match_tier="Exact Match",
                    snippet=snippet,
                    char_offset=m.start(),
                    score=100.0
                )

    # Priority 2: Fuzzy and Phonetic candidate evaluations
    candidate_matches: List[MatchContext] = []
    for field_label, field_text in fields:
        word_iter = list(re.finditer(r'[A-Za-z0-9]+', field_text))

        for qw in q_words:
            m = re.search(r'\b' + re.escape(qw) + r'\b', field_text, re.IGNORECASE) or re.search(re.escape(qw), field_text, re.IGNORECASE)
            if m:
                matched_token = field_text[m.start():m.end()]
                snippet = extract_snippet(field_text, m.start(), len(matched_token))
                candidate_matches.append(MatchContext(
                    field_name=field_label,
                    matched_token=matched_token,
                    query_token=qw,
                    match_tier="Exact Match",
                    snippet=snippet,
                    char_offset=m.start(),
                    score=100.0
                ))
                continue

            if not word_iter:
                continue

            qw_p, qw_s = double_metaphone(qw) if phonetic_enabled else (None, None)

            for w_m in word_iter:
                cw = w_m.group(0)
                cw_lower = cw.lower()

                # Tier 3: Phonetic (check if words share Double Metaphone phonetic key)
                if phonetic_enabled and qw_p:
                    cw_p, cw_s = double_metaphone(cw_lower)
                    if (qw_p and (qw_p == cw_p or qw_p == cw_s)) or (qw_s and (qw_s == cw_p or qw_s == cw_s)):
                        p_score = 95.0 if (qw_p == cw_p) else 88.0
                        snippet = extract_snippet(field_text, w_m.start(), len(cw))
                        candidate_matches.append(MatchContext(
                            field_name=field_label,
                            matched_token=cw,
                            query_token=qw,
                            match_tier=f'Phonetic Match ("{qw}" ≈ "{cw}")',
                            snippet=snippet,
                            char_offset=w_m.start(),
                            score=p_score
                        ))
                        continue

                # Tier 2: Fuzzy (for non-phonetic typos and subsequence alignments)
                if fuzzy_enabled:
                    r = fuzzy_ratio(qw, cw_lower)
                    sub = fzf_subsequence_score(qw, cw_lower) if (len(qw) >= 3 and len(qw) <= len(cw_lower)) else 0.0
                    f_score = max(r, sub)
                    if f_score >= min_word_threshold:
                        snippet = extract_snippet(field_text, w_m.start(), len(cw))
                        candidate_matches.append(MatchContext(
                            field_name=field_label,
                            matched_token=cw,
                            query_token=qw,
                            match_tier=f"Fuzzy Match ({int(round(f_score))}% similarity)",
                            snippet=snippet,
                            char_offset=w_m.start(),
                            score=min(90.0, f_score)
                        ))

    if not candidate_matches:
        return None

    field_priority = {
        'Description / Show Notes': 3,
        'Hosts / Guests': 2,
        'Title': 1,
        'Topics': 0,
        'Episode Number': 0,
        'Length': 0,
        'Size': 0
    }
    candidate_matches.sort(
        key=lambda mc: (mc.score, field_priority.get(mc.field_name, 0)),
        reverse=True
    )
    return candidate_matches[0]


def rank_and_filter_episodes(
    episodes: List[Any],
    query: str,
    fuzzy_enabled: bool = True,
    phonetic_enabled: bool = True,
    min_word_threshold: float = 68.0
) -> List[Any]:
    """Filter and rank a list of episodes according to tiered search score.

    Exact matches (score 100) are placed first, followed by ranked fuzzy/phonetic
    matches ordered by match score in descending order.
    """
    if not query or not query.strip():
        return list(episodes)
    if not episodes:
        return []

    scored_items = []
    for ep in episodes:
        text = extract_searchable_text(ep)
        score = compute_match_score(
            query=query,
            text=text,
            fuzzy_enabled=fuzzy_enabled,
            phonetic_enabled=phonetic_enabled,
            min_word_threshold=min_word_threshold
        )
        if score > 0.0:
            scored_items.append((score, ep))

    # Sort descending by score, maintaining stable relative order for tied scores
    scored_items.sort(key=lambda x: x[0], reverse=True)
    return [ep for _, ep in scored_items]
