import os
import json
import time
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import requests

# =========================
# CONFIGURATION
# =========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Public Telegram channel username
CHANNEL = "@hdhubsports"

API_URL = "https://streamed.pk/api/matches/all"
WEBSITE_URL = "https://venomtv.vercel.app"
CHANNEL_URL = "https://t.me/hdhubsports"

SEEN_FILE = "seen_matches.json"
AUTO_REACTION = "🔥"

TIMEZONE = ZoneInfo("Asia/Dhaka")
REQUEST_TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "VenomTV-Telegram-Bot/1.0"
})


# =========================
# LOAD / SAVE POSTED MATCHES
# =========================

def load_seen_matches():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return set(str(item) for item in data)

    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen_matches(seen_matches):
    temporary_file = SEEN_FILE + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(sorted(seen_matches), file, ensure_ascii=False, indent=2)

    os.replace(temporary_file, SEEN_FILE)


# =========================
# GENERAL HELPERS
# =========================

def safe_text(value, fallback="TBA"):
    if value is None or value == "":
        return fallback

    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("id")
            or fallback
        )

    return html.escape(str(value))


def get_match_id(match):
    for key in ("id", "_id", "slug"):
        value = match.get(key)

        if value:
            return str(value)

    # Fallback if the API does not provide a normal ID
    return "|".join([
        str(match.get("title", "")),
        str(match.get("category", "")),
        str(match.get("date", "")),
        str(match.get("sources", ""))
    ])


def get_category(match):
    category = match.get("category") or match.get("sport") or "Sports"
    return str(category).replace("_", " ").title()


def get_poster_url(match):
    """
    Return a poster URL if the API provides one.
    API fields can vary, so several common fields are checked.
    """
    candidates = [
        match.get("poster"),
        match.get("thumbnail"),
        match.get("image"),
        match.get("logo"),
    ]

    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = (
                candidate.get("url")
                or candidate.get("src")
                or candidate.get("poster")
            )

        if not isinstance(candidate, str) or not candidate.strip():
            continue

        candidate = candidate.strip()

        if candidate.startswith(("https://", "http://")):
            return candidate

        return urljoin("https://streamed.pk/", candidate.lstrip("/"))

    return None


def get_match_datetime(match):
    """
    Parse common timestamp formats and convert to Bangladesh time.
    If the API date is missing or unrecognized, return a safe fallback.
    """
    raw_date = (
        match.get("date")
        or match.get("start")
        or match.get("startsAt")
        or match.get("startTime")
    )

    if raw_date is None:
        return "Schedule not available"

    try:
        if isinstance(raw_date, (int, float)):
            timestamp = raw_date

            # Convert millisecond timestamps to seconds
            if timestamp > 10_000_000_000:
                timestamp /= 1000

            dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC"))

        elif isinstance(raw_date, str):
            cleaned = raw_date.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        else:
            return "Schedule not available"

        dt = dt.astimezone(TIMEZONE)

        return dt.strftime("%d %b %Y, %I:%M %p") + " (BDT)"

    except (ValueError, TypeError, OverflowError, OSError):
        return "Schedule not available"


# =========================
# BUILD TELEGRAM POST
# =========================

def make_post(match):
    title = match.get("title") or match.get("name") or "Upcoming Match"

    title = str(title)
    category = get_category(match)
    date_text = get_match_datetime(match)

    # Escape text for Telegram HTML mode
    title_html = html.escape(title)
    category_html = html.escape(category)
    date_html = html.escape(date_text)

    # Search-friendly terms
    search_text = html.escape(
        f"{title} {category} live match today"
    )

    # Generate hashtags
    tags = ["#VenomTV", "#LiveSports"]

    category_tag = "".join(
        part.capitalize()
        for part in category.split()
        if part.isalnum()
    )

    if category_tag:
        tags.append("#" + category_tag)

    tags_text = " ".join(tags)

    message = (
        f"🏆 <b>{title_html}</b>\n\n"
        f"📂 <b>Category:</b> {category_html}\n"
        f"🕒 <b>Time:</b> {date_html}\n\n"
        f"📺 <b>Watch on VenomTV</b>\n"
        f'🌐 <a href="{WEBSITE_URL}">Open Website</a>\n'
        f'📢 <a href="{CHANNEL_URL}">Join Telegram Channel</a>\n\n'
        f"🔎 <b>Search Keywords:</b>\n"
        f"<code>{search_text}</code>\n\n"
        f"{tags_text}"
    )

    # Telegram photo captions are limited to 1024 characters.
    # Keep a margin for HTML parsing and formatting.
    if len(message) > 950:
        message = (
            f"🏆 <b>{title_html}</b>\n\n"
            f"📂 <b>Category:</b> {category_html}\n"
            f"🕒 <b>Time:</b> {date_html}\n\n"
            f'📺 <a href="{WEBSITE_URL}">Watch on VenomTV</a>\n'
            f'📢 <a href="{CHANNEL_URL}">Join Channel</a>\n\n'
            f"{tags_text}"
        )

    return message


# =========================
# TELEGRAM API
# =========================

def telegram_request(method, payload):
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN GitHub Secret is missing."
        )

    url = f"https://api.telegram.org/bot{TOKEN}/{method}"

    response = session.post(
        url,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram {method} failed: {data.get('description', 'Unknown error')}"
        )

    return data["result"]


def send_message(message, poster_url=None):
    """
    Send a photo with caption when possible.
    Fall back to a regular text message if the photo fails.
    Return the Telegram message ID on success.
    """
    if poster_url:
        try:
            result = telegram_request("sendPhoto", {
                "chat_id": CHANNEL,
                "photo": poster_url,
                "caption": message,
                "parse_mode": "HTML"
            })

            logging.info("Posted photo message: %s", result["message_id"])
            return result["message_id"]

        except Exception as error:
            logging.warning("Photo post failed; trying text: %s", error)

    result = telegram_request("sendMessage", {
        "chat_id": CHANNEL,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    })

    logging.info("Posted text message: %s", result["message_id"])
    return result["message_id"]


def add_auto_reaction(message_id, emoji=AUTO_REACTION):
    """
    Add one reaction to a newly posted message.
    The bot must have the required channel permissions and the
    chosen emoji must be allowed by the channel.
    """
    try:
        telegram_request("setMessageReaction", {
            "chat_id": CHANNEL,
            "message_id": message_id,
            "reaction": [
                {
                    "type": "emoji",
                    "emoji": emoji
                }
            ],
            "is_big": False
        })

        logging.info(
            "Added reaction %s to message %s",
            emoji,
            message_id
        )

    except Exception as error:
        # A reaction failure should not undo a successful post.
        logging.warning(
            "Could not add reaction to message %s: %s",
            message_id,
            error
        )


# =========================
# FETCH MATCHES
# =========================

def fetch_matches():
    logging.info("Fetching matches from %s", API_URL)

    response = session.get(
        API_URL,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        # Handle common API response wrappers
        for key in ("matches", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]

    logging.warning("Unexpected API response format.")
    return []


# =========================
# MAIN BOT
# =========================

def main():
    seen_matches = load_seen_matches()

    try:
        matches = fetch_matches()
    except Exception as error:
        logging.exception("Could not fetch matches: %s", error)
        raise

    if not matches:
        logging.info("No matches returned by the API.")
        return

    logging.info("Received %s matches.", len(matches))

    new_posts = 0

    for match in matches:
        if not isinstance(match, dict):
            continue

        match_id = get_match_id(match)

        if not match_id or match_id in seen_matches:
            continue

        try:
            post_text = make_post(match)
            poster_url = get_poster_url(match)

            # Send the post and get its Telegram message ID
            message_id = send_message(
                post_text,
                poster_url=poster_url
            )

            # React after the post has been sent successfully
            add_auto_reaction(message_id)

            # Save the ID only after successful posting
            seen_matches.add(match_id)
            save_seen_matches(seen_matches)

            new_posts += 1

            # Avoid sending too quickly
            time.sleep(1.5)

        except Exception as error:
            logging.exception(
                "Failed to post match %s: %s",
                match_id,
                error
            )

    logging.info("Finished. New posts sent: %s", new_posts)


if __name__ == "__main__":
    main()
