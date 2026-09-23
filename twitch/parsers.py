"""Twitch normalizers: gql.twitch.tv objects -> one clean snake_case shape
per entity.

Output conventions (shared with the other scrapers here): `link` for
canonical page URLs (always absolute), `image`/`thumbnail`/`banner`/
`box_art` for pictures, `*_count` for counters, `is_*`/`has_*` for
booleans, ISO-8601 UTC ("2026-09-21T09:05:54Z") for timestamps, numbers
as numbers, null for missing. Entity refs share one vocabulary:

  channel   {id, login, username, link, profile_image, is_partner, is_affiliate}
  game      {id, name, slug, link, box_art}   (Twitch calls these "categories")
  stream    a live broadcast (viewers, uptime, game, tags, video encoding)
  video     a VOD: type archive (past broadcast) / highlight / upload / premiere
  clip      {id, slug, title, link, ..., source_video {id, offset_seconds}}

Deliberately dropped as noise: `__typename`, `cursor` on edges (surfaced
once as `next_cursor`), the `{width}x{height}` template URLs (rendered at
one size), `roles.isStaff/isGlobalMod/isSiteAdmin` (always null for other
accounts), badge base64 `id` blobs (set_id + version identify a badge),
`founderBadgeAvailability` (a count that only means something to the
channel owner), `Panel.type` (only DEFAULT panels carry data),
`chansub`/`private`/`device_id`/`user_ip` and the other player-session
fields inside the playback token (the signed token itself is returned
whole because usher needs it verbatim), the HLS `#EXT-X-TWITCH-INFO`
serving diagnostics, `emoteVariants[].isUnlockable` (always true),
`SearchSuggestion.id` (a per-request uuid).
"""
import json
import re
from datetime import datetime, timezone

from twitch import refs

_LANG_NAMES = {
    "en": "English", "es": "Spanish", "pt": "Portuguese", "de": "German", "fr": "French", "ru": "Russian",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "it": "Italian", "tr": "Turkish", "pl": "Polish",
    "nl": "Dutch", "sv": "Swedish", "fi": "Finnish", "no": "Norwegian", "da": "Danish", "cs": "Czech",
    "hu": "Hungarian", "ar": "Arabic", "th": "Thai", "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay",
    "tl": "Tagalog", "el": "Greek", "ro": "Romanian", "bg": "Bulgarian", "uk": "Ukrainian", "sk": "Slovak",
    "hi": "Hindi", "ca": "Catalan", "asl": "American Sign Language", "other": "Other", "zh-hk": "Chinese (Hong Kong)",
}


# ---- value helpers ---------------------------------------------------------------------

def to_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def to_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


def lower(value):
    value = text(value)
    return value.lower() if value else None


def iso_datetime(value):
    """'2026-09-21T19:16:27.033Z' / '2014-09-12T23:50:05.989719Z' /
    '2018-11-14T22:54:33.712283178Z' -> '2026-09-21T19:16:27Z' (UTC).
    Zero dates and junk -> None."""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.startswith(("0001-", "1970-01-01T00:00:00")):
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    # fromisoformat takes at most 6 fractional digits
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value):
    stamp = iso_datetime(value)
    return stamp[:10] if stamp else None


def seconds_since(iso):
    """Whole seconds between an ISO timestamp and now (None if unknown)."""
    if not iso:
        return None
    try:
        started = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(int((datetime.now(timezone.utc) - started).total_seconds()), 0)


def duration_text(seconds):
    """37813 -> '10:30:13'; 33 -> '0:33'."""
    seconds = to_int(seconds)
    if seconds is None:
        return None
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def image(value, width=None, height=None):
    """A CDN link, rendering Twitch's '{width}x{height}' template when the
    caller names a size."""
    value = text(value)
    if not value:
        return None
    if "{width}" in value:
        if width and height:
            value = value.replace("{width}", str(width)).replace("{height}", str(height))
        else:
            return None
    return value


def language(code):
    code = lower(code)
    if not code:
        return None
    return {"code": code, "name": _LANG_NAMES.get(code)}


def _edges(connection):
    if not isinstance(connection, dict):
        return []
    return [e for e in (connection.get("edges") or []) if isinstance(e, dict)]


def nodes(connection):
    return [e["node"] for e in _edges(connection) if isinstance(e.get("node"), dict)]


def page(connection, items, key):
    """A GraphQL connection + its parsed rows -> the list block with the
    cursor the caller passes back as `cursor`."""
    edges = _edges(connection)
    last_cursor = None
    for edge in reversed(edges):
        if text(edge.get("cursor")):
            last_cursor = edge["cursor"]
            break
    info = connection.get("pageInfo") if isinstance(connection, dict) else None
    has_more = bool_or_none((info or {}).get("hasNextPage"))
    if has_more is None:
        has_more = bool(last_cursor)
    out = {"count": len(items)}
    total = to_int(connection.get("totalCount")) if isinstance(connection, dict) else None
    if total is not None:
        out["total_count"] = total
    out[key] = items
    out["next_cursor"] = last_cursor if has_more else None
    out["has_more"] = bool(has_more and last_cursor)
    return out


# ---- refs --------------------------------------------------------------------------------

def channel_ref(user):
    if not isinstance(user, dict):
        return None
    login = lower(user.get("login"))
    roles = user.get("roles") if isinstance(user.get("roles"), dict) else {}
    out = {
        "id": text(user.get("id")),
        "login": login,
        "username": text(user.get("displayName")) or login,
        "link": refs.channel_link(login),
        "profile_image": image(user.get("profileImageURL")),
        "is_partner": bool_or_none(roles.get("isPartner")),
        "is_affiliate": bool_or_none(roles.get("isAffiliate")),
    }
    if "followers" in user:
        out["followers_count"] = to_int((user.get("followers") or {}).get("totalCount"))
    if "description" in user:
        out["bio"] = text(user.get("description"))
    return out


def game_ref(game):
    if not isinstance(game, dict):
        return None
    slug = text(game.get("slug"))
    return {
        "id": text(game.get("id")),
        "name": text(game.get("displayName")) or text(game.get("name")),
        "slug": slug,
        "link": refs.game_link(slug),
        "box_art": image(game.get("boxArtURL"), 285, 380),
    }


def game_card(game):
    out = game_ref(game)
    if out is None:
        return None
    out["viewers_count"] = to_int(game.get("viewersCount"))
    out["followers_count"] = to_int(game.get("followersCount"))
    out["tags"] = [text(t.get("localizedName")) for t in (game.get("tags") or []) if isinstance(t, dict) and text(t.get("localizedName"))]
    return out


def game_details(game):
    out = game_card(game)
    if out is None:
        return None
    out["description"] = text(game.get("description"))
    out["live_channels_count"] = to_int(game.get("broadcastersCount"))
    out["release_date"] = iso_date(game.get("originalReleaseDate"))
    out["developers"] = [text(d) for d in (game.get("developers") or []) if text(d)]
    out["publishers"] = [text(d) for d in (game.get("publishers") or []) if text(d)]
    out["logo"] = image(game.get("logoURL"), 240, 320)
    out["cover"] = image(game.get("coverURL"), 1200, 600)
    order = ["id", "name", "slug", "link", "description", "viewers_count", "live_channels_count",
             "followers_count", "tags", "release_date", "developers", "publishers", "box_art", "logo", "cover"]
    return {k: out.get(k) for k in order}


# ---- streams ----------------------------------------------------------------------------

def stream(node, channel=None):
    """A live Stream node -> the stream card. `channel` overrides the
    embedded broadcaster ref (when the caller already has a richer one)."""
    if not isinstance(node, dict):
        return None
    started = iso_datetime(node.get("createdAt"))
    tags = [text(t.get("name")) for t in (node.get("freeformTags") or []) if isinstance(t, dict) and text(t.get("name"))]
    labels = [text(t.get("id")) for t in (node.get("contentClassificationLabels") or []) if isinstance(t, dict) and text(t.get("id"))]
    encoding = None
    if any(node.get(k) is not None for k in ("averageFPS", "bitrate", "codec", "height", "width")):
        encoding = {
            "width": to_int(node.get("width")),
            "height": to_int(node.get("height")),
            "fps": to_int(node.get("averageFPS")),
            "bitrate_kbps": to_int(node.get("bitrate")),
            "codec": text(node.get("codec")),
        }
    out = {
        "id": text(node.get("id")),
        "title": text(node.get("title")),
        "viewers_count": to_int(node.get("viewersCount")),
        "started_at": started,
        "uptime_seconds": seconds_since(started),
        "type": lower(node.get("type")),
        "language": language(node.get("language")),
        "is_mature": bool_or_none(node.get("isMature")),
        "content_labels": labels,
        "tags": tags,
        "game": game_ref(node.get("game")),
        "preview_image": image(node.get("previewImageURL")),
        "encoding": encoding,
    }
    ref = channel or channel_ref(node.get("broadcaster"))
    if ref is not None:
        out["channel"] = ref
    return out


def without_channel(card):
    if isinstance(card, dict):
        card.pop("channel", None)
    return card


# ---- videos ----------------------------------------------------------------------------

_VIDEO_TYPES = {"ARCHIVE": "archive", "HIGHLIGHT": "highlight", "UPLOAD": "upload", "PREMIERE_UPLOAD": "premiere",
                "PAST_PREMIERE": "premiere"}


def video(node, channel=None):
    if not isinstance(node, dict):
        return None
    vid = text(node.get("id"))
    kind = text(node.get("broadcastType"))
    out = {
        "id": vid,
        "title": text(node.get("title")),
        "link": refs.video_link(vid),
        "description": text(node.get("description")),
        "type": _VIDEO_TYPES.get(kind, lower(kind)),
        "status": lower(node.get("status")),
        "view_count": to_int(node.get("viewCount")),
        "duration_seconds": to_int(node.get("lengthSeconds")),
        "duration": duration_text(node.get("lengthSeconds")),
        "language": language(node.get("language")),
        "published_at": iso_datetime(node.get("publishedAt")),
        "created_at": iso_datetime(node.get("createdAt")),
        "thumbnail": image(node.get("previewThumbnailURL")),
        "animated_preview": image(node.get("animatedPreviewURL")),
        "tags": [text(t.get("localizedName")) for t in (node.get("contentTags") or []) if isinstance(t, dict) and text(t.get("localizedName"))],
        "game": game_ref(node.get("game")),
    }
    ref = channel or channel_ref(node.get("owner"))
    if ref is not None:
        out["channel"] = ref
    return out


def video_details(node):
    out = video(node)
    if out is None:
        return None
    out["recorded_at"] = iso_datetime(node.get("recordedAt"))
    out["updated_at"] = iso_datetime(node.get("updatedAt"))
    out["offset_seconds"] = to_int(node.get("offsetSeconds"))
    out["storyboard_link"] = image(node.get("seekPreviewsURL"))
    restriction = node.get("resourceRestriction")
    out["restriction"] = lower(restriction.get("type")) if isinstance(restriction, dict) else None
    out["is_restricted"] = out["restriction"] is not None
    chapters = []
    for moment in nodes(node.get("moments")):
        details = moment.get("details") if isinstance(moment.get("details"), dict) else {}
        position = to_int(moment.get("positionMilliseconds"))
        length = to_int(moment.get("durationMilliseconds"))
        chapters.append({
            "id": text(moment.get("id")),
            "type": lower(moment.get("type")),
            "title": text(moment.get("description")),
            "start_seconds": position // 1000 if position is not None else None,
            "duration_seconds": length // 1000 if length is not None else None,
            "thumbnail": image(moment.get("thumbnailURL")),
            "game": game_ref(details.get("game")),
        })
    out["chapters"] = chapters
    order = ["id", "title", "link", "description", "type", "status", "is_restricted", "restriction",
             "view_count", "duration_seconds", "duration", "language", "tags", "published_at", "created_at",
             "recorded_at", "updated_at", "offset_seconds", "thumbnail", "animated_preview", "storyboard_link",
             "game", "channel", "chapters"]
    return {k: out.get(k) for k in order}


# ---- clips -----------------------------------------------------------------------------

def clip(node, channel=None):
    if not isinstance(node, dict):
        return None
    slug = text(node.get("slug"))
    broadcaster = channel or channel_ref(node.get("broadcaster"))
    login = (broadcaster or {}).get("login")
    source = node.get("video") if isinstance(node.get("video"), dict) else None
    offset = to_int(node.get("videoOffsetSeconds"))
    out = {
        "id": text(node.get("id")),
        "slug": slug,
        "title": text(node.get("title")),
        "link": text(node.get("url")) or refs.clip_link(slug, login),
        "view_count": to_int(node.get("viewCount")),
        "duration_seconds": to_int(node.get("durationSeconds")),
        "created_at": iso_datetime(node.get("createdAt")),
        "language": language(node.get("language")),
        "is_featured": bool_or_none(node.get("isFeatured")),
        "thumbnail": image(node.get("thumbnailURL")),
        "game": game_ref(node.get("game")),
        "source_video": {
            "id": text(source.get("id")),
            "link": refs.video_link(text(source.get("id"))),
            "offset_seconds": offset,
        } if source and text(source.get("id")) else None,
        "curator": channel_ref(node.get("curator")),
    }
    if broadcaster is not None:
        out["channel"] = broadcaster
    return out


def _playback_token(token):
    """{signature, value} -> {signature, token, expires_at, ...decoded flags}."""
    if not isinstance(token, dict):
        return None
    decoded = {}
    try:
        decoded = json.loads(token.get("value") or "{}")
    except (TypeError, ValueError):
        decoded = {}
    expires = to_int(decoded.get("expires"))
    auth = decoded.get("authorization") if isinstance(decoded.get("authorization"), dict) else {}
    return {
        "signature": text(token.get("signature")),
        "token": text(token.get("value")),
        "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if expires else None,
        "is_forbidden": bool_or_none(auth.get("forbidden")),
        "forbidden_reason": text(auth.get("reason")),
        "geoblock_reason": text(decoded.get("geoblock_reason")),
        "is_mature": bool_or_none(decoded.get("mature")),
        "maximum_resolution": text(decoded.get("maximum_resolution")),
    }


def clip_details(node):
    out = clip(node)
    if out is None:
        return None
    out["embed_link"] = text(node.get("embedURL"))
    source = node.get("video") if isinstance(node.get("video"), dict) else None
    if out.get("source_video") and source:
        out["source_video"]["title"] = text(source.get("title"))
        out["source_video"]["duration_seconds"] = to_int(source.get("lengthSeconds"))
    token = _playback_token(node.get("playbackAccessToken"))
    qualities = []
    for row in node.get("videoQualities") or []:
        if not isinstance(row, dict):
            continue
        src = text(row.get("sourceURL"))
        qualities.append({
            "quality": text(row.get("quality")),
            "frame_rate": to_int(row.get("frameRate")),
            "link": src,
            "download_link": _signed_clip_link(src, token),
        })
    qualities.sort(key=lambda q: -(to_int(q["quality"]) or 0))
    out["videos"] = qualities
    out["playback"] = {k: token.get(k) for k in ("expires_at", "is_forbidden", "forbidden_reason", "geoblock_reason")} if token else None
    order = ["id", "slug", "title", "link", "embed_link", "view_count", "duration_seconds", "created_at",
             "language", "is_featured", "thumbnail", "game", "channel", "curator", "source_video", "videos", "playback"]
    return {k: out.get(k) for k in order}


def _signed_clip_link(src, token):
    """The mp4 plays only with the clip token appended (sig + token)."""
    if not src or not token or not token.get("signature") or not token.get("token"):
        return src
    from urllib.parse import quote
    return f"{src}?sig={token['signature']}&token={quote(token['token'], safe='')}"


# ---- channels ----------------------------------------------------------------------------

def social_links(channel):
    rows = []
    for row in (channel or {}).get("socialMedias") or []:
        if not isinstance(row, dict):
            continue
        rows.append({
            "id": text(row.get("id")),
            "platform": lower(row.get("name")),
            "title": text(row.get("title")),
            "link": text(row.get("url")),
        })
    return rows


def panels(rows):
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or text(row.get("type")) not in (None, "DEFAULT"):
            if isinstance(row, dict) and text(row.get("type")) == "EXTENSION":
                out.append({"id": text(row.get("id")), "kind": "extension", "title": None, "description": None,
                            "link": None, "image": None})
            continue
        out.append({
            "id": text(row.get("id")),
            "kind": "default",
            "title": text(row.get("title")),
            "description": text(row.get("description")),
            "link": text(row.get("linkURL")),
            "image": image(row.get("imageURL")),
        })
    return out


def chat_settings(settings, chat_color=None):
    settings = settings if isinstance(settings, dict) else {}
    slow = to_int(settings.get("slowModeDurationSeconds"))
    followers = to_int(settings.get("followersOnlyDurationMinutes"))
    return {
        "is_emote_only": bool_or_none(settings.get("isEmoteOnlyModeEnabled")),
        "is_subscribers_only": bool_or_none(settings.get("isSubscribersOnlyModeEnabled")),
        "is_unique_chat": bool_or_none(settings.get("isUniqueChatModeEnabled")),
        "is_fast_subs_mode": bool_or_none(settings.get("isFastSubsModeEnabled")),
        "requires_verified_account": bool_or_none(settings.get("requireVerifiedAccount")),
        "slow_mode_seconds": slow,
        "is_slow_mode": slow is not None and slow > 0,
        "followers_only_minutes": followers,
        "is_followers_only": followers is not None and followers >= 0,
        "chat_delay_ms": to_int(settings.get("chatDelayMs")),
        "rules": [text(r) for r in (settings.get("rules") or []) if text(r)],
        "broadcaster_chat_color": text(chat_color),
    }


def pinned_messages(channel):
    out = []
    for node in nodes((channel or {}).get("pinnedChatMessages")):
        message = node.get("pinnedMessage") if isinstance(node.get("pinnedMessage"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), dict) else {}
        out.append({
            "id": text(node.get("id")),
            "text": text(content.get("text")),
            "sent_at": iso_datetime(message.get("sentAt")),
            "sender": channel_ref(message.get("sender")),
            "pinned_by": channel_ref(node.get("pinnedBy")),
            "starts_at": iso_datetime(node.get("startsAt")),
            "ends_at": iso_datetime(node.get("endsAt")),
        })
    return out


def channel_details(user):
    """The full channel card from the ChannelDetails document."""
    ref = channel_ref(user)
    live = stream(user.get("stream"), channel=None) if isinstance(user.get("stream"), dict) else None
    if live is not None:
        live.pop("channel", None)
    last = user.get("lastBroadcast") if isinstance(user.get("lastBroadcast"), dict) else None
    settings = user.get("broadcastSettings") if isinstance(user.get("broadcastSettings"), dict) else {}
    team = user.get("primaryTeam") if isinstance(user.get("primaryTeam"), dict) else None
    channel = user.get("channel") if isinstance(user.get("channel"), dict) else {}
    roles = user.get("roles") if isinstance(user.get("roles"), dict) else {}
    videos = user.get("videos") if isinstance(user.get("videos"), dict) else {}
    return {
        "id": ref["id"],
        "login": ref["login"],
        "username": ref["username"],
        "link": ref["link"],
        "bio": text(user.get("description")),
        "profile_image": image(user.get("profileImageURL")),
        "banner": image(user.get("bannerImageURL")),
        "offline_image": image(user.get("offlineImageURL")),
        "accent_color": ("#" + user["primaryColorHex"]) if text(user.get("primaryColorHex")) else None,
        "chat_color": text(user.get("chatColor")),
        "language": language(user.get("language")),
        "is_live": live is not None,
        "is_partner": bool_or_none(roles.get("isPartner")),
        "is_affiliate": bool_or_none(roles.get("isAffiliate")),
        "is_staff": bool_or_none(roles.get("isStaff")),
        "followers_count": to_int((user.get("followers") or {}).get("totalCount")),
        "videos_count": to_int(videos.get("totalCount")),
        "broadcast_settings": {
            "title": text(settings.get("title")),
            "game": game_ref(settings.get("game")),
            "language": language(settings.get("language")),
            "is_mature": bool_or_none(settings.get("isMature")),
        },
        "last_broadcast": {
            "id": text(last.get("id")),
            "title": text(last.get("title")),
            "started_at": iso_datetime(last.get("startedAt")),
            "game": game_ref(last.get("game")),
        } if last and (last.get("id") or last.get("startedAt")) else None,
        "livestream": live,
        "team": {
            "id": text(team.get("id")),
            "name": text(team.get("name")),
            "display_name": text(team.get("displayName")),
            "link": refs.team_link(text(team.get("name"))),
        } if team else None,
        "socials": social_links(channel),
        "panels": panels(user.get("panels")),
        "chat_settings": chat_settings(user.get("chatSettings"), user.get("chatColor")),
        "created_at": iso_datetime(user.get("createdAt")),
        "updated_at": iso_datetime(user.get("updatedAt")),
    }


def channel_status(user):
    """One channel's live status (ChannelStatus / ChannelsStatus rows)."""
    ref = channel_ref(user)
    live = stream(user.get("stream")) if isinstance(user.get("stream"), dict) else None
    if live is not None:
        live.pop("channel", None)
    last = user.get("lastBroadcast") if isinstance(user.get("lastBroadcast"), dict) else {}
    out = dict(ref)
    out["is_live"] = live is not None
    out["last_broadcast"] = {
        "id": text(last.get("id")),
        "title": text(last.get("title")),
        "started_at": iso_datetime(last.get("startedAt")),
        "game": game_ref(last.get("game")),
    } if last.get("startedAt") else None
    out["livestream"] = live
    return out


def schedule_segment(node):
    return {
        "id": text(node.get("id")),
        "title": text(node.get("title")),
        "starts_at": iso_datetime(node.get("startAt")),
        "ends_at": iso_datetime(node.get("endAt")),
        "is_cancelled": bool_or_none(node.get("isCancelled")),
        "has_reminder": bool_or_none(node.get("hasReminder")),
        "categories": [game_ref(g) for g in (node.get("categories") or []) if isinstance(g, dict)],
    }


def schedule(channel):
    sched = (channel or {}).get("schedule") if isinstance(channel, dict) else None
    if not isinstance(sched, dict):
        return None
    interruption = sched.get("interruption") if isinstance(sched.get("interruption"), dict) else None
    segments = [schedule_segment(s) for s in (sched.get("segments") or []) if isinstance(s, dict)]
    return {
        "id": text(sched.get("id")),
        "vacation": {
            "starts_at": iso_datetime(interruption.get("startAt")),
            "ends_at": iso_datetime(interruption.get("endAt")),
        } if interruption else None,
        "count": len(segments),
        "segments": segments,
    }


_GOAL_TYPES = {"FOLLOWERS": "followers", "SUB_POINTS": "sub_points", "SUBSCRIPTIONS": "subscriptions",
               "NEW_SUBSCRIPTIONS": "new_subscriptions", "NEW_SUB_POINTS": "new_sub_points",
               "NEW_BITS": "new_bits", "NEW_CHEERERS": "new_cheerers"}


def goal(node):
    target = to_int(node.get("targetContributions"))
    current = to_int(node.get("currentContributions"))
    kind = text(node.get("contributionType"))
    return {
        "id": text(node.get("id")),
        "type": _GOAL_TYPES.get(kind, lower(kind)),
        "state": lower(node.get("state")),
        "description": text(node.get("description")),
        "target": target,
        "current": current,
        "progress_percent": round(min(current / target, 1.0) * 100, 1) if target and current is not None else None,
        "is_active": lower(node.get("state")) == "active",
    }


def _image_url(obj):
    return image((obj or {}).get("url")) if isinstance(obj, dict) else None


def reward(node):
    per_stream = node.get("maxPerStreamSetting") if isinstance(node.get("maxPerStreamSetting"), dict) else {}
    per_user = node.get("maxPerUserPerStreamSetting") if isinstance(node.get("maxPerUserPerStreamSetting"), dict) else {}
    cooldown = node.get("globalCooldownSetting") if isinstance(node.get("globalCooldownSetting"), dict) else {}
    return {
        "id": text(node.get("id")),
        "title": text(node.get("title")),
        "prompt": text(node.get("prompt")),
        "cost": to_int(node.get("cost")),
        "is_enabled": bool_or_none(node.get("isEnabled")),
        "is_paused": bool_or_none(node.get("isPaused")),
        "is_in_stock": bool_or_none(node.get("isInStock")),
        "requires_user_input": bool_or_none(node.get("isUserInputRequired")),
        "skips_request_queue": bool_or_none(node.get("shouldRedemptionsSkipRequestQueue")),
        "background_color": text(node.get("backgroundColor")),
        "image": _image_url(node.get("image")) or _image_url(node.get("defaultImage")),
        "max_per_stream": to_int(per_stream.get("maxPerStream")) if per_stream.get("isEnabled") else None,
        "max_per_user_per_stream": to_int(per_user.get("maxPerUserPerStream")) if per_user.get("isEnabled") else None,
        "cooldown_seconds": to_int(cooldown.get("globalCooldownSeconds")) if cooldown.get("isEnabled") else None,
    }


def channel_points(channel):
    settings = (channel or {}).get("communityPointsSettings") if isinstance(channel, dict) else None
    if not isinstance(settings, dict):
        return None
    rewards = [reward(r) for r in (settings.get("customRewards") or []) if isinstance(r, dict)]
    rewards.sort(key=lambda r: (r["cost"] is None, r["cost"] or 0))
    variants = []
    for row in settings.get("emoteVariants") or []:
        if not isinstance(row, dict):
            continue
        emote = row.get("emote") if isinstance(row.get("emote"), dict) else {}
        variants.append(emote_ref(emote))
    return {
        "name": text(settings.get("name")) or "Channel Points",
        "is_enabled": bool_or_none(settings.get("isEnabled")),
        "image": _image_url(settings.get("image")),
        "rewards_count": len(rewards),
        "rewards": rewards,
        "unlockable_emotes_count": len(variants),
        "unlockable_emotes": variants,
    }


def emote_ref(emote):
    if not isinstance(emote, dict):
        return None
    eid = text(emote.get("id"))
    return {
        "id": eid,
        "code": text(emote.get("token")),
        "set_id": text(emote.get("setID")),
        "image": f"https://static-cdn.jtvnw.net/emoticons/v2/{eid}/default/dark/3.0" if eid else None,
    }


def badge(node):
    if not isinstance(node, dict):
        return None
    return {
        "set_id": text(node.get("setID")),
        "version": text(node.get("version")),
        "title": text(node.get("title")),
        "description": text(node.get("description")),
        "image": image(node.get("imageURL")),
        "click_action": lower(node.get("clickAction")),
        "click_link": text(node.get("clickURL")),
    }


def subscription_products(rows):
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        tier = text(row.get("tier"))
        emotes = [emote_ref(e) for e in (row.get("emotes") or []) if isinstance(e, dict)]
        out.append({
            "id": text(row.get("id")),
            "name": text(row.get("name")),
            "tier": {"1000": 1, "2000": 2, "3000": 3}.get(tier, to_int(tier)),
            "display_name": text(row.get("displayName")),
            "emote_set_id": text(row.get("emoteSetID")),
            "emotes_count": len(emotes),
            "emotes": emotes,
        })
    return out


def cheermotes(cheer):
    out = []
    groups = (cheer or {}).get("cheerGroups") if isinstance(cheer, dict) else None
    for group in groups or []:
        for node in (group or {}).get("nodes") or [] if isinstance(group, dict) else []:
            if not isinstance(node, dict):
                continue
            tiers = []
            for tier in node.get("tiers") or []:
                if not isinstance(tier, dict):
                    continue
                images = {}
                for img in tier.get("images") or []:
                    if not isinstance(img, dict):
                        continue
                    key = f"{lower(img.get('theme')) or 'dark'}_{'animated' if img.get('isAnimated') else 'static'}"
                    if to_float(img.get("dpiScale")) in (None, 1.0, 1) and key not in images:
                        images[key] = image(img.get("url"))
                tiers.append({
                    "min_bits": to_int(tier.get("bits")),
                    "color": text(tier.get("color")),
                    "images": images,
                })
            out.append({"prefix": text(node.get("prefix")), "tiers": tiers})
    return out


def chatters(block):
    block = block if isinstance(block, dict) else {}

    def logins(key):
        return [lower(r.get("login")) for r in (block.get(key) or []) if isinstance(r, dict) and text(r.get("login"))]

    groups = {k: logins(k) for k in ("broadcasters", "moderators", "vips", "staff", "viewers")}
    return {
        "total_count": to_int(block.get("count")),
        "listed_count": sum(len(v) for v in groups.values()),
        "broadcasters": groups["broadcasters"],
        "moderators": groups["moderators"],
        "vips": groups["vips"],
        "staff": groups["staff"],
        "viewers": groups["viewers"],
    }


def viewer_card(data):
    viewer = data.get("user") if isinstance(data.get("user"), dict) else None
    if viewer is None:
        return None
    card = data.get("channelViewer") if isinstance(data.get("channelViewer"), dict) else {}
    badges = [badge(b) for b in (card.get("earnedBadges") or []) if isinstance(b, dict)]
    sub_badge = next((b for b in badges if b["set_id"] == "subscriber"), None)
    founder = next((b for b in badges if b["set_id"] == "founder"), None)
    roles = viewer.get("roles") if isinstance(viewer.get("roles"), dict) else {}
    user = channel_ref(viewer)
    user["bio"] = text(viewer.get("description"))
    user["followers_count"] = to_int((viewer.get("followers") or {}).get("totalCount"))
    user["chat_color"] = text(viewer.get("chatColor"))
    user["is_staff"] = bool_or_none(roles.get("isStaff"))
    user["is_live"] = isinstance(viewer.get("stream"), dict)
    user["created_at"] = iso_datetime(viewer.get("createdAt"))
    channel = channel_ref(data.get("channel"))
    return {
        "user": user,
        "channel": channel,
        "is_subscriber": sub_badge is not None or founder is not None,
        # tier 2/3 badge versions are 2000+months / 3000+months
        "subscriber_months": (to_int(sub_badge["version"]) % 1000 if to_int(sub_badge["version"]) is not None else None) if sub_badge else None,
        "is_founder": founder is not None,
        "is_moderator": any(b["set_id"] == "moderator" for b in badges),
        "is_vip": any(b["set_id"] == "vip" for b in badges),
        "is_broadcaster": any(b["set_id"] == "broadcaster" for b in badges),
        "badges_count": len(badges),
        "badges": badges,
    }


# ---- playback ----------------------------------------------------------------------------

_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("(?:[^"\\]|\\.)*"|[^,]*)')


def _attrs(line):
    out = {}
    for key, value in _ATTR_RE.findall(line):
        out[key] = value[1:-1] if value.startswith('"') else value
    return out


def hls_variants(playlist):
    """An HLS master playlist -> one row per rendition
    ({name, group, resolution, width, height, frame_rate, bandwidth_kbps,
    codecs, is_source, is_audio_only, link}), best first."""
    rows = []
    media = {}
    pending = None
    for raw in (playlist or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = _attrs(line[len("#EXT-X-MEDIA:"):])
            media[attrs.get("GROUP-ID")] = attrs
        elif line.startswith("#EXT-X-STREAM-INF:"):
            pending = _attrs(line[len("#EXT-X-STREAM-INF:"):])
        elif not line.startswith("#") and pending is not None:
            group = pending.get("VIDEO") or pending.get("AUDIO")
            info = media.get(group) or {}
            name = info.get("NAME") or group
            resolution = pending.get("RESOLUTION")
            width = height = None
            if resolution and "x" in resolution:
                width, height = (to_int(v) for v in resolution.split("x", 1))
            bandwidth = to_int(pending.get("BANDWIDTH"))
            rows.append({
                "name": name,
                "group": group,
                "resolution": resolution,
                "width": width,
                "height": height,
                "frame_rate": to_float(pending.get("FRAME-RATE")),
                "bandwidth_kbps": bandwidth // 1000 if bandwidth else None,
                "codecs": pending.get("CODECS"),
                "is_source": group == "chunked" or (name or "").lower().endswith("(source)"),
                "is_audio_only": group == "audio_only",
                "link": line,
            })
            pending = None
    rows.sort(key=lambda r: (r["is_audio_only"], -(r["height"] or 0), -(r["frame_rate"] or 0), -(r["bandwidth_kbps"] or 0)))
    return rows


def playback(token, playlist_link, playlist_text):
    info = _playback_token(token) or {}
    variants = hls_variants(playlist_text)
    return {
        "playlist_link": playlist_link,
        "expires_at": info.get("expires_at"),
        "is_forbidden": info.get("is_forbidden"),
        "forbidden_reason": info.get("forbidden_reason"),
        "geoblock_reason": info.get("geoblock_reason"),
        "maximum_resolution": info.get("maximum_resolution"),
        "qualities_count": len(variants),
        "qualities": variants,
    }


# ---- chat replay --------------------------------------------------------------------------

def chat_message(node):
    message = node.get("message") if isinstance(node.get("message"), dict) else {}
    fragments = []
    emotes = []
    for frag in message.get("fragments") or []:
        if not isinstance(frag, dict):
            continue
        emote = frag.get("emote") if isinstance(frag.get("emote"), dict) else None
        piece = text(frag.get("text")) if frag.get("text") is not None else None
        if emote:
            eid = text(emote.get("emoteID")) or text(emote.get("id"))
            emotes.append({"id": eid, "code": frag.get("text"),
                           "image": f"https://static-cdn.jtvnw.net/emoticons/v2/{eid}/default/dark/3.0" if eid else None})
            fragments.append({"type": "emote", "text": frag.get("text"), "emote_id": eid})
        else:
            fragments.append({"type": "text", "text": frag.get("text"), "emote_id": None})
    badges = []
    for b in message.get("userBadges") or []:
        if isinstance(b, dict) and text(b.get("setID")):
            badges.append({"set_id": text(b.get("setID")), "version": text(b.get("version"))})
    offset = to_int(node.get("contentOffsetSeconds"))
    return {
        "id": text(node.get("id")),
        "offset_seconds": offset,
        "offset": duration_text(offset),
        "sent_at": iso_datetime(node.get("createdAt")),
        "text": "".join((f.get("text") or "") for f in (message.get("fragments") or []) if isinstance(f, dict)) or None,
        "user": {
            "id": text((node.get("commenter") or {}).get("id")),
            "login": lower((node.get("commenter") or {}).get("login")),
            "username": text((node.get("commenter") or {}).get("displayName")),
            "color": text(message.get("userColor")),
            "badges": badges,
            "is_subscriber": any(b["set_id"] in ("subscriber", "founder") for b in badges),
            "is_moderator": any(b["set_id"] == "moderator" for b in badges),
            "is_vip": any(b["set_id"] == "vip" for b in badges),
        } if isinstance(node.get("commenter"), dict) else None,
        "emotes": emotes,
        "fragments": fragments,
    }


# ---- search ------------------------------------------------------------------------------

def search_channel(item):
    """A User hit from searchFor -> channel ref + followers + live summary."""
    ref = channel_ref(item)
    if ref is None:
        return None
    live = item.get("stream") if isinstance(item.get("stream"), dict) else None
    ref["is_live"] = live is not None
    ref["livestream"] = {
        "id": text(live.get("id")),
        "title": text(live.get("title")),
        "viewers_count": to_int(live.get("viewersCount")),
        "started_at": iso_datetime(live.get("createdAt")),
        "language": language(live.get("language")),
        "game": game_ref(live.get("game")),
    } if live else None
    return ref


def suggestion(node):
    content = node.get("content") if isinstance(node.get("content"), dict) else None
    kind = text((content or {}).get("__typename"))
    out = {"text": text(node.get("text")), "type": "query", "channel": None, "game": None}
    if kind == "SearchSuggestionChannel":
        user = content.get("user") if isinstance(content.get("user"), dict) else {}
        login = lower(content.get("login"))
        out["type"] = "channel"
        out["channel"] = {
            "id": text(content.get("id")),
            "login": login,
            "username": text(user.get("displayName")) or login,
            "link": refs.channel_link(login),
            "profile_image": image(content.get("profileImageURL")),
            "followers_count": to_int((user.get("followers") or {}).get("totalCount")),
            "is_live": bool_or_none(content.get("isLive")),
            "is_verified": bool_or_none(content.get("isVerified")),
        }
    elif kind == "SearchSuggestionCategory":
        game = content.get("game") if isinstance(content.get("game"), dict) else {}
        slug = text(game.get("slug"))
        out["type"] = "game"
        out["game"] = {
            "id": text(content.get("id")),
            "name": text(game.get("displayName")) or text(game.get("name")),
            "slug": slug,
            "link": refs.game_link(slug),
            "box_art": image(content.get("boxArtURL"), 285, 380),
            "viewers_count": to_int(game.get("viewersCount")),
        }
    return out


# ---- teams -------------------------------------------------------------------------------

def team_member(node):
    ref = channel_ref(node)
    live = node.get("stream") if isinstance(node.get("stream"), dict) else None
    ref["is_live"] = live is not None
    ref["livestream"] = {
        "id": text(live.get("id")),
        "title": text(live.get("title")),
        "viewers_count": to_int(live.get("viewersCount")),
        "started_at": iso_datetime(live.get("createdAt")),
        "game": game_ref(live.get("game")),
    } if live else None
    return ref


def team(node):
    if not isinstance(node, dict):
        return None
    name = lower(node.get("name"))
    members = [team_member(m) for m in nodes(node.get("members"))]
    members.sort(key=lambda m: (-(m["livestream"]["viewers_count"] or 0) if m["livestream"] else 0, -(m.get("followers_count") or 0)))
    return {
        "id": text(node.get("id")),
        "name": name,
        "display_name": text(node.get("displayName")),
        "link": refs.team_link(name),
        "description": text(node.get("description")),
        "logo": image(node.get("logoURL")),
        "banner": image(node.get("bannerURL")),
        "background_image": image(node.get("backgroundImageURL")),
        "members_count": to_int((node.get("members") or {}).get("totalCount")) or len(members),
        "live_members_count": sum(1 for m in members if m["is_live"]),
        "members": members,
    }
