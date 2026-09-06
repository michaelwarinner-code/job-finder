"""
Diagnostic: gender_identity and sexual_orientation answers didn't match any
real option ('male'/'straight' guessed wrong). Rather than guess again,
this clicks each field open and prints every real option it actually
offers, so eeo_answers.json can be updated with wording guaranteed to match.

    python auto-apply/inspect_eeo_options_diagnostic.py
"""
from playwright.sync_api import sync_playwright

URL = "https://job-boards.greenhouse.io/datagrail/jobs/7807686003"
# (label search text, input id -- id confirmed from earlier diagnostic for
#  gender identity; sexual orientation's id is unknown, found by label text instead)
FIELDS = [
    ("gender identity", "4006549003"),
    ("sexual orientation", None),
    ("racial/ethnic", None),
]


def find_input_id_by_label(page, label_text: str):
    return page.evaluate(f"""
        () => {{
            const labels = Array.from(document.querySelectorAll('label'));
            for (const l of labels) {{
                if ((l.innerText || '').toLowerCase().includes("{label_text}".toLowerCase())) {{
                    return l.getAttribute('for');
                }}
            }}
            return null;
        }}
    """)


def dump_options(page, field_id: str, label_hint: str):
    input_loc = page.locator(f'[id="{field_id}"]')
    input_loc.click()
    page.wait_for_timeout(600)

    options_text = page.evaluate(f"""
        () => {{
            const listbox = document.querySelector('#react-select-{field_id}-listbox');
            if (!listbox) return [];
            return Array.from(listbox.querySelectorAll('[role="option"]')).map(o => o.innerText.trim());
        }}
    """)
    print(f"--- {label_hint} (id={field_id}) ---")
    for opt in options_text:
        print(f"  {opt!r}")
    print()

    # Close the dropdown before moving to the next field -- left open, it
    # visually overlaps and physically blocks clicks on whatever comes next.
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(1500)

        for label_hint, known_id in FIELDS:
            field_id = known_id or find_input_id_by_label(page, label_hint)
            if not field_id:
                print(f"--- {label_hint}: could not find field id ---\\n")
                continue
            dump_options(page, field_id, label_hint)

        browser.close()


if __name__ == "__main__":
    main()
