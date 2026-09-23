"""One param per input (tripadvisor QueryOrIdField convention): every
resolver takes a bare id/login/slug OR any twitch.tv link and hands back
what the GraphQL documents need. Each raises ValueError with a user-facing
message; schemas.py wraps them as RefField subclasses.

    resolve_channel   "xqc" | "@xQc" | "71092938" | https://www.twitch.tv/xqc/videos
                      -> {"login": "xqc"} | {"id": "71092938"}
    resolve_channels  comma list of the above (max 100)
    resolve_game      "Just Chatting" | "just-chatting" | "509658"
                      | https://www.twitch.tv/directory/category/just-chatting
                      -> {"name": ...} | {"slug": ...} | {"id": ...}
    resolve_clip      slug | https://clips.twitch.tv/<slug> | twitch.tv/<login>/clip/<slug>
    resolve_video     "2880410519" | "v2880410519" | https://www.twitch.tv/videos/2880410519?t=1h2m
    resolve_team      "otk" | https://www.twitch.tv/team/otk
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

SITE = "https://www.twitch.tv"
CLIPS_SITE = "https://clips.twitch.tv"

_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{0,24}$")
_ID_RE = re.compile(r"^\d{1,20}$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CLIP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,150}$")
_TEAM_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")

_TWITCH_HOSTS = ("twitch.tv", "www.twitch.tv", "m.twitch.tv", "player.twitch.tv",
                 "clips.twitch.tv", "dashboard.twitch.tv", "go.twitch.tv")
# first path segments that are pages, never channel logins
_RESERVED = {"directory", "videos", "video", "settings", "downloads", "p", "jobs", "turbo", "prime",
             "team", "products", "popout", "embed", "moderator", "subscriptions", "inventory",
             "drops", "wallet", "friends", "search", "login", "signup", "u", "clip", "collections",
             "events", "broadcast", "user", "messages", "creatorcamp", "store", "bits", "partner"}


def _is_url(value):
    low = value.lower()
    return low.startswith(("http://", "https://", "//")) or any(
        low.startswith(h + "/") or low == h for h in _TWITCH_HOSTS)


def _parts(value):
    """A twitch link -> (host, [path segments], query dict). ValueError for other sites."""
    raw = value if value.lower().startswith(("http://", "https://")) else \
        ("https:" + value if value.startswith("//") else "https://" + value)
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in _TWITCH_HOSTS and not host.endswith(".twitch.tv"):
        raise ValueError("must be a twitch.tv link")
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    query = {k: v for k, v in parse_qs(parsed.query).items()}
    return host, segments, query


def _login(value):
    value = value.lstrip("@").strip()
    if not _LOGIN_RE.match(value):
        raise ValueError("channel must be a Twitch login (xqc), a numeric user id or a twitch.tv channel link")
    return value.lower()


def resolve_channel(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("channel is required")
    if _is_url(value):
        try:
            host, segments, query = _parts(value)
        except ValueError:
            raise ValueError("channel must be a Twitch login, a numeric user id or a twitch.tv channel link")
        if host == "player.twitch.tv" and query.get("channel"):
            return {"login": _login(query["channel"][0])}
        if not segments:
            raise ValueError("channel link must look like https://www.twitch.tv/xqc")
        first = segments[0].lower()
        if first in ("popout", "embed", "moderator") and len(segments) >= 2:
            return {"login": _login(segments[1])}
        if first in _RESERVED or host == "clips.twitch.tv":
            raise ValueError("channel link must look like https://www.twitch.tv/xqc (that link is not a channel page)")
        return {"login": _login(segments[0])}
    if _ID_RE.match(value):
        return {"id": value}
    return {"login": _login(value)}


def resolve_channels(value, max_items=100):
    out, seen = [], set()
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        ref = resolve_channel(raw)
        key = tuple(sorted(ref.items()))
        if key not in seen:
            seen.add(key)
            out.append(ref)
    if not out:
        raise ValueError("channels is required")
    if len(out) > max_items:
        raise ValueError(f"at most {max_items} channels")
    return out


def resolve_game(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("game is required")
    if _is_url(value):
        try:
            _, segments, _ = _parts(value)
        except ValueError:
            raise ValueError("game must be a category name, slug, numeric id or a twitch.tv category link")
        low = [s.lower() for s in segments]
        if len(segments) >= 3 and low[0] == "directory" and low[1] in ("category", "game"):
            value = segments[2]
        elif len(segments) >= 2 and low[0] == "directory":
            value = segments[1]
        else:
            raise ValueError("game link must look like https://www.twitch.tv/directory/category/just-chatting")
    value = value.split("?")[0].split("#")[0].strip()
    if not value:
        raise ValueError("game is required")
    if _ID_RE.match(value):
        return {"id": value}
    if _SLUG_RE.match(value) and "-" in value:
        return {"slug": value}
    return {"name": value}


def resolve_clip(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("clip is required")
    if _is_url(value):
        try:
            host, segments, query = _parts(value)
        except ValueError:
            raise ValueError("clip must be a clip slug or a twitch.tv / clips.twitch.tv clip link")
        candidate = None
        if query.get("clip"):
            candidate = query["clip"][0]
        elif host == "clips.twitch.tv" and segments and segments[0].lower() != "embed":
            candidate = segments[0]
        else:
            for index, segment in enumerate(segments):
                if segment.lower() == "clip" and index + 1 < len(segments):
                    candidate = segments[index + 1]
                    break
        if not candidate:
            raise ValueError("clip link must look like https://clips.twitch.tv/<slug> or https://www.twitch.tv/<channel>/clip/<slug>")
        value = candidate
    value = value.split("?")[0].split("#")[0]
    if not _CLIP_RE.match(value):
        raise ValueError("clip must be a clip slug (AmericanGentleHedgehogImGlitch-F4NBRoJ29jNLNtQa) or a clip link")
    return value


def resolve_video(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("video is required")
    if _is_url(value):
        try:
            host, segments, query = _parts(value)
        except ValueError:
            raise ValueError("video must be a numeric video id or a twitch.tv video link")
        candidate = None
        if query.get("video"):
            candidate = query["video"][0]
        else:
            low = [s.lower() for s in segments]
            for index, segment in enumerate(low):
                if segment in ("videos", "video", "v") and index + 1 < len(segments):
                    candidate = segments[index + 1]
                    break
        if not candidate:
            raise ValueError("video link must look like https://www.twitch.tv/videos/2880410519")
        value = candidate
    value = value.split("?")[0].split("#")[0]
    if value[:1].lower() == "v" and _ID_RE.match(value[1:]):
        value = value[1:]
    if not _ID_RE.match(value):
        raise ValueError("video must be a numeric Twitch video id (2880410519) or a twitch.tv video link")
    return value


def resolve_team(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("team is required")
    if _is_url(value):
        try:
            _, segments, _ = _parts(value)
        except ValueError:
            raise ValueError("team must be a team name or a twitch.tv team link")
        if len(segments) >= 2 and segments[0].lower() == "team":
            value = segments[1]
        else:
            raise ValueError("team link must look like https://www.twitch.tv/team/otk")
    value = value.split("?")[0].split("#")[0]
    if not _TEAM_RE.match(value):
        raise ValueError("team must be a Twitch team name (otk) or a twitch.tv team link")
    return value.lower()


# ---- links -------------------------------------------------------------------------------

def channel_link(login):
    return f"{SITE}/{login}" if login else None


def video_link(video_id):
    return f"{SITE}/videos/{video_id}" if video_id else None


def clip_link(slug, login=None):
    if not slug:
        return None
    return f"{SITE}/{login}/clip/{slug}" if login else f"{CLIPS_SITE}/{slug}"


def game_link(slug):
    return f"{SITE}/directory/category/{slug}" if slug else None


def team_link(name):
    return f"{SITE}/team/{name}" if name else None


def user_args(ref):
    """A resolved channel ref -> the (login, id) GraphQL variables."""
    return {"login": ref.get("login"), "id": ref.get("id")}


def game_args(ref):
    return {"name": ref.get("name"), "slug": ref.get("slug"), "id": ref.get("id")}


def ref_label(ref):
    return ref.get("login") or ref.get("id") or ref.get("slug") or ref.get("name") or "?"
