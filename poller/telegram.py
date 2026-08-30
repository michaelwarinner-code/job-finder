import html
import os
import requests


def send_telegram_alert(company_name: str, title: str, location: str, url: str, reason: str, is_priority: bool = True):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # Job titles and Claude's fit "reason" are freeform text and can contain
    # characters that break Telegram's Markdown parser (_, *, `, [, etc.),
    # which caused a 400 and silently dropped the whole alert. HTML mode
    # only needs & < > escaped, so it's much safer for uncontrolled text.
    prefix = "🎯 PRIORITY" if is_priority else "📋 Other"
    safe_title = html.escape(title)
    safe_company = html.escape(company_name)
    safe_location = html.escape(location) if location else ""
    safe_reason = html.escape(reason)
    safe_url = html.escape(url)

    text = (
        f"{prefix}: <b>{safe_title}</b>\n"
        f"🏢 {safe_company}"
        + (f" · {safe_location}" if safe_location else "")
        + f"\n💡 {safe_reason}\n"
        f"{safe_url}"
    )

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    r.raise_for_status()
