import os
import json
import html
import requests

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

API_URL = "https://streamed.pk/api/matches/football"
WEBSITE = "https://venomtv.vercel.app"
CHANNEL = "@hdhubsports"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
STATE_FILE = Path("seen_matches.json")
MAX_POSTS_PER_RUN = 1


def load_seen():
    try:
        return set(json.loads(STATE_FILE.read_text()))
    except (FileNotFoundError, ValueError, OSError):
        return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2)
    )


def hashtag(text):
    text = "".join(
        c for c in str(text).title()
        if c.isalnum() or c == "_"
    )
    return f"#{text}" if text else ""


def make_post(match):
    title = html.escape(str(match.get("title", "Sports Match")))
    category = str(match.get("category", "sports"))

    date_text = ""
    timestamp = match.get("date")

    if isinstance(timestamp, (int, float)):
        try:
            dt = datetime.fromtimestamp(
                timestamp / 1000,
                tz=ZoneInfo("Asia/Dhaka")
            )
            date_text = (
                f"\n📅 Date: {dt.strftime('%d %B %Y')}"
                f"\n⏰ Time: {dt.strftime('%I:%M %p')} (Bangladesh)"
            )
        except (ValueError, OverflowError, OSError):
            pass

    tags = []
    teams = match.get("teams") or {}

    for side in ("home", "away"):
        team = teams.get(side) or {}
        tag = hashtag(team.get("name", "").replace(" ", ""))

        if tag and tag not in tags:
            tags.append(tag)

    category_tag = hashtag(category)
    if category_tag:
        tags.append(category_tag)

    tags.append("#VenomTV")

    return (
        f"🏆 <b>{title}</b>\n"
        f"🏅 Sport: {html.escape(category.title())}"
        f"{date_text}\n\n"
        f"📺 Watch match information on VenomTV:\n"
        f"👉 <a href=\"{WEBSITE}\">Open VenomTV</a>\n\n"
        f"{' '.join(tags)}"
    )


def send_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": CHANNEL,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=30
    )

    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")


def main():
    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()

    matches = response.json()

    if not isinstance(matches, list):
        raise RuntimeError("Unexpected matches API response")

    seen = load_seen()
    posted_count = 0

    for match in matches:
        match_id = match.get("id")

        if not match_id or match_id in seen:
            continue

        if posted_count >= MAX_POSTS_PER_RUN:
            break

        send_message(make_post(match))

        # Save each successful post immediately.
        seen.add(match_id)
        save_seen(seen)

        posted_count += 1
        print(f"Posted: {match.get('title', match_id)}")

    print(f"Finished. New posts sent: {posted_count}")


if __name__ == "__main__":
    main()
