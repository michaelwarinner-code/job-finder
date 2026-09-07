/**
 * Full escalation handling: finds the oldest pending job, asks its
 * questions, confirms your answers, and writes them back into the repo --
 * answer_bank.json gets the new entries, auto_apply_state.json gets that
 * job's status flipped back to judged_fit so the next scheduled run
 * retries the fill from scratch with the new answers available (a browser
 * session can't survive between separate runs, so a fresh fill is
 * unavoidable, but it'll sail through everything already answered).
 *
 * Conversation stage (which part of the exchange we're in) lives in KV --
 * a single Worker request has no memory of the previous one on its own.
 *
 * Simplification worth knowing: unlike the Python pipeline's Claude-based
 * semantic consolidation, this just appends new bank entries directly with
 * the literal question as the alias. Future semantic matching from the
 * Python side still works fine against these -- match_question() doesn't
 * care how an entry was created, only that a reasonable alias exists.
 */

const GITHUB_OWNER = "michaelwarinner-code";
const GITHUB_REPO = "job-finder";
const STATE_PATH = "state/auto_apply_state.json";
const ANSWER_BANK_PATH = "state/answer_bank.json";
const CONVO_KEY = "active_conversation";
const CONVO_TTL_SECONDS = 86400; // 24h -- a stalled conversation shouldn't linger forever

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("auto-apply-telegram-worker is running", { status: 200 });
    }

    const update = await request.json();
    const message = update.message;
    if (!message || !message.text) {
      return new Response("ignored", { status: 200 });
    }

    const chatId = message.chat.id;
    const text = message.text.trim();

    try {
      await handleMessage(env, chatId, text);
    } catch (err) {
      await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, `Error: ${err.message}`);
    }

    return new Response("ok", { status: 200 });
  },
};

async function handleMessage(env, chatId, text) {
  const convo = await env.CONVERSATION_STATE.get(CONVO_KEY, "json");

  if (!convo) {
    await startConversation(env, chatId);
  } else if (convo.stage === "awaiting_answers") {
    await handleAnswers(env, chatId, text, convo);
  } else if (convo.stage === "awaiting_confirmation") {
    await handleConfirmation(env, chatId, text, convo);
  } else {
    await env.CONVERSATION_STATE.delete(CONVO_KEY);
    await startConversation(env, chatId);
  }
}

async function startConversation(env, chatId) {
  const state = await fetchJson(env, STATE_PATH);
  const pending = Object.entries(state.jobs || {}).filter(([, job]) => job.status === "pending_answer");

  if (pending.length === 0) {
    await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, "Nothing is currently waiting on an answer.");
    return;
  }

  pending.sort((a, b) => new Date(a[1].pending_since) - new Date(b[1].pending_since));
  const [jobId, job] = pending[0];
  const questions = job.pending_questions || [];

  if (pending.length > 1) {
    await sendTelegramMessage(
      env.TELEGRAM_BOT_TOKEN,
      chatId,
      `${pending.length} jobs are waiting -- starting with the oldest: ${job.company_name} -- ${job.title}. The rest will wait until this one's done.`
    );
  }

  const numbered = questions.map((q, i) => `${i + 1}. ${q}`).join("\n");
  await sendTelegramMessage(
    env.TELEGRAM_BOT_TOKEN,
    chatId,
    `${job.company_name} -- ${job.title}\n\n${numbered}\n\nReply with your answers, one per line, in order.`
  );

  await env.CONVERSATION_STATE.put(
    CONVO_KEY,
    JSON.stringify({ stage: "awaiting_answers", jobId, questions }),
    { expirationTtl: CONVO_TTL_SECONDS }
  );
}

async function handleAnswers(env, chatId, text, convo) {
  const lines = text.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);

  if (lines.length !== convo.questions.length) {
    await sendTelegramMessage(
      env.TELEGRAM_BOT_TOKEN,
      chatId,
      `I need exactly ${convo.questions.length} answer(s), one per line, in order -- got ${lines.length}. Try again.`
    );
    return;
  }

  const pairs = convo.questions.map((q, i) => `${i + 1}. ${q}\n   -> ${lines[i]}`).join("\n\n");
  await sendTelegramMessage(
    env.TELEGRAM_BOT_TOKEN,
    chatId,
    `Got it:\n\n${pairs}\n\nReply 'yes' to confirm, or resend corrected answers.`
  );

  convo.stage = "awaiting_confirmation";
  convo.answers = lines;
  await env.CONVERSATION_STATE.put(CONVO_KEY, JSON.stringify(convo), { expirationTtl: CONVO_TTL_SECONDS });
}

async function handleConfirmation(env, chatId, text, convo) {
  if (text.toLowerCase() !== "yes") {
    await handleAnswers(env, chatId, text, { ...convo, stage: "awaiting_answers" });
    return;
  }

  await saveAnswersToBank(env, convo.questions, convo.answers);
  await resetJobForRetry(env, convo.jobId);
  await env.CONVERSATION_STATE.delete(CONVO_KEY);

  await sendTelegramMessage(
    env.TELEGRAM_BOT_TOKEN,
    chatId,
    "Saved. That job will retry with these answers on the next scheduled run."
  );
}

async function saveAnswersToBank(env, questions, answers) {
  const { content: bank, sha } = await fetchJsonWithSha(env, ANSWER_BANK_PATH);
  const today = new Date().toISOString().slice(0, 10);

  for (let i = 0; i < questions.length; i++) {
    bank.push({ answer: answers[i], aliases: [questions[i]], added_date: today });
  }

  await putJson(env, ANSWER_BANK_PATH, bank, sha, "Add answer(s) from Telegram escalation [skip ci]");
}

async function resetJobForRetry(env, jobId) {
  const { content: state, sha } = await fetchJsonWithSha(env, STATE_PATH);
  const job = state.jobs[jobId];
  if (!job) return;

  job.status = "judged_fit";
  delete job.pending_since;
  delete job.pending_questions;
  job.last_updated = new Date().toISOString();

  await putJson(env, STATE_PATH, state, sha, `Resolved pending answer for ${jobId} [skip ci]`);
}

// ---- GitHub Contents API helpers ----

async function fetchJson(env, path) {
  const { content } = await fetchJsonWithSha(env, path);
  return content;
}

async function fetchJsonWithSha(env, path) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${path}`;
  const res = await fetch(url, {
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "auto-apply-telegram-worker",
    },
  });
  if (!res.ok) throw new Error(`GitHub GET ${path} returned ${res.status}: ${await res.text()}`);
  const data = await res.json();
  const decoded = decodeURIComponent(escape(atob(data.content.replace(/\n/g, ""))));
  return { content: JSON.parse(decoded), sha: data.sha };
}

async function putJson(env, path, content, sha, message) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${path}`;
  const jsonStr = JSON.stringify(content, null, 2);
  const encoded = btoa(unescape(encodeURIComponent(jsonStr)));

  const res = await fetch(url, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "auto-apply-telegram-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      content: encoded,
      sha,
      committer: { name: "job-bot", email: "job-bot@users.noreply.github.com" },
    }),
  });

  if (!res.ok) throw new Error(`GitHub PUT ${path} returned ${res.status}: ${await res.text()}`);
}

async function sendTelegramMessage(botToken, chatId, text) {
  const url = `https://api.telegram.org/bot${botToken}/sendMessage`;
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}
