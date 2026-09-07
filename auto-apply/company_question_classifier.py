"""
Detects application questions that are inherently specific to one company
or role -- "why are you excited about this role," "why do you want to work
here" -- and should NEVER be saved to the reusable answer bank the way
"are you authorized to work in the US" is. A stored answer to one of these
would get matched via semantic similarity against a differently-worded
version of the same question at a COMPLETELY DIFFERENT company, producing
an obviously wrong, off-topic answer.

Keyword-based (like eeo_answers.py's classifier) rather than semantic,
since the pattern here is about question SHAPE, not needing judgment.
"""
import re

# Some questions template the company's OWN name into otherwise-universal
# phrasing (confirmed on BambooHR: "How did you hear about BambooHR?",
# "...employment with BambooHR", "...employed by BambooHR") -- the company
# name appearing in the text does NOT mean the answer is company-specific.
# Checked before the company-name check below, so these always stay
# reusable regardless of which company's name got templated in.
ALWAYS_GENERIC_PATTERNS = [
    re.compile(r"how did you (hear|find out|learn) about", re.I),
    re.compile(r"have you (ever\s+)?(previously\s+)?worked (for|at)", re.I),
    re.compile(r"(current or )?former\s+\S+\s+employee", re.I),  # e.g. "Are you a former Motive Employee?"
    re.compile(r"sponsor|petition.*employment|nonimmigrant status|require.*visa", re.I),
    re.compile(r"family member|relative|close personal relationship.*(employed|working)", re.I),
    # Standard compliance/HR declarations -- the company name usually appears
    # ("...while employed at BambooHR") but the underlying question and the
    # correct answer are the same fact about YOU at every company: do you
    # have a non-compete, an outside financial interest in a competitor, or
    # intend outside employment/board work. Confirmed template on BambooHR;
    # near-identical wording is common across ATS "employment agreement"
    # sections generally, not specific to that one posting.
    re.compile(r"non-compete|non-solicitation|confidentiality obligation|restrictive covenant", re.I),
    re.compile(r"financial interest.*(competitor|customer|vendor|partner)", re.I),
    re.compile(r"outside employment|consulting|freelance work|board|advisory board|officer.*trustee", re.I),
    # GDPR/CCPA-style data-processing consent -- near-universal boilerplate,
    # the company name is just templated in ("...consent to BambooHR and
    # its third-party service providers collecting...").
    re.compile(r"consent to.*(collect|process).*personal data|privacy notice", re.I),
]

COMPANY_SPECIFIC_PATTERNS = [
    re.compile(r"why.*(excited|interested).*(role|position|company|join|team|us\b)", re.I),
    re.compile(r"why.*(want to work|do you want to join)", re.I),
    re.compile(r"why\s+(this\s+)?(company|role|position|team)\b", re.I),
    re.compile(r"what (excites|interests) you about", re.I),
    re.compile(r"why\s+(are\s+you\s+)?(a\s+)?(good\s+)?fit", re.I),
]


def is_company_specific_question(question_text: str, company_name: str = "") -> bool:
    """True if this question's answer would only make sense for ONE
    specific company/role and should never be persisted for reuse
    elsewhere -- callers should skip the answer bank entirely for these
    (never match against it, never save a new answer to it) and always
    escalate fresh each time instead."""
    text = question_text or ""
    if any(p.search(text) for p in ALWAYS_GENERIC_PATTERNS):
        return False
    if company_name and company_name.strip() and company_name.lower() in text.lower():
        return True
    return any(p.search(text) for p in COMPANY_SPECIFIC_PATTERNS)
