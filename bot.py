import os
import json
import html
import time
import requests

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

# API and channel settings
API_URL = "https://streamed.pk/api/matches/all"
STREAMED_BASE = "https://streamed.pk/"
WEBSITE = "https://venomtv.vercel.app"
CHANNEL = "@hdhubsports"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
STATE_FILE = Path("seen_matches.json")

REQUEST_TIMEOUT = 30
TELEGRAM_DELAY = 1.5

session = requests.Session()


def load_seen():
    try:
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
        if isinstance(data, list):
            return set(str(item) for item in data)
    except (FileNotFoundError, ValueError, OSError):
        pass

    return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(
            sorted(seen),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def get_match_date(match):
    timestamp = match.get("date")

    if not isinstance(timestamp, (int, float)):
        return "Not available"

    try:
        dt = datetime.fromtimestamp(
            timestamp / 1000,
            tz=ZoneInfo("Asia/Dhaka")
        )
        return dt.strftime("%d %B %Y | %I:%M %p")
    except (ValueError, OverflowError, OSError):
        return "Not available"


def get_team_name(match, side):
    teams = match.get("teams") or {}
    team = teams.get(side) or {}

    if isinstance(team, dict):
        return str(team.get("name") or "")

    return str(team)


def make_hashtag(name):
    name = "".join(
        c for c in str(name).title()
        if c.isalnum()
    )

    return f"#{name}" if name else ""


def get_poster_url(match):
    poster = match.get("poster")

    if isinstance(poster, dict):
        poster = poster.get("url") or poster.get("src")

    if not isinstance(poster, str) or not poster.strip():
        return None

    return urljoin(STREAMED_BASE, poster.strip())


def make_post(match):
    title = str(match.get("title") or "Football Match")
    category = str(match.get("category") or "Football")

    home = get_team_name(match, "home") or "Team TBC"
    away = get_team_name(match, "away") or "Team TBC"

    match_date = get_match_date(match)

    # Relevant football hashtags
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

    for name in (home, away, category):
        tag = make_hashtag(name)

        if tag and tag.lower() not in {
            item.lower() for item in tags
        }:
            tags.append(tag)

    search_keywords = (
        f"{home} vs {away}, Football News, "
        f"Football Fixtures, Match Updates, VenomTV"
    )

    # Keep the caption below Telegram's photo-caption limit.
    message = (
        f"⚽ <b>{html.escape(title)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>TODAY MATCH UPDATE</b>\n\n"
        f"🥅 <b>Match:</b> "
        f"{html.escape(home)} vs {html.escape(away)}\n"
        f"🌍 <b>Category:</b> {html.escape(category.title())}\n"
        f"📅 <b>Date &amp; Time:</b> "
        f"{html.escape(match_date)} (Bangladesh Time)\n\n"
        f"📢 <b>FOLLOW VENOMTV</b>\n"
        f"⚽ Football news, fixtures and match updates.\n\n"
        f"🌐 <a href=\"{WEBSITE}\">Visit VenomTV Website</a>\n"
        f"📲 <a href=\"https://t.me/hdhubsports\">"
        f"Join Our Telegram Channel</a>\n\n"
        f"🔎 <b>SEARCH KEYWORDS</b>\n"
        f"<code>{html.escape(search_keywords)}</code>\n\n"
        f"{' '.join(tags)}"
    )

    return message


def telegram_request(method, payload):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"

    response = session.post(
        url,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            result.get("description", "Telegram API error")
        )

    return result


def send_message(message, poster_url=None):
    # Try sending the thumbnail first.
    if poster_url:
        try:
            telegram_request(
                "sendPhoto",
                {
                    "chat_id": CHANNEL,
                    "photo": poster_url,
                    "caption": message,
                    "parse_mode": "HTML",
                }
            )
            print("Posted with thumbnail.")
            return

        except (requests.RequestException, RuntimeError) as exc:
            print(f"Photo failed; trying text post: {exc}")

    # Fallback: send the post as text.
    telegram_request(
        "sendMessage",
        {
            "chat_id": CHANNEL,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    )

    print("Posted as text.")


def main():
    print("VenomTV Football Bot starting...")

    response = session.get(
        API_URL,
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    matches = response.json()

    if not isinstance(matches, list):
        raise RuntimeError("Unexpected API response: expected a list.")

    print(f"Matches received from API: {len(matches)}")

    seen = load_seen()
    posted = 0
    skipped = 0
    failed = 0

    # Process every returned match, not just the first one.
    for match in matches:
        if not isinstance(match, dict):
            skipped += 1
            continue

        match_id = match.get("id")

        if not match_id:
            skipped += 1
            continue

        match_id = str(match_id)

        # Only football matches
        category = str(match.get("category") or "").lower()

        if category != "football":
            skipped += 1
            continue

        # Do not repost matches already recorded as successful.
        if match_id in seen:
            skipped += 1
            continue

        try:
            message = make_post(match)
            poster_url = get_poster_url(match)

            send_message(message, poster_url)

            # Record the match only after Telegram accepts the post.
            seen.add(match_id)
            save_seen(seen)

            posted += 1
            print(
                f"SUCCESS: {match.get('title', match_id)}"
            )

            time.sleep(TELEGRAM_DELAY)

        except Exception as exc:
            failed += 1
            print(
                f"FAILED: {match.get('title', match_id)}: {exc}"
            )
            # Continue trying the remaining matches.
            continue

    print("========== SUMMARY ==========")
    print(f"API matches: {len(matches)}")
    print(f"New posts sent: {posted}")
    print(f"Skipped matches: {skipped}")
    print(f"Failed posts: {failed}")
    print("Bot run completed.")


if __name__ == "__main__":
    main()
