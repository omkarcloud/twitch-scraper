"""Live endpoint smoke tests: one call per /twitch/* route against a running
service, with example values proven to return data (2026-09-23). The
listing tooling reads each route's FIRST call from this file's AST as its
working example, so the values stay literals.

Skipped unless TWITCH_BASE points at a running service:

    ONLY_SCRAPER=twitch python run.py
    TWITCH_BASE=http://127.0.0.1:6002 python -m pytest twitch/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("TWITCH_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set TWITCH_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def _live_login():
    return call("/twitch/streams", limit=1)["streams"][0]["channel"]["login"]


def test_channels():
    details = call("/twitch/channels/details", channel="xqc")["channel"]
    assert details["followers_count"] > 1_000_000 and details["panels"] and details["socials"]
    assert call("/twitch/channels/details", channel="https://www.twitch.tv/xqc/videos")["channel"]["login"] == "xqc"
    assert call("/twitch/channels/details", channel="71092938")["channel"]["login"] == "xqc"
    assert "is_live" in call("/twitch/channels/status", channel="xqc")["channel"]
    batch = call("/twitch/channels/status/batch", channels="xqc,kaicenat,71092938,zzzz_not_a_user_9999")
    assert batch["count"] == 4 and batch["channels"][3]["error"] == "not found"
    videos = call("/twitch/channels/videos", channel="xqc", type="archive", sort="time", limit=3)
    assert videos["videos"] and videos["next_cursor"]
    assert call("/twitch/channels/videos", channel="xqc", limit=3, cursor=videos["next_cursor"])["videos"]
    clips = call("/twitch/channels/clips", channel="xqc", period="month", sort="views", limit=3)
    assert clips["clips"][0]["source_video"] and clips["next_cursor"]
    assert call("/twitch/channels/clips", channel="xqc", period="month", sort="views", limit=3, cursor=clips["next_cursor"])["clips"]
    assert call("/twitch/channels/schedule", channel="cohhcarnage")["schedule"]["segments"]
    assert call("/twitch/channels/panels", channel="xqc")["panels"]
    assert "goals" in call("/twitch/channels/goals", channel="kaicenat")
    assert call("/twitch/channels/chat-settings", channel="xqc")["chat_settings"]["rules"]
    assert call("/twitch/channels/points", channel="xqc")["channel_points"]["rewards"]
    assert call("/twitch/channels/emotes", channel="xqc")["subscription_tiers"][0]["emotes"]
    assert call("/twitch/channels/vips", channel="xqc")["vips"]
    assert call("/twitch/channels/chatters", channel="xqc")["total_count"] >= 0
    card = call("/twitch/channels/viewer-card", channel="xqc", user="elias940")
    assert card["user"]["login"] == "elias940" and "is_subscriber" in card
    call("/twitch/channels/details", status=404, channel="zzzz_not_a_user_9999")


def test_playback_live():
    login = _live_login()
    out = call("/twitch/channels/playback", channel=login)
    assert out["is_live"] is True and out["qualities"][0]["link"].startswith("https://")
    assert call("/twitch/channels/chatters", channel=login)["total_count"] > 0


def test_directory():
    page = call("/twitch/streams", sort="viewers", languages="en", limit=3)
    assert page["streams"][0]["viewers_count"] > 0 and page["next_cursor"]
    assert call("/twitch/streams", limit=3, cursor=page["next_cursor"])["streams"]
    assert call("/twitch/streams", tags="Vtuber", limit=2)["streams"]
    games = call("/twitch/games", limit=5)
    assert games["games"][0]["viewers_count"] > 0 and games["next_cursor"]
    assert call("/twitch/games/details", game="Just Chatting")["game"]["id"] == "509658"
    assert call("/twitch/games/details", game="https://www.twitch.tv/directory/category/just-chatting")["game"]["slug"] == "just-chatting"
    assert call("/twitch/games/streams", game="just-chatting", languages="en", limit=3)["streams"]
    assert call("/twitch/games/videos", game="just-chatting", type="archive", sort="views", limit=3)["videos"]
    assert call("/twitch/games/clips", game="fortnite", period="week", sort="views", limit=3)["clips"]
    assert "Vtuber" in call("/twitch/tags/search", query="vtub")["tags"]
    assert call("/twitch/badges")["count"] > 300
    call("/twitch/games/details", status=404, game="zzz-not-a-game-9999")


def test_search():
    out = call("/twitch/search", query="minecraft", limit=3)
    assert out["channels"] and out["games"]
    page = call("/twitch/search/channels", query="minecraft", limit=3)
    assert page["channels"] and page["next_cursor"]
    assert call("/twitch/search/channels", query="minecraft", limit=3, cursor=page["next_cursor"])["channels"]
    assert call("/twitch/search/games", query="minecraft", limit=3)["games"][0]["name"] == "Minecraft"
    assert call("/twitch/search/videos", query="speedrun", limit=3)["videos"]
    assert call("/twitch/search/suggest", query="minec")["suggestions"]


def test_videos_clips_teams():
    video = call("/twitch/videos/details", video="2880410519")["video"]
    assert video["chapters"] and video["duration_seconds"] > 0
    assert call("/twitch/videos/details", video="https://www.twitch.tv/videos/2880410519?t=1h")["video"]["id"] == "2880410519"
    chat = call("/twitch/videos/chat", video="2880410519", offset=600)
    assert chat["messages"] and chat["next_cursor"]
    assert call("/twitch/videos/chat", video="2880410519", cursor=chat["next_cursor"])["messages"]
    assert call("/twitch/videos/playback", video="2880410519")["qualities"]
    clip = call("/twitch/clips/details", clip="AmericanGentleHedgehogImGlitch-F4NBRoJ29jNLNtQa")["clip"]
    assert clip["videos"][0]["download_link"] and clip["source_video"]["id"]
    assert call("/twitch/teams/details", team="otk")["team"]["members"]
    call("/twitch/videos/details", status=404, video="1")
    call("/twitch/clips/details", status=404, clip="nope-zzz-9999")
    call("/twitch/streams", status=400, limit=31)
    call("/twitch/streams", status=400, foo="bar")
