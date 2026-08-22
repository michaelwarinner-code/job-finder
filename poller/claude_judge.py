import json
import os
import re
import requests

MODEL = "claude-haiku-4-5-20251001"  # cheap + fast, plenty for this classification task
API_URL = "https://api.anthropic.com/v1/messages"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def judge_fit(title: str, description: str, company_name: str, candidate_profile: str) -> dict:
    """Returns {"match": bool, "reason": str}"""
    api_key = os.environ["ANTHROPIC_API_KEY"]
    desc_text = _strip_html(description)[:8000]  # cap length to control token cost
    print(f"    [debug] description length={len(desc_text)} | last 300 chars: ...{desc_text[-300:]}")

    system = (
        "You screen a single job posting against one candidate's profile and target-role criteria. "
        "Respond with ONLY a JSON object, no other text: "
        '{"stated_years_required": <number or null>, "match": true or false, "reason": "one short sentence"}. '
        "Some postings state a compound experience requirement, e.g. '5+ years of analytics experience, "
        "with 3+ years in marketing analytics' or '3 years in product management and 5 years in sales.' "
        "In these cases, use the HIGHEST experience number stated as the binding floor for the role -- not whichever "
        "number happens to be first, or whichever number happens to align with the candidate's own "
        "experience. Read every number in the requirement before deciding which is the real threshold." 
        "For stated_years_required: read the posting carefully and extract the HIGHEST years-of-experience "
        "number stated as a requirement anywhere in the text. If no years requirement is stated at all, use "
        "null. Do this extraction first, carefully, before deciding match. "
        "On seniority in TITLES specifically: 'Senior Associate', 'Senior Specialist', 'Senior Coordinator' "
        "and similar are fine -- these denote individual-contributor seniority, not people management. "
        "Reject on title seniority only for people-management-of-marketers or leadership titles: 'Senior "
        "Manager', 'Director', 'Head of', 'VP', 'Lead' (as a management title), 'Principal'. "
        "The candidate wants you to STRETCH their real experience to fit adjacent requirements as long as "
        "it's honest -- a single unfamiliar tool/platform, especially listed as 'nice to have', should NOT "
        "cause a rejection. Only reject on skills/tools if MULTIPLE specific tools are stacked as hard "
        "requirements. Always hard-reject roles that are fundamentally event-execution, social-media-"
        "management, or pure-creative/copywriting, per the candidate profile's explicit exclusions, even if "
        "other parts of the posting look like a fit. When genuinely uncertain on fit, lean toward match=true."
    )

    user = f"""CANDIDATE PROFILE AND CRITERIA:
{candidate_profile}

JOB POSTING:
Company: {company_name}
Title: {title}
Description: {desc_text}

Does this posting match the candidate's target roles and experience level?"""

    r = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 150,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        stated_years = parsed.get("stated_years_required")
        match = bool(parsed.get("match"))
        reason = parsed.get("reason", "")

        print(f"    [debug] stated_years_required={stated_years!r} | raw_match={parsed.get('match')} | title_check")

        if stated_years is not None and stated_years > 3:
            match = False
            reason = f"Requires {stated_years}+ years (exceeds 3-year threshold). {reason}"

        return {"match": match, "reason": reason}
    except (json.JSONDecodeError, ValueError):
        return {"match": False, "reason": f"unparsed model output: {text[:200]}"}
