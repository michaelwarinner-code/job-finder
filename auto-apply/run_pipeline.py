"""
The real end-to-end pipeline: for every job sitting in 'judged_fit' status
(found by broad_discover_run.py but never carried further), this
re-fetches the live posting, generates tailored materials, builds real
PDFs, fills the application, and -- only if dry_run is explicitly set to
False -- submits it. Respects the daily cap and updates job status at
every stage, so a failure partway through is visible and never silently
retried into a duplicate.

Falls back to parsing ats/board_token from the URL for jobs that were
judged before that field existed in state (older entries).

    AUTOAPPLY_ANTHROPIC_API_KEY=... AUTOAPPLY_TELEGRAM_BOT_TOKEN=... AUTOAPPLY_TELEGRAM_CHAT_ID=... python auto-apply/run_pipeline.py

THIS ACTUALLY SUBMITS REAL APPLICATIONS IF DRY_RUN IS FALSE. Leave True
for every test run.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import auto_apply_state as st
from ats_fetchers import fetch_greenhouse, fetch_ashby
from materials_writer import generate_materials
from pdf_builder import build_resume_and_coverletter
from form_filler import fill_application
from telegram_escalation import PendingAnswerRequired
from sheets_logger import append_application_row
from application_archive import archive_application
from broad_source import GREENHOUSE_URL_RE, ASHBY_URL_RE

DAILY_CAP = 15
DRY_RUN = True  # THIS ACTUALLY SUBMITS REAL APPLICATIONS IF SET TO FALSE.
OUTPUT_ROOT = os.path.join(os.path.dirname(__file__), "pipeline_output")


def _resolve_ats_and_token(job: dict):
    """Uses stored ats/board_token if present (jobs judged after that field
    was added), otherwise falls back to parsing them from the URL --
    handles older entries judged before this field existed."""
    if job.get("ats") and job.get("board_token"):
        return job["ats"], job["board_token"]

    url = job.get("url", "")
    gh = GREENHOUSE_URL_RE.search(url)
    if gh:
        return "greenhouse", gh.group(1)
    ashby = ASHBY_URL_RE.search(url)
    if ashby:
        return "ashby", ashby.group(1)
    return None, None


def _find_live_posting(ats: str, board_token: str, title: str, url: str):
    """Re-fetches the board fresh and finds the specific posting by URL
    match, so we get the current, real description rather than anything
    cached -- also naturally handles the case where a posting has since
    been taken down (returns None)."""
    jobs = fetch_greenhouse(board_token) if ats == "greenhouse" else fetch_ashby(board_token)
    for j in jobs:
        if j.get("url") == url:
            return j
    return None


def process_one_job(job_id: str, job: dict, state: dict) -> bool:
    """Returns True if this job reached a terminal state (submitted or
    failed) during this call, False if it's still pending something
    (e.g. mid-escalation) -- mostly informational for the caller's summary."""
    company_name = job["company_name"]
    title = job["title"]
    url = job["url"]

    print(f"\n=== {company_name} -- {title} ===")
    print(f"    {url}")

    ats, board_token = _resolve_ats_and_token(job)
    if not ats:
        print("    Could not determine ATS/board token from state or URL -- skipping.")
        st.set_job_status(state, job_id, "failed_materials", company_name=company_name, title=title, url=url)
        return True

    live_job = _find_live_posting(ats, board_token, title, url)
    if not live_job:
        print("    Posting no longer found on the live board (likely taken down) -- skipping.")
        st.set_job_status(state, job_id, "failed_materials", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        return True

    description = live_job.get("description", "")

    print("    Generating materials...")
    try:
        resume_data, coverletter_data = generate_materials(description, company_name, title)
    except Exception as e:
        print(f"    Materials generation failed: {e}")
        st.set_job_status(state, job_id, "failed_materials", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        return True

    print("    Building PDFs...")
    job_output_dir = os.path.join(OUTPUT_ROOT, job_id.replace("/", "_").replace(":", "_"))
    try:
        resume_pdf, cl_pdf = build_resume_and_coverletter(resume_data, coverletter_data, job_output_dir)
    except Exception as e:
        print(f"    PDF build failed: {e}")
        st.set_job_status(state, job_id, "failed_materials", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        return True

    st.set_job_status(state, job_id, "materials_generated", company_name=company_name, title=title, url=url,
                       ats=ats, board_token=board_token)

    print(f"    Filling application (dry_run={DRY_RUN})...")
    try:
        report = fill_application(url, resume_pdf, cl_pdf, role_title=title, company_name=company_name,
                                   dry_run=DRY_RUN)
    except PendingAnswerRequired as e:
        # One or more questions came up with no stored answer, and this is
        # an unattended run -- everything unanswerable was already sent as
        # ONE batched Telegram message. Mark this job as waiting on all of
        # them and move on to the next job, rather than treating this as a
        # failure or wasting runner time on a single field at a time.
        print(f"    {len(e.questions)} question(s) sent, waiting on your answers: {e.questions}")
        st.set_job_status(state, job_id, "pending_answer", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token, pending_questions=e.questions)
        return False
    except Exception as e:
        print(f"    Form fill/submit failed: {e}")
        st.set_job_status(state, job_id, "failed_form_scan", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        return True

    print(f"    Filled: {len(report['filled'])}, skipped: {len(report['skipped'])}")
    archive_application(job_output_dir, company_name, title, url, report, submitted=report["submitted"])
    print(f"    Screenshot: {report['screenshot_path']}")

    if report["dry_run"]:
        st.set_job_status(state, job_id, "ready_to_submit", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        print("    Dry run complete -- not submitted. Status: ready_to_submit.")
        return False

    if report["submitted"]:
        st.set_job_status(state, job_id, "submitted", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        st.increment_daily_count(state)
        print("    Submitted successfully.")

        try:
            today = date.today()
            date_str = f"{today.month}/{today.day}/{today.year}"
            append_application_row(date_str, title, company_name, description, job_url=url)
            print("    Logged to Google Sheet.")
        except Exception as e:
            # A logging failure should never undo or mask a real
            # submission -- the application already went out successfully,
            # this just means the sheet row needs adding by hand this time.
            print(f"    WARNING: submitted successfully, but Sheets logging failed: {e}")
    else:
        st.set_job_status(state, job_id, "failed_submit", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        print(f"    Submit did not clearly succeed: {report['submit_note']}")

    return True


def main():
    if not DRY_RUN:
        print("!" * 70)
        print("DRY_RUN IS FALSE. THIS WILL ACTUALLY SUBMIT REAL APPLICATIONS.")
        confirm = input("Type SUBMIT (all caps) to proceed, anything else cancels: ")
        if confirm != "SUBMIT":
            print("Cancelled.")
            return

    state = st.load_state()
    expired = st.expire_stale_pending(state, timeout_hours=24)
    if expired:
        print(f"[setup] {len(expired)} job(s) past 24h with no answer, auto-skipped: {expired}")

    pending = [(jid, j) for jid, j in state["jobs"].items() if j["status"] == "judged_fit"]
    print(f"[setup] {len(pending)} job(s) in judged_fit to process")

    for job_id, job in pending:
        if not DRY_RUN and st.is_daily_cap_reached(state, cap=DAILY_CAP):
            print(f"\nDaily cap of {DAILY_CAP} reached ({st.get_daily_count(state)} today) -- stopping here.")
            break

        process_one_job(job_id, job, state)
        st.save_state(state)  # save after every job, not just at the end -- a crash mid-run shouldn't lose progress


if __name__ == "__main__":
    main()
