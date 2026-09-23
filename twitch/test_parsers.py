"""Offline tests: ref parsing and the normalizers against raw gql.twitch.tv
responses captured 2026-09-23 (twitch/fixtures/*.json, *.m3u8).

    python -m pytest twitch/test_parsers.py -q
"""
import json
import os

import pytest

from twitch import parsers as P
from twitch import refs
from twitch import schemas

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name + ".json")) as f:
        return json.load(f)


def text_fx(name):
    with open(os.path.join(FIX, name)) as f:
        return f.read()


def _no_camel_or_url_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            assert key != "__typename"
            _no_camel_or_url_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_camel_or_url_keys(value, f"{path}[{i}]")


# ---- refs -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("xqc", {"login": "xqc"}), ("@xQc", {"login": "xqc"}), ("71092938", {"id": "71092938"}),
    ("https://www.twitch.tv/xqc", {"login": "xqc"}), ("https://www.twitch.tv/XQC/videos?filter=archives", {"login": "xqc"}),
    ("twitch.tv/popout/xqc/chat", {"login": "xqc"}), ("https://m.twitch.tv/xqc", {"login": "xqc"}),
    ("https://player.twitch.tv/?channel=xqc&parent=example.com", {"login": "xqc"}),
])
def test_resolve_channel(value, expected):
    assert refs.resolve_channel(value) == expected


@pytest.mark.parametrize("value", ["https://kick.com/xqc", "https://www.twitch.tv/videos/123",
                                   "https://www.twitch.tv/directory", "x q c", "", "a" * 30])
def test_resolve_channel_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_channel(value)


def test_resolve_channels():
    out = refs.resolve_channels("xqc, https://www.twitch.tv/kaicenat ,71092938,XQC")
    assert out == [{"login": "xqc"}, {"login": "kaicenat"}, {"id": "71092938"}]
    with pytest.raises(ValueError):
        refs.resolve_channels(",".join(f"user{i}" for i in range(101)))
    with pytest.raises(ValueError):
        refs.resolve_channels(" , ")


@pytest.mark.parametrize("value, expected", [
    ("Just Chatting", {"name": "Just Chatting"}), ("just-chatting", {"slug": "just-chatting"}),
    ("509658", {"id": "509658"}), ("Fortnite", {"name": "Fortnite"}),
    ("https://www.twitch.tv/directory/category/just-chatting/videos", {"slug": "just-chatting"}),
    ("https://www.twitch.tv/directory/game/Just%20Chatting", {"name": "Just Chatting"}),
])
def test_resolve_game(value, expected):
    assert refs.resolve_game(value) == expected


@pytest.mark.parametrize("value", ["https://www.twitch.tv/xqc", "", "https://kick.com/category/irl"])
def test_resolve_game_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_game(value)


@pytest.mark.parametrize("value, expected", [
    ("AmericanGentleHedgehogImGlitch-F4NBRoJ29jNLNtQa", "AmericanGentleHedgehogImGlitch-F4NBRoJ29jNLNtQa"),
    ("https://clips.twitch.tv/AmericanGentleHedgehogImGlitch-F4NBRoJ29jNLNtQa?tt_content=x", "AmericanGentleHedgehogImGlitch-F4NBRoJ29jNLNtQa"),
    ("https://www.twitch.tv/xqc/clip/Abc-123", "Abc-123"),
    ("https://clips.twitch.tv/embed?clip=Abc-123&parent=x", "Abc-123"),
])
def test_resolve_clip(value, expected):
    assert refs.resolve_clip(value) == expected


@pytest.mark.parametrize("value", ["https://www.twitch.tv/xqc", "", "a b", "https://clips.twitch.tv/embed"])
def test_resolve_clip_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_clip(value)


@pytest.mark.parametrize("value, expected", [
    ("2880410519", "2880410519"), ("v2880410519", "2880410519"),
    ("https://www.twitch.tv/videos/2880410519?t=1h2m", "2880410519"),
    ("https://player.twitch.tv/?video=v2880410519&parent=x", "2880410519"),
    ("https://m.twitch.tv/videos/2880410519", "2880410519"),
])
def test_resolve_video(value, expected):
    assert refs.resolve_video(value) == expected


@pytest.mark.parametrize("value", ["abc", "https://www.twitch.tv/xqc", "", "https://youtube.com/watch?v=1"])
def test_resolve_video_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_video(value)


def test_resolve_team():
    assert refs.resolve_team("OTK") == "otk"
    assert refs.resolve_team("https://www.twitch.tv/team/otk") == "otk"
    with pytest.raises(ValueError):
        refs.resolve_team("https://www.twitch.tv/otk")


# ---- schemas ----------------------------------------------------------------------------

def test_schema_defaults_and_mapping():
    data = schemas.ChannelClipsSchema().load({"channel": "xqc"})
    assert data == {"channel": {"login": "xqc"}, "period": "LAST_WEEK", "sort": "VIEWS_DESC", "limit": 20, "cursor": None}
    data = schemas.StreamsSchema().load({"languages": "EN, de,en", "tags": "Vtuber,ASMR", "sort": "Recent", "limit": "30"})
    assert data["languages"] == ["en", "de"] and data["tags"] == ["Vtuber", "ASMR"]
    assert data["sort"] == "RECENT" and data["limit"] == 30
    data = schemas.VideoChatSchema().load({"video": "https://www.twitch.tv/videos/2880410519", "offset": "600"})
    assert data == {"video": "2880410519", "offset": 600, "cursor": None}


@pytest.mark.parametrize("schema, query", [
    (schemas.StreamsSchema, {"limit": "31"}),
    (schemas.StreamsSchema, {"foo": "bar"}),
    (schemas.StreamsSchema, {"tags": "two words"}),
    (schemas.ChannelVideosSchema, {"channel": "xqc", "type": "nope"}),
    (schemas.VideoChatSchema, {"video": "1", "offset": "1", "cursor": "x"}),
    (schemas.ChannelsSchema, {"channels": ""}),
])
def test_schema_rejects(schema, query):
    from marshmallow import ValidationError
    with pytest.raises(ValidationError):
        schema().load(query)


# ---- value helpers ------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("2026-09-21T19:16:27.033Z", "2026-09-21T19:16:27Z"),
    ("2014-09-12T23:50:05.989719Z", "2014-09-12T23:50:05Z"),
    ("2018-11-14T22:54:33.712283178Z", "2018-11-14T22:54:33Z"),
    ("2026-09-21T19:06:27Z", "2026-09-21T19:06:27Z"),
    ("0001-01-01T00:00:00Z", None), (None, None), ("junk", None),
])
def test_iso_datetime(value, expected):
    assert P.iso_datetime(value) == expected


def test_duration_and_image():
    assert P.duration_text(37813) == "10:30:13" and P.duration_text(33) == "0:33" and P.duration_text(None) is None
    assert P.image("https://x/{width}x{height}.jpg", 285, 380) == "https://x/285x380.jpg"
    assert P.image("https://x/{width}x{height}.jpg") is None
    assert P.language("EN") == {"code": "en", "name": "English"} and P.language(None) is None


def test_page_cursor_semantics():
    conn = {"edges": [{"cursor": "a", "node": {}}, {"cursor": "b", "node": {}}], "pageInfo": {"hasNextPage": True}}
    out = P.page(conn, [1, 2], "rows")
    assert out == {"count": 2, "rows": [1, 2], "next_cursor": "b", "has_more": True}
    conn["pageInfo"]["hasNextPage"] = False
    assert P.page(conn, [1, 2], "rows")["next_cursor"] is None
    # clip connections: the first edge carries a null cursor
    conn = {"edges": [{"cursor": None, "node": {}}, {"cursor": "Mg==", "node": {}}], "pageInfo": {"hasNextPage": True}}
    assert P.page(conn, [1, 2], "rows")["next_cursor"] == "Mg=="
    assert P.page(None, [], "rows") == {"count": 0, "rows": [], "next_cursor": None, "has_more": False}


# ---- channels ------------------------------------------------------------------------------

def test_channel_details_offline():
    out = P.channel_details(fx("channel_details")["user"])
    _no_camel_or_url_keys(out)
    assert out["id"] == "71092938" and out["login"] == "xqc" and out["username"] == "xQc"
    assert out["link"] == "https://www.twitch.tv/xqc"
    assert out["is_partner"] is True and out["is_affiliate"] is False and out["is_live"] is False
    assert out["followers_count"] > 12_000_000 and out["videos_count"] > 0
    assert out["accent_color"] == "#FFBF00" and out["language"] == {"code": "en", "name": "English"}
    assert out["created_at"] == "2014-09-12T23:50:05Z"
    assert out["broadcast_settings"]["game"]["slug"] == "just-chatting"
    assert out["last_broadcast"]["started_at"].endswith("Z")
    assert out["livestream"] is None and out["team"] is None
    assert [s["platform"] for s in out["socials"]] == ["twitter", "discord", "reddit", "youtube"]
    assert out["panels"] and out["panels"][0]["image"].startswith("https://panels.twitch.tv/")
    assert out["chat_settings"]["is_followers_only"] is True and out["chat_settings"]["followers_only_minutes"] == 1440
    assert out["chat_settings"]["rules"] == ["English please", "Fresh memes"]
    order = list(out)
    assert order[:4] == ["id", "login", "username", "link"] and order[-2:] == ["created_at", "updated_at"]


def test_channel_details_live():
    out = P.channel_details(fx("channel_details_live")["user"])
    _no_camel_or_url_keys(out)
    live = out["livestream"]
    assert out["is_live"] is True and live["viewers_count"] > 1000 and live["uptime_seconds"] >= 0
    assert live["game"]["name"] == "Dota 2" and live["language"]["code"] == "ru"
    assert live["encoding"] == {"width": 2560, "height": 1440, "fps": 60, "bitrate_kbps": 9119,
                                "codec": "hev1.1.6.L150.90.0.0.0.0.0"}
    assert "channel" not in live and live["tags"] == ["Русский"]


def test_channel_status_rows():
    rows = [u for u in fx("channels_status")["users"]]
    assert rows[2] is None                     # unknown login -> null slot
    live = P.channel_status(rows[1])
    assert live["is_live"] is True and live["livestream"]["viewers_count"] > 0 and "channel" not in live["livestream"]
    offline = P.channel_status(rows[0])
    assert offline["is_live"] is False and offline["livestream"] is None and offline["last_broadcast"]["started_at"]


def test_videos_clips_lists():
    user = fx("channel_videos")["user"]
    rows = [P.without_channel(P.video(n)) for n in P.nodes(user["videos"])]
    _no_camel_or_url_keys(rows)
    assert len(rows) == 5 and rows[0]["type"] == "archive" and rows[0]["duration"] and rows[0]["link"].startswith("https://www.twitch.tv/videos/")
    assert rows[0]["view_count"] > 0 and rows[0]["published_at"].endswith("Z") and "channel" not in rows[0]
    page = P.page(user["videos"], rows, "videos")
    assert page["total_count"] == 49 and page["next_cursor"] and page["has_more"] is True
    user = fx("channel_clips")["user"]
    rows = [P.without_channel(P.clip(n)) for n in P.nodes(user["clips"])]
    _no_camel_or_url_keys(rows)
    assert rows[0]["slug"] and rows[0]["link"].startswith("https://www.twitch.tv/xqc/clip/")
    assert rows[0]["source_video"]["offset_seconds"] > 0 and rows[0]["curator"]["login"]
    assert P.page(user["clips"], rows, "clips")["next_cursor"] == "NQ=="


def test_schedule_goals_points_emotes():
    sched = P.schedule(fx("channel_schedule")["user"]["channel"])
    _no_camel_or_url_keys(sched)
    assert sched["count"] == 13 and sched["segments"][0]["starts_at"] == "2026-09-21T12:00:00Z"
    assert P.schedule({"schedule": None}) is None
    goals = [P.goal(n) for n in P.nodes(fx("channel_goals")["user"]["channel"]["goals"])]
    _no_camel_or_url_keys(goals)
    assert goals[0]["type"] == "sub_points" and goals[0]["state"] == "finished" and goals[0]["progress_percent"] == 100.0
    points = P.channel_points(fx("channel_points")["user"]["channel"])
    _no_camel_or_url_keys(points)
    assert points["is_enabled"] is True and points["rewards"][0]["cost"] <= points["rewards"][-1]["cost"]
    assert points["unlockable_emotes"][0]["code"] == "xqcA" and points["unlockable_emotes"][0]["image"].endswith("/3.0")
    user = fx("channel_emotes")["user"]
    tiers = P.subscription_products(user["subscriptionProducts"])
    _no_camel_or_url_keys(tiers)
    assert tiers[0]["tier"] == 1 and tiers[0]["emotes"][0]["code"].startswith("xqc")
    assert P.cheermotes(user["cheer"])[0]["prefix"] == "Charity"
    assert P.badge(user["broadcastBadges"][0])["set_id"] == "bits"


def test_chatters_vips_viewer_card():
    block = fx("channel_chatters")["user"]["channel"]["chatters"]
    out = P.chatters(block)
    _no_camel_or_url_keys(out)
    assert out["total_count"] > 0 and out["broadcasters"] and out["listed_count"] > len(out["moderators"])
    card = P.viewer_card(fx("viewer_card"))
    _no_camel_or_url_keys(card)
    assert card["user"]["login"] == "elias940" and card["channel"]["login"] == "xqc"
    assert card["is_subscriber"] is True and card["subscriber_months"] == 6 and card["badges_count"] == 10
    assert P.viewer_card({"channelViewer": None, "user": None}) is None


def test_chat_settings_partial():
    out = P.chat_settings(None)
    assert out["is_slow_mode"] is False and out["rules"] == [] and out["is_followers_only"] is False


# ---- directory / search --------------------------------------------------------------------

def test_streams_games_directory():
    rows = [P.stream(n) for n in P.nodes(fx("streams")["streams"])]
    _no_camel_or_url_keys(rows)
    assert rows and rows[0]["channel"]["login"] and rows[0]["viewers_count"] >= rows[-1]["viewers_count"]
    assert rows[0]["language"]["code"] == "en" and "Vtuber" in [t for r in rows for t in r["tags"]]
    games = [P.game_card(n) for n in P.nodes(fx("games")["games"])]
    _no_camel_or_url_keys(games)
    assert games[0]["name"] == "Just Chatting" and games[0]["tags"] == ["IRL"] and games[0]["box_art"].endswith("285x380.jpg")
    details = P.game_details(fx("game_details")["game"])
    _no_camel_or_url_keys(details)
    assert details["release_date"] == "2020-06-29" and details["developers"] == ["Epic Games"]
    assert details["live_channels_count"] > 0 and details["logo"].endswith("240x320.jpg")
    assert list(details)[:4] == ["id", "name", "slug", "link"]


def test_search_and_suggest():
    found = fx("search_all")["searchFor"]
    rows = [P.search_channel(e["item"]) for e in found["channels"]["edges"]]
    _no_camel_or_url_keys(rows)
    assert rows[0]["login"] == "minecraft" and rows[0]["followers_count"] > 0 and rows[0]["is_live"] is False
    videos = [P.video(e["item"]) for e in fx("search_videos")["searchFor"]["videos"]["edges"]]
    assert videos and videos[0]["channel"]["login"]
    sugg = [P.suggestion(n) for n in P.nodes(fx("search_suggest")["searchSuggestions"])]
    _no_camel_or_url_keys(sugg)
    assert sugg[0]["type"] == "game" and sugg[0]["game"]["box_art"].endswith("285x380.jpg")
    assert {s["type"] for s in sugg} <= {"game", "channel", "query"}
    games = [P.game_card(n) for n in P.nodes(fx("search_games")["searchCategories"])]
    assert games[0]["name"] == "Minecraft"


def test_tags_and_badges():
    tags = [n["tagName"] for n in P.nodes(fx("tags_search")["searchFreeformTags"])]
    assert "Vtuber" in tags
    badges = [P.badge(b) for b in fx("global_badges")["badges"]]
    _no_camel_or_url_keys(badges)
    assert len(badges) > 400 and badges[0]["set_id"] and badges[0]["image"].startswith("https://")


# ---- videos / clips / teams / playback -------------------------------------------------------

def test_video_details_and_chat():
    out = P.video_details(fx("video_details")["video"])
    _no_camel_or_url_keys(out)
    assert out["type"] == "archive" and out["status"] == "recorded" and out["duration"] == "10:30:13"
    assert out["chapters"][1]["game"]["name"] == "Grand Theft Auto V" and out["chapters"][1]["start_seconds"] == 2435
    assert out["storyboard_link"].endswith("-info.json") and out["is_restricted"] is False
    assert list(out)[:3] == ["id", "title", "link"]
    msgs = [P.chat_message(n) for n in P.nodes(fx("video_chat")["video"]["comments"])]
    _no_camel_or_url_keys(msgs)
    assert msgs[0]["offset_seconds"] == 599 and msgs[0]["offset"] == "9:59" and msgs[0]["text"] == "MVP U"
    assert msgs[0]["user"]["badges"] == [{"set_id": "premium", "version": "1"}]   # the empty badge is dropped
    assert all(m["sent_at"].endswith("Z") for m in msgs)
    emote = P.chat_message({"message": {"fragments": [{"text": "xqcL", "emote": {"id": "x", "emoteID": "555"}}]}})
    assert emote["emotes"][0]["image"].endswith("/555/default/dark/3.0") and emote["fragments"][0]["type"] == "emote"


def test_clip_details():
    out = P.clip_details(fx("clip_details")["clip"])
    _no_camel_or_url_keys(out)
    assert out["videos"][0]["quality"] == "1080" and out["videos"][0]["download_link"].count("sig=") == 1
    assert "token=" in out["videos"][0]["download_link"]
    assert out["source_video"]["title"] and out["source_video"]["offset_seconds"] == 38187
    assert out["playback"]["is_forbidden"] is False and out["embed_link"].startswith("https://clips.twitch.tv/embed")
    assert out["channel"]["followers_count"] > 0 and out["curator"]["login"] == "elias940"


def test_team():
    out = P.team(fx("team_details")["team"])
    _no_camel_or_url_keys(out)
    assert out["name"] == "otk" and out["members_count"] == 5 and out["link"] == "https://www.twitch.tv/team/otk"
    assert out["members"][0]["login"] and "livestream" in out["members"][0]


def test_hls_variants_and_playback():
    live = P.hls_variants(text_fx("live_playlist.m3u8"))
    video = [v for v in live if not v["is_audio_only"]]
    assert video and video[0]["height"] >= video[-1]["height"] and live[-1]["is_audio_only"] is True
    assert all(v["link"].startswith("https://") for v in live)
    vod = P.hls_variants(text_fx("vod_playlist.m3u8"))
    assert vod[0]["name"] == "1080p60" and vod[0]["is_source"] is True and vod[0]["frame_rate"] == 60.0
    assert vod[0]["codecs"].startswith("avc1") and vod[0]["bandwidth_kbps"] > 1000
    token = fx("video_playback_token")["videoPlaybackAccessToken"]
    out = P.playback(token, "https://usher.ttvnw.net/vod/2880410519.m3u8", text_fx("vod_playlist.m3u8"))
    _no_camel_or_url_keys(out)
    assert out["expires_at"].endswith("Z") and out["is_forbidden"] is False and out["qualities_count"] == len(vod)
    assert P.hls_variants("") == [] and P.hls_variants(None) == []


# ---- robustness --------------------------------------------------------------------------------

def test_parsers_survive_partial_input():
    assert P.stream({}) ["viewers_count"] is None and P.stream(None) is None
    assert P.video({"id": "1"})["link"] == "https://www.twitch.tv/videos/1"
    assert P.clip({"slug": "x"})["link"] == "https://clips.twitch.tv/x"
    assert P.channel_ref({}) ["login"] is None and P.game_ref(None) is None
    assert P.channel_details({"id": "1", "login": "a"})["login"] == "a"
    assert P.channel_status({"id": "1"})["is_live"] is False
    assert P.chatters(None)["total_count"] is None
    assert P.channel_points({}) is None and P.channel_points({"communityPointsSettings": {}})["rewards"] == []
    assert P.subscription_products(None) == [] and P.cheermotes(None) == [] and P.panels(None) == []
    assert P.team({})["members"] == [] and P.video_details({"id": "1"})["chapters"] == []
    assert P.clip_details({"slug": "x", "videoQualities": [None, {"quality": "480"}]})["videos"][0]["link"] is None
    assert P.chat_message({})["user"] is None and P.suggestion({})["type"] == "query"
    assert P.goal({})["progress_percent"] is None and P.reward({})["cost"] is None
