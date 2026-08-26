"""
Source for the 6 "hard-tier" companies (Microsoft, Accenture, TikTok, Google,
Uber, Amazon) that don't have a public ATS API -- their postings are instead
extracted daily by a Cowork scheduled task and pasted into a single shared
file: state/manual_postings.json

Expected file shape:
{
  "microsoft": [{"title": "...", "location": "...", "url": "...", "description": "..."}, ...],
  "accenture": [...],
  "tiktok": [...],
  "google": [...],
  "uber": [...],
  "amazon": [...]
}

Each run, Cowork should OVERWRITE this file with a full current snapshot of
every marketing-relevant posting it found -- not an incremental diff. That
full-snapshot behavior lets this plug into the exact same stale-posting
pruning logic every other company already uses.
"""
import hashlib
import json
import os

MANUAL_POSTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "manual_postings.json")


def load_manual_postings(company_key: str):
    try:
        with open(MANUAL_POSTINGS_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    postings = data.get(company_key, [])
    out = []
    for p in postings:
        url = p.get("url", "")
        title = p.get("title", "")
        if not url or not title:
            continue  # skip malformed entries rather than crash the whole run
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        out.append({
            "job_id": f"manual-{company_key}-{url_hash}",
            "title": title,
            "location": p.get("location", ""),
            "url": url,
            "description": p.get("description", ""),
            "posted": None,
        })
    return out
