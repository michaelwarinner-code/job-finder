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
    desc_text = _strip_html(description)[:4000]  # cap length to control token cost

    system = (
        "You screen a single job posting against one candidate's profile and target-role criteria. "
        "Respond with ONLY a JSON object, no other text: "
        '{"match": true or false, "reason": "one short sentence"}. '
        "Be strict on years-of-experience requirements stated in the posting -- if it clearly requires "
        "3+ years, it is NOT a match regardless of title. If experience level isn't stated, use judgment "
        "based on the title/seniority language (avoid senior/director/lead/manager-of-people titles)."
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
        return {"match": bool(parsed.get("match")), "reason": parsed.get("reason", "")}
    except (json.JSONDecodeError, ValueError):
        return {"match": False, "reason": f"unparsed model output: {text[:200]}"}
