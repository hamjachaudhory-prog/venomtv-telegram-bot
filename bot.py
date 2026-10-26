import os
import json
import html
import requests

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

API_URL = "https://streamed.pk/api/matches/all"
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
    title_raw = str(match.get("title") or "Football Match")
    title = html.escape(title_raw)

    category_raw = str(match.get("category") or "Football")
    category = html.escape(category_raw.title())

    teams = match.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}

    home_name = str(home.get("name") or "")
    away_name = str(away.get("name") or "")

    timestamp = match.get("date")
    date_text = "Not confirmed"

    if isinstance(timestamp, (int, float)):
        try:
            dt = datetime.fromtimestamp(
                timestamp / 1000,
                tz=ZoneInfo("Asia/Dhaka")
            )
            date_text = dt.strftime("%d %B %Y | %I:%M %p")
        except (ValueError, OverflowError, OSError):
            pass

    def make_tag(value):
        value = "".join(
            char for char in str(value).title()
            if char.isalnum()
        )
        return f"#{value}" if value else ""

    tags = [
        "#VenomTV",
        "#Football",
        "#FootballNews",
        "#FootballUpdates",
        "#FootballFixtures",
        "#Soccer",
        "#SoccerNews",
        "#MatchDay",
        "#LiveFootball",
        "#SportsNews",
    ]

    for name in (home_name, away_name, category_raw):
        tag = make_tag(name)
        if tag and tag.lower() not in {item.lower() for item in tags}:
            tags.append(tag)

    hashtags = " ".join(tags)

    home_display = html.escape(home_name or "Team TBC")
    away_display = html.escape(away_name or "Team TBC")

    return (
        f"⚽ <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>TODAY MATCH UPDATE</b>\n\n"
        f"🥅 <b>Match:</b> {home_display} vs {away_display}\n"
        f"🌍 <b>Category:</b> {category}\n"
        f"📅 <b>Date & Time:</b> {html.escape(date_text)} "
        f"(Bangladesh Time)\n\n"
        f"📢 <b>FOLLOW VENOMTV</b>\n"
        f"⚽ Football news, fixtures and match updates.\n\n"
        f"🌐 <a href=\"https://venomtv.vercel.app\">"
        f"Visit VenomTV Website</a>\n"
        f"📲 <a href=\"https://t.me/hdhubsports\">"
        f"Join Our Telegram Channel</a>\n\n"
        f"🔎 SEARCH \n"
f"{html.escape(home_name or 'Football')} vs "
f"{html.escape(away_name or 'Football')}, "
f"Football News, Football Fixtures, Match Updates, VenomTV\n\n"
        f"{hashtags}"
    )
    

    
def send_message(message, poster_url=None):
    if poster_url:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        payload = {
            "chat_id": CHANNEL,
            "photo": poster_url,
            "caption": message,
            "parse_mode": "HTML"
        }
    else:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            "chat_id": CHANNEL,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

    response = requests.post(url, json=payload, timeout=30)
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
