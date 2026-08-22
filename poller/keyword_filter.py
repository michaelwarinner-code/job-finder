"""
Cheap, free, local pre-filter. Runs on every new posting BEFORE any Claude API call.
Goal: eliminate the ~90% of postings that are obviously irrelevant (engineering,
finance, legal, ops, etc.) using only string matching -- zero cost, zero latency.

Only postings that pass this filter get sent to Claude for the real judgment call
(experience-level nuance + true fit), which is the expensive/slow step.
"""

CORE_KEYWORDS = [
    "product marketing", "growth marketing", "performance marketing",
    "lifecycle marketing", "go-to-market", "gtm", "brand marketing",
    "marketing manager", "marketing associate", "marketing specialist",
    "growth associate", "growth analyst", "marketing analyst",
    "consumer marketing", "customer marketing", "retention marketing",
]

# Titles that should never pass, even if they contain a core keyword
# (e.g. "Senior Director, Product Marketing" contains "product marketing" but
# is very obviously not an entry-level role -- caught more precisely by Claude,
# but we can pre-reject the most blatant cases here to save API calls)
HARD_EXCLUDE = [
    "senior director", "vp,", "vice president", "svp", "evp",
    "principal", "head of", "chief marketing officer", "cmo",
]


def passes_keyword_filter(title: str, company_key: str) -> bool:
    t = title.lower()

    if any(bad in t for bad in HARD_EXCLUDE):
        return False

    # Coca-Cola gets the widened net: any marketing role OR any sales role
    if company_key == "cocacola":
        return "marketing" in t or "sales" in t

    return any(kw in t for kw in CORE_KEYWORDS)
