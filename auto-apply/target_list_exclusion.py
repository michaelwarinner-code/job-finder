"""
Fuzzy-excludes companies already on the curated target list (state.json's
top-level `companies` dict) from the broad-discovery auto-apply pool, so the
same company never gets both a manual target-list flow AND an auto-applied
one.

Uses difflib (stdlib) instead of a fuzzy-matching library to keep this
dependency-free -- ratio matching after normalizing case, punctuation, and
common corporate suffixes (Inc, LLC, Corp, Co) is precise enough for "is this
literally the same company," which is all this needs to catch. It is NOT
trying to catch parent/subsidiary relationships (e.g. "Instagram" vs "Meta")
-- that would need a maintained company-graph lookup, which is overkill here.
"""
import json
import os
import re
from difflib import SequenceMatcher

SUFFIX_RE = re.compile(
    r"\b(inc|llc|corp|corporation|co|company|ltd|limited|"
    r"technology|technologies|software|group|holdings|labs)\b\.?",
    re.IGNORECASE,
)
PUNCT_RE = re.compile(r"[^\w\s]")

MATCH_THRESHOLD = 0.85
# Below the ratio threshold, still treat a name as the same company if one
# normalized name fully contains the other (e.g. "spotify" vs "spotify
# technology" after suffix-stripping still won't be identical length, but one
# is a clean substring of the other) -- guards against false negatives from
# aggregator data using a longer legal-ish name than the target list's short one.
MIN_SUBSTRING_LEN = 4

TARGET_STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "state.json")


def normalize_company_name(name: str) -> str:
    name = (name or "").lower()
    name = SUFFIX_RE.sub("", name)
    name = PUNCT_RE.sub("", name)
    return " ".join(name.split())


def load_target_company_names() -> list:
    """Pulls display names (cfg["name"]) out of the existing target-list state.json,
    regardless of whether each entry is currently enabled -- a disabled target-list
    company should still be excluded from the broad pool, not silently opened up."""
    with open(TARGET_STATE_PATH) as f:
        state = json.load(f)
    return [cfg.get("name", "") for cfg in state.get("companies", {}).values()]


def is_target_list_company(candidate_name: str, target_names: list) -> bool:
    norm_candidate = normalize_company_name(candidate_name)
    if not norm_candidate:
        return False
    for target in target_names:
        norm_target = normalize_company_name(target)
        if not norm_target:
            continue
        if norm_candidate == norm_target:
            return True
        if SequenceMatcher(None, norm_candidate, norm_target).ratio() >= MATCH_THRESHOLD:
            return True
        shorter, longer = sorted([norm_candidate, norm_target], key=len)
        if len(shorter) >= MIN_SUBSTRING_LEN and shorter in longer:
            return True
    return False
