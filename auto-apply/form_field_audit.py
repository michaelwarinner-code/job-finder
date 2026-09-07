"""
Answer-bank coverage check: for one job or a batch of jobs already sitting
in state, opens each REAL live application page, scans its actual fields,
and reports -- per question -- whether it would auto-resolve (EEO handling,
or an answer-bank match with the answer it would use) or would trigger a
live Telegram escalation, WITHOUT ever sending a Telegram message, calling
Claude for materials, or touching Submit.

This is read-only: no state.json writes, no answer-bank writes. Its only
purpose is to tell you, ahead of time, how much of a batch of applications
your current answer bank already covers and exactly what's still missing,
so you can seed answers once instead of discovering gaps live one ping at
a time.

Usage:
    # one specific job
    AUTOAPPLY_ANTHROPIC_API_KEY=... python auto-apply/form_field_audit.py --job-id "<url>"

    # every non-terminal job currently in state (materials_generated,
    # judged_fit, ready_to_submit, pending_answer), capped at 15 pages
    AUTOAPPLY_ANTHROPIC_API_KEY=... python auto-apply/form_field_audit.py --all

    # narrow the batch
    python auto-apply/form_field_audit.py --all --status ready_to_submit --limit 5

AUTOAPPLY_ANTHROPIC_API_KEY is needed because answer-bank matching itself
uses a Claude call (see answer_bank.match_question) -- no Telegram token is
needed since nothing gets sent.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import auto_apply_state as st
from form_filler import scan_fields_only, IDENTITY_KEYWORD_MAP, _matches_identity_pattern, load_candidate_info
from answer_bank import load_answer_bank, match_question
from eeo_answers import classify_eeo_question

DEFAULT_STATUSES = {"materials_generated", "judged_fit", "ready_to_submit", "pending_answer"}


def _jobs_to_scan(job_id: str, statuses: set, limit: int):
    state = st.load_state()
    if job_id:
        job = state["jobs"].get(job_id)
        if not job:
            raise SystemExit(f"No job found in state with id/url: {job_id}")
        return [(job_id, job)]

    matches = [(jid, j) for jid, j in state["jobs"].items() if j["status"] in statuses]
    return matches[:limit]


def audit_one_job(job_id: str, job: dict, bank_entries: list, candidate_info: dict) -> dict:
    """Returns {"auto": [...], "escalate": [...], "needs_config": [...], "error": str|None}."""
    print(f"\n=== {job['company_name']} -- {job['title']} ===")
    print(f"    {job['url']}")

    try:
        fields = scan_fields_only(job["url"])
    except Exception as e:
        print(f"    Could not scan this page: {e}")
        return {"auto": [], "escalate": [], "needs_config": [], "error": str(e)}

    auto, escalate, needs_config = [], [], []
    for f in fields:
        if f["field_type"] == "file":
            continue
        question = f["question"].strip()
        if not question:
            continue

        # Same check fill_application() runs FIRST, before EEO or the
        # answer bank -- identity fields (name/email/phone/etc) come from
        # candidate_info.json, never from the bank or a Telegram question,
        # so these should never have shown up as "would escalate" at all.
        identity_key = next((key for pattern, key in IDENTITY_KEYWORD_MAP
                              if _matches_identity_pattern(pattern, key, question)), None)
        if identity_key:
            if identity_key == "full_name":
                value = f'{candidate_info.get("first_name", "")} {candidate_info.get("last_name", "")}'.strip()
            else:
                value = candidate_info.get(identity_key, "")
            if value:
                auto.append({"question": question, "detail": f"candidate_info['{identity_key}'] -> {value!r}"})
            else:
                needs_config.append({"question": question,
                                      "detail": f"candidate_info.json['{identity_key}'] is blank -- fill it in"})
            continue

        if classify_eeo_question(question):
            auto.append({"question": question, "detail": "auto-handled (EEO question)"})
            continue

        idx, answer = match_question(question, bank_entries) if bank_entries else (None, None)
        if answer:
            auto.append({"question": question, "detail": f"bank match -> {answer!r}"})
            continue

        opts_note = f" | options: {f['options']}" if f.get("options") else ""
        escalate.append({"question": question, "detail": f"WOULD ESCALATE{opts_note}"})

    for a in auto:
        print(f"    [auto]        {a['question']}  ({a['detail']})")
    for c in needs_config:
        print(f"    [needs-config] {c['question']}  ({c['detail']})")
    for e in escalate:
        print(f"    [escalate]    {e['question']}  -- {e['detail']}")

    return {"auto": auto, "escalate": escalate, "needs_config": needs_config, "error": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job-id", help="Scan one specific job by its URL/job_id from state.json")
    parser.add_argument("--all", action="store_true", help="Scan a batch of jobs currently in state")
    parser.add_argument("--status", help="Comma-separated status filter for --all "
                                          f"(default: {','.join(sorted(DEFAULT_STATUSES))})")
    parser.add_argument("--limit", type=int, default=15, help="Max jobs to scan in --all mode (default 15)")
    args = parser.parse_args()

    if not args.job_id and not args.all:
        parser.error("pass --job-id <url> for one job, or --all for a batch")

    statuses = set(args.status.split(",")) if args.status else DEFAULT_STATUSES
    jobs = _jobs_to_scan(args.job_id, statuses, args.limit)
    print(f"[setup] scanning {len(jobs)} job(s)")

    bank_entries = load_answer_bank()
    print(f"[setup] answer bank currently has {len(bank_entries)} entries")
    candidate_info = load_candidate_info()

    total_auto, total_escalate = 0, 0
    escalate_questions_seen = []
    needs_config_seen = []
    errors = 0

    for job_id, job in jobs:
        result = audit_one_job(job_id, job, bank_entries, candidate_info)
        if result["error"]:
            errors += 1
            continue
        total_auto += len(result["auto"])
        total_escalate += len(result["escalate"])
        escalate_questions_seen.extend(e["question"] for e in result["escalate"])
        needs_config_seen.extend(c["question"] for c in result["needs_config"])

    total_questions = total_auto + total_escalate
    coverage = (total_auto / total_questions * 100) if total_questions else 100.0

    print("\n=== SUMMARY ===")
    print(f"{len(jobs)} job(s) scanned, {errors} could not be loaded")
    print(f"{total_questions} question(s) seen, {total_auto} auto-resolved, {total_escalate} would escalate "
          f"({coverage:.0f}% covered)")
    if needs_config_seen:
        unique_config = sorted(set(needs_config_seen))
        print(f"\n{len(unique_config)} identity field(s) matched but candidate_info.json has no value for them "
              f"-- fill these in, not the answer bank:")
        for q in unique_config:
            print(f"  - {q}")
    if escalate_questions_seen:
        unique = sorted(set(escalate_questions_seen))
        print(f"\n{len(unique)} unique question(s) not covered by the bank:")
        for q in unique:
            print(f"  - {q}")


if __name__ == "__main__":
    main()
