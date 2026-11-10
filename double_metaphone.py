"""Double Metaphone phonetic matching algorithm in pure Python.
Based on the Double Metaphone algorithm by Lawrence Philips (2000).
"""

import re
from typing import Tuple, List, Set


def double_metaphone(string: str) -> Tuple[str, str]:
    """Compute primary and secondary Double Metaphone phonetic codes for a string."""
    if not string:
        return ("", "")

    s = string.upper().strip()
    # Filter out non-alphabetic characters
    s = re.sub(r'[^A-Z]', '', s)
    if not s:
        return ("", "")

    length = len(s)
    primary = []
    secondary = []
    current = 0

    def is_vowel(idx: int) -> bool:
        if idx < 0 or idx >= length:
            return False
        return s[idx] in 'AEIOUY'

    def substr(start: int, length_sub: int) -> str:
        if start < 0 or start >= length:
            return ""
        return s[start:start + length_sub]

    def string_at(start: int, length_sub: int, *matches: str) -> bool:
        sub = substr(start, length_sub)
        return sub in matches

    # Pad at the end for boundary checks
    padded = s + "     "

    # Initial letter exceptions
    if substr(0, 2) in ('GN', 'KN', 'PN', 'WR', 'PS'):
        current += 1

    # Initial 'X' sounds like 'S'
    if substr(0, 1) == 'X':
        primary.append('S')
        secondary.append('S')
        current += 1

    while current < length and (len(primary) < 4 or len(secondary) < 4):
        ch = s[current]

        if ch in 'AEIOUY':
            if current == 0:
                primary.append('A')
                secondary.append('A')
            current += 1
            continue

        elif ch == 'B':
            primary.append('P')
            secondary.append('P')
            if substr(current + 1, 1) == 'B':
                current += 2
            else:
                current += 1
            continue

        elif ch == 'Ç':
            primary.append('S')
            secondary.append('S')
            current += 1
            continue

        elif ch == 'C':
            # various special cases for C
            if current > 1 and not is_vowel(current - 2) and string_at(current - 1, 3, "ACH") and \
                    substr(current + 2, 1) != "I" and (substr(current + 2, 1) != "E" or string_at(current - 2, 6, "BACHER", "MACHER")):
                primary.append('K')
                secondary.append('K')
                current += 2
                continue

            if current == 0 and string_at(current, 6, "CAESAR"):
                primary.append('S')
                secondary.append('S')
                current += 2
                continue

            if string_at(current, 4, "CHIA"):
                primary.append('K')
                secondary.append('K')
                current += 2
                continue

            if string_at(current, 2, "CH"):
                if current > 0 and string_at(current, 4, "CHAE"):
                    primary.append('K')
                    secondary.append('K')
                    current += 2
                    continue

                if current == 0 and (string_at(current + 1, 5, "HARAC", "HARIS") or
                                     string_at(current + 1, 3, "HOR", "HYM", "HIA", "HEM")) and \
                        not string_at(0, 5, "CHORE"):
                    primary.append('K')
                    secondary.append('K')
                    current += 2
                    continue

                if string_at(0, 4, "VAN ", "VON ") or string_at(0, 3, "SCH") or \
                        string_at(current - 2, 6, "ORCHES", "ARCHIT", "ORCHID") or \
                        string_at(current + 2, 1, "T", "S") or \
                        ((string_at(current - 1, 1, "A", "O", "U", "E") or current == 0) and
                         string_at(current + 2, 1, "L", "R", "N", "M", "B", "H", "F", "V", "W", " ")):
                    primary.append('K')
                    secondary.append('K')
                else:
                    if current > 0:
                        if string_at(0, 2, "MC"):
                            primary.append('K')
                            secondary.append('K')
                        else:
                            primary.append('X')
                            secondary.append('K')
                    else:
                        primary.append('X')
                        secondary.append('X')
                current += 2
                continue

            if string_at(current, 2, "CZ") and not string_at(current - 2, 4, "WICZ"):
                primary.append('S')
                secondary.append('X')
                current += 2
                continue

            if string_at(current + 1, 3, "CIA"):
                primary.append('X')
                secondary.append('X')
                current += 3
                continue

            if string_at(current, 2, "CC") and not (current == 1 and substr(0, 1) == "M"):
                if string_at(current + 2, 1, "I", "E", "H") and not string_at(current + 2, 2, "HU"):
                    if (current == 1 and substr(current - 1, 1) == "A") or \
                            string_at(current - 1, 5, "UCCEE", "UCCES"):
                        primary.append('K')
                        secondary.append('K')
                        primary.append('S')
                        secondary.append('S')
                    else:
                        primary.append('X')
                        secondary.append('X')
                    current += 3
                    continue
                else:
                    primary.append('K')
                    secondary.append('K')
                    current += 2
                    continue

            if string_at(current, 2, "CK", "CG", "CQ"):
                primary.append('K')
                secondary.append('K')
                current += 2
                continue

            if string_at(current, 2, "CI", "CE", "CY"):
                if string_at(current, 3, "CIO", "CIE", "CIA"):
                    primary.append('S')
                    secondary.append('X')
                else:
                    primary.append('S')
                    secondary.append('S')
                current += 2
                continue

            primary.append('K')
            secondary.append('K')

            if string_at(current + 1, 2, " C", " Q", " G"):
                current += 3
            elif string_at(current + 1, 1, "C", "K", "Q") and not string_at(current + 1, 2, "CE", "CI"):
                current += 2
            else:
                current += 1
            continue

        elif ch == 'D':
            if string_at(current, 2, "DG"):
                if string_at(current + 2, 1, "I", "E", "Y"):
                    primary.append('J')
                    secondary.append('J')
                    current += 3
                    continue
                else:
                    primary.append('T')
                    secondary.append('K')
                    current += 2
                    continue

            if string_at(current, 2, "DT", "DD"):
                primary.append('T')
                secondary.append('T')
                current += 2
                continue

            primary.append('T')
            secondary.append('T')
            current += 1
            continue

        elif ch == 'F':
            if substr(current + 1, 1) == 'F':
                current += 2
            else:
                current += 1
            primary.append('F')
            secondary.append('F')
            continue

        elif ch == 'G':
            if substr(current + 1, 1) == 'H':
                if current > 0 and not is_vowel(current - 1):
                    primary.append('K')
                    secondary.append('K')
                    current += 2
                    continue
                if current == 0:
                    if substr(current + 2, 1) == 'I':
                        primary.append('J')
                        secondary.append('J')
                    else:
                        primary.append('K')
                        secondary.append('K')
                    current += 2
                    continue
                if (current > 1 and string_at(current - 2, 1, "B", "H", "D")) or \
                        (current > 2 and string_at(current - 3, 1, "B", "H", "D")) or \
                        (current > 3 and string_at(current - 4, 1, "B", "H")):
                    current += 2
                    continue
                else:
                    if current > 2 and substr(current - 1, 1) == 'U' and \
                            string_at(current - 3, 1, "C", "G", "L", "R", "T"):
                        primary.append('F')
                        secondary.append('F')
                    elif current > 0 and substr(current - 1, 1) != 'I':
                        primary.append('K')
                        secondary.append('K')
                    current += 2
                    continue

            if substr(current + 1, 1) == 'N':
                if current == 1 and is_vowel(0) and not string_at(0, 6, "DANGER", "RANGER", "MANGER"):
                    primary.append('K')
                    secondary.append('N')
                else:
                    if not string_at(current + 2, 2, "EY") and substr(current + 1, 1) != "Y" and not string_at(0, 4, "SUGN"):
                        primary.append('N')
                        secondary.append('K')
                    else:
                        primary.append('K')
                        secondary.append('K')
                current += 2
                continue

            if string_at(current + 1, 2, "LI") and not string_at(0, 4, "VAN ", "VON "):
                primary.append('K')
                secondary.append('L')
                current += 2
                continue

            if current == 0 and (substr(current + 1, 1) == 'Y' or
                                 string_at(current + 1, 2, "ES", "EP", "EB", "EL", "EY", "IB", "IL", "IN", "IE", "EI", "ER")):
                primary.append('K')
                secondary.append('J')
                current += 2
                continue

            if (string_at(current + 1, 2, "ER") or substr(current + 1, 1) == 'Y') and \
                    not string_at(0, 6, "DANGER", "RANGER", "MANGER") and \
                    not string_at(current - 1, 1, "E", "I") and \
                    not string_at(current - 1, 3, "RGY", "OGY"):
                primary.append('K')
                secondary.append('J')
                current += 2
                continue

            if string_at(current + 1, 1, "E", "I", "Y") or string_at(current - 1, 4, "GGIE", "GGI"):
                if string_at(0, 4, "VAN ", "VON ") or string_at(0, 3, "SCH") or \
                        string_at(current + 1, 2, "ET"):
                    primary.append('K')
                    secondary.append('K')
                else:
                    if string_at(current + 1, 4, "IER "):
                        primary.append('J')
                        secondary.append('J')
                    else:
                        primary.append('J')
                        secondary.append('K')
                current += 2
                continue

            if substr(current + 1, 1) == 'G':
                current += 2
            else:
                current += 1
            primary.append('K')
            secondary.append('K')
            continue

        elif ch == 'H':
            if (current == 0 or is_vowel(current - 1)) and is_vowel(current + 1):
                primary.append('H')
                secondary.append('H')
                current += 2
            else:
                current += 1
            continue

        elif ch == 'J':
            if string_at(current, 4, "JOSE") or string_at(0, 4, "SAN "):
                if (current == 0 and substr(current + 4, 1) == ' ') or string_at(0, 4, "SAN "):
                    primary.append('H')
                    secondary.append('H')
                else:
                    primary.append('J')
                    secondary.append('H')
                current += 1
                continue

            if current == 0 and not string_at(current, 4, "JOSE"):
                primary.append('J')
                secondary.append('A')
            else:
                if is_vowel(current - 1) and not string_at(0, 4, "SAN ") and \
                        (substr(current + 1, 1) == 'A' or substr(current + 1, 1) == 'O'):
                    primary.append('J')
                    secondary.append('H')
                else:
                    if current == length - 1:
                        primary.append('J')
                        secondary.append('')
                    else:
                        if not string_at(current + 1, 1, "L", "T", "K", "S", "N", "M", "B", "Z") and \
                                not string_at(current - 1, 1, "S", "K", "L"):
                            primary.append('J')
                            secondary.append('J')
            if substr(current + 1, 1) == 'J':
                current += 2
            else:
                current += 1
            continue

        elif ch == 'K':
            if substr(current + 1, 1) == 'K':
                current += 2
            else:
                current += 1
            primary.append('K')
            secondary.append('K')
            continue

        elif ch == 'L':
            if substr(current + 1, 1) == 'L':
                if (current == length - 3 and string_at(current - 1, 4, "ILLO", "ILLA", "ALLE")) or \
                        ((string_at(length - 2, 2, "AS", "OS") or string_at(length - 1, 1, "A", "O")) and
                         string_at(current - 1, 4, "ALLE")):
                    primary.append('L')
                    secondary.append('')
                    current += 2
                    continue
                current += 2
            else:
                current += 1
            primary.append('L')
            secondary.append('L')
            continue

        elif ch == 'M':
            if string_at(current - 1, 3, "UMB") and \
                    (current + 1 == length - 1 or string_at(current + 2, 2, "ER")):
                current += 2
            elif substr(current + 1, 1) == 'M':
                current += 2
            else:
                current += 1
            primary.append('M')
            secondary.append('M')
            continue

        elif ch == 'N':
            if substr(current + 1, 1) == 'N':
                current += 2
            else:
                current += 1
            primary.append('N')
            secondary.append('N')
            continue

        elif ch == 'Ñ':
            current += 1
            primary.append('N')
            secondary.append('N')
            continue

        elif ch == 'P':
            if substr(current + 1, 1) == 'H':
                primary.append('F')
                secondary.append('F')
                current += 2
                continue
            if string_at(current + 1, 1, "P", "B"):
                current += 2
            else:
                current += 1
            primary.append('P')
            secondary.append('P')
            continue

        elif ch == 'Q':
            if substr(current + 1, 1) == 'Q':
                current += 2
            else:
                current += 1
            primary.append('K')
            secondary.append('K')
            continue

        elif ch == 'R':
            if current == length - 1 and not string_at(0, 4, "VAN ", "VON ") and \
                    string_at(current - 2, 2, "IE") and not string_at(current - 4, 2, "ME", "MA"):
                secondary.append('R')
            else:
                primary.append('R')
                secondary.append('R')
            if substr(current + 1, 1) == 'R':
                current += 2
            else:
                current += 1
            continue

        elif ch == 'S':
            if string_at(current - 1, 3, "ISL", "YSL"):
                current += 1
                continue
            if current == 0 and string_at(current, 5, "SUGAR"):
                primary.append('X')
                secondary.append('S')
                current += 1
                continue
            if string_at(current, 2, "SH"):
                if string_at(current + 1, 4, "HEIM", "HOEK", "HOLM", "HOLZ"):
                    primary.append('S')
                    secondary.append('S')
                else:
                    primary.append('X')
                    secondary.append('X')
                current += 2
                continue
            if string_at(current, 3, "SIO", "SIA") or string_at(current, 4, "SIAN"):
                primary.append('S')
                secondary.append('X')
                current += 3
                continue
            if (current == 0 and string_at(current + 1, 1, "M", "N", "L", "W")) or \
                    string_at(current + 1, 1, "Z"):
                primary.append('S')
                secondary.append('X')
                if string_at(current + 1, 1, "Z"):
                    current += 2
                else:
                    current += 1
                continue
            if string_at(current, 2, "SC"):
                if substr(current + 2, 1) == 'H':
                    if string_at(current + 3, 2, "OO", "ER", "EN", "UY", "ED", "EM"):
                        if string_at(current + 3, 2, "ER", "EN"):
                            primary.append('X')
                            secondary.append('S')
                            primary.append('K')
                            secondary.append('K')
                        else:
                            primary.append('S')
                            secondary.append('K')
                            primary.append('K')
                            secondary.append('K')
                        current += 3
                        continue
                    else:
                        if current == 0 and not is_vowel(3) and substr(3, 1) != 'W':
                            primary.append('X')
                            secondary.append('S')
                        else:
                            primary.append('X')
                            secondary.append('X')
                        current += 3
                        continue
                if string_at(current + 2, 1, "I", "E", "Y"):
                    primary.append('S')
                    secondary.append('S')
                    current += 3
                    continue
                primary.append('S')
                secondary.append('S')
                primary.append('K')
                secondary.append('K')
                current += 3
                continue

            if current == length - 1 and string_at(current - 2, 2, "AI", "OI"):
                secondary.append('S')
            else:
                primary.append('S')
                secondary.append('S')

            if string_at(current + 1, 1, "S", "Z"):
                current += 2
            else:
                current += 1
            continue

        elif ch == 'T':
            if string_at(current, 4, "TION", "TIAN", "TIEN"):
                primary.append('X')
                secondary.append('X')
                current += 3
                continue
            if string_at(current, 3, "TCH", "TH"):
                if string_at(current + 2, 2, "OM", "AM") or string_at(0, 4, "VAN ", "VON ") or \
                        string_at(0, 3, "SCH"):
                    primary.append('T')
                    secondary.append('T')
                else:
                    primary.append('0')  # theta
                    secondary.append('T')
                current += 2
                continue
            if string_at(current + 1, 1, "T", "D"):
                current += 2
            else:
                current += 1
            primary.append('T')
            secondary.append('T')
            continue

        elif ch == 'V':
            if substr(current + 1, 1) == 'V':
                current += 2
            else:
                current += 1
            primary.append('F')
            secondary.append('F')
            continue

        elif ch == 'W':
            if string_at(current, 2, "WR"):
                primary.append('R')
                secondary.append('R')
                current += 2
                continue
            if current == 0 and (is_vowel(current + 1) or string_at(current, 2, "WH")):
                if is_vowel(current + 1):
                    primary.append('A')
                    secondary.append('F')
                else:
                    primary.append('A')
                    secondary.append('A')
                current += 1
                continue
            if (current == length - 1 and is_vowel(current - 1)) or \
                    string_at(current - 1, 5, "EWSKI", "EWSKY", "OWSKI", "OWSKY") or \
                    string_at(0, 3, "SCH"):
                secondary.append('F')
                current += 1
                continue
            if string_at(current, 4, "WICZ", "WITZ"):
                primary.append('T')
                secondary.append('T')
                primary.append('S')
                secondary.append('F')
                primary.append('X')
                secondary.append('X')
                current += 4
                continue
            current += 1
            continue

        elif ch == 'X':
            if not (current == length - 1 and (string_at(current - 3, 3, "IAU", "EAU") or
                                               string_at(current - 2, 2, "AU", "OU"))):
                primary.append('K')
                secondary.append('K')
                primary.append('S')
                secondary.append('S')
            if string_at(current + 1, 1, "C", "X"):
                current += 2
            else:
                current += 1
            continue

        elif ch == 'Z':
            if substr(current + 1, 1) == 'H':
                primary.append('J')
                secondary.append('J')
                current += 2
                continue
            elif string_at(current + 1, 2, "ZO", "ZI", "ZA") or \
                    (not string_at(0, 4, "VAN ", "VON ") and current > 0 and substr(current - 1, 1) != 'T'):
                primary.append('S')
                secondary.append('T')
                secondary.append('S')
            else:
                primary.append('S')
                secondary.append('S')
            if substr(current + 1, 1) == 'Z':
                current += 2
            else:
                current += 1
            continue

        else:
            current += 1

    prim_str = "".join(primary)[:4]
    sec_str = "".join(secondary)[:4]
    return (prim_str, sec_str or prim_str)


def get_phonetic_keys(text: str) -> Set[str]:
    """Extract unique Double Metaphone codes for all words in text."""
    if not text:
        return set()
    words = re.findall(r'[A-Za-z0-9]+', str(text))
    keys = set()
    for w in words:
        if not w:
            continue
        p, s = double_metaphone(w)
        if p:
            keys.add(p)
        if s:
            keys.add(s)
    return keys
