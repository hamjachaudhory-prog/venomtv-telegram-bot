import os
import json
import html
import re
import requests

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

API_URL = "https://streamed.pk/api/matches/all-today"
WEBSITE = "https://venomtv.vercel.app"
CHANNEL = "@hdhubsports"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
STATE_FILE = Path("seen_matches.json")


def load_seen():
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except (ValueError, OSError):
            pass
    return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2)
    )


def make_hashtag(text):
    text = re.sub(r"[^a-zA-Z0-9_]", "", text)
    return f"#{text}" if text else ""


def make_post(match):
    title = html.escape(match.get("title", "Sports Match"))
    category = match.get("category", "sports")
    category_tag = make_hashtag(category.title())

    date_text = ""
    timestamp = match.get("date")

    if isinstance(timestamp, (int, float)):
        try:
            dt = datetime.fromtimestamp(
                timestamp / 1000,
                tz=ZoneInfo("Asia/Dhaka")
            )
            date_text = (
                f"\n📅 Date: {dt.strftime('%d %b %Y')}"
                f"\n⏰ Time: {dt.strftime('%I:%M %p')} (Bangladesh)"
            )
        except (ValueError, OverflowError, OSError):
            pass

    tags = []
    for team in (
        match.get("teams", {}).get("home", {}),
        match.get("teams", {}).get("away", {})
    ):
        name = team.get("name", "")
        tag = make_hashtag(name.replace(" ", ""))
        if tag and tag not in tags:
            tags.append(tag)

    if category_tag:
        tags.append(category_tag)

    tags.append("#VenomTV")

    return (
        f"🏆 <b>{title}</b>\n"
        f"🏅 Sport: {html.escape(str(category).title())}"
        f"{date_text}\n\n"
        f"📺 <b>Match information &amp; viewing options</b>\n"
        f"👉 <a href=\"{WEBSITE}\">Watch on VenomTV</a>\n\n"
        f"{' '.join(tags)}"
    )


def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": CHANNEL,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=30
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError("Telegram could not send the message")


def main():
    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()
    matches = response.json()

    if not isinstance(matches, list):
        raise RuntimeError("Unexpected API response")

    seen = load_seen()
    updated = set(seen)

    for match in matches:
        match_id = match.get("id")

        if not match_id or match_id in seen:
            continue

        post = make_post(match)

        try:
            send_message(post)
            updated.add(match_id)
            print(f"Posted: {match.get('title', match_id)}")

        except requests.RequestException as error:
            print(f"Posting failed for {match_id}: {error}")
            raise

    save_seen(updated)
    print(f"Finished. Total matches received: {len(matches)}")


if __name__ == "__main__":
    main()
