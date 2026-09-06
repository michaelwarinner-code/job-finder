"""
Diagnostic: react-select doesn't render its dropdown options into the page
until you actually click/focus the input -- this clicks the Country field
open, types a filter, and prints the real rendered option-list markup, so
the actual click-selection logic can be built against real structure
instead of guessed.

    python auto-apply/inspect_reactselect_options_diagnostic.py
"""
from playwright.sync_api import sync_playwright

URL = "https://job-boards.greenhouse.io/datagrail/jobs/7807686003"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(1500)

        country_input = page.locator("#country")
        country_input.click()
        page.wait_for_timeout(300)
        country_input.type("United States", delay=50)
        page.wait_for_timeout(800)

        html = page.evaluate("""
            () => {
                const listbox = document.querySelector('[role="listbox"]')
                    || document.querySelector('[id*="listbox"]')
                    || document.querySelector('[class*="menu"]');
                return listbox ? listbox.outerHTML : "NO LISTBOX/MENU FOUND -- dropdown may not have opened";
            }
        """)

        print(html[:3000])

        browser.close()


if __name__ == "__main__":
    main()
