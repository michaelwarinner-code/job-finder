"""
Escalates an unmatched application question to you over Telegram: sends the
role/company and the question text, waits for your reply, sends back a
confirmation, and on "yes" commits the answer permanently to the answer
bank (with the same consolidation logic as everywhere else).

IMPORTANT: this version BLOCKS and polls Telegram for your reply in real
time -- fine for running interactively yourself, but this exact approach
cannot run unattended inside a GitHub Actions job (a runner can't sit idle
waiting on you indefinitely). The escalation LOGIC here (the message
content, the confirm-then-commit flow) is what the eventual automated
pipeline will reuse -- but the "wait for reply" mechanism will need to be
swapped for the two-phase Cloudflare Worker webhook approach when this
moves into the real unattended pipeline. Not built yet.

Uses AUTOAPPLY_TELEGRAM_BOT_TOKEN / AUTOAPPLY_TELEGRAM_CHAT_ID -- the
separate bot created for this track, not the target-list poller's bot.
"""
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from answer_bank import add_or_consolidate, save_answer_bank

POLL_INTERVAL_SECONDS = 3
DEFAULT_TIMEOUT_SECONDS = 1800  # 30 minutes -- long enough for a real reply while doing other things
MAX_NETWORK_RETRIES = 4
NETWORK_RETRY_BACKOFF_SECONDS = 5

# GitHub Actions sets this automatically on every run -- used to detect
# "nobody is watching this run in real time" rather than adding a separate
# setting. Blocking and waiting for a reply is fine on your own machine,
# but a cloud run can't sit there idle -- it needs to send the question
# once and move on to the next job instead of hanging.
IS_UNATTENDED = os.environ.get("GITHUB_ACTIONS") == "true"


class PendingAnswerRequired(Exception):
    """Raised after a full fill attempt (unattended mode only) once every
    question that couldn't be answered has been collected and sent as a
    single batched Telegram message -- carries the full list, so the
    caller can mark the whole job as pending_answer and move on to the
    next one, rather than wasting runner time. A later Worker (reading
    Telegram replies live) resolves this by writing the answers back into
    the repo and flipping the job's status so the next scheduled run picks
    it back up and retries the fill from scratch.

    Also carries the filled/skipped report for everything that happened
    BEFORE the pending question came up -- confirmed necessary: without
    this, a run that gets 90% through a form and then hits one unanswered
    question loses all visibility into whether that other 90% actually
    worked, since raising here used to happen before the report was ever
    returned to the caller."""
    def __init__(self, questions: list, report: dict = None):
        self.questions = questions
        self.report = report or {}
        super().__init__("; ".join(questions))


def _api_url(bot_token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}/{method}"


def _request_with_retry(request_fn, *args, **kwargs):
    """Wraps a requests call with retry-and-backoff for transient network
    failures (connection resets, timeouts) -- confirmed necessary the hard
    way: a single Wi-Fi blip during a long-polling getUpdates call crashed
    an entire in-progress run, losing work that hadn't been saved yet."""
    last_exc = None
    for attempt in range(MAX_NETWORK_RETRIES):
        try:
            return request_fn(*args, **kwargs)
        except requests.exceptions.RequestException as e:
            last_exc = e
            print(f"    [telegram] network error (attempt {attempt + 1}/{MAX_NETWORK_RETRIES}): {e}")
            if attempt < MAX_NETWORK_RETRIES - 1:
                time.sleep(NETWORK_RETRY_BACKOFF_SECONDS)
    raise last_exc


def send_message(bot_token: str, chat_id: str, text: str):
    r = _request_with_retry(requests.post, _api_url(bot_token, "sendMessage"),
                             json={"chat_id": chat_id, "text": text}, timeout=15)
    r.raise_for_status()
    return r.json()


def _get_updates(bot_token: str, offset=None, timeout: int = 0):
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    r = _request_with_retry(requests.get, _api_url(bot_token, "getUpdates"),
                             params=params, timeout=timeout + 10)
    r.raise_for_status()
    return r.json().get("result", [])


def _get_latest_update_id(bot_token: str) -> int:
    updates = _get_updates(bot_token)
    return max((u["update_id"] for u in updates), default=0)


def wait_for_reply(bot_token: str, chat_id: str, after_update_id: int,
                    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
    """Blocks (polling), returns (text, last_update_id) for the next text
    message from chat_id after after_update_id, or (None, after_update_id)
    on timeout."""
    deadline = time.time() + timeout_seconds
    offset = after_update_id + 1
    while time.time() < deadline:
        try:
            updates = _get_updates(bot_token, offset=offset, timeout=10)
        except requests.exceptions.RequestException as e:
            # Already retried internally -- if it still failed, don't end
            # the whole wait over one bad stretch of network, just try
            # again next cycle as long as the overall deadline hasn't passed.
            print(f"    [telegram] getUpdates still failing after retries, will try again: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        for u in updates:
            offset = max(offset, u["update_id"] + 1)
            msg = u.get("message", {})
            if str(msg.get("chat", {}).get("id")) == str(chat_id) and "text" in msg:
                return msg["text"], u["update_id"]
        time.sleep(POLL_INTERVAL_SECONDS)
    return None, after_update_id


def escalate_question(question_text: str, role_title: str, company_name: str, job_url: str,
                       bank_entries: list, save_to_bank: bool = True, options: list = None):
    """Pings for an answer, confirms it, and -- unless save_to_bank is
    False -- commits it permanently to the answer bank. Set save_to_bank
    to False for company-specific questions (see
    company_question_classifier.py) whose answer would be wrong if reused
    at a different company; the answer is still returned and used for
    THIS application, it just isn't persisted for future ones.

    Pass options (the real list of choices pulled from a live dropdown) to
    have them included in the message -- confirmed necessary the hard way:
    without the real options, a blind free-text reply can easily not match
    anything on a given company's actual dropdown.

    Returns the confirmed answer string, or None if it timed out waiting
    for a reply at any point. Mutates bank_entries in place and saves it
    only when save_to_bank is True."""
    bot_token = os.environ["AUTOAPPLY_TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["AUTOAPPLY_TELEGRAM_CHAT_ID"]

    baseline = _get_latest_update_id(bot_token)

    options_note = ""
    if options:
        options_note = "\n\nOptions available:\n" + "\n".join(f"  - {o}" for o in options)

    send_message(bot_token, chat_id,
                 f"New application question needs an answer.\n\n"
                 f"Role: {role_title} at {company_name}\n"
                 f"Posting: {job_url}\n\n"
                 f"Question: {question_text}{options_note}\n\n"
                 f"Reply with your answer{' (must match one of the options above exactly)' if options else ''}.")

    print("[escalation] sent, waiting for your Telegram reply...")
    answer, last_update_id = wait_for_reply(bot_token, chat_id, baseline)
    if answer is None:
        print("[escalation] timed out waiting for a reply")
        return None

    while True:
        reuse_note = "" if save_to_bank else "\n\n(This is specific to this company -- it won't be reused elsewhere.)"
        confirm_options = "Reply 'yes' to confirm" if save_to_bank else \
            "Reply 'yes' to confirm without saving, 'save' to confirm AND save this for reuse everywhere"
        send_message(bot_token, chat_id,
                     f"Got it, I'll use:\n\n\"{answer}\"\n\nfor:\n\"{question_text}\"{reuse_note}\n\n"
                     f"{confirm_options}, or send a corrected answer.")
        print("[escalation] sent confirmation, waiting for your reply...")
        reply, last_update_id = wait_for_reply(bot_token, chat_id, last_update_id)
        if reply is None:
            print("[escalation] timed out waiting for confirmation")
            return None

        reply_clean = reply.strip().lower()
        if reply_clean in ("yes", "save"):
            do_save = save_to_bank or reply_clean == "save"
            if do_save:
                bank_entries[:] = add_or_consolidate(question_text, answer, bank_entries)
                save_answer_bank(bank_entries)
                send_message(bot_token, chat_id, "Saved to the answer bank.")
            else:
                send_message(bot_token, chat_id, "Got it -- using this for this application only.")
            print(f"[escalation] confirmed{' and saved' if do_save else ' (not saved, company-specific)'}: {answer!r}")
            return answer
        else:
            answer = reply  # treat as a corrected answer, loop back to confirm again


def escalate_checkbox_group(questions: list, role_title: str, company_name: str, job_url: str,
                             bank_entries: list, save_to_bank: bool = True, select_one: bool = False,
                             group_question: str = None):
    """Batches multiple checkbox/radio-group options into ONE numbered
    Telegram message instead of asking one at a time. Returns a list of
    0-based indices selected (empty list if none apply), or None on
    timeout.

    select_one=False (default): "check all that apply" -- e.g. BambooHR's
    independent compliance declarations, where each option genuinely is
    its own fact. Reply with comma-separated numbers or 'none'. Saves
    each option to the bank as its own Yes/No fact when save_to_bank.

    select_one=True: exactly one answer applies (radio buttons, or an
    office-style "which one" checkbox group) -- e.g. "How many years of
    experience do you have?" with options 0-1/2-3/4+. Reply with just the
    one number that applies. Saves ONE entry -- group_question (shown as
    context above the option list) mapped to the text of whichever option
    was picked -- not one Yes/No fact per option, since the group_question
    itself is what a future posting's differently-worded version of this
    same question would actually get matched against."""
    bot_token = os.environ["AUTOAPPLY_TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["AUTOAPPLY_TELEGRAM_CHAT_ID"]

    baseline = _get_latest_update_id(bot_token)

    numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    context_line = f"Question: {group_question}\n\n" if group_question else ""
    instructions = "Reply with the ONE number that applies" if select_one else \
        "Check all that apply -- reply with the numbers that apply to you, separated by commas, or 'none'"
    send_message(bot_token, chat_id,
                 f"New application question needs an answer.\n\n"
                 f"Role: {role_title} at {company_name}\n"
                 f"Posting: {job_url}\n\n"
                 f"{context_line}"
                 f"{instructions}:\n\n{numbered}")

    def parse_indices(text: str):
        text = (text or "").strip().lower()
        if text in ("none", "none apply", "n/a", "0", "no", "no one"):
            return []
        nums = re.findall(r"\d+", text)
        indices = sorted({int(n) - 1 for n in nums if 0 < int(n) <= len(questions)})
        return indices[:1] if select_one and len(indices) > 1 else indices

    print("[escalation] sent (checkbox group), waiting for your Telegram reply...")
    answer, last_update_id = wait_for_reply(bot_token, chat_id, baseline)
    if answer is None:
        print("[escalation] timed out waiting for a reply")
        return None
    selected = parse_indices(answer)

    while True:
        selected_desc = "\n".join(f"  - {questions[i]}" for i in selected) if selected else "  (none)"
        confirm_options = "Reply 'yes' to confirm" if save_to_bank else \
            "Reply 'yes' to confirm without saving, 'save' to confirm AND save this for reuse everywhere"
        send_message(bot_token, chat_id,
                     f"Got it, I'll check:\n{selected_desc}\n\n"
                     f"{confirm_options}, or send corrected numbers.")
        print("[escalation] sent confirmation, waiting for your reply...")
        reply, last_update_id = wait_for_reply(bot_token, chat_id, last_update_id)
        if reply is None:
            print("[escalation] timed out waiting for confirmation")
            return None

        reply_clean = reply.strip().lower()
        if reply_clean in ("yes", "save"):
            do_save = save_to_bank or reply_clean == "save"
            if do_save:
                if select_one and group_question and selected:
                    bank_entries[:] = add_or_consolidate(group_question, questions[selected[0]], bank_entries)
                elif not select_one:
                    for i, q in enumerate(questions):
                        ans = "Yes" if i in selected else "No"
                        bank_entries[:] = add_or_consolidate(q, ans, bank_entries)
                save_answer_bank(bank_entries)
                send_message(bot_token, chat_id, "Saved to the answer bank.")
            else:
                send_message(bot_token, chat_id, "Got it -- using this for this application only.")
            print(f"[escalation] confirmed{' and saved' if do_save else ''}: selected {selected}")
            return selected
        else:
            selected = parse_indices(reply)


def _format_pending_questions(pending_questions: list) -> str:
    """Formats a structured list of pending items (see form_filler.py's
    _get_answer_or_queue/_get_group_selection_or_queue) into ONE numbered
    reply line per TOP-LEVEL item -- a whole checkbox/radio group is one
    line to reply to (e.g. "2-3", or a letter combo for a "check all that
    apply" group), not one line per underlying option. Must stay in sync
    with the Worker's formatPendingQuestions() in index.js, which
    independently rebuilds this same message if the person's reply
    arrives after the conversation has to restart -- there's no shared
    source between the Python pipeline and the Worker.

    Confirmed necessary the hard way: the earlier version numbered every
    individual checkbox/radio OPTION as its own line, so a 3-way
    single-choice question needed 3 separate reply lines instead of the
    one a person would naturally give ("2" to mean "pick option 2")."""
    import string
    lines = []
    for i, item in enumerate(pending_questions):
        if item["type"] == "single":
            lines.append(f"{i + 1}. {item['question']}")
        elif item["select"] == "one":
            options_text = ", ".join(item["options"])
            header = f"{item['group_question']} " if item.get("group_question") else ""
            lines.append(f"{i + 1}. {header}Reply with ONE of: {options_text}")
        else:  # select == "any"
            letters = string.ascii_lowercase
            options_text = " ".join(f"{letters[j]}) {opt}" for j, opt in enumerate(item["options"]))
            header = f"{item['group_question']} " if item.get("group_question") else "Do any of these apply to you? "
            lines.append(f"{i + 1}. {header}Reply with the letters that apply, comma-separated, or 'none': {options_text}")
    return "\n\n".join(lines)


def escalate_question_batch(pending_questions: list, role_title: str, company_name: str, job_url: str):
    """Sends ONE Telegram message listing every question this application
    still needs answered, instead of a separate message per question.
    Unattended-mode only: without this, an application with several
    unanswerable questions could take one separate scheduled run PER
    question to fully resolve, since a browser session can't survive
    between runs and each retry only gets as far as the next unanswered
    field. Does NOT wait for a reply -- a Worker listening to Telegram in
    real time handles the actual back-and-forth and writes answers back
    into the repo; this function's only job is sending the initial batch."""
    bot_token = os.environ["AUTOAPPLY_TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["AUTOAPPLY_TELEGRAM_CHAT_ID"]

    numbered = _format_pending_questions(pending_questions)
    send_message(bot_token, chat_id,
                 f"New application needs {len(pending_questions)} answer(s).\n\n"
                 f"Role: {role_title} at {company_name}\n"
                 f"Posting: {job_url}\n\n"
                 f"{numbered}\n\n"
                 f"Reply with your answers, one per line, in the same order.")
