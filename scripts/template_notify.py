import os
import sys
import argparse
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

# === Load ENV and config ===
root_env_path = Path(__file__).resolve().parent.parent / ".env"
from dotenv import load_dotenv
load_dotenv(dotenv_path=root_env_path)

from app.config_telegram import TELEGRAM_BOTS, DEFAULT_BOT_NAME

# === Email Config ===
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

def get_timestamp():
    return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

def send_push(bot_name, message):
    bot_settings = TELEGRAM_BOTS.get(bot_name)
    if not bot_settings:
        print(f"{get_timestamp()} ERROR: Bot '{bot_name}' not found.")
        return

    token = bot_settings.get("bot_token")
    chat_id = bot_settings.get("chat_id")

    if not token or not chat_id:
        print(f"{get_timestamp()} ERROR: Missing token or chat_id for bot '{bot_name}'")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        resp = requests.post(url, json=payload)
        if resp.status_code == 200:
            print(f"{get_timestamp()} Push sent via '{bot_name}' to chat {chat_id}")
        else:
            print(f"{get_timestamp()} Failed to send push: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"{get_timestamp()} Push error:", str(e))

def send_email(to_list, subject, body):
    if not EMAIL_USER or not EMAIL_PASS:
        print(f"{get_timestamp()} ERROR: Email credentials not set.")
        return

    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, to_list, msg.as_string())
        print(f"{get_timestamp()} Email sent to:", ", ".join(to_list))
    except Exception as e:
        print(f"{get_timestamp()} Email error:", str(e))

def main():
    parser = argparse.ArgumentParser(description="Universal notification script for PipeCrab Dashboard")
    parser.add_argument('--bot', help="Telegram bot name from config_telegram.py")
    parser.add_argument('--push', help="Push message text to send via Telegram")
    parser.add_argument('--email', help="Comma-separated list of email recipients")

    args = parser.parse_args()

    # Telegram push
    if args.push:
        bot_name = (args.bot or DEFAULT_BOT_NAME).strip()
        send_push(bot_name, args.push.strip())

    # Email
    if args.email:
        recipients = [e.strip() for e in args.email.split(",") if e.strip()]
        if recipients:
            subject = "Notification from PipeCrab"
            body = f"This is an automatic email notification.\n\nMessage:\n{args.push or 'No message provided.'}"
            send_email(recipients, subject, body)

    print(f"{get_timestamp()} Script completed.")

if __name__ == "__main__":
    main()
