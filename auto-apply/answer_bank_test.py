"""
Standalone test for answer_bank.py. Seeds a couple of realistic entries,
then tests matching against differently-phrased versions of the same
questions, plus a genuinely new question, so you can see the matching
and consolidation behavior before this gets wired into the real form-scan
flow.

    AUTOAPPLY_ANTHROPIC_API_KEY=... python auto-apply/answer_bank_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from answer_bank import load_answer_bank, save_answer_bank, match_question, add_or_consolidate

TEST_BANK_PATH_NOTE = "This test writes to the REAL state/answer_bank.json -- fine for now since it starts empty."


def main():
    entries = load_answer_bank()
    print(f"[start] bank currently has {len(entries)} entries")

    # Seed two realistic entries directly (simulating you having answered
    # these once already via the Telegram confirm flow).
    entries = add_or_consolidate(
        "Are you legally authorized to work in the United States?",
        "Yes", entries,
    )
    entries = add_or_consolidate(
        "Will you now or in the future require visa sponsorship?",
        "No", entries,
    )
    print(f"[seed] bank now has {len(entries)} entries")
    for e in entries:
        print(f"  - {e['answer']!r} <- {e['aliases']}")

    # Test 1: a differently-worded version of an existing question -- should
    # match and NOT create a new entry, just add the phrasing as an alias.
    test_q1 = "Do you require sponsorship to work in the US, now or in the future?"
    idx, answer = match_question(test_q1, entries)
    print(f"\n[test 1] '{test_q1}'")
    print(f"  -> matched index {idx}, answer: {answer!r}")

    if idx is not None:
        entries = add_or_consolidate(test_q1, answer, entries)
        print(f"  -> consolidated as alias, entry now has aliases: {entries[idx]['aliases']}")

    # Test 2: a genuinely different question -- should NOT match.
    test_q2 = "How many years of experience do you have with HubSpot specifically?"
    idx2, answer2 = match_question(test_q2, entries)
    print(f"\n[test 2] '{test_q2}'")
    print(f"  -> matched index {idx2}, answer: {answer2!r} (expect None/None -- this is a new question)")

    save_answer_bank(entries)
    print(f"\n[done] final bank has {len(entries)} entries, saved to state/answer_bank.json")


if __name__ == "__main__":
    main()
