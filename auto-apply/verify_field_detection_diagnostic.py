"""
Verifies the ACTUAL field-detection + locator-building code (not just a raw
DOM dump) against a job's live application page -- calls the real
_extract_fields_with_refs(), filters to fields whose question text contains
a given substring, and for each one found, confirms _locator_for() can
actually locate a real element with it. Read-only: no filling, no
escalation, no submission.

    python auto-apply/verify_field_detection_diagnostic.py "<job url>" "Location"
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
from form_filler import _goto_application_page, _extract_fields_with_refs, _locator_for


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python verify_field_detection_diagnostic.py "<job_url>" [question_substring]')
    url = sys.argv[1]
    substring = sys.argv[2] if len(sys.argv) > 2 else "Location"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _goto_application_page(page, url)

        fields = _extract_fields_with_refs(page)
        matches = [f for f in fields if substring.lower() in f["question"].lower()]

        if not matches:
            print(f"Still not detected: no field with '{substring}' in its question text came back from "
                  f"_extract_fields_with_refs(). Total fields detected on page: {len(fields)}")
            browser.close()
            return

        for f in matches:
            print(json.dumps(f, indent=2))
            loc = _locator_for(page, f["ref_type"], f["ref_value"])
            count = loc.count()
            print(f"  -> _locator_for() with ref_type={f['ref_type']!r}, ref_value={f['ref_value']!r} "
                  f"matches {count} real element(s) on the page.")

        browser.close()


if __name__ == "__main__":
    main()