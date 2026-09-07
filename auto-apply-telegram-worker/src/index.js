/**
 * First slice: prove Telegram can actually reach this Worker, and that
 * the Worker can send a message back. Just echoes whatever you send it.
 * Real escalation logic (reading pending questions, confirming answers,
 * writing back to GitHub) comes next, once this basic wiring is proven.
 */
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
    const text = message.text;

    await sendTelegramMessage(env.TELEGRAM_BOT_TOKEN, chatId, `Echo: ${text}`);

    return new Response("ok", { status: 200 });
  },
};

async function sendTelegramMessage(botToken, chatId, text) {
  const url = `https://api.telegram.org/bot${botToken}/sendMessage`;
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}
