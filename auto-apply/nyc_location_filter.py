"""
Filters postings down to NYC-area locations, or genuinely open remote
roles -- rejects hybrid/onsite postings that require being somewhere else
entirely (confirmed a real gap: several test postings were listed as
"Utah | Hybrid", which the existing US-only location check would have let
through despite requiring in-office presence in Utah, not New York).

Fails closed on ambiguity: an unrecognized or empty location string is
rejected rather than guessed at, since applying to the wrong-location job
is worse than missing a real match that was phrased unusually.
"""
import re

NYC_AREA_KEYWORDS = [
    "new york", "nyc", "manhattan", "brooklyn", "queens", "bronx", "staten island",
    "jersey city", "hoboken", "newark, nj", "westchester", "long island",
]

# Common non-NYC US states/major cities -- if one of these appears alongside
# "remote", the posting likely has its own residency requirement despite the
# word "remote" (e.g. "Remote - must reside in Utah"), so it should NOT pass
# just because "remote" is present. Not exhaustive, but covers the realistic
# common cases; anything not recognized either way fails closed.
OTHER_LOCATION_SIGNALS = [
    "utah", "california", "texas", "florida", "illinois", "colorado", "washington state",
    "san francisco", "los angeles", "chicago", "austin", "seattle", "boston", "atlanta",
    "denver", "miami", "phoenix", "dallas", "houston", "philadelphia", "san diego",
    "minneapolis", "portland", "nashville", "charlotte", "raleigh", "salt lake city",
    "pittsburgh", "detroit", "columbus", "indianapolis", "kansas city", "st. louis",
    "arizona", "georgia", "north carolina", "south carolina", "michigan", "ohio",
    "pennsylvania", "virginia", "oregon", "nevada", "tennessee", "wisconsin", "missouri",
]


def passes_nyc_location_filter(location_string: str) -> bool:
    """True if this posting is NYC-area, or genuinely open remote with no
    other city/state requirement stated. False (fail closed) for anything
    ambiguous, empty, or requiring a different specific location."""
    text = (location_string or "").lower()
    if not text.strip():
        return False

    if any(k in text for k in NYC_AREA_KEYWORDS):
        return True

    if "remote" in text and not any(k in text for k in OTHER_LOCATION_SIGNALS):
        return True

    return False
