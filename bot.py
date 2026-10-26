import os
import json
import html
import requests

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

API_URL = "https://streamed.pk/api/matches/all"
WEBSITE = "https://venomtv.vercel.app"
CHANNEL = "@hdhubsports"
STREAMED_BASE = "https://streamed.pk/"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
STATE_FILE = Path("seen_matches.json")

# One new match per GitHub Actions run.
MAX_POSTS_PER_RUN = 1

REQUEST_TIMEOUT = 30


def load_seen():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (FileNotFoundError, ValueError, OSError):
        return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def hashtag(text):
    text = "".join(
        char for char in str(text).title()
        if char.isalnum()
    )
    return f"#{text}" if text else ""


def get_team_name(teams, side):
    team = teams.get(side) or {}

    if isinstance(team, dict):
        return str(team.get("name") or "")

    return str(team or "")


def get_match_datetime(match):
    timestamp = match.get("date")

    if not isinstance(timestamp, (int, float)):
        return "Not available"

    try:
        # Streamed match timestamps are expected in milliseconds.
        dt = datetime.fromtimestamp(
            timestamp / 1000,
            tz=ZoneInfo("Asia/Dhaka")
        )
        return dt.strftime("%d %B %Y | %I:%M %p")
    except (ValueError, OverflowError, OSError):
        return "Not available"


def get_poster_url(match):
    poster = match.get("poster")

    if isinstance(poster, dict):
        poster = poster.get("url") or poster.get("src")

    if not isinstance(poster, str) or not poster.strip():
        return None

    poster = poster.strip()

    # Handle absolute and relative image URLs.
    return urljoin(STREAMED_BASE, poster)


def make_post(match):
    title_raw = str(match.get("title") or "Football Match")
    title = html.escape(title_raw)

    category_raw = str(match.get("category") or "football")
    category = html.escape(category_raw.title())

    teams = match.get("teams") or {}

    if not isinstance(teams, dict):
        teams = {}

    home_name = get_team_name(teams, "home")
    away_name = get_team_name(teams, "away")

    home_display = html.escape(home_name or "Team TBC")
    away_display = html.escape(away_name or "Team TBC")

    match_date = html.escape(get_match_datetime(match))

    # Generate relevant hashtags.
    tags = [
        "#VenomTV",
        "#Football",
        "#FootballNews",
        "#FootballUpdates",
        "#FootballFixtures",
        "#Soccer",
        "#SoccerNews",
        "#MatchDay",
        "#SportsNews",
    ]

    for value in (home_name, away_name, category_raw):
        tag = hashtag(value)

        if tag and tag.lower() not in {
            existing.lower() for existing in tags
        }:
            tags.append(tag)

    # Keep the caption within Telegram's caption limit.
    hashtags = " ".join(tags)

    search_text = (
        f"{home_name or 'Football'} vs "
        f"{away_name or 'Football'}, "
        "Football News, Football Fixtures, "
        "Football Match Updates, VenomTV"
    )

    message = (
        f"⚽ <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>TODAY MATCH UPDATE</b>\n\n"
        f"🥅 <b>Match:</b> {home_display} vs {away_display}\n"
        f"🌍 <b>Category:</b> {category}\n"
        f"📅 <b>Date &amp; Time:</b> {match_date} "
        f"(Bangladesh Time)\n\n"
        f"📢 <b>FOLLOW VENOMTV</b>\n"
        f"⚽ Football news, fixtures and match updates.\n\n"
        f"🌐 <a href=\"{WEBSITE}\">Visit VenomTV Website</a>\n"
        f"📲 <a href=\"https://t.me/hdhubsports\">"
        f"Join Our Telegram Channel</a>\n\n"
        f"🔎 <b>SEARCH KEYWORDS</b>\n"
        f"<code>{html.escape(search_text)}</code>\n\n"
        f"{hashtags}"
    )

    # Telegram photo captions have a 1024-character limit.
    if len(message) > 1000:
        message = (
            f"⚽ <b>{title}</b>\n\n"
            f"🥅 {home_display} vs {away_display}\n"
            f"🏆 {category}\n"
            f"📅 {match_date} (Bangladesh Time)\n\n"
            f"🌐 <a href=\"{WEBSITE}\">Visit VenomTV</a>\n"
            f"📲 <a href=\"https://t.me/hdhubsports\">"
            f"Join Telegram</a>\n\n"
            f"🔎 <code>{html.escape(search_text)}</code>\n\n"
            f"{hashtags}"
        )

    return message


def send_message(message, poster_url=None):
    if poster_url:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

        payload = {
            "chat_id": CHANNEL,
            "photo": poster_url,
            "caption": message,
            "parse_mode": "HTML",
        }
    else:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        payload = {
            "chat_id": CHANNEL,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

    response = requests.post(
        url,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API rejected the message: "
            f"{result.get('description', 'Unknown error')}"
        )


def main():
    response = requests.get(
        API_URL,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    matches = response.json()

    if not isinstance(matches, list):
        raise RuntimeError("Unexpected football API response")

    seen = load_seen()
    posted_count = 0

    for match in matches:
        if not isinstance(match, dict):
            continue

        match_id = match.get("id")
        if not match_id:
            continue

        match_id = str(match_id)

        if match_id in seen:
            continue

        # Only allow football-category matches.
        category = str(match.get("category") or "").lower()

        if category != "football":
            continue

        if posted_count >= MAX_POSTS_PER_RUN:
            break

        message = make_post(match)
        poster_url = get_poster_url(match)

        try:
            send_message(message, poster_url=poster_url)

        except requests.RequestException as exc:
            # If photo delivery fails, try a text-only post.
            if poster_url:
                print(
                    f"Photo post failed for {match_id}; "
                    "trying text-only post."
                )
                send_message(message, poster_url=None)
            else:
                raise exc

        # Mark a match as seen only after successful delivery.
        seen.add(match_id)
        save_seen(seen)

        posted_count += 1
        print(f"Posted: {match.get('title', match_id)}")

    print(f"Finished. New posts sent: {posted_count}")


if __name__ == "__main__":
    main()
