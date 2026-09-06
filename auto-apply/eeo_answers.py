"""
Handles EEO/voluntary self-identification questions (gender identity, race
or ethnic background, sexual orientation, transgender status, disability,
veteran status) separately from the general answer bank in answer_bank.py.

These are always legally optional -- companies cannot use them in hiring
decisions, which is why the scanner never flags them as required -- and the
question categories are fixed and well-known, so this uses keyword
classification instead of the Claude-based semantic matcher the general
answer bank uses. That also means these questions and answers never need to
be sent through any API call at all.

Kept in state/eeo_answers.json, a separate file from state/answer_bank.json,
so it's always unambiguous what that file contains. It ships with empty
placeholder values -- fill in your real answers directly in that file on
your own machine. This module never asks for or receives them through the
chat or any API call.
"""
import json
import os
import re

EEO_ANSWERS_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "eeo_answers.json")

# (keyword pattern, key into eeo_answers.json)
# Patterns are intentionally broad on the second try -- confirmed the hard
# way that different companies phrase the same EEO category very
# differently (DataGrail: "How would you describe your gender identity?",
# BambooHR: bare "Gender"; DataGrail: "racial/ethnic background", BambooHR:
# "Please identify your race"). Checked in order -- hispanic_latino before
# the broader race pattern, since BambooHR asks it as its own separate
# Yes/No question, distinct from race category.
EEO_KEYWORD_MAP = [
    (re.compile(r"gender identity|\bgender\b", re.I), "gender_identity"),
    (re.compile(r"hispanic|latino|latinx", re.I), "hispanic_latino"),
    (re.compile(r"racial|ethnic|\brace\b", re.I), "racial_ethnic_background"),
    (re.compile(r"sexual orientation", re.I), "sexual_orientation"),
    (re.compile(r"transgender", re.I), "transgender"),
    (re.compile(r"disabilit|chronic condition", re.I), "disability"),
    (re.compile(r"veteran|armed forces", re.I), "veteran_status"),
]


def classify_eeo_question(question_text: str):
    """Returns the eeo_answers.json key this question maps to, or None if
    this isn't an EEO/self-identification question at all -- callers should
    check this BEFORE ever passing a question to the general answer bank,
    so these never get routed through Claude matching or a Telegram
    escalation."""
    for pattern, key in EEO_KEYWORD_MAP:
        if pattern.search(question_text or ""):
            return key
    return None


def load_eeo_answers() -> dict:
    if not os.path.exists(EEO_ANSWERS_PATH):
        return {}
    with open(EEO_ANSWERS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_eeo_answer(question_text: str, field_type: str = None):
    """Returns (is_eeo_question: bool, answer: str or None).

    is_eeo_question=True means this question should be routed here and
    NEVER to the general answer bank, regardless of whether a real answer
    has been filled in yet.

    Some questions (race/ethnicity in particular) get offered as either a
    true multi-select widget (pick "White" and "Asian" separately) or a
    single-select with one combined option ("Two or more races") depending
    on the company's form -- there's no way to know which in advance. To
    handle both, a value in eeo_answers.json can be either:
      - a plain string, used as-is regardless of widget type, or
      - an object {"multi": "...", "single": "..."}, in which case the
        right variant is picked based on the field_type actually detected
        on the real form.

    If the corresponding value is still blank (or the needed variant is
    missing), answer comes back as None -- callers should treat that as
    "select decline to answer" / leave blank rather than escalating,
    since these are never required and no other fallback is appropriate."""
    key = classify_eeo_question(question_text)
    if key is None:
        return False, None

    answers = load_eeo_answers()
    raw = answers.get(key)

    if isinstance(raw, dict):
        variant = "multi" if field_type == "react-select-multi" else "single"
        value = (raw.get(variant) or "").strip()
    else:
        value = (raw or "").strip()

    return True, (value if value else None)
