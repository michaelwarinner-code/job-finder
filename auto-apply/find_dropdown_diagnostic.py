"""
Types into a field and then scans the WHOLE page for anything that looks
like a dropdown/listbox of suggestions -- role="listbox", role="option",
or role="listbox"/"option" anywhere -- rather than assuming the
react-select-specific #react-select-{id}-listbox ID pattern. Built to find
where a CUSTOM autocomplete widget (confirmed: Ashby's Location field uses
class "ashby-application-form-input-autocomplete", not react-select's
"select__..." classes) actually renders its suggestions, since that ID
guess returned zero options despite waiting 5 full seconds.

    python auto-apply/find_dropdown_diagnostic.py "<job url>" "Location" "New York"
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
from form_filler import _goto_application_page, _extract_fields_with_refs, _locator_for


def main():
    if len(sys.argv) < 4:
        raise SystemExit('Usage: python find_dropdown_diagnostic.py "<job_url>" "<question_substring>" "<value_to_type>"')
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
        loc = _locator_for(page, f["ref_type"], f["ref_value"])

        loc.click()
        page.wait_for_timeout(200)
        loc.fill("")
        loc.type(value_text, delay=30)
        page.wait_for_timeout(2500)

        result = page.evaluate("""
            () => {
                const describe = (el) => ({
                    tag: el.tagName,
                    id: el.id || null,
                    class: el.className || null,
                    role: el.getAttribute('role'),
                    text_preview: (el.innerText || '').slice(0, 300),
                    child_count: el.children.length,
                });

                const listboxes = Array.from(document.querySelectorAll('[role="listbox"]')).map(describe);
                const options = Array.from(document.querySelectorAll('[role="option"]')).map(describe);

                const input = document.activeElement;
                const ariaControls = input ? input.getAttribute('aria-controls') : null;
                const ariaOwns = input ? input.getAttribute('aria-owns') : null;
                const ariaExpanded = input ? input.getAttribute('aria-expanded') : null;
                const controlledEl = ariaControls ? document.getElementById(ariaControls) : null;

                return {
                    active_element_tag: input ? input.tagName : null,
                    active_element_aria_controls: ariaControls,
                    active_element_aria_owns: ariaOwns,
                    active_element_aria_expanded: ariaExpanded,
                    controlled_element_found: !!controlledEl,
                    controlled_element_html_preview: controlledEl ? controlledEl.outerHTML.slice(0, 1000) : null,
                    listboxes_found: listboxes,
                    options_found: options,
                };
            }
        """)

        import json
        print(json.dumps(result, indent=2))

        browser.close()


if __name__ == "__main__":
    main()