"""
Generates resume_data.json and coverletter_data.json for one matched
posting, using state/resume_coverletter_prompt.md as the system prompt --
Michael's existing, working content generator (vehicle bank, experience
bank, skill bank, hard rules) verbatim, with only three adaptations for
running headless via the API instead of in a Claude Project chat:
  1. Framing note that this is a system prompt, not project knowledge.
  2. A "needs_clarification" JSON escape hatch for the several places the
     original document says "ask me in the chat before generating" -- there
     is no chat to ask in here, so the model returns that JSON instead and
     this script surfaces it rather than generating anything.
  3. A salutation fallback for when the recruiter name field is blank
     (always true on this track, since there's no recruiter lookup at this
     volume) -- falls back to "Dear Hiring Team," instead of a name-based
     salutation.
Every other rule, bank, and instruction in that document is untouched --
see state/resume_coverletter_prompt.md for the source of truth, this file
does not duplicate or override any of its content.
"""
import json
import os
import re
import time
from datetime import date

MODEL = "claude-sonnet-4-6"
API_URL = "https://api.anthropic.com/v1/messages"
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "resume_coverletter_prompt.md")
MAX_API_RETRIES = 3
API_RETRY_BACKOFF_SECONDS = 10


class NeedsClarification(Exception):
    """Raised when the model determines it needs a human answer before it
    can generate honestly (a hard keyword not in the bank, an unknown
    connection company, etc.) -- per the prompt document's own escalation
    rules, just surfaced as an exception instead of a plain-text question
    since nothing is listening for a mid-conversation reply here."""
    def __init__(self, question: str):
        self.question = question
        super().__init__(question)


def load_system_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _build_user_message(job_description: str, company: str, job_title: str) -> str:
    # Recruiter and connection fields are left blank on purpose -- no
    # recruiter lookup happens on this track, and connections only exist
    # for target-list companies Michael has personally networked at, never
    # for companies surfaced by broad discovery.
    today_obj = date.today()
    today = f"{today_obj.day} {today_obj.strftime('%B %Y')}"
    return f"""{job_description}
recruiter name:
recruiter city, state:
recruiter title:
Company: {company}
Job title: {job_title}
Connection names (if applicable):
Connection amount (if applicable):
Today's date: {today}"""


def _call_claude(system: str, messages: list) -> tuple:
    """POSTs to the Messages API with retry-and-backoff for transient
    network failures (timeouts, connection resets) -- confirmed necessary
    the hard way: a 12000-max_tokens response with heavy visible reasoning
    can legitimately take a couple minutes to fully generate, and a single
    slow moment shouldn't kill an otherwise-fine request."""
    import requests
    api_key = os.environ["AUTOAPPLY_ANTHROPIC_API_KEY"]

    last_exc = None
    for attempt in range(MAX_API_RETRIES):
        try:
            r = requests.post(
                API_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={
                    "model": MODEL,
                    "max_tokens": 32000,
                    "temperature": 0.3,
                    "system": system,
                    "messages": messages,
                },
                timeout=600,
            )
            if not r.ok:
                print(f"    [claude-api-error] status={r.status_code} body={r.text[:500]}")
            r.raise_for_status()
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return text, data.get("stop_reason")
        except requests.exceptions.RequestException as e:
            last_exc = e
            print(f"    [materials-api] network error (attempt {attempt + 1}/{MAX_API_RETRIES}): {e}")
            if attempt < MAX_API_RETRIES - 1:
                time.sleep(API_RETRY_BACKOFF_SECONDS)
    raise last_exc


def _try_parse_clarification(text: str):
    """Checks whether the whole response is (or contains) a
    {"needs_clarification": true, "question": "..."} object, per the
    prompt's escalation contract. Returns the question string, or None."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and parsed.get("needs_clarification"):
            return parsed.get("question", "(no question text provided)")
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _extract_labeled_json_block(text: str, label: str) -> dict:
    """Finds a fenced ```json block that appears after the given label
    (e.g. 'resume_data.json'), per the document's own labeling rule."""
    pattern = rf"{re.escape(label)}.*?```(?:json)?\s*\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if not m:
        raise ValueError(f"Could not find a labeled '{label}' code block in the model's response")
    return json.loads(m.group(1))


MAX_CORRECTION_ATTEMPTS = 5


def generate_materials(job_description: str, company: str, job_title: str) -> tuple:
    """Returns (resume_data, coverletter_data) as dicts. Raises
    NeedsClarification if the model determined it can't generate honestly
    without a human answer -- catch this at the call site and route it
    into whatever escalation flow (Telegram ping, skip-and-log, etc.)
    makes sense there.

    If the generated resume violates the bullet-count rule (confirmed the
    hard way: the model can pass every individual per-company check while
    still failing the TOTAL, since summing three separately-verified counts
    is a different check the model doesn't always run), this automatically
    sends the specific violation back in the same conversation and asks for
    a corrected version, up to MAX_CORRECTION_ATTEMPTS times, rather than
    just hoping a one-shot self-check instruction was followed."""
    system = load_system_prompt()
    user = _build_user_message(job_description, company, job_title)
    messages = [{"role": "user", "content": user}]

    raw, stop_reason = _call_claude(system, messages)

    question = _try_parse_clarification(raw)
    if question:
        raise NeedsClarification(question)

    resume_data, coverletter_data = _parse_materials(raw, stop_reason)

    for attempt in range(MAX_CORRECTION_ATTEMPTS):
        violations = _validate_bullet_counts(resume_data)
        if not violations:
            break

        print(f"[bullet-count-violation] attempt {attempt + 1}: {violations}")
        total_bullets = sum(len(e.get("bullets", [])) for e in resume_data.get("experience", []))
        overage = total_bullets - TOTAL_BULLET_CAP
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
            f"Your resume violates the bullet-count rule: " + "; ".join(violations) + ". "
            f"You currently have {total_bullets} bullets total -- that's {max(overage, 0)} more than the "
            f"7-bullet cap allows, so you need to cut {max(overage, 0)} bullets in this pass, not just one. "
            f"Cut bullets per the trimming order already specified in your instructions (fluff first, then "
            f"shorten near-limit bullets, then cut whole bullets by relevance) until the total is 7 or fewer "
            f"and every per-company range is also satisfied. Output the corrected resume_data.json and "
            f"coverletter_data.json in the exact same labeled format, nothing else."})

        raw, stop_reason = _call_claude(system, messages)
        resume_data, coverletter_data = _parse_materials(raw, stop_reason)

    remaining_violations = _validate_bullet_counts(resume_data)
    for warning in remaining_violations:
        print(f"[bullet-count-warning] STILL VIOLATING after {MAX_CORRECTION_ATTEMPTS} correction attempt(s): {warning}")

    return resume_data, coverletter_data


def _parse_materials(raw: str, stop_reason: str = None) -> tuple:
    try:
        resume_data = _extract_labeled_json_block(raw, "resume_data.json")
        coverletter_data = _extract_labeled_json_block(raw, "coverletter_data.json")
    except ValueError:
        if stop_reason == "max_tokens":
            print(f"\n[parse-error] Response got CUT OFF by the {MODEL} max_tokens limit before it ever reached "
                  f"the labeled JSON blocks -- this is a truncation, not a malformed response. The model was "
                  f"still mid-reasoning (see raw text below) when it ran out of budget. Raise max_tokens in "
                  f"_call_claude() further if this keeps happening.\n")
        else:
            print("\n[parse-error] Could not find the expected labeled JSON blocks. "
                  "Here is the model's raw response so you can see what it actually said:\n")
        print(raw)
        raise
    return resume_data, coverletter_data


# Per-company allowed bullet ranges and the overall cap, per the prompt
# document's own P0 rule -- this only VERIFIES the model followed its own
# instructions, it never rewrites or trims anything itself.
EXPERIENCE_BULLET_RANGES = {
    "The Coca-Cola Company": (2, 4),
    "Chick-fil-A": (2, 4),
    "TN Marketing": (1, 3),
}
TOTAL_BULLET_CAP = 7


def _validate_bullet_counts(resume_data: dict) -> list:
    """Returns a list of human-readable warning strings if the generated
    resume violates the document's own bullet-count rule -- catches a
    compliance miss (the model dropping a numeric constraint under the
    weight of a long prompt) before it ever reaches a PDF, rather than
    only noticing after the resume spills onto a second page."""
    warnings = []
    experience = resume_data.get("experience", [])
    total = 0

    for entry in experience:
        company = entry.get("company", "")
        count = len(entry.get("bullets", []))
        total += count

        matched_range = next((r for name, r in EXPERIENCE_BULLET_RANGES.items() if name in company), None)
        if matched_range:
            low, high = matched_range
            if not (low <= count <= high):
                warnings.append(f"{company}: {count} bullets (expected {low}-{high})")

    if total > TOTAL_BULLET_CAP:
        warnings.append(f"Total experience bullets: {total} (cap is {TOTAL_BULLET_CAP}) -- likely to spill to a second page")

    return warnings
