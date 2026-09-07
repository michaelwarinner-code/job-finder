"""
Excludes a posting if its URL matches something already logged in the
"Jobs I applied to" sheet -- including rows added by hand, for jobs
applied to outside this pipeline entirely. Without this, discovery has no
visibility into anything you did manually, and could apply again to a job
you already handled yourself.

URL-only matching, exact after stripping tracking query params that can
differ between two links to the literal same posting. Deliberately
simpler than an earlier version of this module that also tried fuzzy
company+title text matching and a best-effort req-ID extraction -- traded
away on purpose for simplicity, with one known accepted gap: the SAME
posting under two genuinely different URLs (a company's own careers page
vs. an Ashby/Greenhouse-hosted mirror of it) won't be caught as a
duplicate. If that turns out to matter in practice, the fix is pasting
the URL you actually applied through into the sheet consistently, or
reintroducing a secondary match signal.
"""
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """Strips query string and fragment (tracking params like ?gh_src=...
    can differ between two links to the exact same posting) and lowercases
    the host, so two links to the same job compare equal even if the
    tracking parameters don't match."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def already_applied(candidate_url: str, logged_jobs: list) -> bool:
    """True if this posting's URL exactly matches (after normalization)
    something already logged."""
    norm_candidate = normalize_url(candidate_url)
    if not norm_candidate:
        return False

    for job in logged_jobs:
        if normalize_url(job.get("url", "")) == norm_candidate:
            return True

    return False
