"""
One-off diagnostic: dumps the real DOM around any <label> whose text
contains a given substring (default "Location") on a job's live
application page -- built specifically to diagnose a field that produces
ZERO output in fill_application()'s filled/skipped report (neither filled
nor flagged as skipped), which means the label-to-field detection logic
in _extract_fields_with_refs() never found it at all.

Read-only: navigates and inspects only. No filling, no answer-bank use,
no Telegram escalation, no submission -- completely safe to run against
any real job posting.

    python auto-apply/inspect_missing_field_diagnostic.py "<job url>" "Location"
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
from form_filler import _goto_application_page


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python inspect_missing_field_diagnostic.py "<job_url>" [label_text_substring]')
    url = sys.argv[1]
    label_text = sys.argv[2] if len(sys.argv) > 2 else "Location"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _goto_application_page(page, url)

        result = page.evaluate("""
            (labelText) => {
                const labels = Array.from(document.querySelectorAll('label'))
                    .filter(l => (l.innerText || '').toLowerCase().includes(labelText.toLowerCase()));

                return labels.map(label => {
                    const forId = label.getAttribute('for');
                    const forResolves = forId ? !!document.getElementById(forId) : null;
                    const nestedField = label.querySelector('input, select, textarea');
                    const parent = label.parentElement;
                    const parentField = parent
                        ? parent.querySelector('[role="combobox"], input, select, textarea')
                        : null;

                    return {
                        label_text: (label.innerText || '').trim(),
                        label_outerHTML: label.outerHTML.slice(0, 500),
                        for_attribute: forId,
                        for_resolves_to_real_element: forResolves,
                        has_nested_field: !!nestedField,
                        nested_field_tag: nestedField ? nestedField.tagName : null,
                        parent_tag: parent ? parent.tagName : null,
                        parent_class: parent ? parent.className : null,
                        parent_outerHTML: parent ? parent.outerHTML.slice(0, 800) : null,
                        parent_has_combobox_or_input: !!parentField,
                        parent_field_tag: parentField ? parentField.tagName : null,
                        parent_field_role: parentField ? parentField.getAttribute('role') : null,
                    };
                });
            }
        """, label_text)

        browser.close()

        if not result:
            print(f"No <label> element found containing text {label_text!r}. Either it's not a <label> tag "
                  f"at all (try inspecting the page manually), or the text doesn't match -- try a different "
                  f"substring.")
            return

        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()