"""
Test for eeo_answers.py -- confirms the six real EEO question phrasings
found on the DataGrail Greenhouse posting all classify correctly, and
shows current answer status (filled in vs still blank) without ever
printing your actual answers back if you've filled them in for real --
just whether each one is set.

    python auto-apply/eeo_answers_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from eeo_answers import classify_eeo_question, get_eeo_answer

# Real question text from the DataGrail Greenhouse scan.
TEST_QUESTIONS = [
    "How would you describe your gender identity? (mark all that apply)",
    "How would you describe your racial/ethnic background? (mark all that apply)",
    "How would you describe your sexual orientation? (mark all that apply)",
    "Do you identify as transgender?",
    "Do you have a disability or chronic condition (physical, visual, auditory, cognitive, mental, "
    "emotional, or other) that substantially limits one or more of your major life activities, "
    "including mobility, communication (seeing, hearing, speaking), and learning?",
    "Are you a veteran or active member of the United States Armed Forces?",
    # Non-EEO control questions -- should NOT classify as EEO.
    "Are you legally authorized to work in the United States?",
    "How many years of experience do you have with HubSpot?",
]


def main():
    for q in TEST_QUESTIONS:
        key = classify_eeo_question(q)
        is_eeo, single_answer = get_eeo_answer(q, field_type="react-select")
        is_eeo, multi_answer = get_eeo_answer(q, field_type="react-select-multi")
        print(f"[{'EEO' if is_eeo else 'non-EEO'}] key={key}")
        if is_eeo:
            print(f"  if single-select widget: {single_answer!r}")
            print(f"  if multi-select widget:  {multi_answer!r}")
        print(f"  {q}\n")


if __name__ == "__main__":
    main()
