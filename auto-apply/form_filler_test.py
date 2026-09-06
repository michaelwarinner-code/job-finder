"""
Standalone test for form_filler.py. Fills ONE real application form and
saves a full-page screenshot so you can visually verify the result against
the real page.

Edit the values below, then run:

    AUTOAPPLY_ANTHROPIC_API_KEY=... AUTOAPPLY_TELEGRAM_BOT_TOKEN=... AUTOAPPLY_TELEGRAM_CHAT_ID=... python auto-apply/form_filler_test.py

Needs real PDFs to upload -- generate them via materials_writer_test.py
and your existing ResumeCustomizer build step first, then point
RESUME_PDF_PATH / COVERLETTER_PDF_PATH at the real output files.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from form_filler import fill_application
import auto_apply_state as st

# --- Edit these ---
URL = "https://job-boards.greenhouse.io/bamboohr17/jobs/5998305004"
RESUME_PDF_PATH = r"C:\Users\thebo\Downloads\Clone\job-finder\auto-apply\pipeline_output\https___job-boards.greenhouse.io_bamboohr17_jobs_5998305004\resume.pdf"
COVERLETTER_PDF_PATH = r"C:\Users\thebo\Downloads\Clone\job-finder\auto-apply\pipeline_output\https___job-boards.greenhouse.io_bamboohr17_jobs_5998305004\cover_letter.pdf"
ROLE_TITLE = "Sales Operations Manager"
COMPANY_NAME = "BambooHR"
DAILY_CAP = 15

# THIS ACTUALLY SUBMITS A REAL APPLICATION IF SET TO FALSE. Leave True for
# every test run. Only flip to False when you specifically intend to submit
# THIS real application to THIS real company, right now.
DRY_RUN = True
# ------------------


def main():
    state = st.load_state()

    if not DRY_RUN:
        if st.is_already_handled(state, URL):
            print(f"This job is already marked '{st.get_job_status(state, URL)}' -- refusing to "
                  f"process it again to avoid a double application. Nothing was done.")
            return
        if st.is_daily_cap_reached(state, cap=DAILY_CAP):
            print(f"Daily cap of {DAILY_CAP} already reached ({st.get_daily_count(state)} today). "
                  f"Refusing to submit. Nothing was done.")
            return

        print("!" * 70)
        print("DRY_RUN IS FALSE. THIS WILL ACTUALLY SUBMIT A REAL APPLICATION.")
        print(f"  Company: {COMPANY_NAME}")
        print(f"  Role: {ROLE_TITLE}")
        print(f"  URL: {URL}")
        print(f"  Today's count so far: {st.get_daily_count(state)}/{DAILY_CAP}")
        confirm = input("Type SUBMIT (all caps) to proceed, anything else cancels: ")
        if confirm != "SUBMIT":
            print("Cancelled. Nothing was submitted.")
            return

    print(f"Filling: {URL}\n")
    report = fill_application(URL, RESUME_PDF_PATH, COVERLETTER_PDF_PATH,
                               role_title=ROLE_TITLE, company_name=COMPANY_NAME, dry_run=DRY_RUN)

    print(f"--- Filled ({len(report['filled'])}) ---")
    for item in report["filled"]:
        print(f"  [{item['source']}] {item['question']} -> {item['value']}")

    print(f"\n--- Skipped / needs attention ({len(report['skipped'])}) ---")
    for item in report["skipped"]:
        print(f"  {item['question']}")
        print(f"    reason: {item['reason']}")

    print(f"\nScreenshot saved: {report['screenshot_path']}")
    print(f"Dry run: {report['dry_run']}")
    print(f"Submitted: {report['submitted']}")
    print(f"Note: {report['submit_note']}")

    if not report["dry_run"] and report["submitted"]:
        st.set_job_status(state, URL, "submitted", company_name=COMPANY_NAME, title=ROLE_TITLE, url=URL)
        st.increment_daily_count(state)
        st.save_state(state)
        print(f"\nMarked as submitted in state. Today's count: {st.get_daily_count(state)}/{DAILY_CAP}")
    elif not report["dry_run"]:
        st.set_job_status(state, URL, "failed_submit", company_name=COMPANY_NAME, title=ROLE_TITLE, url=URL)
        st.save_state(state)
        print("\nSubmit did not clearly succeed -- marked as failed_submit in state, will not auto-retry.")

    if not report["dry_run"]:
        print("Open the post-submit screenshot and confirm the real result manually.")
    else:
        print("Open the screenshot and visually compare against the real page before trusting this output.")


if __name__ == "__main__":
    main()
