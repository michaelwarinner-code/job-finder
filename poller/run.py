"""
Main entrypoint, run by GitHub Actions on a schedule (and on-demand via
workflow_dispatch when a company is toggled back on for an immediate resync).

Logic per enabled company:
  1. Fetch current live postings from the ATS.
  2. Diff against known_job_ids to find NEW postings.
     - If needs_resync=True, treat EVERY currently-live posting as "new" for
       evaluation purposes (full catch-up), but suppress Telegram notifications
       for that pass (avoids a notification storm on re-toggle) -- they still
       populate the dashboard.
  3. Run the free keyword pre-filter on new postings.
  4. Run the Claude fit-judgment call only on postings that pass step 3.
  5. For matches: add to state.matches, send Telegram (unless this is a
     suppressed resync pass), and add job_id to known_job_ids either way
     (matched or not) so we don't re-evaluate it again.
  6. Write state.json back to disk (committed to the repo by the workflow step).

Disabled companies are skipped entirely -- no fetch, no cost -- and their
existing matches are filtered out at DISPLAY time by the dashboard (not
deleted here), per spec.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from ats_fetchers import FETCHERS, fetch_workday, fetch_workday_job_description
from keyword_filter import passes_keyword_filter
from claude_judge import judge_fit
from telegram import send_telegram_alert

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "state.json")
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "candidate_profile.md")

# Optional: restrict this run to a single company (used by the "resync on
# toggle-on" workflow_dispatch trigger). Set via env var by the workflow.
TARGET_COMPANY = os.environ.get("TARGET_COMPANY", "").strip() or None


def load_state():
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def load_profile():
    with open(PROFILE_PATH) as f:
        return f.read()


def fetch_company_jobs(key, cfg):
    ats = cfg["ats"]
    if ats == "workday":
        jobs = fetch_workday(cfg["workday_tenant"], cfg["workday_site"])
        # Workday needs a 2nd call per job for description -- only do this
        # lazily, later, for jobs that pass the keyword filter (cost control).
        return jobs
    fetcher = FETCHERS[ats]
    return fetcher(cfg["board_token"])


def main():
    state = load_state()
    profile = load_profile()
    now = datetime.now(timezone.utc).isoformat()

    for key, cfg in state["companies"].items():
        if not cfg["enabled"]:
            continue
        if TARGET_COMPANY and key != TARGET_COMPANY:
            continue

        is_resync = cfg.get("needs_resync", False)
        print(f"[{key}] fetching (resync={is_resync})...")

        try:
            live_jobs = fetch_company_jobs(key, cfg)
        except Exception as e:
            print(f"[{key}] FETCH FAILED: {e}")
            continue

        known_ids = set(cfg.get("known_job_ids", []))
        new_jobs = live_jobs if is_resync else [j for j in live_jobs if j["job_id"] not in known_ids]

        print(f"[{key}] {len(live_jobs)} live, {len(new_jobs)} to evaluate")

        for job in new_jobs:
            title = job["title"]

            if not passes_keyword_filter(title, key):
                known_ids.add(job["job_id"])
                continue

            description = job.get("description", "")
            if cfg["ats"] == "workday" and not description and job.get("_workday_path"):
                try:
                    description = fetch_workday_job_description(
                        cfg["workday_tenant"], cfg["workday_site"], job["_workday_path"]
                    )
                except Exception as e:
                    print(f"[{key}] workday description fetch failed for {job['job_id']}: {e}")

            try:
                verdict = judge_fit(title, description, cfg["name"], profile)
                print(f"[{key}] '{title}' -> match={verdict['match']} | {verdict['reason']}")
            except Exception as e:
                print(f"[{key}] Claude judgment failed for {job['job_id']}: {e}")
                continue

            known_ids.add(job["job_id"])

            if verdict["match"]:
                match_entry = {
                    "id": job["job_id"],
                    "company_key": key,
                    "company_name": cfg["name"],
                    "title": title,
                    "location": job.get("location", ""),
                    "url": job.get("url", ""),
                    "first_seen": now,
                    "fit_reason": verdict["reason"],
                }
                # avoid duplicate entries if this job_id was already matched before
                state["matches"] = [m for m in state["matches"] if m["id"] != job["job_id"]]
                state["matches"].append(match_entry)

                if not is_resync:
                    try:
                        send_telegram_alert(
                            cfg["name"], title, job.get("location", ""), job.get("url", ""), verdict["reason"]
                        )
                    except Exception as e:
                        print(f"[{key}] Telegram send failed: {e}")
                else:
                    print(f"[{key}] resync match (notification suppressed): {title}")

        cfg["known_job_ids"] = sorted(known_ids)
        cfg["needs_resync"] = False

    state["last_run"] = now
    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
