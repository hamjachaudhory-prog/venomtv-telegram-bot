import os
import requests

API_BASE = "https://streamed.pk/api"
WEBSITE = "https://venomtv.vercel.app"
CHANNEL = "@hdhubsports"

def get_matches():
    url = f"{API_BASE}/matches/all-today"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()

def create_post(match):
    title = match.get("title", "Sports Match")
    category = match.get("category", "sports")
    match_id = match.get("id", "")

    hashtags = {
        word.strip()
        for word in title.replace("vs", " ").replace("VS", " ").split()
        if word.isalnum()
    }

    tags = " ".join(
        "#" + tag for tag in list(hashtags)[:5]
    )

    return (
        f"🏆 {title}\n\n"
        f"🏅 Sport: {category.title()}\n\n"
        f"📺 Match details and viewing options:\n"
        f"{WEBSITE}\n\n"
        f"{tags} #VenomTV"
    )

def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    matches = get_matches()
    print(f"Found {len(matches)} matches")

    for match in matches:
        print(create_post(match))
        print("-" * 30)

if __name__ == "__main__":
    main()
