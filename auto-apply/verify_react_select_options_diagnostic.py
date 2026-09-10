"""
Verifies exactly what a react-select combobox's dropdown returns after
typing a given value -- calls the SAME production code path as
_select_react_select_option (click, type, poll for options) but stops
right before clicking anything, and prints every option text it actually
found. Built to diagnose "no dropdown option matched" skips where the
field IS detected and the code DOES wait for options, but the exact/
substring match still fails -- shows whether the expected option genuinely
wasn't in the returned list (a query/timing problem) or there's a subtle
text-formatting mismatch (a matching-logic problem).

    python auto-apply/verify_react_select_options_diagnostic.py "<job url>" "Location" "New York"
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
from form_filler import _goto_application_page, _extract_fields_with_refs, _locator_for


def main():
    if len(sys.argv) < 4:
        raise SystemExit('Usage: python verify_react_select_options_diagnostic.py "<job_url>" "<question_substring>" "<value_to_type>"')
    url, substring, value_text = sys.argv[1], sys.argv[2], sys.argv[3]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _goto_application_page(page, url)

        fields = _extract_fields_with_refs(page)
        matches = [f for f in fields if substring.lower() in f["question"].lower()]
        if not matches:
            print(f"No field found matching '{substring}'.")
            browser.close()
            return

        f = matches[0]
        field_id = f["ref_value"]
        loc = _locator_for(page, f["ref_type"], f["ref_value"])

        loc.click()
        page.wait_for_timeout(200)
        loc.fill("")
        loc.type(value_text, delay=30)

        listbox = page.locator(f'#react-select-{field_id}-listbox')
        options = listbox.locator('[role="option"]')
        max_wait_ms = 5000
        poll_interval_ms = 200
        waited_ms = 0
        count = options.count()
        while count == 0 and waited_ms < max_wait_ms:
            page.wait_for_timeout(poll_interval_ms)
            waited_ms += poll_interval_ms
            count = options.count()

        texts = [options.nth(i).inner_text().strip() for i in range(count)]

        print(f"Typed: {value_text!r}")
        print(f"Waited: {waited_ms}ms before options stopped being empty (cap was {max_wait_ms}ms)")
        print(f"Options found ({count}):")
        for t in texts:
            print(f"  - {t!r}")

        exact = [t for t in texts if t.lower() == value_text.lower()]
        substr = [t for t in texts if value_text.lower() in t.lower()]
        print(f"\nWould match EXACT: {exact}")
        print(f"Would match SUBSTRING: {substr}")

        browser.close()


if __name__ == "__main__":
    main()