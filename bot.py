import os
import json
import time
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

import requests

# =========================
# CONFIGURATION
# =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL = "@hdhubsports"

API_URL = "https://streamed.pk/api/matches/all"
STREAM_API_BASE = "https://streamed.pk/api/stream/"
WEBSITE_URL = "https://venomtv.vercel.app"
CHANNEL_URL = "https://t.me/hdhubsports"

STATE_FILE = "posted_matches.json"
LEGACY_SEEN_FILE = "seen_matches.json"
AUTO_REACTION = "🔥"
TIMEZONE = ZoneInfo("Asia/Dhaka")
REQUEST_TIMEOUT = 25
MAX_STREAM_BUTTONS = 100  # Telegram inline keyboard practical limit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

session = requests.Session()
session.headers.update({"User-Agent": "VenomTV-Telegram-Bot/2.0"})


# =========================
# STATE
# =========================
def load_legacy_seen():
    try:
        with open(LEGACY_SEEN_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, list):
            return set(str(x) for x in old)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return set()


def load_state():
    """State format: {match_id: {message_id, photo, streams: [embedUrl, ...]}}"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Backward compatibility: old seen_matches.json contains IDs only.
    # IDs alone cannot identify Telegram message IDs, so old posts cannot
    # be edited automatically unless their message IDs are known.
    try:
        with open(LEGACY_SEEN_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, list):
            logging.warning(
                "Legacy seen_matches.json found. It has match IDs but no "
                "Telegram message IDs; old posts cannot be edited automatically."
            )
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# =========================
# HELPERS
# =========================
def safe_str(value, fallback="TBA"):
    if value is None or value == "":
        return fallback
    if isinstance(value, dict):
        value = value.get("name") or value.get("title") or value.get("id") or fallback
    return str(value)


def get_match_id(match):
    value = match.get("id") or match.get("_id") or match.get("slug")
    if value:
        return str(value)
    return "|".join([
        str(match.get("title", "")),
        str(match.get("category", "")),
        str(match.get("date", "")),
    ])


def get_category(match):
    value = match.get("category") or match.get("sport") or "Sports"
    return str(value).replace("_", " ").title()


def get_poster_url(match):
    for candidate in (
        match.get("poster"),
        match.get("thumbnail"),
        match.get("image"),
        match.get("logo"),
    ):
        if isinstance(candidate, dict):
            candidate = candidate.get("url") or candidate.get("src") or candidate.get("poster")
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        candidate = candidate.strip()
        if candidate.startswith(("https://", "http://")):
            return candidate
        # The documented poster endpoint is /api/images/proxy/[poster].webp
        if candidate.startswith("/"):
            return urljoin("https://streamed.pk", candidate)
        return f"https://streamed.pk/api/images/proxy/{candidate}.webp"
    return None


def get_match_datetime(match):
    raw = match.get("date") or match.get("start") or match.get("startsAt") or match.get("startTime")
    if raw is None:
        return "Schedule not available"
    try:
        if isinstance(raw, (int, float)):
            ts = raw / 1000 if raw > 10_000_000_000 else raw
            dt = datetime.fromtimestamp(ts, tz=ZoneInfo("UTC"))
        elif isinstance(raw, str):
            dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        else:
            return "Schedule not available"
        return dt.astimezone(TIMEZONE).strftime("%d %b %Y, %I:%M %p") + " (BDT)"
    except (ValueError, TypeError, OverflowError, OSError):
        return "Schedule not available"


def fetch_matches():
    response = session.get(API_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("matches", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError("Unexpected matches API response format")


def fetch_streams_for_match(match):
    """Fetch streams for every source listed on a match; deduplicate embed URLs."""
    found = []
    seen_urls = set()
    sources = match.get("sources") or []

    for source_info in sources:
        if not isinstance(source_info, dict):
            continue
        source = str(source_info.get("source", "")).strip()
        source_id = str(source_info.get("id", "")).strip()
        if not source or not source_id:
            continue

        # Do not build endpoints from arbitrary values.
        if not source.replace("-", "").isalnum():
            logging.warning("Skipping invalid source name: %r", source)
            continue

        endpoint = f"{STREAM_API_BASE}{source}/{source_id}"
        try:
            response = session.get(endpoint, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                logging.info("No streams for source %s/%s", source, source_id)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                continue

            for stream in payload:
                if not isinstance(stream, dict):
                    continue
                embed_url = stream.get("embedUrl")
                if not isinstance(embed_url, str):
                    continue
                embed_url = embed_url.strip()
                parsed = urlparse(embed_url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    continue
                if embed_url in seen_urls:
                    continue
                seen_urls.add(embed_url)

                lang = safe_str(stream.get("language"), "Unknown language")
                quality = "HD" if stream.get("hd") is True else "SD"
                stream_no = stream.get("streamNo")
                found.append({
                    "url": embed_url,
                    "source": source,
                    "language": lang,
                    "quality": quality,
                    "stream_no": stream_no,
                })
        except Exception as exc:
            logging.warning("Stream request failed for %s/%s: %s", source, source_id, exc)

    return found[:MAX_STREAM_BUTTONS]


# =========================
# TELEGRAM
# =========================
def telegram_request(method, payload):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN GitHub Secret is missing.")
    response = session.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description', 'Unknown error')}")
    return data["result"]


def build_keyboard(streams):
    rows = []
    for index, stream in enumerate(streams, start=1):
        label = f"▶️ Play {index} · {stream['language']} · {stream['quality']}"
        # Telegram button labels should remain short.
        if len(label) > 60:
            label = f"▶️ Play {index} · {stream['quality']}"
        rows.append([{"text": label, "url": stream["url"]}])
    return {"inline_keyboard": rows} if rows else None


def make_post(match, streams):
    title = html.escape(safe_str(match.get("title") or match.get("name"), "Upcoming Match"))
    category = html.escape(get_category(match))
    date_text = html.escape(get_match_datetime(match))

    if streams:
        stream_line = f"📺 <b>Available Streams:</b> {len(streams)}"
        hint = "Choose a Play button below to open a stream in Telegram's in-app browser."
    else:
        stream_line = "📺 <b>Streams:</b> Not available yet"
        hint = "The bot will check again and add Play buttons when streams become available."

    # Keep caption under Telegram's 1024-character caption limit.
    message = (
        f"🏆 <b>{title}</b>\n\n"
        f"📂 <b>Category:</b> {category}\n"
        f"🕒 <b>Time:</b> {date_text}\n\n"
        f"{stream_line}\n"
        f"ℹ️ {html.escape(hint)}\n\n"
        f'🌐 <a href="{WEBSITE_URL}">VenomTV Website</a> · '
        f'📢 <a href="{CHANNEL_URL}">Join Channel</a>\n\n'
        f"#VenomTV #HDHUBSPORTS #LiveSports"
    )
    return message[:1000]


def send_message(message, poster_url=None, streams=None):
    payload_keyboard = build_keyboard(streams or [])
    if poster_url:
        payload = {
            "chat_id": CHANNEL,
            "photo": poster_url,
            "caption": message,
            "parse_mode": "HTML",
        }
        if payload_keyboard:
            payload["reply_markup"] = payload_keyboard
        try:
            result = telegram_request("sendPhoto", payload)
            return result["message_id"], True
        except Exception as exc:
            logging.warning("Photo post failed; falling back to text: %s", exc)

    payload = {
        "chat_id": CHANNEL,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if payload_keyboard:
        payload["reply_markup"] = payload_keyboard
    result = telegram_request("sendMessage", payload)
    return result["message_id"], False


def edit_existing_post(message_id, is_photo, message, streams):
    keyboard = build_keyboard(streams)
    payload = {
        "chat_id": CHANNEL,
        "message_id": message_id,
        "parse_mode": "HTML",
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    else:
        # Telegram accepts an empty inline keyboard to remove old buttons.
        payload["reply_markup"] = {"inline_keyboard": []}

    if is_photo:
        payload["caption"] = message[:1000]
        telegram_request("editMessageCaption", payload)
    else:
        payload["text"] = message[:4000]
        payload["disable_web_page_preview"] = True
        telegram_request("editMessageText", payload)


def add_auto_reaction(message_id, emoji=AUTO_REACTION):
    try:
        telegram_request("setMessageReaction", {
            "chat_id": CHANNEL,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
            "is_big": False,
        })
    except Exception as exc:
        logging.warning("Could not add reaction to message %s: %s", message_id, exc)


# =========================
# MAIN
# =========================
def main():
    state = load_state()
    legacy_seen = load_legacy_seen()
    matches = fetch_matches()
    if not matches:
        logging.info("No matches returned; keeping existing state.")
        return

    logging.info("Received %s matches.", len(matches))
    new_posts = 0
    updated_posts = 0

    for match in matches:
        if not isinstance(match, dict):
            continue

        match_id = get_match_id(match)
        if not match_id:
            continue

        try:
            streams = fetch_streams_for_match(match)
            stream_urls = [item["url"] for item in streams]
            message = make_post(match, streams)
            poster_url = get_poster_url(match)

            old = state.get(match_id)
            if old and old.get("message_id"):
                old_urls = set(old.get("stream_urls", []))
                new_urls = set(stream_urls)

                # Edit only when the set of available streams changed.
                if old_urls != new_urls:
                    edit_existing_post(
                        int(old["message_id"]),
                        bool(old.get("is_photo")),
                        message,
                        streams,
                    )
                    old["stream_urls"] = stream_urls
                    old["updated_at"] = int(time.time())
                    state[match_id] = old
                    save_state(state)
                    updated_posts += 1
                    logging.info("Updated match post: %s", match_id)
            elif match_id in legacy_seen:
                # The old file has this match ID but not its Telegram message ID.
                # Avoid duplicate posts; old messages cannot be edited automatically.
                logging.info("Skipping legacy match %s: no stored Telegram message ID.", match_id)
                continue
            else:
                message_id, is_photo = send_message(message, poster_url, streams)
                state[match_id] = {
                    "message_id": message_id,
                    "is_photo": is_photo,
                    "stream_urls": stream_urls,
                    "posted_at": int(time.time()),
                }
                save_state(state)
                add_auto_reaction(message_id)
                new_posts += 1
                logging.info("Posted match %s as message %s", match_id, message_id)
                time.sleep(1.2)

        except Exception as exc:
            logging.exception("Failed processing match %s: %s", match_id, exc)

    logging.info("Finished. New posts: %s; updated posts: %s", new_posts, updated_posts)


if __name__ == "__main__":
    main()
