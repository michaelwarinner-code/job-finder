"""
Standalone runner for the auto-apply track's discovery stage, wiring together:
  1. broad_source.py       -- Fantastic Jobs search, filtered to Greenhouse/Ashby
  2. target_list_exclusion -- drop anything already on the curated target list
  3. keyword_filter.py     -- reuse the existing free local pre-filter as-is
  4. ats_fetchers.py       -- re-fetch the CLEAN posting data from the actual
                               ATS (not the aggregator's copy) using the token
                               parsed out of the apply URL
  5. claude_judge_broad.py -- role fit + strict software-core gate

Intentionally NOT wired into GitHub Actions yet, and does not write to any
application-state file -- this is for confirming steps 1-5 behave correctly
against real data before anything downstream (materials writer, applier,
answer bank) gets built on top of it.

Every judged posting (not just matches) is logged to
state/auto_apply_audit_log.csv, so rejections can be reviewed for false
negatives -- in particular, whether the software-core gate is wrongly
rejecting real tech companies. Open that file in Excel/Sheets and filter
is_software_company=False to review the gate specifically, or match=False
to review every rejection reason. Run locally:

    AUTOAPPLY_ANTHROPIC_API_KEY=... FANTASTIC_JOBS_API_KEY=... python auto-apply/broad_discover_run.py
"""
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from broad_source import discover_greenhouse_ashby_postings
from target_list_exclusion import is_target_list_company, load_target_company_names
from keyword_filter import passes_keyword_filter
from ats_fetchers import fetch_greenhouse, fetch_ashby
from location_filter import is_us_location
from nyc_location_filter import passes_nyc_location_filter
from claude_judge_broad import judge_fit_broad
import auto_apply_state as st

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "candidate_profile.md")
AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "auto_apply_audit_log.csv")
AUDIT_FIELDS = ["timestamp", "company_name", "ats", "title", "url", "match", "is_software_company", "reason"]


def log_audit_rows(rows: list):
    """Appends every judged posting to a CSV, creating it with a header on
    first run. The same posting may get logged again on a later run if it's
    still live -- that's fine for review purposes, it's a record of what the
    judge decided each time, not a dedup log."""
    if not rows:
        return
    file_exists = os.path.exists(AUDIT_LOG_PATH)
    with open(AUDIT_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def load_profile():
    with open(PROFILE_PATH) as f:
        return f.read()


def main():
    profile = load_profile()
    target_names = load_target_company_names()
    print(f"[setup] {len(target_names)} companies on the target list, will exclude those")

    state = st.load_state()
    expired = st.expire_stale_pending(state, timeout_hours=24)
    if expired:
        print(f"[setup] {len(expired)} job(s) past 24h with no answer, auto-skipped: {expired}")

    fantastic_key = os.environ["FANTASTIC_JOBS_API_KEY"]
    raw_postings = discover_greenhouse_ashby_postings(fantastic_key)

    # Dedupe to one entry per (ats, board_token) -- the same company shows up once
    # per keyword hit, but we only need to fetch its board once.
    seen_boards = {}
    for p in raw_postings:
        key = (p["ats"], p["board_token"])
        if key not in seen_boards:
            seen_boards[key] = p["company_name"]

    print(f"[setup] {len(seen_boards)} unique company boards to check")

    matches = []
    audit_rows = []
    already_seen_count = 0
    now = datetime.now(timezone.utc).isoformat()

    for (ats, token), company_name in seen_boards.items():
        if is_target_list_company(company_name, target_names):
            print(f"[skip-target-list] {company_name}")
            continue

        try:
            jobs = fetch_greenhouse(token) if ats == "greenhouse" else fetch_ashby(token)
        except Exception as e:
            print(f"[{token}] FETCH FAILED: {e}")
            continue

        print(f"[{token}] ({ats}) {len(jobs)} live postings")

        for job in jobs:
            title = job["title"]
            job_url = job.get("url", "")

            # Skip re-judging (and re-spending an API call on) any posting
            # we've already judged in a previous run, regardless of the
            # verdict -- a still-live rejected posting would otherwise get
            # re-judged, and re-billed, every single cycle indefinitely.
            if st.get_job_status(state, job_url) is not None:
                already_seen_count += 1
                continue

            if not passes_keyword_filter(title, token):
                continue

            loc_string = job.get("location_blob", job.get("location", ""))
            if not is_us_location(loc_string):
                continue
            if not passes_nyc_location_filter(loc_string):
                continue

            try:
                verdict = judge_fit_broad(title, job.get("description", ""), company_name, profile)
            except Exception as e:
                print(f"[{token}] judge failed for '{title}': {e}")
                continue

            print(f"  '{title}' -> match={verdict['match']} | software={verdict['is_software_company']} "
                  f"| {verdict['reason']}")

            audit_rows.append({
                "timestamp": now,
                "company_name": company_name,
                "ats": ats,
                "title": title,
                "url": job_url,
                "match": verdict["match"],
                "is_software_company": verdict["is_software_company"],
                "reason": verdict["reason"],
            })

            status = "judged_fit" if verdict["match"] else "judged_reject"
            st.set_job_status(state, job_url, status, company_name=company_name, title=title, url=job_url,
                               ats=ats, board_token=token)

            if verdict["match"]:
                matches.append({
                    "company_name": company_name, "ats": ats, "board_token": token,
                    "title": title, "url": job_url, "reason": verdict["reason"],
                })

    st.save_state(state)
    log_audit_rows(audit_rows)
    rejected_for_software = sum(1 for r in audit_rows if not r["is_software_company"])
    print(f"\n[state] {already_seen_count} posting(s) already judged in a previous run, skipped without re-judging")
    print(f"[audit] logged {len(audit_rows)} newly-judged postings to {AUDIT_LOG_PATH}")
    print(f"[audit] {rejected_for_software} of those were rejected specifically for failing "
          f"the software-core gate -- review those rows for false negatives")

    print(f"\n=== {len(matches)} new matches this run ===")
    for m in matches:
        print(f"[{m['ats']}] {m['company_name']} -- {m['title']}\n  {m['url']}\n  {m['reason']}\n")


if __name__ == "__main__":
    main()
