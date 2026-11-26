"""Search and phonetic matching subpackage for TwitTUI."""

from twittui.search.double_metaphone import double_metaphone
from twittui.search.tiered_search import (
    MatchContext,
    compute_match_score,
    extract_searchable_text,
    find_match_context,
    get_episode_fields,
    rank_and_filter_episodes,
)

__all__ = [
    "MatchContext",
    "compute_match_score",
    "double_metaphone",
    "extract_searchable_text",
    "find_match_context",
    "get_episode_fields",
    "rank_and_filter_episodes",
]
