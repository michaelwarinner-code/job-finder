"""
Direct company-board comparison, for checking discovery against what you
can see yourself on a company's actual Greenhouse/Ashby page. Fetches
EVERY live posting straight from that one company's board -- bypassing
the Fantastic Jobs aggregator, its keyword list, and its 7-day window
entirely -- then cross-references each posting's URL against
state/auto_apply_state.json and state/auto_apply_audit_log.csv to show
whether/how discovery has judged it.

Get the token from the company's careers page URL:
  Greenhouse: https://job-boards.greenhouse.io/<token>          -> --ats greenhouse --token <token>
  Ashby:      https://jobs.ashbyhq.com/<token>                  -> --ats ashby --token <token>

Usage:
    python auto-apply/compare_company_board.py --ats greenhouse --token airbnb
    python auto-apply/compare_company_board.py --ats ashby --token linear

A posting showing "never seen by discovery" means the aggregator search
never surfaced it -- most likely its title didn't overlap with
broad_source.SEARCH_KEYWORDS, or it's a company that also happens to be
on your target list (which is excluded from broad discovery on purpose,
since the target-list track handles those separately) -- not that the fit
judge rejected it.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import auto_apply_state as st
from ats_fetchers import fetch_greenhouse, fetch_ashby

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "auto_apply_audit_log.csv")


def _load_audit_reasons() -> dict:
    """Returns {url: most_recent_audit_row_dict}. If a URL was judged more
    than once across runs, the last row wins (the CSV is append-only in
    chronological order)."""
    reasons = {}
    if not os.path.exists(AUDIT_LOG_PATH):
        return reasons
    with open(AUDIT_LOG_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            reasons[row["url"]] = row
    return reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ats", required=True, choices=["greenhouse", "ashby"])
    parser.add_argument("--token", required=True, help="Board token from the company's careers URL")
    args = parser.parse_args()

    fetch_fn = fetch_greenhouse if args.ats == "greenhouse" else fetch_ashby
    try:
        live_jobs = fetch_fn(args.token)
    except Exception as e:
        raise SystemExit(f"Could not fetch the {args.ats} board for token '{args.token}': {e}")

    print(f"[setup] {len(live_jobs)} live posting(s) currently on this board\n")

    state = st.load_state()
    audit_reasons = _load_audit_reasons()

    never_seen = 0
    seen_counts = {}

    for job in live_jobs:
        title = job.get("title", "")
        url = job.get("url", "")

        status = st.get_job_status(state, url)
        if status is None:
            never_seen += 1
            print(f"[NEVER SEEN BY DISCOVERY]  {title}\n    {url}")
            continue

        seen_counts[status] = seen_counts.get(status, 0) + 1
        line = f"[{status}]  {title}\n    {url}"
        row = audit_reasons.get(url)
        if row and row.get("reason"):
            line += f"\n    reason: {row['reason']}  (is_software_company={row.get('is_software_company')})"
        print(line)

    print("\n=== SUMMARY ===")
    print(f"{len(live_jobs)} live posting(s) on the board")
    print(f"{never_seen} never seen by discovery at all")
    for status, count in sorted(seen_counts.items()):
        print(f"{count} already tracked as: {status}")


if __name__ == "__main__":
    main()
