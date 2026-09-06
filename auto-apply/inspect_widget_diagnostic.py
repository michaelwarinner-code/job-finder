"""
One-off diagnostic: finds the element containing "work authorization" text
on the real application page and prints its surrounding HTML, so we can see
the ACTUAL markup of that custom Yes/No widget instead of guessing a third
ARIA pattern blind.

    python auto-apply/inspect_widget_diagnostic.py
"""
from playwright.sync_api import sync_playwright

URL = "https://jobs.ashbyhq.com/Clera/54fc9546-f535-4def-b9c0-dd4e18f02c4b/application"
SEARCH_TEXT = "work authorization"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(1500)

        html = page.evaluate(f"""
            () => {{
                const search = "{SEARCH_TEXT}".toLowerCase();
                const all = Array.from(document.querySelectorAll('*'));
                // Find the most specific (deepest/smallest) element whose
                // OWN text content contains the search phrase.
                let best = null;
                for (const el of all) {{
                    const ownText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent).join('').toLowerCase();
                    if (ownText.includes(search)) {{
                        best = el;
                        break;
                    }}
                }}
                if (!best) return "NOT FOUND on page";

                // Walk up 2 ancestor levels -- enough to capture the question
                // text plus its Yes/No buttons together, without pulling in
                // large unrelated sections of the form.
                let container = best;
                for (let i = 0; i < 2 && container.parentElement; i++) {{
                    container = container.parentElement;
                }}
                return container.outerHTML;
            }}
        """)

        browser.close()

    idx = html.lower().find(SEARCH_TEXT.lower())
    if idx == -1:
        print("Search text not found within the captured HTML at all.")
        print(html[:1000])
    else:
        start = max(0, idx - 300)
        end = min(len(html), idx + 1700)
        print(html[start:end])


if __name__ == "__main__":
    main()
