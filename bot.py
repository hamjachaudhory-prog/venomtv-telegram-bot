
import os
import json
import time
import html
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

import requests

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
MAX_STREAM_BUTTONS = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

session = requests.Session()
session.headers.update({"User-Agent": "VenomTV-Telegram-Bot/4.0"})


# =========================
# STATE
# =========================
def load_legacy_seen():
    try:
        with open(LEGACY_SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(map(str, data)) if isinstance(data, list) else set()
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# =========================
# MATCH HELPERS
# =========================
def safe_str(value, fallback="TBA"):
    if value is None or value == "":
        return fallback
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("id")
            or fallback
        )
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
    return str(
        match.get("category") or match.get("sport") or "Sports"
    ).replace("_", " ").title()


def get_poster_url(match):
    for candidate in (
        match.get("poster"),
        match.get("thumbnail"),
        match.get("image"),
        match.get("logo"),
    ):
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

        if candidate.startswith("/"):
            return urljoin("https://streamed.pk", candidate)

        return (
            f"https://streamed.pk/api/images/proxy/{candidate}.webp"
        )

    return None


def get_match_datetime(match):
    raw = (
        match.get("date")
        or match.get("start")
        or match.get("startsAt")
        or match.get("startTime")
    )

    if raw is None:
        return "Schedule not available"

    try:
        if isinstance(raw, (int, float)):
            ts = raw / 1000 if raw > 10_000_000_000 else raw
            dt = datetime.fromtimestamp(ts, tz=ZoneInfo("UTC"))
        else:
            dt = datetime.fromisoformat(
                str(raw).strip().replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        return dt.astimezone(TIMEZONE).strftime(
            "%d %b %Y, %I:%M %p"
        ) + " BDT"

    except (ValueError, TypeError, OverflowError, OSError):
        return "Schedule not available"


# =========================
# EXACTLY 50 UNIQUE HASHTAGS
# =========================
def make_hashtags(match):
    category = get_category(match).lower()
    title = safe_str(
        match.get("title") or match.get("name"),
        "Live Sports"
    )

    tags = [
        "HDHUBSPORTS", "VenomTV", "LiveSports", "SportsNews",
        "SportsLive", "MatchDay", "LiveMatch", "WatchLive",
        "SportsFans", "TrendingSports", "ViralSports",
        "TodaySports", "LatestSports", "SportsUpdates",
        "LiveUpdates", "MatchUpdates", "SportsHighlights",
        "GameDay", "WorldSports", "InternationalSports",
    ]

    category_tags = {
        "football": [
            "Football", "Soccer", "FootballLive", "FootballNews",
            "FootballFans", "Goal", "Goals", "SoccerLive",
            "FootballHighlights", "ClubFootball",
        ],
        "basketball": [
            "Basketball", "BasketballLive", "NBA",
            "BasketballNews", "Hoops",
        ],
        "cricket": [
            "Cricket", "CricketLive", "CricketNews",
            "LiveCricket", "CricketFans",
        ],
        "tennis": [
            "Tennis", "TennisLive", "TennisNews",
            "TennisFans", "GrandSlam",
        ],
        "hockey": [
            "Hockey", "HockeyLive", "HockeyNews",
            "IceHockey", "FieldHockey",
        ],
        "rugby": [
            "Rugby", "RugbyLive", "RugbyNews",
            "RugbyFans", "RugbyMatch",
        ],
        "mma": [
            "MMA", "FightNight", "CombatSports",
            "MMAFans", "MMAFight",
        ],
        "boxing": [
            "Boxing", "BoxingLive", "BoxingNews",
            "FightNight", "BoxingFans",
        ],
        "baseball": [
            "Baseball", "BaseballLive", "MLB",
            "BaseballNews", "BaseballFans",
        ],
        "volleyball": [
            "Volleyball", "VolleyballLive",
            "VolleyballNews", "VolleyballFans",
        ],
    }

    matched = next(
        (values for key, values in category_tags.items()
         if key in category),
        None
    )

    if matched:
        tags.extend(matched)
    else:
        clean_category = re.sub(r"[^a-zA-Z0-9]", "", category)
        if clean_category:
            tags.extend([
                clean_category,
                clean_category + "Live",
                clean_category + "News",
                clean_category + "Fans",
                clean_category + "Updates",
            ])

    tags.extend(
        word for word in re.findall(r"[A-Za-z0-9]+", title)
        if len(word) >= 3
    )

    extras = [
        "SportsWorld", "FanZone", "LiveCoverage", "MatchCentre",
        "SportsCommunity", "GameHighlights", "TopSports",
        "SportsAction", "PlayByPlay", "GlobalSports", "WatchSports",
        "MatchTime", "SportsArena", "TeamNews", "MatchPreview",
        "LiveCompetition", "SportsBuzz", "GameOn", "SportsToday",
        "AllSports", "MatchLive", "SportsMedia", "TeamFans",
        "LiveEvent", "GameHighlightsLive", "SportsChannel",
        "OnlineSports", "SportsNetwork", "MatchAlert", "SportsFeed",
        "FanCommunity", "LiveGame", "SportUpdates", "MatchAction",
        "SportsZone", "GameCoverage", "WatchTheMatch", "SportsDaily",
        "LiveSportEvent", "SportsWorldWide", "MatchNews", "TeamUpdate",
        "LiveArena", "SportsPassion", "WatchTogether", "SportsFever",
    ]

    unique, seen = [], set()

    for tag in tags + extras:
        tag = re.sub(r"[^A-Za-z0-9_]", "", tag)
        key = tag.lower()

        if tag and key not in seen:
            seen.add(key)
            unique.append("#" + tag)

        if len(unique) == 50:
            break

    n = 1
    while len(unique) < 50:
        tag = f"SportsUpdate{n}"
        if tag.lower() not in seen:
            seen.add(tag.lower())
            unique.append("#" + tag)
        n += 1

    return " ".join(unique[:50])


# =========================
# API FETCHING
# =========================
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
    found, seen_urls = [], set()

    for source_info in match.get("sources") or []:
        if not isinstance(source_info, dict):
            continue

        source = str(source_info.get("source", "")).strip()
        source_id = str(source_info.get("id", "")).strip()

        if not source or not source_id:
            continue

        if not source.replace("-", "").isalnum():
            continue

        endpoint = f"{STREAM_API_BASE}{source}/{source_id}"

        try:
            response = session.get(endpoint, timeout=REQUEST_TIMEOUT)

            if response.status_code == 404:
                continue

            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, list):
                continue

            for stream in payload:
                if not isinstance(stream, dict):
                    continue

                url = stream.get("embedUrl")
                if not isinstance(url, str):
                    continue

                url = url.strip()
                parsed = urlparse(url)

                if (
                    parsed.scheme not in ("http", "https")
                    or not parsed.netloc
                    or url in seen_urls
                ):
                    continue

                seen_urls.add(url)

                found.append({
                    "url": url,
                    "language": safe_str(
                        stream.get("language"), "Unknown"
                    ),
                    "quality": (
                        "HD" if stream.get("hd") is True else "SD"
                    ),
                })

        except Exception as exc:
            logging.warning(
                "Stream fetch failed for %s/%s: %s",
                source, source_id, exc
            )

    return found[:MAX_STREAM_BUTTONS]


# =========================
# TELEGRAM API
# =========================
def telegram_request(method, payload):
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN GitHub Secret")

    response = session.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram {method} failed: "
            f"{result.get('description', 'Unknown error')}"
        )

    return result["result"]


def build_keyboard(streams):
    rows = []

    for index, stream in enumerate(streams, start=1):
        label = (
            f"▶️ Play {index} · "
            f"{stream['language']} · {stream['quality']}"
        )

        if len(label) > 60:
            label = f"▶️ Play {index} · {stream['quality']}"

        rows.append([{
            "text": label,
            "url": stream["url"],
        }])

    return {"inline_keyboard": rows} if rows else None


# =========================
# POST CONTENT
# =========================
def make_post(match, streams):
    title = html.escape(
        safe_str(match.get("title") or match.get("name"),
                 "Upcoming Match")
    )
    category = html.escape(get_category(match))
    match_time = html.escape(get_match_datetime(match))
    hashtags = make_hashtags(match)

    if streams:
        stream_text = f"🟢 <b>STREAMS AVAILABLE:</b> {len(streams)}"
        hint = "👇 <b>Select a Play button below</b>"
    else:
        stream_text = "🟡 <b>STREAM STATUS:</b> Awaiting streams"
        hint = "🔔 Play buttons will appear when streams are available."

    body = (
        "🏆 <b>HD HUB SPORTS | LIVE MATCH CENTRE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 <b>{title}</b>\n\n"
        f"🏷️ <b>SPORT:</b> {category}\n"
        f"🕒 <b>TIME:</b> {match_time}\n\n"
        f"{stream_text}\n"
        f"{hint}\n\n"
        f'🌐 <a href="{WEBSITE_URL}">VenomTV Website</a> · '
        f'📢 <a href="{CHANNEL_URL}">Join Channel</a>\n\n'
    )

    message = body + hashtags

    if len(message) > 1024:
        body = (
            f"🏆 <b>HD HUB SPORTS</b>\n"
            f"🔥 <b>{title}</b>\n"
            f"🏷️ {category} · 🕒 {match_time}\n"
            f"📺 Streams: {len(streams)}\n"
            f'🌐 <a href="{WEBSITE_URL}">VenomTV</a> · '
            f'📢 <a href="{CHANNEL_URL}">Join Channel</a>\n\n'
        )
        message = body + hashtags

    if len(message) > 1024:
        body = (
            f"🏆 <b>HD HUB SPORTS</b> | "
            f"🔥 <b>{title}</b>\n"
            f"{category} · {match_time}\n"
            f"📺 Streams: {len(streams)}\n\n"
        )
        message = body + hashtags

    # Never cut a hashtag in half.
    if len(message) > 1024:
        logging.warning(
            "Caption is over Telegram's 1024-character limit; "
            "consider using a text post."
        )

    return message


def send_message(message, poster_url=None, streams=None):
    keyboard = build_keyboard(streams or [])

    if poster_url:
        payload = {
            "chat_id": CHANNEL,
            "photo": poster_url,
            "caption": message,
            "parse_mode": "HTML",
        }

        if keyboard:
            payload["reply_markup"] = keyboard

        try:
            result = telegram_request("sendPhoto", payload)
            return result["message_id"], True
        except Exception as exc:
            logging.warning("sendPhoto failed; text fallback: %s", exc)

    payload = {
        "chat_id": CHANNEL,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if keyboard:
        payload["reply_markup"] = keyboard

    result = telegram_request("sendMessage", payload)
    return result["message_id"], False


def edit_existing_post(message_id, is_photo, message, streams):
    keyboard = build_keyboard(streams)

    payload = {
        "chat_id": CHANNEL,
        "message_id": int(message_id),
        "parse_mode": "HTML",
        "reply_markup": keyboard or {"inline_keyboard": []},
    }

    if is_photo:
        payload["caption"] = message
        telegram_request("editMessageCaption", payload)
    else:
        payload["text"] = message
        payload["disable_web_page_preview"] = True
        telegram_request("editMessageText", payload)


def add_auto_reaction(message_id):
    try:
        telegram_request("setMessageReaction", {
            "chat_id": CHANNEL,
            "message_id": int(message_id),
            "reaction": [{"type": "emoji", "emoji": AUTO_REACTION}],
            "is_big": False,
        })
    except Exception as exc:
        logging.warning(
            "Could not add reaction to message %s: %s",
            message_id, exc
        )


# =========================
# MAIN: UPDATE EXISTING POSTS
# =========================
def main():
    state = load_state()
    legacy_seen = load_legacy_seen()
    matches = fetch_matches()

    if not matches:
        logging.info("No matches returned; preserving state.")
        return

    logging.info("Fetched %s matches", len(matches))

    new_posts = 0
    updated_posts = 0
    skipped_legacy = 0

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

            # Existing saved Telegram post: edit it instead of reposting.
            if old and old.get("message_id"):
                old_urls = set(old.get("stream_urls", []))
                new_urls = set(stream_urls)

                # Force one edit for old records without buttons_added.
                needs_update = (
                    old_urls != new_urls
                    or not old.get("buttons_added", False)
                )

                if needs_update:
                    edit_existing_post(
                        int(old["message_id"]),
                        bool(old.get("is_photo")),
                        message,
                        streams,
                    )

                    old["stream_urls"] = stream_urls
                    old["buttons_added"] = True
                    old["poster_url"] = (
                        poster_url or old.get("poster_url")
                    )
                    old["updated_at"] = int(time.time())
                    state[match_id] = old
                    save_state(state)

                    updated_posts += 1
                    logging.info(
                        "Edited existing post for %s; message_id=%s",
                        match_id, old["message_id"]
                    )

                continue

            # Legacy IDs don't include Telegram message IDs.
            # Skip them to avoid making duplicate posts.
            if match_id in legacy_seen:
                skipped_legacy += 1
                logging.info(
                    "Skipping legacy match %s: no message ID saved",
                    match_id
                )
                continue

            # Only genuinely new matches are posted.
            message_id, is_photo = send_message(
                message, poster_url, streams
            )

            state[match_id] = {
                "message_id": message_id,
                "is_photo": is_photo,
                "stream_urls": stream_urls,
                "poster_url": poster_url,
                "buttons_added": True,
                "posted_at": int(time.time()),
            }

            save_state(state)
            add_auto_reaction(message_id)
            new_posts += 1

            logging.info(
                "Posted new match %s as message %s",
                match_id, message_id
            )
            time.sleep(1.2)

        except Exception as exc:
            logging.exception(
                "Failed processing match %s: %s",
                match_id, exc
            )

    logging.info(
        "Finished. New posts: %s; updated posts: %s; "
        "skipped legacy: %s",
        new_posts, updated_posts, skipped_legacy
    )


if __name__ == "__main__":
    main()
