"""
The answer bank for recurring application-form questions (work authorization,
sponsorship, years of experience in X, salary expectations, start date, etc).

Storage: state/answer_bank.json, a list of entries:
    {"answer": str, "aliases": [known question phrasings], "added_date": iso date}

Matching a NEW question against the bank uses Claude rather than exact string
matching, since the same question gets phrased differently across companies
("Are you legally authorized to work in the US?" vs "Do you require
sponsorship, now or in the future?"). When a match is found, the new phrasing
gets added as an alias on that entry (consolidation) rather than creating a
near-duplicate entry -- so the bank converges toward one entry per real
question over time instead of accumulating variants.
"""
import json
import re
import os
import re
from datetime import date

MODEL = "claude-haiku-4-5-20251001"  # cheap/fast is fine for a yes/no match call
API_URL = "https://api.anthropic.com/v1/messages"
BANK_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "answer_bank.json")


def load_answer_bank() -> list:
    if not os.path.exists(BANK_PATH):
        return []
    with open(BANK_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_answer_bank(entries: list):
    os.makedirs(os.path.dirname(BANK_PATH), exist_ok=True)
    with open(BANK_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def _call_claude(system: str, user: str) -> str:
    import requests
    api_key = os.environ["AUTOAPPLY_ANTHROPIC_API_KEY"]
    r = requests.post(
        API_URL,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": MODEL,
            "max_tokens": 300,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=30,
    )
    if not r.ok:
        print(f"    [claude-api-error] status={r.status_code} body={r.text[:500]}")
    r.raise_for_status()
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    # Some responses include a bit of text alongside the JSON rather than
    # ONLY the JSON -- confirmed the hard way (a strict json.loads() on the
    # whole response crashed with "Extra data" once the bank grew large
    # enough that the model added a short aside). Pull out just the first
    # {...} object instead of assuming the whole string is clean JSON.
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    return json.loads(cleaned)


def match_question(question_text: str, entries: list):
    """Checks whether question_text is asking for the same information as an
    existing bank entry. Returns (index, answer) if matched, or (None, None)
    if this is a genuinely new question."""
    if not entries:
        return None, None

    numbered = "\n".join(
        f"{i}. Answer: \"{e['answer']}\" | Known phrasings: {e['aliases']}"
        for i, e in enumerate(entries)
    )

    system = (
        "You match a new job application question against a bank of previously-answered questions. "
        "Two questions match if they are asking for the SAME underlying information, even when worded "
        "completely differently (e.g. 'Are you legally authorized to work in the US?' and 'Do you have "
        "US work authorization?' are the same underlying question). Do NOT match questions that are "
        "related but ask for genuinely different information, even when they share a lot of vocabulary "
        "(e.g. 'years of experience in marketing' and 'years of experience with HubSpot specifically' "
        "are different questions, even though both are 'years of experience' questions). "
        "Work authorization and visa sponsorship are a common false-positive pair -- 'Are you legally "
        "authorized to work in the US?' and 'Will you now or in the future require visa sponsorship?' "
        "sound related but ask opposite things and can have opposite answers (someone can be authorized "
        "to work AND require future sponsorship, e.g. on a visa that needs renewal). NEVER match "
        "authorization-status questions to sponsorship-requirement questions, or vice versa, even though "
        "they're both immigration-adjacent -- treat them as always separate entries. "
        "When uncertain, do not match -- a missed match just means one extra question gets asked, a "
        "false match means giving a wrong answer to something, which is the worse failure. "
        'Respond with ONLY a JSON object: {"matched_index": <integer index from the list, or null>}.'
    )
    user = f"""EXISTING BANK ENTRIES:
{numbered}

NEW QUESTION TO CHECK:
"{question_text}"

Does this match one of the existing entries?"""

    raw = _call_claude(system, user)
    parsed = _extract_json(raw)
    idx = parsed.get("matched_index")

    if idx is None or not (0 <= idx < len(entries)):
        return None, None
    return idx, entries[idx]["answer"]


def add_or_consolidate(question_text: str, answer_text: str, entries: list) -> list:
    """Adds a new confirmed answer to the bank. If the question matches an
    existing entry, the phrasing is added as a new alias on that entry
    instead of creating a near-duplicate. Returns the updated entries list
    -- caller is responsible for calling save_answer_bank() with it."""
    idx, _ = match_question(question_text, entries)

    if idx is not None:
        if question_text not in entries[idx]["aliases"]:
            entries[idx]["aliases"].append(question_text)
        return entries

    entries.append({
        "answer": answer_text,
        "aliases": [question_text],
        "added_date": date.today().isoformat(),
    })
    return entries
