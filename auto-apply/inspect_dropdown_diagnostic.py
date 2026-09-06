"""
Diagnostic: Country (claimed filled, actually blank on screen) and the EEO
"mark all that apply" fields are both very likely custom dropdown/listbox
widgets, not native <select> elements -- same category of problem as
Ashby's Yes/No widget, just a different implementation. This finds both
and prints their real markup so we can build correct click-based
interaction instead of guessing.

    python auto-apply/inspect_dropdown_diagnostic.py
"""
from playwright.sync_api import sync_playwright

URL = "https://job-boards.greenhouse.io/datagrail/jobs/7807686003"
SEARCHES = ["Country", "How would you describe your gender identity"]


def find_and_print(page, search_text):
    html = page.evaluate(f"""
        () => {{
            const search = "{search_text}".toLowerCase();
            const all = Array.from(document.querySelectorAll('*'));
            let best = null;
            for (const el of all) {{
                const ownText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent).join('').toLowerCase();
                if (ownText.includes(search)) {{ best = el; break; }}
            }}
            if (!best) return "NOT FOUND on page";
            let container = best;
            for (let i = 0; i < 2 && container.parentElement; i++) {{
                container = container.parentElement;
            }}
            return container.outerHTML;
        }}
    """)
    idx = html.lower().find(search_text.lower())
    if idx == -1:
        print(f"--- '{search_text}': not found in captured HTML ---")
        print(html[:500])
    else:
        start = max(0, idx - 200)
        end = min(len(html), idx + 1500)
        print(f"--- '{search_text}' ---")
        print(html[start:end])
    print()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(1500)

        for search in SEARCHES:
            find_and_print(page, search)

        browser.close()


if __name__ == "__main__":
    main()
