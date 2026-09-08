"""
The real end-to-end pipeline: for every job sitting in 'judged_fit' status
(found by broad_discover_run.py but never carried further), this
re-fetches the live posting, generates tailored materials, builds real
PDFs, fills the application, and -- only if dry_run is on -- submits it.
Respects the daily cap and updates job status at every stage, so a
failure partway through is visible and never silently retried into a
duplicate.

Falls back to parsing ats/board_token from the URL for jobs that were
judged before that field existed in state (older entries).

DRY_RUN is controlled by the AUTOAPPLY_DRY_RUN env var, defaulting to
true if unset -- so nothing can go live by accident just from a missing
variable. To actually submit, you must set it to false AND pass --yes:

    # normal test run (dry run, everything in judged_fit)
    AUTOAPPLY_ANTHROPIC_API_KEY=... python auto-apply/run_pipeline.py

    # test ONE job, stop after materials are generated (no PDF, no browser)
    python auto-apply/run_pipeline.py --job-id "<url>" --stop-after materials

    # test ONE job through PDF build, skip the form fill
    python auto-apply/run_pipeline.py --job-id "<url>" --stop-after pdf

    # test ONE job's full form fill, still dry run (stops before Submit)
    python auto-apply/run_pipeline.py --job-id "<url>"

    # THE REAL THING -- submits for real, only for jobs in judged_fit
    AUTOAPPLY_DRY_RUN=false AUTOAPPLY_TELEGRAM_BOT_TOKEN=... AUTOAPPLY_TELEGRAM_CHAT_ID=... \\
        python auto-apply/run_pipeline.py --yes

THIS ACTUALLY SUBMITS REAL APPLICATIONS IF AUTOAPPLY_DRY_RUN=false. Leave
it unset (or "true") for every test run.
"""
import argparse
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
from company_question_classifier import is_company_specific_question
from sheets_logger import append_application_row
from application_archive import archive_application
from broad_source import GREENHOUSE_URL_RE, ASHBY_URL_RE

DAILY_CAP = 15
DRY_RUN = os.environ.get("AUTOAPPLY_DRY_RUN", "true").strip().lower() != "false"
OUTPUT_ROOT = os.path.join(os.path.dirname(__file__), "pipeline_output")
STAGE_ORDER = ["materials", "pdf", "form_fill"]


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


def process_one_job(job_id: str, job: dict, state: dict, stop_after: str = None) -> bool:
    """Returns True if this job reached a terminal state (submitted or
    failed) during this call, False if it's still pending something
    (e.g. mid-escalation) -- mostly informational for the caller's summary.

    stop_after, if set, is one of STAGE_ORDER ("materials", "pdf",
    "form_fill") -- the pipeline runs through that stage and returns
    without going further, so you can inspect what a stage produced
    (generated resume/cover-letter text, or the built PDFs) before
    deciding whether the next stage is worth running. None (the default)
    runs the full chain, same as before."""
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

    if stop_after == "materials":
        print("    --stop-after materials: generated resume/cover-letter data, stopping here.")
        print(f"    Objective line: {resume_data.get('objective', '(no objective field)')}")
        print(f"    Cover letter opening: {str(coverletter_data)[:300]}")
        st.set_job_status(state, job_id, "materials_generated", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        return False

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

    if stop_after == "pdf":
        print(f"    --stop-after pdf: built {resume_pdf} and {cl_pdf}, stopping here.")
        return False

    print(f"    Filling application (dry_run={DRY_RUN})...")
    job_specific_answers = st.get_job_specific_answers(state, job_id)
    try:
        report = fill_application(url, resume_pdf, cl_pdf, role_title=title, company_name=company_name,
                                   dry_run=DRY_RUN, job_specific_answers=job_specific_answers)
    except PendingAnswerRequired as e:
        # One or more questions came up with no stored answer, and this is
        # an unattended run -- everything unanswerable was already sent as
        # ONE batched Telegram message. Mark this job as waiting on all of
        # them and move on to the next job, rather than treating this as a
        # failure or wasting runner time on a single field at a time.
        print(f"    {len(e.questions)} question(s) sent, waiting on your answers: {e.questions}")
        for entry in e.report.get("filled", []):
            print(f"      [filled]  {entry['question']}  (source: {entry['source']}, value: {entry['value']})")
        for entry in e.report.get("skipped", []):
            print(f"      [skipped] {entry['question']}  -- {entry['reason']}")
        if e.report.get("screenshot_path"):
            print(f"    Screenshot (as of the point it stopped): {e.report['screenshot_path']}")
        st.set_job_status(state, job_id, "pending_answer", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token, pending_questions=e.questions)
        return False
    except Exception as e:
        print(f"    Form fill/submit failed: {e}")
        st.set_job_status(state, job_id, "failed_form_scan", company_name=company_name, title=title, url=url,
                           ats=ats, board_token=board_token)
        return True

    # Persist any freshly-escalated company-specific answers as job-specific
    # (never the reusable bank) -- so a LOCAL re-run of this same job (e.g.
    # testing with --job-id) doesn't ask again either, same reasoning as the
    # unattended Worker path.
    for entry in report["filled"]:
        if entry["source"].startswith("TELEGRAM_ESCALATION") and \
                is_company_specific_question(entry["question"], company_name):
            st.add_job_specific_answer(state, job_id, entry["question"], entry["value"])

    print(f"    Filled: {len(report['filled'])}, skipped: {len(report['skipped'])}")
    for entry in report["filled"]:
        print(f"      [filled]  {entry['question']}  (source: {entry['source']}, value: {entry['value']})")
    for entry in report["skipped"]:
        print(f"      [skipped] {entry['question']}  -- {entry['reason']}")
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job-id", help="Process only this one job (its URL, matching state.json's key), "
                                          "regardless of its current status. For iterating on a single job "
                                          "repeatedly during testing.")
    parser.add_argument("--stop-after", choices=STAGE_ORDER,
                         help="Stop after this stage instead of running the full chain: 'materials' (no PDFs, "
                              "no browser), 'pdf' (no form fill), or 'form_fill' (same as omitting this flag).")
    parser.add_argument("--yes", action="store_true",
                         help="Required in addition to AUTOAPPLY_DRY_RUN=false to actually submit -- without it, "
                              "a live run is refused even with dry run off. Also skips the interactive confirm "
                              "prompt, so this is what a scheduled/Actions run needs to pass.")
    args = parser.parse_args()

    # Fail fast on a missing Telegram credential -- reaching the form-fill
    # stage without one wastes a full (slow, non-free) materials generation
    # and PDF build before dying deep inside a browser session, for
    # something that was knowable before any of that started. Only reached
    # if this run will actually get to form_fill (materials/pdf-only stops
    # never touch Telegram at all).
    if args.stop_after not in ("materials", "pdf"):
        missing = [v for v in ("AUTOAPPLY_TELEGRAM_BOT_TOKEN", "AUTOAPPLY_TELEGRAM_CHAT_ID") if v not in os.environ]
        if missing:
            raise SystemExit(f"Missing required env var(s): {', '.join(missing)} -- form_fill needs these the "
                              f"moment it hits any question that isn't already answered by identity info, EEO, "
                              f"or the answer bank. Set them before running, or pass --stop-after pdf if you "
                              f"only meant to test materials/PDF generation this time.")

    if not DRY_RUN:
        if not args.yes:
            raise SystemExit("AUTOAPPLY_DRY_RUN=false but --yes was not passed -- refusing to submit real "
                              "applications without explicit confirmation. Re-run with --yes if this is intended.")
        print("!" * 70)
        print("DRY_RUN IS FALSE AND --yes WAS PASSED. THIS WILL ACTUALLY SUBMIT REAL APPLICATIONS.")
        if sys.stdin.isatty():
            confirm = input("Type SUBMIT (all caps) to proceed, anything else cancels: ")
            if confirm != "SUBMIT":
                print("Cancelled.")
                return
        else:
            print("(non-interactive session, --yes stands in for the confirm prompt)")

    state = st.load_state()
    expired = st.expire_stale_pending(state, timeout_hours=24)
    if expired:
        print(f"[setup] {len(expired)} job(s) past 24h with no answer, auto-skipped: {expired}")

    if args.job_id:
        job_id = args.job_id.strip().strip("'\"")  # forgiving of quote marks pasted in by mistake (e.g. copied
        # from a local shell command's --job-id "url" into a GitHub Actions text input, which needs no quoting)
        job = state["jobs"].get(job_id)
        if not job:
            raise SystemExit(f"No job found in state with id/url: {job_id}")
        pending = [(job_id, job)]
    else:
        pending = [(jid, j) for jid, j in state["jobs"].items() if j["status"] == "judged_fit"]
    print(f"[setup] {len(pending)} job(s) to process")

    for job_id, job in pending:
        if not DRY_RUN and args.stop_after is None and st.is_daily_cap_reached(state, cap=DAILY_CAP):
            print(f"\nDaily cap of {DAILY_CAP} reached ({st.get_daily_count(state)} today) -- stopping here.")
            break

        process_one_job(job_id, job, state, stop_after=args.stop_after)
        st.save_state(state)  # save after every job, not just at the end -- a crash mid-run shouldn't lose progress


if __name__ == "__main__":
    main()
