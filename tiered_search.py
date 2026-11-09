"""Tiered, weighted search architecture for TwitTUI.

Matching Pipeline:
1. Exact Substring Match (Score: 100) - Highest Priority Display
2. Ranked Fuzzy / fzf Subsequence Score - Sorted by Match Quality (catches typos like 'ballacer' -> 'ballecer')
3. Phonetic Match (Double Metaphone) - Fallback for Phonetic Outliers
"""

import re
from typing import List, Dict, Any, Tuple, Set, Optional

try:
    from rapidfuzz import fuzz as rf_fuzz
except ImportError:
    rf_fuzz = None

from double_metaphone import double_metaphone, get_phonetic_keys


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


def extract_searchable_text(episode: Any) -> str:
    """Extract and combine searchable text fields from an episode dict or object."""
    if not episode:
        return ""
    fields = []
    keys = ('title', 'label', 'description', 'summary', 'body', 'number', 'episode', 'episodeNumber', 'show_notes', 'notes')

    if isinstance(episode, dict):
        for key in keys:
            val = episode.get(key)
            if val is not None and str(val).strip():
                fields.append(str(val).strip())
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
