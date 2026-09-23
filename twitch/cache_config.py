"""Cache TTL per /twitch/* endpoint (cache.py, keyed on the validated params).

Tiers follow how fast Twitch moves each surface: a live viewer count
changes every few seconds, a finished VOD or clip never changes again, the
global badge set changes a few times a month.
"""
from datetime import timedelta

# --- live surfaces -----------------------------------------------------------
LIVE_CACHE = timedelta(seconds=30)        # live status, chatters
DIRECTORY_CACHE = timedelta(seconds=45)   # top streams / games, streams in a category
# --- channel -----------------------------------------------------------------
CHANNEL_CACHE = timedelta(minutes=5)      # profile, panels, socials, schedule
SETTINGS_CACHE = timedelta(minutes=2)     # chat settings, goals, channel points, VIPs, viewer card
EMOTES_CACHE = timedelta(hours=1)
# --- videos / clips ----------------------------------------------------------
VIDEOS_CACHE = timedelta(minutes=5)
VIDEO_CACHE = timedelta(minutes=30)
CHAT_CACHE = timedelta(hours=6)           # a VOD's chat replay is immutable
CLIPS_CACHE = timedelta(minutes=5)
CLIP_CACHE = timedelta(minutes=30)
# --- catalogues / search -----------------------------------------------------
GAME_CACHE = timedelta(minutes=5)
SEARCH_CACHE = timedelta(minutes=5)
SUGGEST_CACHE = timedelta(minutes=10)
TAGS_CACHE = timedelta(hours=1)
BADGES_CACHE = timedelta(hours=12)
TEAM_CACHE = timedelta(minutes=2)
