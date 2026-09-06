"""
Tracks per-job application status and enforces the daily application cap,
so the pipeline can run on a schedule without double-applying to the same
job or blowing past your 15/day limit.

State file: state/auto_apply_state.json
{
  "daily": {"date": "2026-09-05", "count": 3},
  "jobs": {
    "<job_id>": {
      "status": "discovered" | "judged_fit" | "materials_generated" |
                 "pending_answer" | "ready_to_submit" | "submitted" |
                 "skipped_no_response" | "failed_materials" |
                 "failed_form_scan" | "failed_submit" | "captcha_blocked",
      "company_name": str, "title": str, "url": str,
      "first_seen": iso timestamp, "last_updated": iso timestamp,
      "pending_since": iso timestamp (only while status == pending_answer)
    }
  }
}

job_id should be a stable identifier for the posting -- the ATS's own job
id if available, otherwise the apply URL itself works fine as a key.
"""
import json
import os
from datetime import datetime, timezone, timedelta

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "auto_apply_state.json")

TERMINAL_STATUSES = {"submitted", "skipped_no_response", "failed_materials",
                      "failed_form_scan", "failed_submit", "captcha_blocked"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"daily": {"date": "", "count": 0}, "jobs": {}}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def get_daily_count(state: dict) -> int:
    """Returns today's application count, resetting to 0 automatically if
    the stored date isn't today (a new day starts a fresh count)."""
    if state["daily"].get("date") != _today_str():
        return 0
    return state["daily"].get("count", 0)


def increment_daily_count(state: dict):
    """Call this once per successful submission. Resets the counter first
    if the stored date has rolled over to a new day."""
    if state["daily"].get("date") != _today_str():
        state["daily"] = {"date": _today_str(), "count": 0}
    state["daily"]["count"] += 1


def is_daily_cap_reached(state: dict, cap: int = 15) -> bool:
    return get_daily_count(state) >= cap


def get_job_status(state: dict, job_id: str):
    job = state["jobs"].get(job_id)
    return job["status"] if job else None


def is_already_handled(state: dict, job_id: str) -> bool:
    """True if this job has already reached a terminal status (submitted,
    permanently skipped, or failed) -- callers should skip re-processing
    it entirely rather than risk a double application."""
    status = get_job_status(state, job_id)
    return status in TERMINAL_STATUSES


def set_job_status(state: dict, job_id: str, status: str, company_name: str = "",
                    title: str = "", url: str = "", ats: str = "", board_token: str = ""):
    """Creates or updates a job's tracked status. Setting status to
    'pending_answer' stamps pending_since (used by expire_stale_pending());
    moving to any other status clears it. ats/board_token let a later
    pipeline stage re-fetch the live posting (description, current
    open/closed state) without needing to cache potentially-stale content."""
    existing = state["jobs"].get(job_id, {})
    job = {
        "status": status,
        "company_name": company_name or existing.get("company_name", ""),
        "title": title or existing.get("title", ""),
        "url": url or existing.get("url", ""),
        "ats": ats or existing.get("ats", ""),
        "board_token": board_token or existing.get("board_token", ""),
        "first_seen": existing.get("first_seen", _now_iso()),
        "last_updated": _now_iso(),
    }
    if status == "pending_answer":
        job["pending_since"] = existing.get("pending_since", _now_iso())
    state["jobs"][job_id] = job


def expire_stale_pending(state: dict, timeout_hours: int = 24) -> list:
    """Marks any job stuck in pending_answer for longer than timeout_hours
    as skipped_no_response, so a question you never got to doesn't block
    that job forever. Returns the list of job_ids that got expired, so the
    caller can notify about them if desired."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
    expired = []
    for job_id, job in state["jobs"].items():
        if job.get("status") != "pending_answer":
            continue
        pending_since = job.get("pending_since")
        if not pending_since:
            continue
        try:
            since_dt = datetime.fromisoformat(pending_since)
        except ValueError:
            continue
        if since_dt < cutoff:
            job["status"] = "skipped_no_response"
            job["last_updated"] = _now_iso()
            expired.append(job_id)
    return expired
