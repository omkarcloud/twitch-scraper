"""/twitch/clips/details — one clip with its mp4 renditions (signed
download links), curator, game and source-VOD offset."""
from twitch import parsers as P
from twitch import queries as Q
from twitch.fetch import TwitchNotFound, gql


def details(clip):
    data = gql(Q.CLIP_DETAILS, {"slug": clip})
    node = data.get("clip")
    if not isinstance(node, dict) or not node.get("id"):
        raise TwitchNotFound(f"clip '{clip}' not found")
    return {"clip": P.clip_details(node)}
