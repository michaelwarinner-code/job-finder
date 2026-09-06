"""
Standalone test for telegram_escalation.py. Escalates ONE real question
(edit below) that was skipped in your last form_filler_test.py run. Watch
your phone -- you'll get pinged, reply with an answer, then confirm it.

    AUTOAPPLY_TELEGRAM_BOT_TOKEN=... AUTOAPPLY_TELEGRAM_CHAT_ID=... python auto-apply/telegram_escalation_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from telegram_escalation import escalate_question
from answer_bank import load_answer_bank

QUESTION = ("Have you held a role where Product Marketing was a primary responsibility "
            "(e.g., positioning & Messaging, product launches, sales enablement, or "
            "competitive intelligence)?")
ROLE_TITLE = "Senior Product Marketing Manager"
COMPANY_NAME = "DataGrail"
JOB_URL = "https://job-boards.greenhouse.io/datagrail/jobs/7807686003"


def main():
    entries = load_answer_bank()
    answer = escalate_question(QUESTION, ROLE_TITLE, COMPANY_NAME, JOB_URL, entries)
    if answer:
        print(f"\nDone. Confirmed answer: {answer!r}")
        print("This question will now match automatically on future postings.")
    else:
        print("\nNo answer was confirmed (timed out).")


if __name__ == "__main__":
    main()
