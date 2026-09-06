"""
Diagnostic: after two attempted fixes, the race field still only shows one
chip selected instead of two. This selects "White or European", dumps the
REAL DOM state of the value-container, then selects "East Asian" and dumps
it again -- so we see with certainty whether the widget actually replaces
instead of accumulating, or whether the chip-reading selector used in
form_filler.py's verification step is simply wrong (which would explain
why it didn't catch the problem).

    python auto-apply/inspect_multiselect_behavior_diagnostic.py
"""
from playwright.sync_api import sync_playwright

URL = "https://job-boards.greenhouse.io/datagrail/jobs/7807686003"
FIELD_ID = "4006547003"  # racial/ethnic background, confirmed earlier


def dump_value_container(page, field_id: str, label: str):
    chips = page.evaluate(f"""
        () => {{
            const input = document.getElementById("{field_id}");
            const container = input ? input.closest('.select__container') : null;
            if (!container) return "COULD NOT FIND .select__container";
            return Array.from(container.querySelectorAll('[class*="multi-value__label"]'))
                .map(el => el.innerText.trim());
        }}
    """)
    print(f"--- {label} ---")
    print(f"  chips: {chips}")
    print()


def select_option(page, field_id: str, value_text: str, click_to_open: bool = True, clear_first: bool = True):
    """clear_first=False skips the explicit fill("") before typing -- testing
    whether that clear action itself is what's dropping the prior selection,
    if the widget's search box is already empty after a pick anyway."""
    input_loc = page.locator(f'[id="{field_id}"]')
    if click_to_open:
        input_loc.click()
        page.wait_for_timeout(300)
    if clear_first:
        input_loc.fill("")
    input_loc.type(value_text, delay=30)
    page.wait_for_timeout(600)

    listbox = page.locator(f'#react-select-{field_id}-listbox')
    options = listbox.locator('[role="option"]')
    count = options.count()
    for i in range(count):
        text = options.nth(i).inner_text().strip()
        if text.lower() == value_text.lower():
            options.nth(i).click()
            page.wait_for_timeout(600)
            return True
    return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(1500)

        dump_value_container(page, FIELD_ID, "BEFORE any selection")

        ok1 = select_option(page, FIELD_ID, "White or European", click_to_open=True, clear_first=True)
        print(f"selected 'White or European': {ok1}\n")
        dump_value_container(page, FIELD_ID, "AFTER selecting 'White or European'")

        # This time: don't reopen (already ruled that out) AND don't
        # explicitly clear the search box first -- testing whether the
        # clear itself, not the reopen, is what's dropping the prior pick.
        ok2 = select_option(page, FIELD_ID, "East Asian", click_to_open=False, clear_first=False)
        print(f"selected 'East Asian' (no reopen, no explicit clear): {ok2}\n")
        dump_value_container(page, FIELD_ID, "AFTER selecting 'East Asian'")

        browser.close()


if __name__ == "__main__":
    main()
