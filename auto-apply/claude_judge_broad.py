"""
Fit judgment for the broad-discovery auto-apply track (non-target-list
companies). Kept as a separate function/file from claude_judge.py rather than
modifying judge_fit() directly, so the existing target-list pipeline's
behavior can't regress from changes made for this new track.

Adds one gate on top of the same role-fit logic used everywhere else: the
company's CORE business must be software. A role being remote, tech-adjacent,
or at a company that "uses" software doesn't qualify -- software has to be
the actual product being sold.
"""
import json
import os
import re
import requests

MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def judge_fit_broad(title: str, description: str, company_name: str, candidate_profile: str) -> dict:
    """Returns {"match": bool, "is_software_company": bool, "reason": str}"""
    api_key = os.environ["AUTOAPPLY_ANTHROPIC_API_KEY"]
    desc_text = _strip_html(description)[:8000]

    system = (
        "You screen a single job posting against one candidate's profile and target-role criteria, "
        "for a company NOT on the candidate's manually curated target list -- this is a broader, "
        "auto-apply pool, so apply the SAME role-fit logic as always, plus one additional strict gate. "
        "Respond with ONLY a JSON object, no other text: "
        '{"stated_years_required": <number or null>, "match": true or false, '
        '"is_software_company": true or false, "reason": "one short sentence"}. '
        "\n\nROLE FIT (apply exactly as usual): "
        "Some postings state a RANGE like '3-6 years' or '3-5+ years of experience.' For a range, the "
        "LOWEST number is the actual floor -- if the candidate meets or exceeds the low end, that's a "
        "match on years, regardless of the range's upper bound. Do NOT use the high end of a stated "
        "range as the requirement. "
        "Separately, some postings state a COMPOUND requirement across different sub-skills, e.g. '5+ "
        "years of analytics experience, with 3+ years in marketing analytics' -- here there are two "
        "distinct conditions, not one range, and the HIGHEST number is the binding floor. "
        "On seniority in TITLES: 'Senior Associate', 'Senior Specialist', 'Senior Coordinator' and "
        "similar are fine -- these denote individual-contributor seniority, not people management. "
        "'Manager' inside a COMPOUND functional title (e.g. 'Merchant Success Manager', 'Account "
        "Manager', 'Customer Success Manager', 'Product Manager') is a standard industry IC title, NOT "
        "a people-management role, even when preceded by 'Senior'. Only treat 'Manager' as a "
        "people-management signal when it stands alone as the generic title, or the description "
        "explicitly states the role manages/leads a team of people. Reject on title seniority only for "
        "genuine leadership titles: standalone 'Senior Manager'/'Manager' with no compound function "
        "attached, 'Director', 'Head of', 'VP', 'Lead' (as a management title), 'Principal'. "
        "The candidate wants you to STRETCH their real experience to fit adjacent requirements as long "
        "as it's honest -- a single unfamiliar tool/platform, especially 'nice to have', should NOT "
        "cause a rejection. Only reject on skills/tools if MULTIPLE specific tools are stacked as hard "
        "requirements. Always hard-reject roles that are fundamentally event-execution, social-media-"
        "management, or pure-creative/copywriting, per the candidate profile's explicit exclusions, "
        "even if other parts of the posting look like a fit. When genuinely uncertain on role fit, "
        "lean toward match=true."
        "\n\nSOFTWARE-COMPANY GATE (new, strict -- applies ONLY to this track): "
        "Classify whether the company's CORE product/business IS software -- SaaS, a software "
        "platform, developer tools, or consumer/enterprise software as the primary thing the company "
        "sells. This does NOT include companies where software supports the business but isn't the "
        "product itself: retail, e-commerce, logistics, media/streaming content, consumer packaged "
        "goods, restaurants, healthcare providers, financial services with a banking/lending core, "
        "or any company primarily known for a physical product or non-software service -- even if that "
        "company has a strong engineering org, a popular app, or the role itself is remote and tech-"
        "adjacent. If you cannot confidently place the company as software-core from the company name "
        "and posting content, set is_software_company to false rather than guessing yes -- do NOT lean "
        "toward true the way you lean toward true on role fit; this gate is intentionally strict, not "
        "generous. Base this on the company as a whole, not the specific team the role sits in."
        "\n\nFor stated_years_required: report the correct binding floor number (low end for a range, "
        "high end for a compound requirement). If no years requirement is stated at all, use null. "
        "The final \"match\" value must be false whenever is_software_company is false, regardless of "
        "how strong the role fit is."
    )

    user = f"""CANDIDATE PROFILE AND CRITERIA:
{candidate_profile}

JOB POSTING:
Company: {company_name}
Title: {title}
Description: {desc_text}

Does this posting match the candidate's target roles and experience level, AND is the company's core business software?"""

    r = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 200,
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
        is_software = bool(parsed.get("is_software_company"))
        match = bool(parsed.get("match"))
        reason = parsed.get("reason", "")

        print(f"    [debug] stated_years_required={stated_years!r} | is_software_company={is_software} "
              f"| raw_match={parsed.get('match')}")

        if stated_years is not None and stated_years > 3:
            match = False
            reason = f"Requires {stated_years}+ years (exceeds 3-year threshold). {reason}"

        if not is_software:
            match = False
            reason = f"Not a software-core company. {reason}"

        return {"match": match, "is_software_company": is_software, "reason": reason}
    except (json.JSONDecodeError, ValueError):
        return {"match": False, "is_software_company": False, "reason": f"unparsed model output: {text[:200]}"}
