"""
Diagnostic: Greenhouse shows two file-upload fields both labeled just
"Attach" (resume and cover letter), with no visible text distinguishing
them. This finds every file input on the page and prints its real
underlying attributes (name, id, and any nearby heading text) so we can
see what actually tells them apart under the hood -- almost certainly the
`name` attribute, even though the visible label doesn't show it.

    python auto-apply/inspect_attach_fields_diagnostic.py
"""
from playwright.sync_api import sync_playwright

URL = "https://job-boards.greenhouse.io/datagrail/jobs/7807686003"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(1500)

        results = page.evaluate("""
            () => {
                const fileInputs = Array.from(document.querySelectorAll('input[type="file"]'));
                return fileInputs.map(input => {
                    // Walk up to find the nearest heading-like text above this field.
                    let heading = null;
                    let node = input;
                    for (let depth = 0; depth < 5 && node && !heading; depth++) {
                        let sib = node.previousElementSibling;
                        while (sib && !heading) {
                            const h = sib.matches('h1,h2,h3,h4,h5,h6,legend') ? sib
                                : sib.querySelector('h1,h2,h3,h4,h5,h6,legend');
                            if (h && h.innerText.trim()) heading = h.innerText.trim();
                            sib = sib.previousElementSibling;
                        }
                        node = node.parentElement;
                    }

                    return {
                        name: input.name || null,
                        id: input.id || null,
                        nearby_heading: heading,
                        outer_html_snippet: input.outerHTML.slice(0, 300),
                    };
                });
            }
        """)

        browser.close()

    print(f"Found {len(results)} file input(s):\\n")
    for i, r in enumerate(results):
        print(f"--- File input {i} ---")
        print(f"  name: {r['name']}")
        print(f"  id: {r['id']}")
        print(f"  nearby_heading: {r['nearby_heading']}")
        print(f"  html: {r['outer_html_snippet']}")
        print()


if __name__ == "__main__":
    main()
