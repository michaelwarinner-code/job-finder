"""
Generic Playwright-based application-form scanner. Works against a live
Greenhouse or Ashby application page and extracts the form's questions by
reading real <label> elements and their associated input/select/textarea
fields -- a generic, DOM-structure-agnostic approach rather than
site-specific CSS selectors, since accessible React forms (both ATSs are
React apps) still emit proper label-to-field associations for screen
readers even though visual styling and class names differ and change over
time. Using one generic approach instead of per-ATS selectors also means
this doesn't quietly break the next time either site redesigns.

This is READ-ONLY: it never fills in or submits anything, only reads the
form's current question list. Filling and submitting is a separate, later
piece, built only after this is proven to read real forms correctly.

Known limitation, to verify against real forms: this catches standard
label+input/select/textarea pairs. Custom-styled dropdown or multi-select
widgets that aren't real <select> elements (common in polished React UIs)
may not be caught by this generic approach and could need ATS-specific
handling once we see real scan results -- don't assume 100% field coverage
until tested against a few real postings from each ATS.

Needs Playwright installed first:
    pip install playwright
    playwright install chromium
"""
import re
from playwright.sync_api import sync_playwright

TIMEOUT_MS = 30000
APPLY_BUTTON_PATTERN = re.compile(r"\bapply\b", re.IGNORECASE)


def _clean_label_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"\*\s*$", "", text).strip()  # trailing required-asterisk
    return text


def scan_application_form(url: str) -> dict:
    """
    Returns {"fields": [...], "diagnostic": {...}}.

    fields: one entry per detected form field --
        {"question": str, "field_type": str, "required": bool, "options": [str, ...]}
    "options" is only populated for select fields (radio/checkbox groups
    are a known gap, see module docstring).

    diagnostic: page_title and a short body-text snippet, populated
    whenever zero fields are found, so a caller can tell WHY nothing was
    found (wrong page, need to click Apply first, genuinely no form,
    field structure the generic approach doesn't catch) instead of just
    seeing an empty list and having to guess.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Ashby application forms live at a separate /application path from
        # the job description page -- confirmed against a real posting.
        # Try that direct path first, since it's far more reliable than
        # simulating an Apply click and hoping the resulting page matches
        # what we expect.
        target_url = url
        if "ashbyhq.com" in url and not url.rstrip("/").endswith("/application"):
            target_url = url.rstrip("/") + "/application"

        page.goto(target_url, timeout=TIMEOUT_MS, wait_until="networkidle")
        page.wait_for_timeout(1500)

        raw_fields = _extract_fields(page)

        # Many ATS job pages show the description first, with the actual
        # application form only appearing after an "Apply" click (either
        # inline expansion or navigation). If nothing was found on the
        # initial page, try clicking an Apply-like control before giving up.
        clicked_apply = False
        if not raw_fields:
            try:
                apply_control = page.get_by_role("link", name=APPLY_BUTTON_PATTERN).first
                if apply_control.count() == 0:
                    apply_control = page.get_by_role("button", name=APPLY_BUTTON_PATTERN).first
                if apply_control.count() > 0:
                    apply_control.click(timeout=8000)
                    clicked_apply = True
                    page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
                    page.wait_for_timeout(1500)
                    raw_fields = _extract_fields(page)
            except Exception as e:
                print(f"    [form-scan] apply-click attempt failed: {e}")

        diagnostic = {}
        if not raw_fields:
            diagnostic = {
                "page_title": page.title(),
                "clicked_apply": clicked_apply,
                "body_text_snippet": (page.inner_text("body") or "")[:500],
            }

        browser.close()

    results = []
    for f in raw_fields:
        f["question"] = _clean_label_text(f["question"])
        if f["question"]:
            results.append(f)
    return {"fields": results, "diagnostic": diagnostic}


def _extract_fields(page) -> list:
    return page.evaluate("""
            () => {
                const results = [];
                const labels = Array.from(document.querySelectorAll('label'));
                const seen = new Set();

                for (const label of labels) {
                    const text = label.innerText || '';
                    if (!text.trim()) continue;

                    let field = null;
                    const forId = label.getAttribute('for');
                    if (forId) {
                        field = document.getElementById(forId);
                        if (!field) {
                            // Ashby's custom Yes/No widgets point `for` at a
                            // value that's the target's `name`, not its `id` --
                            // confirmed against a real posting's markup.
                            field = document.querySelector('[name="' + CSS.escape(forId) + '"]');
                        }
                    }
                    if (!field) {
                        field = label.querySelector('input, select, textarea');
                    }
                    if (!field) continue;

                    const key = field.name || field.id || text;
                    if (seen.has(key)) continue;
                    seen.add(key);

                    let fieldType = field.tagName.toLowerCase();
                    if (fieldType === 'input') fieldType = field.type || 'text';

                    // react-select comboboxes (confirmed on Country and the
                    // EEO "mark all that apply" fields) render as a plain
                    // <input type="text" role="combobox">, indistinguishable
                    // from a real text field by tag/type alone -- detect via
                    // the ARIA role instead, and tell single- vs multi-select
                    // apart via the value-container class react-select adds.
                    if (field.getAttribute('role') === 'combobox') {
                        const container = field.closest('.select__container') || field.parentElement;
                        const isMulti = container && !!container.querySelector('[class*="is-multi"]');
                        fieldType = isMulti ? 'react-select-multi' : 'react-select';
                    }

                    // File uploads (resume/cover letter) often share an
                    // identical generic visible label like "Attach" -- the
                    // real distinguishing info lives in the field's id/name
                    // instead, confirmed against real Greenhouse markup.
                    let questionText = text;
                    if (fieldType === 'file') {
                        const idOrName = ((field.id || field.name || '')).toLowerCase();
                        if (idOrName.includes('resume') || idOrName.includes('cv')) {
                            questionText = 'Resume';
                        } else if (idOrName.includes('cover')) {
                            questionText = 'Cover Letter';
                        } else if (idOrName) {
                            questionText = text + ' (' + idOrName + ')';
                        }
                    }

                    let options = [];
                    if (fieldType === 'select') {
                        options = Array.from(field.querySelectorAll('option'))
                            .map(o => o.innerText.trim()).filter(Boolean);
                    } else if (fieldType === 'checkbox') {
                        // Custom button-choice widgets (e.g. Yes/No) represent
                        // their real value via a hidden checkbox with sibling
                        // <button data-option="..."> elements next to it --
                        // pull those button labels as the real options.
                        const container = field.parentElement;
                        if (container) {
                            const optionButtons = Array.from(container.querySelectorAll('button[data-option]'));
                            if (optionButtons.length > 0) {
                                options = optionButtons.map(b => b.innerText.trim()).filter(Boolean);
                            }
                        }
                    }

                    const required = field.required === true
                        || field.getAttribute('aria-required') === 'true'
                        || text.includes('*')
                        || label.className.toLowerCase().includes('required');

                    results.push({
                        question: questionText,
                        field_type: fieldType,
                        required: required,
                        options: options,
                    });
                }

                return results;
            }
        """)
