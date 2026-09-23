"""/twitch/videos/* — one VOD with its chapters, its chat replay and its
HLS playlist."""
from twitch import parsers as P
from twitch import queries as Q
from twitch import refs
from twitch.fetch import TwitchNotFound, gql, vod_playlist


def _video_of(data, video_id):
    node = data.get("video") if isinstance(data, dict) else None
    if not isinstance(node, dict) or not node.get("id"):
        raise TwitchNotFound(f"video '{video_id}' not found")
    return node


def details(video):
    """One VOD: title, type, views, duration, game, owner, tags, thumbnails,
    storyboard and the chapter markers (game changes with timestamps)."""
    data = gql(Q.VIDEO_DETAILS, {"id": video})
    return {"video": P.video_details(_video_of(data, video))}


def chat(video, offset=None, cursor=None):
    """The chat replay of a VOD: one chunk (~50-60 messages, Twitch fixes the
    size) from `offset` seconds in (default the start), or the chunk after
    `cursor`. Each page returns the cursor and the offset to continue from."""
    variables = {"id": video}
    if cursor:
        variables["after"] = cursor
    else:
        variables["offset"] = offset or 0
    data = gql(Q.VIDEO_CHAT, variables)
    node = _video_of(data, video)
    comments = node.get("comments") if isinstance(node.get("comments"), dict) else {}
    rows = [P.chat_message(n) for n in P.nodes(comments)]
    info = comments.get("pageInfo") if isinstance(comments.get("pageInfo"), dict) else {}
    edges = [e for e in comments.get("edges") or [] if isinstance(e, dict)]
    last_cursor = next((e["cursor"] for e in reversed(edges) if P.text(e.get("cursor"))), None)
    has_more = P.bool_or_none(info.get("hasNextPage"))
    if has_more is None:
        has_more = bool(last_cursor)
    return {
        "video": {"id": P.text(node.get("id")), "link": refs.video_link(P.text(node.get("id"))),
                  "duration_seconds": P.to_int(node.get("lengthSeconds"))},
        "count": len(rows),
        "first_offset_seconds": rows[0]["offset_seconds"] if rows else None,
        "last_offset_seconds": rows[-1]["offset_seconds"] if rows else None,
        "messages": rows,
        "next_cursor": last_cursor if has_more else None,
        "has_more": bool(has_more and last_cursor),
    }


def playback(video):
    """The VOD's HLS master playlist (signed, short-lived) and every quality
    rendition in it."""
    data = gql(Q.VIDEO_PLAYBACK_TOKEN, {"id": video})
    node = _video_of(data, video)
    token = data.get("videoPlaybackAccessToken")
    if not isinstance(token, dict) or not token.get("value"):
        raise TwitchNotFound(f"video '{video}' has no playback token")
    playlist_link = f"https://usher.ttvnw.net/vod/{video}.m3u8"
    text = vod_playlist(video, token)
    out = {
        "video": {"id": P.text(node.get("id")), "title": P.text(node.get("title")),
                  "link": refs.video_link(P.text(node.get("id"))),
                  "duration_seconds": P.to_int(node.get("lengthSeconds")),
                  "channel": P.channel_ref(node.get("owner"))},
    }
    out.update(P.playback(token, playlist_link, text))
    return out
