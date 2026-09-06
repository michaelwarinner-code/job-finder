"""
Free, local US-location filter. Runs before the Claude call to avoid paying
for judgment on postings we'd reject anyway. Errs toward INCLUDING ambiguous
cases (e.g. bare "Remote" with no country listed) rather than excluding --
a false negative (missing a real match) is worse than one extra Claude call
on a posting that turns out to be non-US.
"""

US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
]

US_CITIES = [
    "san francisco", "new york", "los angeles", "chicago", "boston",
    "seattle", "austin", "denver", "atlanta", "miami", "washington dc",
    "washington, dc", "san diego", "houston", "dallas", "philadelphia",
    "phoenix", "portland", "nashville", "san jose", "oakland", "brooklyn",
    "manhattan", "minneapolis", "detroit", "charlotte", "raleigh",
    "pittsburgh", "columbus", "salt lake city", "sacramento", "santa monica",
]

US_SIGNALS = US_STATES + US_CITIES + [
    "united states", "usa", "u.s.", "u.s.a", "remote - us", "remote, us",
    "remote (us)", "remote-usa",
]

NON_US_SIGNALS = [
    "united kingdom", "uk", "london", "england", "scotland", "ireland",
    "dublin", "canada", "toronto", "vancouver", "montreal", "india",
    "bangalore", "bengaluru", "mumbai", "hyderabad", "germany", "berlin",
    "munich", "france", "paris", "spain", "madrid", "netherlands",
    "amsterdam", "singapore", "australia", "sydney", "melbourne", "japan",
    "tokyo", "china", "beijing", "shanghai", "mexico", "brazil", "colombia",
    "philippines", "manila", "poland", "warsaw", "italy", "milan",
    "sweden", "stockholm", "switzerland", "zurich", "belgium", "brussels",
    "israel", "tel aviv", "south korea", "seoul", "taiwan", "hong kong",
    "eu -", "emea", "apac", "latam", "uae", "united arab emirates", "dubai", "abu dhabi",
    "jakarta", "São Paulo",
]


def is_us_location(location: str) -> bool:
    loc = (location or "").lower()

    if any(sig in loc for sig in US_SIGNALS):
        return True

    if any(sig in loc for sig in NON_US_SIGNALS):
        return False

    return True  # ambiguous/blank -> include, to avoid false negatives

def is_ambiguous_location(location: str) -> bool:
    """Flags cases worth digging deeper into before trusting the default-include
    behavior -- specifically blank locations and Workday's generic
    'Multiple Locations' summary string, which hides the real location list."""
    loc = (location or "").lower().strip()
    if not loc:
        return True
    if "multiple location" in loc:
        return True
    return False
