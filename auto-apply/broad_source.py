"""
Broad job discovery for the auto-apply track (non-target-list companies).

Searches the Fantastic Jobs API (RapidAPI pay-as-you-go tier) across a set of
marketing/growth keywords, then keeps only postings whose apply URL is hosted
on Greenhouse or Ashby -- those are the only two ATS platforms the Playwright
applier (built separately) knows how to fill out. The board token is parsed
straight out of the apply URL, then handed to the existing ats_fetchers.py
fetch_greenhouse()/fetch_ashby() so the actual posting data (full description,
structured location, application form schema) comes from the clean ATS API,
not from the aggregator's own (possibly truncated) copy.

VERIFIED against a live RapidAPI Playground screenshot: host is
active-jobs-db.p.rapidapi.com, path is /active-ats, and the real param names
are `title`, `location` (quoted country string, e.g. '"United States"'),
`time_frame`, `limit`, `offset`, `description_format`. The response field
names below (job.get("url")/("company_name")/etc.) are still unverified --
confirm those against a real response the first time this actually runs,
and adjust the field lookups in discover_greenhouse_ashby_postings() if
they don't match (the constants above are already correct, don't need to
change again).
"""
import os
import re
import time
import requests

FANTASTIC_HOST = "active-jobs-db.p.rapidapi.com"
FANTASTIC_URL = f"https://{FANTASTIC_HOST}/active-ats"
TIMEOUT = 30
REQUEST_DELAY_SECONDS = 2  # pause between each keyword search
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

GREENHOUSE_URL_RE = re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9_-]+)")
ASHBY_URL_RE = re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)")

# Kept broad and overlapping with keyword_filter.py's POSITIVE_SIGNALS on purpose --
# this list decides what we ASK the aggregator for; keyword_filter.py still runs
# afterward as the free local re-check before anything reaches the Claude judge.
SEARCH_KEYWORDS = [
    "growth marketing", "product marketing", "performance marketing",
    "demand generation", "revenue operations", "lifecycle marketing",
    "go-to-market marketing", "growth strategist", "marketing analyst",
]


def _extract_ats_and_token(job: dict):
    """Prefers the API's own source/source_slug fields (confirmed present in
    live responses) over regex-parsing the apply URL, which only worked
    before by coincidence (job-boards.greenhouse.io happens to contain the
    substring boards.greenhouse.io). Falls back to URL parsing only if
    source/source_slug are ever missing from a given record."""
    source = (job.get("source") or "").lower()
    slug = job.get("source_slug")
    if source in ("greenhouse", "ashby") and slug:
        return source, slug

    apply_url = job.get("url") or job.get("final_url") or job.get("application_url", "")
    if not apply_url:
        return None, None
    gh = GREENHOUSE_URL_RE.search(apply_url)
    if gh:
        return "greenhouse", gh.group(1)
    ashby = ASHBY_URL_RE.search(apply_url)
    if ashby:
        return "ashby", ashby.group(1)
    return None, None


def _search_fantastic_jobs(title_query: str, api_key: str) -> dict:
    headers = {"x-rapidapi-host": FANTASTIC_HOST, "x-rapidapi-key": api_key}
    params = {
        "title": title_query,
        "location": '"United States"',
        "time_frame": "24h",
        "limit": 500,
        "offset": 0,
        "description_format": "text",
    }
    r = requests.get(FANTASTIC_URL, headers=headers, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _build_combined_title_query() -> str:
    """Combines all keywords into one OR query, e.g. '"growth marketing" OR
    "product marketing" OR ...' -- confirmed via live RapidAPI docs that the
    title param supports Google-style OR syntax, so this turns what used to
    be 9 separate requests into 1, cutting request volume 9x with no loss
    in coverage."""
    return " OR ".join(f'"{kw}"' for kw in SEARCH_KEYWORDS)


def discover_greenhouse_ashby_postings(api_key: str) -> list:
    """
    Runs ONE combined-keyword search (all of SEARCH_KEYWORDS OR'd together
    into a single title query), keeps only Greenhouse/Ashby-hosted postings,
    dedupes by apply URL, and returns:
        [{"ats": "greenhouse"|"ashby", "board_token": str,
          "company_name": str, "title": str, "apply_url": str}, ...]
    """
    combined_title = _build_combined_title_query()
    seen_urls = set()
    out = []

    data = None
    for attempt in range(MAX_RETRIES):
        try:
            data = _search_fantastic_jobs(combined_title, api_key)
            break
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_SECONDS * (attempt + 1)
                print(f"[broad-discovery] rate limited, retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                print(f"[broad-discovery] search failed: {e}")
        except requests.RequestException as e:
            print(f"[broad-discovery] search failed: {e}")
            break

    if data is None:
        print("[broad-discovery] no data returned, returning empty result set")
        return out

    records = data if isinstance(data, list) else data.get("jobs", [])

    if records:
        # One-time diagnostic on the first run, so field names can be confirmed
        # in a single pass instead of guessing blind.
        import json as _json
        print("[debug] sample raw record from the API:")
        print(_json.dumps(records[0], indent=2)[:1500])

    for job in records:
        apply_url = job.get("url") or job.get("final_url") or job.get("application_url", "")
        if not apply_url or apply_url in seen_urls:
            continue
        ats, token = _extract_ats_and_token(job)
        if not ats:
            continue  # not Greenhouse/Ashby-hosted -- applier can't handle it, skip
        seen_urls.add(apply_url)
        out.append({
            "ats": ats,
            "board_token": token,
            "company_name": job.get("organization") or job.get("company_name") or job.get("company", ""),
            "title": job.get("title", ""),
            "apply_url": apply_url,
        })

    print(f"[broad-discovery] {len(out)} unique Greenhouse/Ashby postings found "
          f"from 1 combined-keyword request (was {len(SEARCH_KEYWORDS)} separate requests before)")
    return out


if __name__ == "__main__":
    # Standalone smoke test: python poller/broad_source.py
    # Prints what the aggregator returns before anything downstream touches it,
    # so you can confirm field names/response shape against a real key.
    key = os.environ.get("FANTASTIC_JOBS_API_KEY")
    if not key:
        raise SystemExit("Set FANTASTIC_JOBS_API_KEY to test this standalone.")
    postings = discover_greenhouse_ashby_postings(key)
    for p in postings[:20]:
        print(f"  [{p['ats']}] {p['company_name']} -- {p['title']} (token={p['board_token']})")
