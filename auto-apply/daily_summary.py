"""
Sends a daily summary over Telegram: how many applications went out today,
how close to the cap, and a breakdown of any failures -- read entirely
from state/auto_apply_state.json, so this can run standalone or get
scheduled independently of the discovery/apply cycle itself.

    AUTOAPPLY_TELEGRAM_BOT_TOKEN=... AUTOAPPLY_TELEGRAM_CHAT_ID=... python auto-apply/daily_summary.py
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import auto_apply_state as st
from telegram_escalation import send_message

DAILY_CAP = 15


def build_summary_text(state: dict) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    submitted_count = st.get_daily_count(state)

    # Only jobs actually TOUCHED today, by last_updated date, not the
    # whole all-time history -- a daily summary should reflect today.
    todays_jobs = [j for j in state["jobs"].values() if (j.get("last_updated") or "").startswith(today)]
    status_counts = Counter(j["status"] for j in todays_jobs)

    lines = [
        f"Auto-apply summary for {today}",
        "",
        f"Applications submitted: {submitted_count}/{DAILY_CAP}",
    ]

    failure_statuses = ["failed_materials", "failed_form_scan", "failed_submit", "captcha_blocked"]
    failures = {s: status_counts[s] for s in failure_statuses if status_counts.get(s)}
    if failures:
        lines.append("\nFailures:")
        for s, count in failures.items():
            lines.append(f"  {s}: {count}")

    if status_counts.get("skipped_no_response"):
        lines.append(f"\nSkipped (no answer within 24h): {status_counts['skipped_no_response']}")

    if status_counts.get("pending_answer"):
        lines.append(f"Currently waiting on your answer: {status_counts['pending_answer']}")

    if status_counts.get("judged_reject"):
        lines.append(f"\nReviewed and passed on today: {status_counts['judged_reject']}")

    if not todays_jobs:
        lines.append("\nNo activity recorded today.")

    return "\n".join(lines)


def send_daily_summary():
    state = st.load_state()
    text = build_summary_text(state)
    bot_token = os.environ["AUTOAPPLY_TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["AUTOAPPLY_TELEGRAM_CHAT_ID"]
    send_message(bot_token, chat_id, text)
    print("Sent:\n")
    print(text)


if __name__ == "__main__":
    send_daily_summary()
