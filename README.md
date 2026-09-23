# 🎮 Twitch Scraper

Twitch Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Twitch data for free.

## ✨ What Can I Get?

- 📺 **Full profile of any Twitch channel in 1 call** — followers, bio, socials, panels, team, live stream & chat rules
- 🔴 **Live status for 100 channels per call** — viewers, uptime, title, game, tags & stream quality, plus the whole live directory
- 🎬 **Clips & VODs with download links** — MP4s in every quality, chapter markers and full chat replay
- 🎮 **Categories, search & channel extras** — top games by viewers, schedules, goals, channel points, emotes & VIPs

## 🎥 Example: A Full Twitch Channel

```json
{
  "channel": {
    "id": "641972806",
    "login": "kaicenat",
    "username": "KaiCenat",
    "link": "https://www.twitch.tv/kaicenat",
    "profile_image": "https://static-cdn.jtvnw.net/jtv_user_pictures/bf6a04cf-3f44-4986-8eed-5c36bfad542b-profile_image-600x600.png",
    "language": { "code": "en", "name": "English" },
    "is_live": false,
    "is_partner": true,
    "followers_count": 21771319,
    "videos_count": 183,
    "broadcast_settings": {
      "title": "🇮🇸EXPLORING ICELAND🇮🇸[Exploring The Unexplored]",
      "game": { "id": "509672", "name": "IRL", "link": "https://www.twitch.tv/directory/category/irl" }
    },
    "last_broadcast": { "id": "320337261020", "started_at": "2026-09-16T08:01:52Z" },
    "socials": [
      { "platform": "instagram", "link": "https://www.instagram.com/kaicenat/?hl=en" },
      { "platform": "youtube", "link": "https://www.youtube.com/c/KaiCenat" }
    ],
    "panels": [
      { "title": "SUBSCRIBE", "description": "Subcribe Now!", "link": "https://www.twitch.tv/products/imkaicenat" }
    ],
    "chat_settings": { "is_followers_only": true, "followers_only_minutes": 10, "is_slow_mode": false },
    "created_at": "2021-01-27T01:55:08Z"
  }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Twitch Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/twitch-scraper
cd twitch-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/channels/details?channel=kaicenat"
```

```json
{
  "channel": {
    "id": "641972806",
    "login": "kaicenat",
    "username": "KaiCenat",
    "link": "https://www.twitch.tv/kaicenat",
    "is_live": false,
    "is_partner": true,
    "followers_count": 21771320,
    "videos_count": 183,
    "broadcast_settings": {
      "title": "🇮🇸EXPLORING ICELAND🇮🇸[Exploring The Unexplored]",
      "game": {
        "name": "IRL"
      }
    },
    "socials": [
      {
        "platform": "instagram",
        "link": "https://www.instagram.com/kaicenat/?hl=en"
      }
    ],
    "created_at": "2021-01-27T01:55:08Z"
  }
}
```

All 33 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

33 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Channel Details | `/channels/details` | Everything about one channel in a single call |
| Search / Suggestions | `/search`, `/search/suggest` | Channels, categories and videos for any query, plus autocomplete |
| Search Channels / Categories / Videos | `/search/channels`, `/search/games`, `/search/videos` | One index at a time, with cursor paging |
| Channel Live Status / Bulk | `/channels/status`, `/channels/status/batch` | Live or not, viewers and uptime — up to 100 channels per call |
| Channel Videos / Clips | `/channels/videos`, `/channels/clips` | VODs and top clips, 100 per page, sorted how you like |
| Clip Details | `/clips/details` | MP4 download links in every quality, plus the source VOD |
| Video Details / Chat / Playback | `/videos/details`, `/videos/chat`, `/videos/playback` | Chapters, full chat replay and signed HLS links for any VOD |
| Top Live Streams | `/streams` | The live directory, filtered by language and tags |
| Top Categories / Category Details | `/games`, `/games/details` | Games ranked by viewers; one category's full stats |
| Category Streams / Videos / Clips | `/games/streams`, `/games/videos`, `/games/clips` | Everything live or recorded in one category |
| Search Tags | `/tags/search` | Stream tags ready for the `tags` filter |
| Channel Schedule / Panels / Goals | `/channels/schedule`, `/channels/panels`, `/channels/goals` | Weekly schedule, About panels and follower/sub goals |
| Chat Settings / Points / Emotes / VIPs | `/channels/chat-settings`, `/channels/points`, `/channels/emotes`, `/channels/vips` | Chat rules, rewards with costs, emotes per tier and VIP list |
| Channel Chatters / Viewer Card | `/channels/chatters`, `/channels/viewer-card` | Who is in chat now; one viewer's sub months and badges |
| Live Playback Links | `/channels/playback` | Signed HLS playlist with every quality of a live stream |
| Team Details / Global Chat Badges | `/teams/details`, `/badges` | Team members with live status; every global badge |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-twitch-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-twitch-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-twitch-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/channels/details",
    params={"channel": "kaicenat"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Twitch Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Twitch%20Scraper%20API.)

[![Ask Us by Email about Twitch Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Twitch%20Scraper%20API&body=I%20need%20help%20using%20the%20Twitch%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**Kick Scraper**](https://github.com/omkarcloud/kick-scraper) — Kick channels, live streams, chat, clips & VODs
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/twitch-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/twitch-scraper)
