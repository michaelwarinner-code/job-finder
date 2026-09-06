"""
Standalone test for browser_form_scanner.py. Scans ONE real application
page (edit URL below) and prints every question it found, marking each
one as already known (via the answer bank) or new.

    AUTOAPPLY_ANTHROPIC_API_KEY=... python auto-apply/form_scan_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from browser_form_scanner import scan_application_form
from answer_bank import load_answer_bank, match_question

# --- Edit this to a real posting URL from your last discovery run ---
URL = "https://job-boards.greenhouse.io/datagrail/jobs/7807686003"
# ---------------------------------------------------------------------


def main():
    print(f"Scanning: {URL}\n")
    result = scan_application_form(URL)
    fields = result["fields"]
    print(f"Found {len(fields)} form fields:\n")

    if not fields:
        diag = result.get("diagnostic", {})
        print("No fields detected.")
        print(f"  Page title: {diag.get('page_title', '(unknown)')}")
        print(f"  Clicked an Apply-like control: {diag.get('clicked_apply', False)}")
        print(f"  Body text snippet (first 500 chars):\n  {diag.get('body_text_snippet', '')}")
        return

    entries = load_answer_bank()

    for f in fields:
        idx, answer = match_question(f["question"], entries) if entries else (None, None)
        status = f"KNOWN -> {answer!r}" if idx is not None else "NEW -- needs an answer"
        req = " *required*" if f["required"] else ""
        print(f"  [{f['field_type']}]{req} {f['question']}")
        if f["options"]:
            print(f"      options: {f['options']}")
        print(f"      {status}\n")


if __name__ == "__main__":
    main()
