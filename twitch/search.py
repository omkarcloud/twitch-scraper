"""/twitch/search* — the site search: channels + categories + videos in
one call, or each index on its own with a cursor, plus the search-box
autocomplete."""
import uuid

from twitch import parsers as P
from twitch import queries as Q
from twitch.fetch import gql, gql_batch


def _rid():
    return str(uuid.uuid4())


def _hits(block):
    return [e.get("item") for e in (block or {}).get("edges") or [] if isinstance(e, dict) and isinstance(e.get("item"), dict)]


def _search_page(block, rows, key):
    block = block if isinstance(block, dict) else {}
    cursor = P.text(block.get("cursor"))
    return {
        "count": len(rows),
        "total_count": P.to_int(block.get("totalMatches")),
        key: rows,
        "next_cursor": cursor if rows else None,
        "has_more": bool(cursor and rows),
    }


def search(query, limit=5):
    """What the twitch.tv search page shows for a query: top channels,
    categories and videos (up to `limit` of each)."""
    rid = _rid()
    ops = [
        {"query": Q.SEARCH_ALL, "variables": {"query": query, "requestID": rid, "channels": limit, "games": limit, "videos": limit}},
        {"query": Q.SEARCH_GAMES, "variables": {"query": query, "first": limit}},
    ]
    found, games = gql_batch(ops)
    result = found.get("searchFor") if isinstance(found.get("searchFor"), dict) else {}
    channels = [P.search_channel(u) for u in _hits(result.get("channels"))]
    videos = [P.video(v) for v in _hits(result.get("videos"))]
    game_rows = [P.game_card(n) for n in P.nodes(games.get("searchCategories"))]
    if not game_rows:
        game_rows = [P.game_ref(g) for g in _hits(result.get("games"))]
    return {
        "query": query,
        "channels_total_count": P.to_int((result.get("channels") or {}).get("totalMatches")),
        "videos_total_count": P.to_int((result.get("videos") or {}).get("totalMatches")),
        "channels": channels,
        "games": game_rows,
        "videos": videos,
    }


def channels(query, limit=20, cursor=None):
    """Channels matching a query (by name / login), with live status, paged."""
    data = gql(Q.SEARCH_CHANNELS, {"query": query, "requestID": _rid(), "first": limit, "cursor": cursor})
    block = (data.get("searchFor") or {}).get("channels")
    rows = [P.search_channel(u) for u in _hits(block)]
    out = {"query": query}
    out.update(_search_page(block, rows, "channels"))
    return out


def games(query, limit=20, cursor=None):
    """Categories matching a query, with current viewers, paged."""
    data = gql(Q.SEARCH_GAMES, {"query": query, "first": limit, "after": cursor})
    rows = [P.game_card(n) for n in P.nodes(data.get("searchCategories"))]
    out = {"query": query}
    out.update(P.page(data.get("searchCategories"), rows, "games"))
    return out


def videos(query, limit=20, cursor=None):
    """VODs matching a query, paged."""
    data = gql(Q.SEARCH_VIDEOS, {"query": query, "requestID": _rid(), "first": limit, "cursor": cursor})
    block = (data.get("searchFor") or {}).get("videos")
    rows = [P.video(v) for v in _hits(block)]
    out = {"query": query}
    out.update(_search_page(block, rows, "videos"))
    return out


def suggest(query):
    """The search-box autocomplete: channels (with live flag), categories
    and query completions for a prefix."""
    data = gql(Q.SEARCH_SUGGEST, {"query": query, "requestID": _rid()})
    rows = [P.suggestion(n) for n in P.nodes(data.get("searchSuggestions"))]
    return {"query": query, "count": len(rows), "suggestions": rows}
