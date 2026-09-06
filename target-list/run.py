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

Failed Telegram sends are queued in state["pending_notifications"] and
retried at the start of every run, up to MAX_NOTIFY_ATTEMPTS times, so a
transient failure (or a bad character that used to silently eat the alert)
doesn't just vanish.

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
from manual_source import load_manual_postings
from location_filter import is_us_location, is_ambiguous_location
from keyword_filter import passes_keyword_filter
from claude_judge import judge_fit
from telegram import send_telegram_alert

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "state.json")
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "candidate_profile.md")

MAX_NOTIFY_ATTEMPTS = 5

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
        return jobs
    if ats == "manual":
        return load_manual_postings(key)
    fetcher = FETCHERS[ats]
    return fetcher(cfg["board_token"])


def queue_notification(state, job_id, company_key, company_name, title, location, url, reason, is_priority):
    state["pending_notifications"].append({
        "job_id": job_id,
        "company_key": company_key,
        "company_name": company_name,
        "title": title,
        "location": location,
        "url": url,
        "reason": reason,
        "is_priority": is_priority,
        "attempts": 1,
    })


def flush_pending_notifications(state):
    pending = state.get("pending_notifications", [])
    if not pending:
        return

    print(f"[notify-retry] {len(pending)} pending notification(s) to retry")
    still_pending = []
    for entry in pending:
        try:
            send_telegram_alert(
                entry["company_name"], entry["title"], entry["location"],
                entry["url"], entry["reason"],
                os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
                entry.get("is_priority", True),
            )
            print(f"[notify-retry] sent: {entry['title']} ({entry['company_name']})")
        except Exception as e:
            entry["attempts"] += 1
            if entry["attempts"] >= MAX_NOTIFY_ATTEMPTS:
                print(f"[notify-retry] GIVING UP after {entry['attempts']} attempts on "
                      f"'{entry['title']}' ({entry['company_name']}): {e}")
            else:
                print(f"[notify-retry] attempt {entry['attempts']} failed for "
                      f"'{entry['title']}' ({entry['company_name']}): {e}")
                still_pending.append(entry)

    state["pending_notifications"] = still_pending


def main():
    state = load_state()
    state.setdefault("pending_notifications", [])
    profile = load_profile()
    now = datetime.now(timezone.utc).isoformat()

    flush_pending_notifications(state)

    for key, cfg in state["companies"].items():
        if not cfg["enabled"]:
            continue
        if TARGET_COMPANY and key != TARGET_COMPANY:
            continue

        is_resync = cfg.get("needs_resync", False)
        if is_resync:
            state["matches"] = [m for m in state["matches"] if m["company_key"] != key]
        print(f"[{key}] fetching (resync={is_resync})...")

        try:
            live_jobs = fetch_company_jobs(key, cfg)
        except Exception as e:
            print(f"[{key}] FETCH FAILED: {e}")
            continue

        known_ids = set(cfg.get("known_job_ids", []))
        live_ids = {j["job_id"] for j in live_jobs}

        if is_resync:
            state["matches"] = [m for m in state["matches"] if m["company_key"] != key]
        else:
            # Prune matches for postings that have since closed, even on normal runs
            state["matches"] = [
                m for m in state["matches"]
                if not (m["company_key"] == key and m["id"] not in live_ids)
            ]
        new_jobs = live_jobs if is_resync else [j for j in live_jobs if j["job_id"] not in known_ids]

        print(f"[{key}] {len(live_jobs)} live, {len(new_jobs)} to evaluate")
        if key == "cocacola":
            print(f"[{key}] ALL LIVE TITLES: {[j['title'] for j in live_jobs]}")

        for job in new_jobs:
            title = job["title"]

            if not passes_keyword_filter(title, key):
                print(f"[{key}] KEYWORD-REJECT: '{title}'")
                known_ids.add(job["job_id"])
                continue

            description = job.get("description", "")
            loc_string = job.get("location_blob", job.get("location", ""))

            if cfg["ats"] == "workday" and job.get("_workday_path"):
                try:
                    fetched_desc, full_location = fetch_workday_job_description(
                        cfg["workday_tenant"], cfg["workday_site"], job["_workday_path"]
                    )
                    if fetched_desc:
                        description = fetched_desc
                    if full_location:
                        loc_string = full_location
                except Exception as e:
                    print(f"[{key}] workday detail fetch failed for {job['job_id']}: {e}")

            if not is_us_location(loc_string):
                print(f"[{key}] LOCATION-REJECT: '{title}' | location={loc_string!r}")
                known_ids.add(job["job_id"])
                continue

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
                            cfg["name"], title, job.get("location", ""), job.get("url", ""), verdict["reason"],
                            os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
                            cfg.get("is_priority", True)
                        )
                    except Exception as e:
                        print(f"[{key}] Telegram send failed, queuing for retry: {e}")
                        queue_notification(
                            state, job["job_id"], key, cfg["name"], title,
                            job.get("location", ""), job.get("url", ""), verdict["reason"],
                            cfg.get("is_priority", True),
                        )
                else:
                    print(f"[{key}] resync match (notification suppressed): {title}")

        cfg["known_job_ids"] = sorted(known_ids)
        cfg["needs_resync"] = False

    state["last_run"] = now
    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
