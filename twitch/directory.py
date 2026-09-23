"""/twitch/streams, /twitch/games/*, /twitch/tags/search, /twitch/badges —
the live directory (top streams with language / tag filters), top
categories, one category with its live streams, VODs and clips, the
freeform-tag autocomplete and the global chat badge set."""
from twitch import parsers as P
from twitch import queries as Q
from twitch import refs
from twitch.fetch import TwitchNotFound, gql
from twitch.shared import lower_langs, upper_langs


def _stream_options(sort, languages, tags):
    options = {"sort": sort or "VIEWER_COUNT"}
    if languages:
        options["languages"] = upper_langs(languages)
    if tags:
        options["freeformTags"] = tags
    return options


def streams(sort="VIEWER_COUNT", languages=None, tags=None, limit=20, cursor=None):
    """The site-wide live directory: streams by viewers (or most recent /
    recommended), optionally in given languages and/or with given tags."""
    data = gql(Q.STREAMS, {"first": limit, "after": cursor, "options": _stream_options(sort, languages, tags)})
    rows = [P.stream(n) for n in P.nodes(data.get("streams"))]
    return P.page(data.get("streams"), rows, "streams")


def games(limit=20, cursor=None):
    """Top categories by current viewers."""
    data = gql(Q.GAMES, {"first": limit, "after": cursor, "options": {"sort": "VIEWER_COUNT"}})
    rows = [P.game_card(n) for n in P.nodes(data.get("games"))]
    return P.page(data.get("games"), rows, "games")


def _game(document, ref, extra=None):
    """Run a game document; a name that misses is retried as a slug and
    vice versa (Twitch's category URLs use slugs, its API mostly names)."""
    variables = dict(refs.game_args(ref), **(extra or {}))
    data = gql(document, variables)
    node = data.get("game")
    if not isinstance(node, dict) or not node.get("id"):
        alt = None
        if ref.get("name") and " " not in ref["name"]:
            alt = {"slug": ref["name"].lower()}
        elif ref.get("slug"):
            alt = {"name": ref["slug"].replace("-", " ")}
        if alt:
            data = gql(document, dict(refs.game_args(alt), **(extra or {})))
            node = data.get("game")
    if not isinstance(node, dict) or not node.get("id"):
        raise TwitchNotFound(f"game '{refs.ref_label(ref)}' not found")
    return node


def game_details(game):
    """One category: viewers, live channels, followers, description,
    release date, developers / publishers, tags and art."""
    node = _game(Q.GAME_DETAILS, game)
    return {"game": P.game_details(node)}


def game_streams(game, sort="VIEWER_COUNT", languages=None, tags=None, limit=20, cursor=None):
    """Live streams in a category, with the directory's language / tag filters."""
    node = _game(Q.GAME_STREAMS, game, {"first": limit, "after": cursor,
                                        "options": _stream_options(sort, languages, tags)})
    ref = P.game_ref(node)
    ref["viewers_count"] = P.to_int(node.get("viewersCount"))
    rows = [P.stream(n) for n in P.nodes(node.get("streams"))]
    for row in rows:
        row.pop("game", None)
    out = {"game": ref}
    out.update(P.page(node.get("streams"), rows, "streams"))
    return out


def game_videos(game, type=None, sort="VIEWS", languages=None, limit=20, cursor=None):
    """VODs in a category (most viewed or newest), optionally by type and language."""
    node = _game(Q.GAME_VIDEOS, game, {"first": limit, "after": cursor, "sort": sort,
                                       "types": [type] if type else None, "languages": lower_langs(languages)})
    rows = [P.video(n) for n in P.nodes(node.get("videos"))]
    for row in rows:
        row.pop("game", None)
    out = {"game": P.game_ref(node)}
    out.update(P.page(node.get("videos"), rows, "videos"))
    return out


def game_clips(game, period="LAST_WEEK", sort="VIEWS_DESC", languages=None, limit=20, cursor=None):
    """Top clips in a category for a period, optionally by language."""
    criteria = {"period": period, "sort": sort}
    if languages:
        criteria["languages"] = upper_langs(languages)
    node = _game(Q.GAME_CLIPS, game, {"first": limit, "after": cursor, "criteria": criteria})
    rows = [P.clip(n) for n in P.nodes(node.get("clips"))]
    for row in rows:
        row.pop("game", None)
    out = {"game": P.game_ref(node)}
    out.update(P.page(node.get("clips"), rows, "clips"))
    return out


def tags(query, limit=20):
    """Freeform stream tags matching a prefix (what the `tags` filter takes)."""
    data = gql(Q.TAGS_SEARCH, {"query": query, "first": limit})
    rows = [P.text(n.get("tagName")) for n in P.nodes(data.get("searchFreeformTags")) if P.text(n.get("tagName"))]
    return {"query": query, "count": len(rows), "tags": rows}


def badges():
    """Every global chat badge (set, version, title, image)."""
    data = gql(Q.GLOBAL_BADGES, {})
    rows = [P.badge(b) for b in (data.get("badges") or []) if isinstance(b, dict)]
    sets = {}
    for row in rows:
        sets.setdefault(row["set_id"], []).append(row)
    return {"count": len(rows), "sets_count": len(sets), "badges": rows}
