"""
Structured job locations (city, state code, country, lat/lng) for payload.py.

Cities are looked up in scraper/data/cities_us_ca.tsv, which turns store names
("Chicago Mag Mile, IL Store") into real cities and gives lat/lng for core's
40 km candidate matching. States are codes ("CA") because web's job board and
candidate matching compare codes. A city is never returned without a state,
since web would render "City, null".
"""
import csv
import logging
import os
import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import pycountry

_CITIES_FILE = os.path.join(os.path.dirname(__file__), "data", "cities_us_ca.tsv")
_COUNTRIES = ("US", "CA")

_LOCATION_LINE_RE = re.compile(r"^\s*Location\s*:\s*(.+?)\s*$", re.IGNORECASE)
_ALTERNATIVES_RE = re.compile(r"\s+(?:and/or|or|and)\s+|\s*;\s*|\s+/\s+")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z.'\-]*|,")


@lru_cache(maxsize=1)
def _states() -> Dict[str, Tuple[str, str, str]]:
    """Code ("CA") or lowercase full name ("california") -> (code, full name, country)."""
    states = {}
    for country in _COUNTRIES:
        for sub in pycountry.subdivisions.get(country_code=country):
            code = sub.code.split("-")[1]
            states[code] = states[sub.name.lower()] = (code, sub.name, country)
    return states


_ABBREVIATIONS = {"st": "saint", "ste": "sainte", "mt": "mount", "ft": "fort"}


def _city_key(name: str) -> str:
    """Spelling-insensitive key: "St George" == "St. George" == "Saint George",
    "Bailey's Crossroads" == "Baileys Crossroads" (GeoNames' spellings)."""
    words = re.sub(r"[.'’]", "", name.lower()).split()
    return " ".join(_ABBREVIATIONS.get(w, w) for w in words)


@lru_cache(maxsize=1)
def _cities() -> Dict[Tuple[str, str], Tuple[float, float]]:
    """(city key, state code) -> (lat, lng)."""
    with open(_CITIES_FILE, encoding="utf-8") as f:
        rows = csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t")
        return {(_city_key(r["city"]), r["state"]): (float(r["lat"]), float(r["lng"])) for r in rows}


def location_line(description: Optional[str]) -> Optional[str]:
    """Value of a "**Location:** ..." line in the posting text, if any."""
    for line in (description or "").splitlines():
        match = _LOCATION_LINE_RE.match(line.replace("*", ""))
        if match:
            return match.group(1)
    return None


def _find_state(tokens: List[str]) -> Optional[Tuple[int, Tuple[str, str, str]]]:
    """Last state in the tokens: a code ("CA", "B.C.") or a full name ("New York")."""
    states = _states()
    for end in range(len(tokens) - 1, -1, -1):
        code = tokens[end].replace(".", "")
        if code.isupper() and code in states:
            return end, states[code]
        for size in (3, 2, 1):
            start = end - size + 1
            name = " ".join(tokens[start:end + 1]).lower() if start >= 0 else ""
            if name in states and "," not in name:
                return start, states[name]
    return None


def _find_city(words: List[str], state: str) -> Optional[Tuple[str, float, float]]:
    """Longest run of words that is a real city in that state, e.g. "Chicago Mag Mile" -> Chicago.
    Returns the city as the posting spells it."""
    cities = _cities()
    for size in range(len(words), 0, -1):
        for start in range(len(words) - size + 1):
            city = " ".join(words[start:start + size])
            hit = cities.get((_city_key(city), state))
            if hit:
                return city, hit[0], hit[1]
    return None


def _parse_one(text: str) -> Optional[Dict]:
    tokens = _TOKEN_RE.findall(re.sub(r"\([^)]*\)", " ", text))
    found = _find_state(tokens)
    if not found:
        return None
    state_at, (state, state_name, country) = found

    # City words: the comma-separated part right before the state,
    # e.g. "Fletcher Chouinard Designs, Ventura CA Store" -> ["Ventura"].
    i = state_at - 1
    if i >= 0 and tokens[i] == ",":
        i -= 1
    city_words = []
    while i >= 0 and tokens[i] != ",":
        city_words.insert(0, tokens[i])
        i -= 1

    city = _find_city(city_words, state) if city_words else None
    if city_words and not city:
        logging.info(f"Location: no city match for {' '.join(city_words)!r} in {state}, sending state only")
    return {
        "city": city[0] if city else None,
        "state": state,
        "state_name": state_name,
        "country": country,
        "country_name": pycountry.countries.get(alpha_2=country).name,
        "lat": city[1] if city else 0,
        "lng": city[2] if city else 0,
    }


def _parse_text(text: str) -> List[Dict]:
    locations = []
    for part in _ALTERNATIVES_RE.split(text):
        location = _parse_one(part)
        if location and location not in locations:
            locations.append(location)
    return locations


def parse_locations(line: Optional[str], jsonld_struct: Optional[Dict]) -> List[Dict]:
    """The "Location:" line wins when it names a state (it has real cities and every
    location when there are several); JSON-LD is the fallback."""
    locations = _parse_text(line) if line else []
    if locations or not jsonld_struct:
        return locations
    city, region = jsonld_struct.get("city") or "", jsonld_struct.get("region") or ""
    return _parse_text(f"{city}, {region}" if region else city)
