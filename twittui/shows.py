"""Unified TWiT.tv show registry (single source of truth).

Consolidates public RSS feeds, Memberful / Club TWiT feed IDs, search path
slug aliases, transcript URL slug candidates, and default fallback show IDs
into one ``SHOW_REGISTRY`` mapping so every subsystem stays consistent.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShowEntry:
    """Metadata and URL/feed mappings for a TWiT.tv show or network feed."""

    key: str
    display_name: str
    default_show_id: str | None = None
    public_feeds: tuple[str, ...] = ()
    memberful_feeds: tuple[int, ...] = ()
    search_slugs: tuple[str, ...] = ()
    transcript_slugs: tuple[str, ...] = ()


_REGISTRY_ENTRIES: tuple[ShowEntry, ...] = (
    ShowEntry(
        key="all twit.tv shows",
        display_name="All TWiT.tv Shows",
        default_show_id="65161",
        public_feeds=("twit_video_hd.xml", "twit.xml"),
        memberful_feeds=(9041, 9040),
    ),
    ShowEntry(
        key="this week in tech",
        display_name="This Week in Tech",
        default_show_id="1635",
        public_feeds=("twit_video_hd.xml", "twit.xml"),
        memberful_feeds=(9067, 9066),
        search_slugs=("twit", "this-week-in-tech"),
        transcript_slugs=("twit", "week-tech", "this-week-in-tech"),
    ),
    ShowEntry(
        key="security now",
        display_name="Security Now",
        default_show_id="1636",
        public_feeds=("sn_video_hd.xml", "sn.xml"),
        memberful_feeds=(9055, 9054),
        search_slugs=("sn", "security-now"),
        transcript_slugs=("security-now", "sn"),
    ),
    ShowEntry(
        key="macbreak weekly",
        display_name="MacBreak Weekly",
        default_show_id="1643",
        public_feeds=("mbw_video_hd.xml", "mbw.xml"),
        memberful_feeds=(9051, 9050),
        search_slugs=("mbw", "macbreak-weekly"),
        transcript_slugs=("macbreak-weekly", "mbw"),
    ),
    ShowEntry(
        key="windows weekly",
        display_name="Windows Weekly",
        default_show_id="1645",
        public_feeds=("ww_video_hd.xml", "ww.xml"),
        memberful_feeds=(9079, 9078),
        search_slugs=("ww", "windows-weekly"),
        transcript_slugs=("windows-weekly", "ww"),
    ),
    ShowEntry(
        key="tech news weekly",
        display_name="Tech News Weekly",
        default_show_id="540261",
        public_feeds=("tnw_video_hd.xml", "tnw.xml"),
        memberful_feeds=(9059, 9058),
        search_slugs=("tnw", "tech-news-weekly"),
        transcript_slugs=("tech-news-weekly", "tnw"),
    ),
    ShowEntry(
        key="hands-on tech",
        display_name="Hands-On Tech",
        default_show_id="726171",
        public_feeds=("hot_video_hd.xml", "hot.xml"),
        memberful_feeds=(9047, 9046),
        search_slugs=("hot", "hands-on-tech"),
        transcript_slugs=("hands-on-tech", "hot"),
    ),
    ShowEntry(
        key="hands-on ai",
        display_name="Hands-On AI",
        default_show_id="862716",
        public_feeds=("hoa_video_hd.xml", "hoa.xml"),
        search_slugs=("hoa", "hands-on-ai"),
        transcript_slugs=("hands-on-ai", "hoa"),
    ),
    ShowEntry(
        key="hands-on mac",
        display_name="Hands-On Mac",
        public_feeds=("hom_video_hd.xml", "hom.xml"),
        search_slugs=("hom", "hands-on-mac"),
        transcript_slugs=("hands-on-mac", "hom"),
    ),
    ShowEntry(
        key="hands-on windows",
        display_name="Hands-On Windows",
        default_show_id="837161",
        public_feeds=("how_video_hd.xml", "how.xml"),
        search_slugs=("how", "hands-on-windows"),
        transcript_slugs=("hands-on-windows", "how"),
    ),
    ShowEntry(
        key="hands-on photography",
        display_name="Hands-On Photography",
        public_feeds=("hop_video_hd.xml", "hop.xml"),
        memberful_feeds=(9045, 9044),
        search_slugs=("hop", "hands-on-photography"),
        transcript_slugs=("hands-on-photography", "hop"),
    ),
    ShowEntry(
        key="this week in space",
        display_name="This Week in Space",
        default_show_id="832621",
        public_feeds=("twis_video_hd.xml", "twis.xml"),
        search_slugs=("twis", "this-week-in-space"),
        transcript_slugs=("week-space", "twis", "this-week-in-space"),
    ),
    ShowEntry(
        key="this week in google",
        display_name="This Week in Google",
        public_feeds=("twig_video_hd.xml", "twig.xml"),
        search_slugs=("twig", "this-week-in-google"),
        transcript_slugs=("week-google", "twig", "this-week-in-google"),
    ),
    ShowEntry(
        key="this week in enterprise tech",
        display_name="This Week in Enterprise Tech",
        public_feeds=("twiet_video_hd.xml", "twiet.xml"),
        memberful_feeds=(9063, 9062),
        search_slugs=("twiet", "this-week-in-enterprise-tech"),
        transcript_slugs=("week-enterprise-tech", "twiet", "this-week-in-enterprise-tech"),
    ),
    ShowEntry(
        key="untitled linux show",
        display_name="Untitled Linux Show",
        default_show_id="832795",
        public_feeds=("uls_video_hd.xml", "uls.xml"),
        search_slugs=("uls", "untitled-linux-show"),
        transcript_slugs=("untitled-linux-show", "uls"),
    ),
    ShowEntry(
        key="ios today",
        display_name="iOS Today",
        default_show_id="1660",
        public_feeds=("iost_video_hd.xml", "iost.xml"),
        memberful_feeds=(9049, 9048),
        search_slugs=("iost", "ios-today"),
        transcript_slugs=("ios-today", "iost"),
    ),
    ShowEntry(
        key="intelligent machines",
        display_name="Intelligent Machines",
        default_show_id="1653",
        public_feeds=("im_video_hd.xml", "im.xml"),
        memberful_feeds=(9065, 9064),
        search_slugs=("im", "intelligent-machines"),
        transcript_slugs=("intelligent-machines", "im"),
    ),
    ShowEntry(
        key="ask the tech guys",
        display_name="Ask The Tech Guys",
        default_show_id="1642",
        public_feeds=("attg_video_hd.xml", "attg.xml"),
        memberful_feeds=(9061, 9060),
        search_slugs=("attg", "ask-the-tech-guys", "ask-the-tech-guy"),
        transcript_slugs=("ask-tech-guys", "tech-guy", "atg", "attg"),
    ),
    ShowEntry(
        key="ask the tech guy",
        display_name="Ask The Tech Guy",
        default_show_id="791331",
        public_feeds=("attg_video_hd.xml", "attg.xml"),
        memberful_feeds=(9061, 9060),
        search_slugs=("attg", "ask-the-tech-guys", "ask-the-tech-guy"),
        transcript_slugs=("ask-tech-guys", "tech-guy", "atg", "attg"),
    ),
    ShowEntry(
        key="the tech guy",
        display_name="The Tech Guy",
        public_feeds=("ttg_video_hd.xml", "ttg.xml"),
        search_slugs=("ttg", "the-tech-guy"),
        transcript_slugs=("the-tech-guy", "tech-guy", "ttg"),
    ),
    ShowEntry(
        key="floss weekly",
        display_name="FLOSS Weekly",
        public_feeds=("floss_video_hd.xml", "floss.xml"),
        memberful_feeds=(9043, 9042),
        search_slugs=("floss", "floss-weekly"),
        transcript_slugs=("floss-weekly", "floss"),
    ),
    ShowEntry(
        key="all about android",
        display_name="All About Android",
        default_show_id="1665",
        public_feeds=("aaa_video_hd.xml", "aaa.xml"),
        memberful_feeds=(9039, 9038),
        search_slugs=("aaa", "all-about-android"),
        transcript_slugs=("all-about-android", "aaa"),
    ),
    ShowEntry(
        key="home theater geeks",
        display_name="Home Theater Geeks",
        default_show_id="1657",
        public_feeds=("htg_video_hd.xml", "htg.xml"),
        search_slugs=("htg", "home-theater-geeks"),
        transcript_slugs=("home-theater-geeks", "htg"),
    ),
    ShowEntry(
        key="smart tech today",
        display_name="Smart Tech Today",
        public_feeds=("stt_video_hd.xml", "stt.xml"),
        memberful_feeds=(9057, 9056),
        search_slugs=("stt", "smart-tech-today"),
        transcript_slugs=("smart-tech-today", "stt"),
    ),
    ShowEntry(
        key="triangulation",
        display_name="Triangulation",
        default_show_id=None,
        public_feeds=("tri_video_hd.xml", "tri.xml"),
        search_slugs=("tri", "triangulation"),
        transcript_slugs=("triangulation", "tri"),
    ),
    ShowEntry(
        key="know how",
        display_name="Know How",
        public_feeds=("kh_video_hd.xml", "kh.xml"),
        search_slugs=("kh", "know-how"),
        transcript_slugs=("know-how", "kh"),
    ),
    ShowEntry(
        key="twit news",
        display_name="TWiT News",
        memberful_feeds=(9077, 9076),
        search_slugs=("twit-news",),
        transcript_slugs=("twit-news",),
    ),
    ShowEntry(
        key="twit+ news",
        display_name="TWiT+ News",
        default_show_id="856956",
        memberful_feeds=(9077, 9076),
        search_slugs=("twit-news", "twit-plus-news", "twit_news"),
        transcript_slugs=("twit-news",),
    ),
    ShowEntry(
        key="twit events",
        display_name="TWiT Events",
        memberful_feeds=(9037, 9036),
        search_slugs=("twit-events",),
    ),
    ShowEntry(
        key="twit+ clips",
        display_name="TWiT+ Clips",
        default_show_id="825225",
        memberful_feeds=(9162, 9161),
        search_slugs=("twit-clips",),
    ),
    ShowEntry(
        key="twit+ club shows",
        display_name="TWiT+ Club Shows",
        default_show_id="856957",
        memberful_feeds=(9162, 9161, 9073, 9072, 9053, 9052, 9075, 9074, 9069, 9068),
        search_slugs=("twit-club-shows",),
    ),
    ShowEntry(
        key="ai inside",
        display_name="AI Inside",
        default_show_id="846616",
        memberful_feeds=(9073, 9072),
        search_slugs=("ai-inside",),
        transcript_slugs=("ai-inside",),
    ),
    ShowEntry(
        key="total jason",
        display_name="Total Jason",
        memberful_feeds=(9073, 9072),
        search_slugs=("total-jason",),
    ),
    ShowEntry(
        key="total leo",
        display_name="Total Leo",
        default_show_id="1647",
        memberful_feeds=(9053, 9052),
        search_slugs=("total-leo",),
    ),
    ShowEntry(
        key="total mikah",
        display_name="Total Mikah",
        default_show_id="813334",
        memberful_feeds=(9075, 9074),
        search_slugs=("total-mikah",),
    ),
    ShowEntry(
        key="total ant",
        display_name="Total Ant",
        memberful_feeds=(9069, 9068),
        search_slugs=("total-ant",),
    ),
    ShowEntry(
        key="abby's road",
        display_name="Abby's Road",
        default_show_id="1652",
        search_slugs=("abbys-road",),
    ),
    ShowEntry(
        key="android app arena",
        display_name="Android App Arena",
        default_show_id="1684",
        search_slugs=("android-app-arena",),
    ),
)

SHOW_REGISTRY: dict[str, ShowEntry] = {entry.key: entry for entry in _REGISTRY_ENTRIES}

# Derived backward-compatible lookup tables (all computed from SHOW_REGISTRY)
KNOWN_SHOW_FEEDS: dict[str, list[str]] = {
    key: list(entry.public_feeds)
    for key, entry in SHOW_REGISTRY.items()
    if entry.public_feeds
}

MEMBERFUL_SHOW_FEEDS: dict[str, list[int]] = {
    key: list(entry.memberful_feeds)
    for key, entry in SHOW_REGISTRY.items()
    if entry.memberful_feeds
}

# Host and network-wide Club TWiT feeds for deeper episode discovery
MEMBERFUL_HOST_FEEDS: list[int] = [
    9073, 9072, 9053, 9052, 9075, 9074, 9069, 9068, 9162, 9161
]

SHOW_SEARCH_SLUGS: dict[str, list[str]] = {
    key: list(entry.search_slugs)
    for key, entry in SHOW_REGISTRY.items()
    if entry.search_slugs
}

TRANSCRIPT_SLUG_MAP: dict[str, list[str]] = {
    key: list(entry.transcript_slugs)
    for key, entry in SHOW_REGISTRY.items()
    if entry.transcript_slugs
}

DEFAULT_SHOWS: list[tuple[str, str | None]] = [
    ("AI Inside", "846616"),
    ("Abby's Road", "1652"),
    ("All About Android", "1665"),
    ("All TWiT.tv Shows", "65161"),
    ("Android App Arena", "1684"),
    ("Ask The Tech Guy", "791331"),
    ("Ask The Tech Guys", "1642"),
    ("Hands-On AI", "862716"),
    ("Hands-On Tech", "726171"),
    ("Hands-On Windows", "837161"),
    ("Home Theater Geeks", "1657"),
    ("Intelligent Machines", "1653"),
    ("MacBreak Weekly", "1643"),
    ("Security Now", "1636"),
    ("TWiT+ Clips", "825225"),
    ("TWiT+ Club Shows", "856957"),
    ("TWiT+ News", "856956"),
    ("Tech News Weekly", "540261"),
    ("This Week in Space", "832621"),
    ("This Week in Tech", "1635"),
    ("Total Leo", "1647"),
    ("Total Mikah", "813334"),
    ("Triangulation", None),
    ("Untitled Linux Show", "832795"),
    ("Windows Weekly", "1645"),
    ("iOS Today", "1660"),
]


def get_show_entry(show_name: str) -> ShowEntry | None:
    """Look up a ``ShowEntry`` case-insensitively by normalized show name."""
    if not show_name:
        return None
    return SHOW_REGISTRY.get(show_name.strip().lower())
