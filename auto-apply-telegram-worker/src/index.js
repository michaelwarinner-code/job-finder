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

const ALWAYS_GENERIC_PATTERNS = [
  /how did you (hear|find out|learn) about/i,
  /have you (ever\s+)?(previously\s+)?worked (for|at)/i,
  /(current or )?former\s+\S+\s+employee/i,
  /sponsor|petition.*employment|nonimmigrant status|require.*visa/i,
  /family member|relative|close personal relationship.*(employed|working)/i,
  /non-compete|non-solicitation|confidentiality obligation|restrictive covenant/i,
  /financial interest.*(competitor|customer|vendor|partner)/i,
  /outside employment|consulting|freelance work|board|advisory board|officer.*trustee/i,
  /consent to.*(collect|process).*personal data|privacy notice/i,
];

const COMPANY_SPECIFIC_PATTERNS = [
  /why.*(excited|interested).*(role|position|company|join|team|us\b)/i,
  /why.*(want to work|do you want to join)/i,
  /why\s+(this\s+)?(company|role|position|team)\b/i,
  /what (excites|interests) you about/i,
  /why\s+(are\s+you\s+)?(a\s+)?(good\s+)?fit/i,
];

function isCompanySpecificQuestion(questionText, companyName) {
  const text = questionText || "";
  if (ALWAYS_GENERIC_PATTERNS.some((p) => p.test(text))) return false;
  if (companyName && companyName.trim() && text.toLowerCase().includes(companyName.toLowerCase())) return true;
  return COMPANY_SPECIFIC_PATTERNS.some((p) => p.test(text));
}

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
  if (text.trim().toLowerCase() === "reset") {
    await env.CONVERSATION_STATE.delete(CONVO_KEY);
    await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, "Cleared. Send anything to start fresh.");
    return;
  }

  if (text.trim().toLowerCase() === "status") {
    const state = await fetchJson(env, STATE_PATH);
    const pending = Object.entries(state.jobs || {}).filter(([, job]) => job.status === "pending_answer");
    if (pending.length === 0) {
      await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, "Nothing is currently waiting on an answer.");
      return;
    }
    pending.sort((a, b) => new Date(a[1].pending_since) - new Date(b[1].pending_since));
    const list = pending.map(([, job], i) => `${i + 1}. ${job.company_name} -- ${job.title}${i === 0 ? "  (next up)" : ""}`).join("\n");
    await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId,
      `${pending.length} job(s) waiting on an answer, oldest first:\n\n${list}\n\nSend anything else to start on the next one.`);
    return;
  }

  const convo = await env.CONVERSATION_STATE.get(CONVO_KEY, "json");

  if (!convo) {
    const newConvo = await startConversation(env, chatId);
    if (!newConvo) return;

    const lines = text.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
    if (lines.length === newConvo.questions.length) {
      await handleAnswers(env, chatId, text, newConvo);
    }
    return;
  } else if (convo.stage === "awaiting_answers") {
    await handleAnswers(env, chatId, text, convo);
  } else if (convo.stage === "awaiting_confirmation") {
    await handleConfirmation(env, chatId, text, convo);
  } else {
    await env.CONVERSATION_STATE.delete(CONVO_KEY);
    await startConversation(env, chatId);
  }
}

function formatPendingQuestions(items) {
  const letters = "abcdefghijklmnopqrstuvwxyz";
  return items
    .map((item, i) => {
      if (item.type === "single") {
        return `${i + 1}. ${item.question}`;
      }
      if (item.select === "one") {
        const optionsText = item.options.join(", ");
        const header = item.group_question ? `${item.group_question} ` : "";
        return `${i + 1}. ${header}Reply with ONE of: ${optionsText}`;
      }
      const optionsText = item.options.map((opt, j) => `${letters[j]}) ${opt}`).join(" ");
      const header = item.group_question ? `${item.group_question} ` : "Do any of these apply to you? ";
      return `${i + 1}. ${header}Reply with the letters that apply, comma-separated, or 'none': ${optionsText}`;
    })
    .join("\n\n");
}

async function startConversation(env, chatId) {
  const state = await fetchJson(env, STATE_PATH);
  const pending = Object.entries(state.jobs || {}).filter(([, job]) => job.status === "pending_answer");

  if (pending.length === 0) {
    await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, "Nothing is currently waiting on an answer.");
    return null;
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

  const numbered = formatPendingQuestions(questions);
  await sendTelegramMessage(
    env.TELEGRAM_BOT_TOKEN,
    chatId,
    `${job.company_name} -- ${job.title}\n\n${numbered}\n\nReply with your answers, one per line, in order.`
  );

  const convo = { stage: "awaiting_answers", jobId, companyName: job.company_name, questions };
  await env.CONVERSATION_STATE.put(CONVO_KEY, JSON.stringify(convo), { expirationTtl: CONVO_TTL_SECONDS });
  return convo;
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

  const pairs = convo.questions
    .map((item, i) => `${i + 1}. ${describeItem(item)}\n   -> ${lines[i]}`)
    .join("\n\n");
  await sendTelegramMessage(
    env.TELEGRAM_BOT_TOKEN,
    chatId,
    `Got it:\n\n${pairs}\n\nReply 'yeah' to confirm and save to the reusable answer bank as usual, 'nah' to confirm but save NONE of these to the bank (still used for this job), 'only save <numbers>' to save just specific ones (e.g. 'only save 2, 3'), or resend corrected answers.`
  );

  convo.stage = "awaiting_confirmation";
  convo.answers = lines;
  await env.CONVERSATION_STATE.put(CONVO_KEY, JSON.stringify(convo), { expirationTtl: CONVO_TTL_SECONDS });
}

function describeItem(item) {
  if (item.type === "single") return item.question;
  return item.group_question || `(${item.options.join(" / ")})`;
}

function parseConfirmationCommand(text, questionCount) {
  const trimmed = text.trim();
  if (/^yeah$/i.test(trimmed)) return { mode: "auto" };
  if (/^nah$/i.test(trimmed)) return { mode: "none" };
  const onlyMatch = trimmed.match(/^only save\s+([\d,\s]+)$/i);
  if (onlyMatch) {
    const positions = new Set(
      onlyMatch[1]
        .split(",")
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !isNaN(n) && n >= 1 && n <= questionCount)
    );
    return { mode: "only", positions };
  }
  return null;
}

async function handleConfirmation(env, chatId, text, convo) {
  const command = parseConfirmationCommand(text, convo.questions.length);
  if (!command) {
    await handleAnswers(env, chatId, text, { ...convo, stage: "awaiting_answers" });
    return;
  }

  const savedCount = await saveAnswers(env, convo.jobId, convo.questions, convo.answers, convo.companyName, command);
  await resetJobForRetry(env, convo.jobId);
  await env.CONVERSATION_STATE.delete(CONVO_KEY);

  const jobOnlyCount = convo.questions.length - savedCount;
  const scopeNote = jobOnlyCount > 0
    ? ` ${jobOnlyCount} won't be reused elsewhere (company-specific, or kept out at your request) -- saved for THIS job only.`
    : "";
  await sendTelegramMessage(
    env.TELEGRAM_BOT_TOKEN,
    chatId,
    `Saved ${savedCount} of ${convo.questions.length} to the reusable answer bank.${scopeNote} That job will retry with these answers on the next scheduled run.`
  );
}

async function saveAnswers(env, jobId, questions, answers, companyName, command = { mode: "auto" }) {
  const { content: bank, sha: bankSha } = await fetchJsonWithSha(env, ANSWER_BANK_PATH);
  const { content: state, sha: stateSha } = await fetchJsonWithSha(env, STATE_PATH);
  const today = new Date().toISOString().slice(0, 10);
  const letters = "abcdefghijklmnopqrstuvwxyz";

  let savedToBank = 0;
  let savedToJob = false;
  const job = state.jobs[jobId];

  const goesToBank = (question, position) => {
    if (command.mode === "none") return false;
    if (command.mode === "only") return command.positions.has(position);
    return !isCompanySpecificQuestion(question, companyName);  // "auto"
  };

  const saveOne = (question, answer, position) => {
    if (goesToBank(question, position)) {
      bank.push({ answer, aliases: [question], added_date: today });
      savedToBank++;
      return;
    }
    if (job) {
      job.job_specific_answers = job.job_specific_answers || {};
      job.job_specific_answers[question] = answer;
      savedToJob = true;
    }
  };

  for (let i = 0; i < questions.length; i++) {
    const item = questions[i];
    const reply = (answers[i] || "").trim();
    const position = i + 1;

    if (item.type === "single") {
      saveOne(item.question, reply, position);
      continue;
    }

    if (item.select === "one") {
      if (item.group_question && reply) {
        saveOne(item.group_question, reply, position);
      }
      continue;
    }

    const replyLower = reply.toLowerCase();
    const chosenLetters = replyLower === "none" ? [] : replyLower.split(",").map((s) => s.trim());
    for (let j = 0; j < item.options.length; j++) {
      const chosen = chosenLetters.includes(letters[j]);
      saveOne(item.options[j], chosen ? "Yes" : "No", position);
    }
  }

  if (savedToBank > 0) {
    await putJson(env, ANSWER_BANK_PATH, bank, bankSha, "Add answer(s) from Telegram escalation [skip ci]");
  }
  if (savedToJob) {
    await putJson(env, STATE_PATH, state, stateSha, `Job-specific answer(s) for ${jobId} [skip ci]`);
  }
  return savedToBank;
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
