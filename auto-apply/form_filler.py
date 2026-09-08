"""
Fills a real application form -- identity fields from candidate_info.json,
file uploads for resume/cover letter, and known answer-bank answers where
the field type is one we've confirmed how to interact with safely.

Deliberately does NOT attempt to fill:
  - EEO/self-identification questions (see eeo_answers.py) -- these need
    their own widget inspection before being touched, they are NOT simple
    <select> elements based on how they scanned (field_type: text, which is
    almost certainly a custom multi-select/typeahead, not a plain text box).
  - Greenhouse Yes/No-style screening questions (sponsorship, US location,
    etc.) -- these also scanned as field_type: text despite clearly being
    Yes/No questions, meaning they're very likely a custom widget too. Blindly
    calling .fill() on an unconfirmed widget risks typing into the wrong
    place and silently producing a wrong or unregistered answer, which is a
    worse failure than just not filling it and flagging it for a human to
    check.

Anything not confidently fillable gets reported as "needs verification"
rather than attempted. Submitting is gated behind dry_run, which defaults
to True -- with dry_run left at its default, this fills the form, takes a
screenshot, and reports what happened, without ever touching Submit. Only
an explicit dry_run=False click-submits for real, since that's the one
genuinely irreversible action in this whole pipeline.
"""
import json
import re
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from playwright.sync_api import sync_playwright
from answer_bank import load_answer_bank, match_question
from eeo_answers import classify_eeo_question, get_eeo_answer
from telegram_escalation import (escalate_question, escalate_checkbox_group,
                                  escalate_question_batch, PendingAnswerRequired, IS_UNATTENDED)
from company_question_classifier import is_company_specific_question

TIMEOUT_MS = 30000
CANDIDATE_INFO_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "candidate_info.json")
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "test_output")

# (keyword pattern, candidate_info.json key) -- checked in order, first match wins.
IDENTITY_KEYWORD_MAP = [
    (re.compile(r"first name", re.I), "first_name"),
    (re.compile(r"last name", re.I), "last_name"),
    (re.compile(r"\bname\b", re.I), "full_name"),  # single combined field, e.g. Ashby's "Name"
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"phone", re.I), "phone"),
    (re.compile(r"linkedin", re.I), "linkedin_url"),
    (re.compile(r"website|portfolio(?!\s+compan)", re.I), "website_url"),
    (re.compile(r"location|city", re.I), "location_city"),
    (re.compile(r"country", re.I), "country"),
    (re.compile(r"school|university|college", re.I), "school"),
    (re.compile(r"degree", re.I), "degree"),
    (re.compile(r"discipline|major|field of study", re.I), "discipline"),
    (re.compile(r"pronoun", re.I), "pronouns"),
    (re.compile(r"date of birth|\bdob\b", re.I), "date_of_birth"),
]


def _matches_identity_pattern(pattern, key: str, question: str) -> bool:
    """Same as pattern.search(question), except the bare 'name' pattern
    only matches SHORT, standalone labels (e.g. Ashby's plain "Name" field).
    Confirmed necessary the hard way: it was matching "If Yes, please enter
    your legal name while working at BambooHR previously. If No, please
    enter N/A." purely because the word "name" appears in that much longer,
    conditional sentence, and blindly filled the real name even though the
    label's own text said to answer N/A given a prior "No" answer."""
    if key == "full_name" and len(question) > 30:
        return False
    return bool(pattern.search(question))

# Known-safe field types to actually fill. Anything else gets flagged, not guessed.
FILLABLE_NATIVE_TYPES = {"text", "email", "tel", "url", "textarea"}

CONDITIONAL_FALLBACK_PATTERN = re.compile(
    r"if\s+no,?\s*(?:please\s+)?(?:enter|answer|type|put|write)\s+([^.\n]+)", re.IGNORECASE)


def _resolve_conditional_fallback(question: str):
    """Some fields literally state their own fallback answer in the label
    itself (e.g. "If Yes, enter your legal name... If No, please enter
    N/A."). Since this whole pipeline only ever targets companies never
    previously worked at, the "No" branch always applies -- so the
    fallback value stated in the label can be used directly, with no
    escalation needed, since it's not a judgment call, it's just reading
    the instruction that's already printed on the form."""
    m = CONDITIONAL_FALLBACK_PATTERN.search(question or "")
    return m.group(1).strip().rstrip(".") if m else None


def load_candidate_info() -> dict:
    with open(CANDIDATE_INFO_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get_selected_multi_labels(page, field_id: str) -> list:
    """Reads back the currently-visible selected chip labels for a
    react-select multi-select field -- used to verify a prior selection is
    still present after a subsequent one, rather than assuming success.
    react-select's default class naming (confirmed elsewhere on this same
    page: select__control, select__option, select__value-container) follows
    the pattern select__multi-value__label for chip text."""
    return page.evaluate(f"""
        () => {{
            const input = document.getElementById("{field_id}");
            const container = input ? input.closest('.select__container') : null;
            if (!container) return [];
            return Array.from(container.querySelectorAll('[class*="multi-value__label"]'))
                .map(el => el.innerText.trim());
        }}
    """)


def _peek_react_select_options(page, input_loc, field_id: str) -> list:
    """Opens a react-select dropdown just to read its available options --
    without selecting anything -- so an escalation can show you the real
    choices instead of asking blind. Closes the dropdown before returning."""
    try:
        input_loc.click()
        page.wait_for_timeout(500)
        listbox = page.locator(f'#react-select-{field_id}-listbox')
        options = listbox.locator('[role="option"]')
        count = options.count()
        texts = [options.nth(i).inner_text().strip() for i in range(count)]
    except Exception:
        texts = []
    finally:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    return [t for t in texts if t]


def _select_react_select_option(page, input_loc, value_text: str, field_id: str,
                                 click_to_open: bool = True, clear_first: bool = True) -> bool:
    """Clicks open a react-select combobox, types value_text to filter its
    dropdown, and clicks the matching rendered option -- confirmed against
    real markup (Country field). Returns True if a matching option was
    found and clicked, False otherwise. Setting the input's raw value
    directly (fill()) does NOT work for these -- the visible selection only
    updates through this real click interaction.

    For a SECOND (or later) pick within the same multi-select field, pass
    click_to_open=False and clear_first=False -- confirmed the hard way
    that explicitly clearing the search box (fill("")) before a later pick
    causes this widget to drop the PRIOR selection instead of keeping both,
    even though reopening the dropdown on its own is harmless. The first
    pick in a sequence should use the defaults (both True)."""
    if click_to_open:
        input_loc.click()
        page.wait_for_timeout(200)
    if clear_first:
        input_loc.fill("")
    input_loc.type(value_text, delay=30)
    page.wait_for_timeout(600)

    listbox = page.locator(f'#react-select-{field_id}-listbox')
    options = listbox.locator('[role="option"]')
    count = options.count()
    texts = [options.nth(i).inner_text().strip() for i in range(count)]

    # Prefer an EXACT match over a substring match -- confirmed necessary
    # the hard way: searching "Asian" matched "East Asian" as a substring
    # instead of failing cleanly, when what was actually wanted was a
    # generic "Asian" option that may not exist as phrased. Exact match
    # first avoids silently picking an unintended similar-sounding option.
    for i, text in enumerate(texts):
        if text.lower() == value_text.lower():
            options.nth(i).click()
            page.wait_for_timeout(500)  # let the chip render / dropdown settle before the next interaction
            return True
    for i, text in enumerate(texts):
        if value_text.lower() in text.lower():
            options.nth(i).click()
            page.wait_for_timeout(500)
            return True

    # No match found -- close the dropdown before returning, or it stays
    # open and can physically block clicks on whatever field comes next.
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    return False


def _locator_for(page, ref_type: str, ref_value: str):
    if ref_type == "id":
        return page.locator(f'[id="{ref_value}"]')
    return page.locator(f'[name="{ref_value}"]')


def _extract_fields_with_refs(page) -> list:
    """Same detection logic as browser_form_scanner.py, but also returns a
    stable id/name reference for each field so it can be re-located and
    interacted with via Playwright locators afterward, in the same page
    session."""
    return page.evaluate("""
        () => {
            const results = [];
            const labels = Array.from(document.querySelectorAll('label'));
            const seen = new Set();

            // Ashby checkbox-GROUPS: a fieldset with one shared question
            // label plus several individually-labeled option checkboxes.
            // The shared label's `for` attribute points at the fieldset's
            // own id, not at any single <input>, so the generic per-label
            // loop below finds no matching element for it and silently
            // drops the real question -- and each checkbox's own `name`
            // attribute is its OWN option text (e.g. name="Los Angeles
            // (Venice)"), never shared, so the raw_name-based grouping
            // used later never recognizes these as one group either.
            // Handle this shape explicitly with its own field_type
            // ('checkbox-group-option') rather than reusing plain
            // 'checkbox' -- confirmed the hard way that reusing the
            // existing Yes/No checkbox-group machinery here was wrong:
            // that mechanism treats a bank match as "resolved, skip it"
            // without ever actually checking the box, then a DIFFERENT
            // answer-is-literally-yes/no check downstream never checks it
            // either since the real answer here is text like "New York",
            // not "yes". This shape needs its own resolution: match the
            // GROUP question once, then check whichever option's own
            // label the answer text actually matches.
            const groupFieldsets = Array.from(document.querySelectorAll('fieldset.ashby-application-form-input-checkbox-group'));
            for (const fieldset of groupFieldsets) {
                const groupLabel = fieldset.querySelector('label.ashby-application-form-question-title');
                const groupQuestion = groupLabel ? (groupLabel.innerText || '').trim() : '';
                if (!groupQuestion) continue;
                const groupId = groupLabel.getAttribute('for') || groupQuestion;

                const options = Array.from(fieldset.querySelectorAll('.ashby-application-form-input-checkbox-group-option'));
                for (const opt of options) {
                    const input = opt.querySelector('input[type="checkbox"]');
                    const optLabel = opt.querySelector('label');
                    if (!input || !optLabel) continue;

                    const optKey = input.id || input.name;
                    seen.add(optKey);

                    results.push({
                        question: groupQuestion + ' -- ' + (optLabel.innerText || '').trim(),
                        group_question: groupQuestion,
                        option_label: (optLabel.innerText || '').trim(),
                        field_type: 'checkbox-group-option',
                        required: groupQuestion.includes('*'),
                        ref_type: input.id ? 'id' : 'name',
                        ref_value: input.id || input.name || '',
                        raw_name: 'ashby-group:' + groupId,
                    });
                }
            }

            for (const label of labels) {
                const text = label.innerText || '';
                if (!text.trim()) continue;

                let field = null;
                const forId = label.getAttribute('for');
                if (forId) {
                    field = document.getElementById(forId);
                    if (!field) field = document.querySelector('[name="' + CSS.escape(forId) + '"]');
                }
                if (!field) field = label.querySelector('input, select, textarea');
                if (!field) continue;

                const key = field.id || field.name || text;
                if (seen.has(key)) continue;
                seen.add(key);

                let fieldType = field.tagName.toLowerCase();
                if (fieldType === 'input') fieldType = field.type || 'text';

                if (field.getAttribute('role') === 'combobox') {
                    const container = field.closest('.select__container') || field.parentElement;
                    const isMulti = container && !!container.querySelector('[class*="is-multi"]');
                    fieldType = isMulti ? 'react-select-multi' : 'react-select';
                }

                let questionText = text;
                if (fieldType === 'file') {
                    const idOrName = ((field.id || field.name || '')).toLowerCase();
                    if (idOrName.includes('resume') || idOrName.includes('cv')) questionText = 'Resume';
                    else if (idOrName.includes('cover')) questionText = 'Cover Letter';
                    else if (idOrName) questionText = text + ' (' + idOrName + ')';
                }

                const required = field.required === true
                    || field.getAttribute('aria-required') === 'true'
                    || text.includes('*')
                    || label.className.toLowerCase().includes('required');

                results.push({
                    question: questionText,
                    field_type: fieldType,
                    required: required,
                    ref_type: field.id ? 'id' : 'name',
                    ref_value: field.id || field.name || '',
                    raw_name: field.name || '',
                });
            }
            return results;
        }
    """)


def _get_answer_or_queue(pending_questions: list, question: str, role_title: str, company_name: str,
                          url: str, bank_entries: list, save_to_bank: bool = True, options: list = None):
    """Routes a question either to immediate escalation (local/attended
    runs -- exactly the same blocking behavior as before) or to a queue
    for one single batched message at the very end (unattended runs --
    confirmed necessary: escalating and blocking per-question would mean
    an application needing several answers could take one separate
    scheduled run PER question to resolve, since a browser session can't
    survive between runs)."""
    if IS_UNATTENDED:
        pending_questions.append(question)
        return None
    return escalate_question(question, role_title, company_name, url, bank_entries,
                              save_to_bank=save_to_bank, options=options)


def _get_group_selection_or_queue(pending_questions: list, questions: list, role_title: str,
                                   company_name: str, url: str, bank_entries: list, save_to_bank: bool = True):
    """Same routing as _get_answer_or_queue, for a checkbox-group batch."""
    if IS_UNATTENDED:
        pending_questions.extend(questions)
        return None
    return escalate_checkbox_group(questions, role_title, company_name, url, bank_entries,
                                    save_to_bank=save_to_bank)


def _goto_application_page(page, url: str):
    """Navigates to a job's application page. Uses domcontentloaded instead
    of networkidle -- confirmed the hard way that networkidle times out on
    a real chunk of postings (chat widgets, analytics beacons, background
    polling never let network activity fully stop for 500ms), which would
    otherwise fail the whole scan/fill on pages that actually loaded fine.
    domcontentloaded plus the explicit wait below is the standard, more
    reliable pattern for this. Ashby application forms live at .../application,
    not the bare posting URL."""
    target_url = url
    if "ashbyhq.com" in url and not url.rstrip("/").endswith("/application"):
        target_url = url.rstrip("/") + "/application"

    page.goto(target_url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)  # lets JS-rendered fields (react-select etc.) finish hydrating


def scan_fields_only(url: str) -> list:
    """Opens the real live application page and returns the raw scanned
    fields (question, field_type, and real dropdown options for
    react-select fields) with NO filling, NO answer-bank lookups, NO
    escalation, and NO submission -- just the same navigation +
    extraction fill_application() does before it starts acting on
    anything, plus a peek at each dropdown's real options. Used by
    form_field_audit.py to check what questions a posting actually asks
    (and whether the answer bank would cover them) without spending a
    Telegram message, a Claude call, or generating any materials."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _goto_application_page(page, url)

        fields = _extract_fields_with_refs(page)

        for f in fields:
            if f["field_type"] in ("react-select", "react-select-multi"):
                loc = _locator_for(page, f["ref_type"], f["ref_value"])
                f["options"] = _peek_react_select_options(page, loc, f["ref_value"])
            else:
                f["options"] = []

        browser.close()
        return fields


def _resolve_answer(question: str, bank_entries: list, job_specific_answers: dict, company_specific: bool):
    """Checks job-specific pre-supplied answers FIRST -- from a prior
    Telegram exchange for THIS exact job, always safe to reuse here
    regardless of company_specific, since it's already scoped to just
    this one job. Falls back to the reusable answer bank, but ONLY when
    the question isn't company-specific -- for those, no bank entry is
    ever consulted, a fresh escalation is required (and its answer gets
    persisted as a job-specific answer by the caller, not to the bank)."""
    if job_specific_answers and question in job_specific_answers:
        return job_specific_answers[question]
    if company_specific or not bank_entries:
        return None
    idx, answer = match_question(question, bank_entries)
    return answer


def fill_application(url: str, resume_pdf_path: str, coverletter_pdf_path: str,
                      role_title: str = "", company_name: str = "", dry_run: bool = True,
                      job_specific_answers: dict = None) -> dict:
    """Returns a report: {"filled": [...], "skipped": [...], "screenshot_path": str}

    In unattended mode (see telegram_escalation.IS_UNATTENDED), any question
    with no available answer is queued rather than escalated immediately --
    at the end of the fill, if anything was queued, ONE batched Telegram
    message gets sent covering everything, and PendingAnswerRequired is
    raised so the caller (run_pipeline.py) marks the whole job pending and
    moves on. In local/attended mode, nothing changes -- each question
    still escalates and blocks exactly as before."""
    pending_questions = []
    candidate_info = load_candidate_info()
    bank_entries = load_answer_bank()

    filled = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _goto_application_page(page, url)

        fields = _extract_fields_with_refs(page)

        # Pre-pass: native checkboxes sharing a raw `name` attribute (a
        # standard HTML checkbox-group pattern, e.g. "check all that apply")
        # get batched into ONE Telegram message instead of asking about
        # each one individually, when 2+ of them would otherwise need
        # escalating. Anything already answerable via the bank or EEO
        # answers is left for the normal per-field loop below.
        handled_field_ids = set()
        groups = {}
        for f in fields:
            if f["field_type"] == "checkbox" and f.get("raw_name"):
                groups.setdefault(f["raw_name"], []).append(f)

        for group_fields in groups.values():
            if len(group_fields) < 2:
                continue

            unresolved = []
            for gf in group_fields:
                q = gf["question"].strip()
                if classify_eeo_question(q):
                    continue
                idx, ans = match_question(q, bank_entries) if bank_entries else (None, None)
                if job_specific_answers and q in job_specific_answers:
                    ans = job_specific_answers[q]
                if ans:
                    continue
                unresolved.append(gf)

            if len(unresolved) < 2:
                continue

            group_questions = [gf["question"].strip() for gf in unresolved]
            group_company_specific = any(is_company_specific_question(q, company_name) for q in group_questions)
            selected = _get_group_selection_or_queue(pending_questions, group_questions, role_title, company_name,
                                                       url, bank_entries, save_to_bank=not group_company_specific)

            for i, gf in enumerate(unresolved):
                handled_field_ids.add(gf["ref_value"])
                if selected is None:
                    reason = "queued for batch escalation" if IS_UNATTENDED else "checkbox group escalated to Telegram but timed out"
                    skipped.append({"question": gf["question"], "reason": reason})
                    continue
                should_check = i in selected
                gf_loc = _locator_for(page, gf["ref_type"], gf["ref_value"])
                try:
                    if should_check:
                        gf_loc.check(timeout=5000)
                    actual = gf_loc.is_checked()
                except Exception as e:
                    skipped.append({"question": gf["question"], "reason": f"group checkbox click failed: {e}"})
                    continue
                if actual == should_check:
                    filled.append({"question": gf["question"], "source": "TELEGRAM_ESCALATION (group)",
                                    "value": "checked" if should_check else "unchecked"})
                else:
                    skipped.append({"question": gf["question"],
                                     "reason": f"checkbox state after is checked={actual}, expected {should_check}"})

        # Pre-pass 2: Ashby-style checkbox-OPTION groups (one shared
        # question, several options -- e.g. "Which office are you willing
        # to work out of?"). Different semantics from the plain Yes/No
        # group above: the bank answer is TEXT to match against each
        # option's own label (e.g. "New York" -> check "New York City
        # (Chelsea)"), not a yes/no fact per option, and the group
        # question is matched against the bank ONCE (not per-option),
        # since matching the combined "question -- option" string against
        # a plain "which office" bank entry risks a false-ish match purely
        # because the answer text happens to appear inside the option
        # label. Every member ALWAYS ends up in handled_field_ids here,
        # whether resolved via the bank or via escalation -- unlike the
        # bug this replaced, nothing from this group is ever allowed to
        # fall through to the single-checkbox path below.
        option_groups = {}
        for f in fields:
            if f["field_type"] == "checkbox-group-option" and f.get("raw_name"):
                option_groups.setdefault(f["raw_name"], []).append(f)

        for group_fields in option_groups.values():
            group_question = group_fields[0]["group_question"]
            company_specific = is_company_specific_question(group_question, company_name)
            answer = None
            if job_specific_answers and group_question in job_specific_answers:
                answer = job_specific_answers[group_question]
            elif not company_specific and bank_entries:
                idx, answer = match_question(group_question, bank_entries)

            if not answer:
                option_questions = [gf["question"] for gf in group_fields]
                selected = _get_group_selection_or_queue(pending_questions, option_questions, role_title,
                                                           company_name, url, bank_entries,
                                                           save_to_bank=not company_specific)
                for i, gf in enumerate(group_fields):
                    handled_field_ids.add(gf["ref_value"])
                    if selected is None:
                        reason = "queued for batch escalation" if IS_UNATTENDED else "checkbox group escalated to Telegram but timed out"
                        skipped.append({"question": gf["question"], "reason": reason})
                        continue
                    should_check = i in selected
                    gf_loc = _locator_for(page, gf["ref_type"], gf["ref_value"])
                    try:
                        if should_check:
                            gf_loc.check(timeout=5000)
                        actual = gf_loc.is_checked()
                    except Exception as e:
                        skipped.append({"question": gf["question"], "reason": f"group checkbox click failed: {e}"})
                        continue
                    if actual == should_check:
                        filled.append({"question": gf["question"], "source": "TELEGRAM_ESCALATION (group)",
                                        "value": "checked" if should_check else "unchecked"})
                    else:
                        skipped.append({"question": gf["question"],
                                         "reason": f"checkbox state after is checked={actual}, expected {should_check}"})
                continue

            for gf in group_fields:
                handled_field_ids.add(gf["ref_value"])
                should_check = answer.strip().lower() in gf["option_label"].strip().lower()
                gf_loc = _locator_for(page, gf["ref_type"], gf["ref_value"])
                try:
                    if should_check:
                        gf_loc.check(timeout=5000)
                    actual = gf_loc.is_checked()
                except Exception as e:
                    skipped.append({"question": gf["question"], "reason": f"group checkbox click failed: {e}"})
                    continue
                if actual == should_check:
                    filled.append({"question": gf["question"], "source": "ANSWER_BANK",
                                    "value": "checked" if should_check else "unchecked (didn't match the bank answer)"})
                else:
                    skipped.append({"question": gf["question"],
                                     "reason": f"checkbox state after is checked={actual}, expected {should_check}"})

        for f in fields:
            if f["ref_value"] in handled_field_ids:
                continue
            question = f["question"].strip()
            field_type = f["field_type"]
            loc = _locator_for(page, f["ref_type"], f["ref_value"])

            # 1. File uploads -- exact match on the cleaned question text.
            if field_type == "file":
                path = None
                if question == "Resume":
                    path = resume_pdf_path
                elif question == "Cover Letter":
                    path = coverletter_pdf_path
                if path and os.path.exists(path):
                    loc.set_input_files(path)
                    try:
                        actual_file_count = loc.evaluate("el => el.files ? el.files.length : 0", timeout=5000)
                    except Exception:
                        # Some ATS UIs (confirmed on Greenhouse) swap out the
                        # underlying input element once a file is attached,
                        # which makes re-querying it afterward legitimately
                        # fail even on success -- that's different from Ashby,
                        # where the same element persisted. Can't confirm
                        # programmatically here, so flag for a visual check
                        # via the screenshot rather than assuming failure.
                        filled.append({"question": question, "source": "FILE_UPLOAD (UNVERIFIED)",
                                        "value": f"{os.path.basename(path)} -- element changed after upload, "
                                                  f"confirm via screenshot"})
                        continue
                    if actual_file_count > 0:
                        filled.append({"question": question, "source": "FILE_UPLOAD", "value": os.path.basename(path)})
                    else:
                        skipped.append({"question": question,
                                         "reason": "set_input_files() did not error, but the field shows 0 files "
                                                    "after -- likely bound to the wrong element (e.g. Ashby's "
                                                    "separate 'Autofill from resume' widget instead of the real "
                                                    "required Resume field). Needs investigation before trusting."})
                else:
                    skipped.append({"question": question, "reason": "unrecognized file field or missing PDF path"})
                continue

            # 2. EEO questions on a widget type we haven't confirmed how to
            # handle -- react-select and react-select-multi EEO fields are
            # handled below (step 5a), so only genuinely-unconfirmed widget
            # types get flagged here instead of guessed at.
            if classify_eeo_question(question) and field_type not in ("react-select", "react-select-multi"):
                skipped.append({"question": question, "reason": f"EEO question on unconfirmed widget type '{field_type}' -- needs inspection before filling"})
                continue

            # 3. Ashby's known Yes/No hidden-checkbox-behind-buttons widget.
            if field_type == "checkbox":
                company_specific = is_company_specific_question(question, company_name)
                answer = _resolve_answer(question, bank_entries, job_specific_answers, company_specific)
                if not answer:
                    answer = _get_answer_or_queue(pending_questions, question, role_title, company_name, url,
                                                   bank_entries, save_to_bank=not company_specific)
                    source_label = "TELEGRAM_ESCALATION"
                else:
                    source_label = "ANSWER_BANK"

                if not answer:
                    reason = "queued for batch escalation" if IS_UNATTENDED else "no answer-bank match, and escalation timed out"
                    skipped.append({"question": question, "reason": reason})
                    continue

                button = loc.locator("xpath=..").locator(f'button[data-option="{answer.lower()}"]')
                if button.count() > 0:
                    # Ashby's hidden-checkbox-behind-buttons widget.
                    button.first.click(timeout=5000)
                    try:
                        pressed = button.first.get_attribute("aria-pressed", timeout=5000)
                    except Exception:
                        filled.append({"question": question, "source": f"{source_label} (UNVERIFIED)",
                                        "value": f"{answer} -- could not re-check button state after click, confirm via screenshot"})
                        continue
                    if pressed == "true":
                        filled.append({"question": question, "source": source_label, "value": answer})
                    else:
                        skipped.append({"question": question,
                                         "reason": f"clicked the '{answer}' button but aria-pressed is "
                                                    f"{pressed!r} after, not 'true' -- needs investigation."})
                else:
                    # No Ashby-style button wrapper found -- this is a plain
                    # native <input type="checkbox">, confirmed on BambooHR's
                    # disclosure-style questions. A "yes"-shaped answer checks
                    # it; anything else leaves it unchecked (its default state).
                    is_affirmative = answer.strip().lower() in ("yes", "true", "checked", "i agree", "agree")
                    try:
                        if is_affirmative:
                            loc.check(timeout=5000)
                        actual_checked = loc.is_checked()
                    except Exception as e:
                        skipped.append({"question": question, "reason": f"native checkbox click failed: {e}"})
                        continue
                    if actual_checked == is_affirmative:
                        filled.append({"question": question, "source": source_label, "value": answer})
                    else:
                        skipped.append({"question": question,
                                         "reason": f"checkbox state after is checked={actual_checked}, "
                                                    f"expected {is_affirmative} for answer {answer!r} -- needs investigation."})
                continue

            # 4. Identity fields from candidate_info.json.
            identity_key = next((key for pattern, key in IDENTITY_KEYWORD_MAP
                                  if _matches_identity_pattern(pattern, key, question)), None)
            if identity_key and field_type in FILLABLE_NATIVE_TYPES | {"react-select"}:
                if identity_key == "full_name":
                    value = f'{candidate_info.get("first_name", "")} {candidate_info.get("last_name", "")}'.strip()
                else:
                    value = candidate_info.get(identity_key, "")
                if not value:
                    skipped.append({"question": question, "reason": f"candidate_info.json['{identity_key}'] is blank -- fill it in"})
                    continue

                if field_type == "react-select":
                    ok = _select_react_select_option(page, loc, value, f["ref_value"])
                    if ok:
                        filled.append({"question": question, "source": "CANDIDATE_INFO", "value": value})
                    else:
                        skipped.append({"question": question,
                                         "reason": f"react-select: no dropdown option matched '{value}' -- "
                                                    f"check the value in candidate_info.json against the real options."})
                    continue

                loc.fill(value)
                try:
                    actual_value = loc.input_value(timeout=5000)
                except Exception:
                    filled.append({"question": question, "source": "CANDIDATE_INFO (UNVERIFIED)",
                                    "value": f"{value} -- could not re-read field after fill, confirm via screenshot"})
                    continue
                if actual_value == value:
                    filled.append({"question": question, "source": "CANDIDATE_INFO", "value": value})
                else:
                    skipped.append({"question": question,
                                     "reason": f"fill() didn't error, but the field's actual value after is "
                                                f"{actual_value!r}, not {value!r} -- needs investigation."})
                continue

            # 5a. EEO react-select fields (single or multi) -- only attempted
            # if a real answer has been filled into state/eeo_answers.json.
            # For react-select-multi, a comma-separated value selects
            # multiple options (e.g. "White or European, East Asian"); for
            # react-select (single), the whole value is matched as one
            # option (e.g. "Two or more races"). Left untouched (not
            # explicitly declined) when blank, since these are never
            # required and a blank multi-select or unselected single-select
            # is itself a valid non-answer.
            #
            # For multi-select, only the FIRST pick clicks to open the
            # dropdown and clears the search box -- confirmed against real
            # markup that explicitly clearing the search box before a LATER
            # pick causes this widget to drop the prior selection instead of
            # keeping both. Later picks just type directly into the
            # already-open, already-empty search box.
            if field_type in ("react-select", "react-select-multi") and classify_eeo_question(question):
                is_eeo, answer = get_eeo_answer(question, field_type)
                if not answer:
                    skipped.append({"question": question, "reason": "EEO question, no answer set in eeo_answers.json -- left blank (valid decline)"})
                    continue

                if field_type == "react-select-multi":
                    values = [v.strip() for v in answer.split(",") if v.strip()]
                else:
                    values = [answer]

                all_ok = True
                for i, v in enumerate(values):
                    is_first = (i == 0)
                    ok = _select_react_select_option(page, loc, v, f["ref_value"],
                                                      click_to_open=is_first, clear_first=is_first)
                    if not ok:
                        # Your stored wording doesn't match THIS company's exact
                        # option text (confirmed: "Man" worked at DataGrail but
                        # not BambooHR) -- ask with the real options rather than
                        # silently failing every time this happens. Not saved
                        # back to eeo_answers.json -- that file stays yours to
                        # edit manually; this only fixes the current field.
                        real_options = _peek_react_select_options(page, loc, f["ref_value"])
                        escalated = _get_answer_or_queue(pending_questions, question, role_title, company_name, url,
                                                          bank_entries, save_to_bank=False, options=real_options)
                        if escalated:
                            ok = _select_react_select_option(page, loc, escalated, f["ref_value"],
                                                              click_to_open=is_first, clear_first=is_first)
                        if not ok:
                            skipped.append({"question": question, "reason": f"no option matched '{v}' or the escalated reply"})
                    all_ok = all_ok and ok

                if field_type == "react-select-multi" and values:
                    # Verify the full set actually stuck -- real safety net,
                    # not a workaround for the bug (that's fixed above), just
                    # confirming the end state matches what was intended
                    # before ever calling this a success.
                    current = _get_selected_multi_labels(page, f["ref_value"])
                    missing = [v for v in values if not any(v.lower() in c.lower() for c in current)]
                    if missing:
                        all_ok = False
                        skipped.append({"question": question,
                                         "reason": f"react-select-multi: {missing} not showing as selected -- "
                                                    f"current chips: {current}. Needs investigation, do not trust this field."})

                if all_ok and values:
                    filled.append({"question": question, "source": "EEO_ANSWERS", "value": answer})
                continue

            # 5. Everything else that's a confirmed-safe native type: answer bank.
            if field_type in FILLABLE_NATIVE_TYPES:
                fallback = _resolve_conditional_fallback(question)
                if fallback is not None:
                    loc.fill(fallback)
                    filled.append({"question": question, "source": "CONDITIONAL_FALLBACK", "value": fallback})
                    continue

                company_specific = is_company_specific_question(question, company_name)
                answer = _resolve_answer(question, bank_entries, job_specific_answers, company_specific)

                if answer:
                    loc.fill(answer)
                    try:
                        actual_value = loc.input_value(timeout=5000)
                    except Exception:
                        filled.append({"question": question, "source": "ANSWER_BANK (UNVERIFIED)",
                                        "value": f"{answer} -- could not re-read field after fill, confirm via screenshot"})
                        continue
                    if actual_value == answer:
                        filled.append({"question": question, "source": "ANSWER_BANK", "value": answer})
                    else:
                        skipped.append({"question": question,
                                         "reason": f"fill() didn't error, but actual value after is "
                                                    f"{actual_value!r}, not {answer!r} -- needs investigation."})
                else:
                    escalated = _get_answer_or_queue(pending_questions, question, role_title, company_name, url,
                                                      bank_entries, save_to_bank=not company_specific)
                    if escalated:
                        loc.fill(escalated)
                        source = "TELEGRAM_ESCALATION (not saved, company-specific)" if company_specific else "TELEGRAM_ESCALATION"
                        filled.append({"question": question, "source": source, "value": escalated})
                    else:
                        reason = "queued for batch escalation" if IS_UNATTENDED else "escalated to Telegram but timed out waiting for a reply"
                        skipped.append({"question": question, "reason": reason})
                continue

            # 5b. Non-EEO react-select (single) fields -- same answer-bank
            # lookup as plain text fields, but using real click interaction
            # instead of fill(), since react-select ignores raw value-setting.
            if field_type == "react-select":
                company_specific = is_company_specific_question(question, company_name)
                answer = _resolve_answer(question, bank_entries, job_specific_answers, company_specific)

                if answer:
                    ok = _select_react_select_option(page, loc, answer, f["ref_value"])
                    if ok:
                        filled.append({"question": question, "source": "ANSWER_BANK", "value": answer})
                    else:
                        # Stored answer's wording doesn't match THIS company's real
                        # options -- rather than fail silently, ask with the real
                        # choices instead of leaving the field blank.
                        real_options = _peek_react_select_options(page, loc, f["ref_value"])
                        escalated = _get_answer_or_queue(pending_questions, question, role_title, company_name, url,
                                                          bank_entries,
                                                          save_to_bank=not is_company_specific_question(question, company_name),
                                                          options=real_options)
                        if escalated and _select_react_select_option(page, loc, escalated, f["ref_value"]):
                            filled.append({"question": question, "source": "TELEGRAM_ESCALATION", "value": escalated})
                        else:
                            reason = "queued for batch escalation" if IS_UNATTENDED else (
                                f"stored answer '{answer}' didn't match this company's dropdown, "
                                f"and the escalated reply also didn't match -- needs investigation.")
                            skipped.append({"question": question, "reason": reason})
                else:
                    company_specific = is_company_specific_question(question, company_name)
                    real_options = _peek_react_select_options(page, loc, f["ref_value"])
                    escalated = _get_answer_or_queue(pending_questions, question, role_title, company_name, url,
                                                      bank_entries, save_to_bank=not company_specific, options=real_options)
                    if escalated:
                        ok = _select_react_select_option(page, loc, escalated, f["ref_value"])
                        if ok:
                            source = "TELEGRAM_ESCALATION (not saved, company-specific)" if company_specific else "TELEGRAM_ESCALATION"
                            filled.append({"question": question, "source": source, "value": escalated})
                        else:
                            skipped.append({"question": question, "reason": f"got answer '{escalated}' via Telegram, but no matching dropdown option found"})
                    else:
                        reason = "queued for batch escalation" if IS_UNATTENDED else "escalated to Telegram but timed out waiting for a reply"
                        skipped.append({"question": question, "reason": reason})
                continue

            # 6. Any other field type we haven't confirmed how to interact with.
            skipped.append({"question": question, "reason": f"unconfirmed widget type '{field_type}' -- needs inspection, not guessed at"})

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        screenshot_path = os.path.join(
            SCREENSHOT_DIR, f"filled_form_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        page.screenshot(path=screenshot_path, full_page=True)

        submitted = False
        submit_note = "DRY RUN -- form filled but NOT submitted. Pass dry_run=False to actually submit."

        if not dry_run:
            # Only reached when dry_run is explicitly set to False -- this
            # is the one genuinely irreversible action in this whole
            # pipeline, so it never happens by accident or by default.
            submit_btn = page.get_by_role("button", name=re.compile(r"submit", re.IGNORECASE)).first
            if submit_btn.count() == 0:
                submit_note = "Could not find a Submit button -- nothing was submitted."
            else:
                submit_btn.click(timeout=10000)
                page.wait_for_timeout(2500)
                confirmation_screenshot = os.path.join(
                    SCREENSHOT_DIR, f"post_submit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                )
                page.screenshot(path=confirmation_screenshot, full_page=True)
                body_text = (page.inner_text("body") or "").lower()
                looks_successful = any(kw in body_text for kw in
                                        ["thank you", "application submitted", "we've received", "successfully submitted"])
                submitted = looks_successful
                submit_note = (
                    f"Clicked Submit. Page {'shows a confirmation message' if looks_successful else 'does NOT clearly show a confirmation message -- check the screenshot manually'}. "
                    f"Post-submit screenshot: {confirmation_screenshot}"
                )

        browser.close()

    if pending_questions and IS_UNATTENDED:
        # Nobody's watching this run live -- send everything that couldn't
        # be answered as ONE batched message, then hand back control so
        # run_pipeline.py can mark the whole job pending and move on to
        # the next one, rather than sitting idle.
        escalate_question_batch(pending_questions, role_title, company_name, url)
        raise PendingAnswerRequired(pending_questions,
                                     report={"filled": filled, "skipped": skipped,
                                             "screenshot_path": screenshot_path})

    return {"filled": filled, "skipped": skipped, "screenshot_path": screenshot_path,
            "dry_run": dry_run, "submitted": submitted, "submit_note": submit_note}
