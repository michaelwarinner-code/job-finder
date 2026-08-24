"""
Fetchers for each ATS type. Each function returns a list of normalized dicts:
    { "job_id": str, "title": str, "location": str, "url": str, "description": str, "posted": str|None }

job_id must be STABLE and UNIQUE per posting per company so we can diff against
previously-seen IDs to detect "new" postings.
"""
import requests

HEADERS = {"User-Agent": "job-alert-bot/1.0 (personal use)"}
TIMEOUT = 20


def fetch_greenhouse(board_token: str):
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    out = []
    for job in data.get("jobs", []):
        out.append({
            "job_id": f"gh-{board_token}-{job['id']}",
            "title": job.get("title", ""),
            "location": (job.get("location") or {}).get("name", ""),
            "url": job.get("absolute_url", ""),
            "description": job.get("content", "") or "",
            "posted": job.get("updated_at"),
        })
    return out


def fetch_lever(board_token: str):
    url = f"https://api.lever.co/v0/postings/{board_token}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    out = []
    for job in data:
        cat = job.get("categories", {}) or {}
        out.append({
            "job_id": f"lever-{board_token}-{job['id']}",
            "title": job.get("text", ""),
            "location": cat.get("location", ""),
            "url": job.get("hostedUrl", ""),
            "description": job.get("descriptionPlain", "") or job.get("description", "") or "",
            "posted": job.get("createdAt"),
        })
    return out


def fetch_ashby(board_token: str):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_token}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    out = []
    for job in data.get("jobs", []):
        out.append({
            "job_id": f"ashby-{board_token}-{job['id']}",
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "url": job.get("jobUrl", job.get("applyUrl", "")),
            "description": job.get("descriptionPlain", "") or job.get("descriptionHtml", "") or "",
            "posted": job.get("publishedAt"),
        })
    return out


def fetch_smartrecruiters(company_identifier: str):
    """company_identifier is the SmartRecruiters company slug/ID, e.g. 'Snap'.
    NOTE: verify this slug during setup -- see README."""
    url = f"https://api.smartrecruiters.com/v1/companies/{company_identifier}/postings"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params={"limit": 100})
    r.raise_for_status()
    data = r.json()
    out = []
    for job in data.get("content", []):
        loc = job.get("location", {}) or {}
        location_str = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        job_id = job.get("id")
        # Fetch full description (SmartRecruiters list endpoint doesn't include it)
        desc = ""
        try:
            detail = requests.get(
                f"https://api.smartrecruiters.com/v1/companies/{company_identifier}/postings/{job_id}",
                headers=HEADERS, timeout=TIMEOUT,
            )
            if detail.ok:
                jd = detail.json().get("jobAd", {}).get("sections", {})
                desc = " ".join(
                    (jd.get(k, {}) or {}).get("text", "") for k in jd
                )
        except requests.RequestException:
            pass
        out.append({
            "job_id": f"sr-{company_identifier}-{job_id}",
            "title": job.get("name", ""),
            "location": location_str,
            "url": job.get("ref", f"https://jobs.smartrecruiters.com/{company_identifier}/{job_id}"),
            "description": desc,
            "posted": job.get("releasedDate"),
        })
    return out


def fetch_workday(tenant: str, site: str, locale: str = "en-US"):
    """tenant e.g. 'snapchat', site e.g. the site name shown in the Workday URL path
    after the locale segment (e.g. 'snap' in snapchat.wd1.myworkdayjobs.com/en-US/snap/...).
    NOTE: verify tenant + site during setup -- see README."""
    base = f"https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        out = []
    offset = 0
    limit = 20
    while True:
        r = requests.post(
            base, headers={**HEADERS, "Content-Type": "application/json"},
            json={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for job in postings:
            path = job.get("externalPath", "")
            job_id = path.rsplit("/", 1)[-1] if path else job.get("title", "")
            out.append({
                "job_id": f"wd-{tenant}-{job_id}",
                "title": job.get("title", ""),
                "location": job.get("locationsText", "") or job.get("bulletFields", [""])[0],
                "url": f"https://{tenant}.wd1.myworkdayjobs.com/{locale}/{site}{path}",
                "description": "",
                "posted": job.get("postedOn"),
                "_workday_path": path,
            })
        total = data.get("total", 0)
        print(f"    [workday-debug] site={site} offset={offset} got={len(postings)} api_reported_total={total}")
        offset += limit
        if total and offset >= total:
            break


def fetch_workday_job_description(tenant: str, site: str, external_path: str):
    """Second call needed to get full description text for a single Workday posting."""
    url = f"https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{tenant}/{site}{external_path}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if not r.ok:
        print(f"    [workday-desc-debug] FAILED status={r.status_code} url={url}")
        return ""
    data = r.json()
    desc = (data.get("jobPostingInfo", {}) or {}).get("jobDescription", "") or ""
    if not desc:
        print(f"    [workday-desc-debug] empty description, response keys: {list(data.keys())}")
    return desc


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    # workday handled specially in run.py since it needs tenant+site, not one token
}
