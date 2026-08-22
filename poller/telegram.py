import os
import requests


def send_telegram_alert(company_name: str, title: str, location: str, url: str, reason: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    text = (
        f"🎯 New match: *{title}*\n"
        f"🏢 {company_name}"
        + (f" · {location}" if location else "")
        + f"\n💡 {reason}\n"
        f"{url}"
    )

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    r.raise_for_status()
