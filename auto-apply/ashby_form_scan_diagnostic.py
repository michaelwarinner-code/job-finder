"""
Diagnostic tool for Ashby's application form structure. Ashby's public job
listing endpoint (used by ats_fetchers.fetch_ashby) only returns posting
metadata (title, location, description) -- NOT the application form's
questions. This script hits the per-job detail endpoint to see whether
question/field data comes back there.

I'm building this as a print-and-inspect diagnostic rather than guessing
the real shape and writing parsing code against a guess -- same mistake I
made with the Fantastic Jobs endpoint earlier, worth not repeating. Run
this against a REAL job from one of your matches, read the printed JSON,
and we'll build the actual field-parsing code (ashby_form_scan proper)
against whatever it actually returns.

Usage: edit BOARD_TOKEN and JOB_ID below to a real Ashby posting from your
last discovery run (job_id is the part after the board token in the job's
url, e.g. for https://jobs.ashbyhq.com/Clera/54fc9546-f535-4def-b9c0-dd4e18f02c4b
board_token="Clera", job_id="54fc9546-f535-4def-b9c0-dd4e18f02c4b").

    python auto-apply/ashby_form_scan_diagnostic.py
"""
import json
import requests

BOARD_TOKEN = "Clera"
JOB_ID = "54fc9546-f535-4def-b9c0-dd4e18f02c4b"

HEADERS = {"User-Agent": "job-alert-bot/1.0 (personal use)"}
TIMEOUT = 20


def main():
    # Attempt 1: per-job detail via the same public job-board API used for listings.
    url = f"https://api.ashbyhq.com/posting-api/job-board/{BOARD_TOKEN}/{JOB_ID}"
    print(f"[attempt 1] GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    print(f"  status: {r.status_code}")
    if r.ok:
        data = r.json()
        print(json.dumps(data, indent=2)[:4000])
        print(f"\n  top-level keys: {list(data.keys())}")
    else:
        print(f"  body: {r.text[:500]}")


if __name__ == "__main__":
    main()
