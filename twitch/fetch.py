"""Twitch transport: plain curl_cffi with browser-impersonated TLS against
the site's own GraphQL gateway. No browser, no cookies, no login (validated
2026-09-23 from direct Indian egress: ~0.3 s a call, 100-row pages, cursor
paging, chat replay and the chatters list all 200).

One upstream host does everything:

  * GQL    POST https://gql.twitch.tv/gql   {"query": ..., "variables": ...}
    Twitch's web/app GraphQL. It accepts RAW query documents (no persisted
    hash needed, so nothing rotates) with any of Twitch's first-party client
    ids. The id matters: with the WEB id (kimne78kx3ncx6brgo4mv6wki5h1ko)
    every `after:` cursor, the VOD chat replay by cursor and the chatters
    list answer `IntegrityCheckFailed` (a browser-minted Client-Integrity
    token is expected); the MOBILE id (config.TWITCH_CLIENT_ID, the Android
    app's) is exempt from that check for the same documents, so it is the
    default. A batch (JSON array of operations) is one round trip.

  * USHER  GET https://usher.ttvnw.net/api/channel/hls/<login>.m3u8
           GET https://usher.ttvnw.net/vod/<id>.m3u8
    The HLS master playlists, signed with the playback access token GQL
    hands out (streamPlaybackAccessToken / videoPlaybackAccessToken).

Still gated whatever the client id: the moderator list (`user.mods`,
Unauthenticated) and the follower / following LISTS (edges always empty;
only the counts are public). Those are simply not offered.

Blocks: none seen. If the pod's egress ever starts answering 403/429, a
worker moves its session to a sticky residential proxy exit
(config.twitch_fallback_proxy()) for config.TWITCH_BLOCK_COOLDOWN seconds,
the same shape as the kick transport.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  TwitchUpstreamError  transport failure / 5xx / GQL "server error"   — retryable
  TwitchBlocked        403 / 429 / integrity challenge                 — retryable on a new exit
  TwitchBadRequest     GQL argument error / auth-only field at the root — never retried
  TwitchNotFound       entity is null                                  — never retried
"""
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

GQL_URL = "https://gql.twitch.tv/gql"
USHER = "https://usher.ttvnw.net"
SITE = "https://www.twitch.tv"
IMPERSONATE = "chrome"

TIMEOUT = 45
FANOUT_WORKERS = 6

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": SITE,
    "referer": SITE + "/",
}
USHER_HEADERS = {
    "accept": "application/x-mpegURL, application/vnd.apple.mpegurl, application/json, text/plain",
    "accept-language": "en-US,en;q=0.9",
    "origin": SITE,
    "referer": SITE + "/",
}


class TwitchUpstreamError(UpstreamError):
    """Transport failure, 5xx or a GraphQL 'server error' — retryable."""


class TwitchBlocked(TwitchUpstreamError, Blocked):
    """403 / 429 or an integrity challenge — retryable on a fresh exit."""


class TwitchBadRequest(BadRequest):
    """GraphQL rejected an argument, or the root field needs a login. Never retried."""


class TwitchNotFound(NotFound):
    """Entity does not exist (GraphQL answered null) — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per worker thread. Direct egress by default; after a block
# the thread's sessions go through a sticky residential exit for a cooldown.
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy_for_new_session():
    forced = config.twitch_proxy()
    if forced:
        return forced
    if time.time() < _fallback_until:
        return config.twitch_fallback_proxy()
    return None


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block():
    """A 403/429 on direct egress: send new sessions through a residential
    exit for a while (no-op when no fallback country is configured)."""
    global _fallback_until
    if config.twitch_fallback_proxy() is not None:
        with _fallback_lock:
            _fallback_until = time.time() + config.TWITCH_BLOCK_COOLDOWN


def dump_debug(name, text):
    """Keep the last body of each failure kind when TWITCH_DEBUG_DIR is set."""
    dbg = os.environ.get("TWITCH_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))
        except OSError:
            pass


# ---- GraphQL ---------------------------------------------------------------------

_INTEGRITY = "IntegrityCheckFailed"
_ARGUMENT_RE = re.compile(r"argument '([^']+)' value must be", re.I)
_FIELD_RE = re.compile(r"Cannot query field|Unknown argument|is not defined by type|must not have a selection|Field \"[^\"]+\" of type", re.I)


def _retrying(fn):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except TwitchUpstreamError as e:      # includes TwitchBlocked
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _post(payload, label):
    def once():
        sess = _session()
        headers = dict(HEADERS)
        headers["client-id"] = config.TWITCH_CLIENT_ID
        try:
            resp = sess.post(GQL_URL, headers=headers, data=json.dumps(payload), timeout=TIMEOUT)
        except Exception as e:
            raise TwitchUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        if status in (403, 429):
            dump_debug("blocked", resp.text)
            _note_block()
            raise TwitchBlocked(f"HTTP {status} on {label}")
        if status == 400:
            raise TwitchBadRequest(_http_error_message(resp) or f"upstream rejected {label}")
        if status != 200:
            raise TwitchUpstreamError(f"HTTP {status} on {label}")
        body = resp.text or ""
        if not body.lstrip().startswith(("{", "[")):
            dump_debug("nonjson", body)
            raise TwitchBlocked(f"{label} returned HTML, not JSON")
        try:
            return resp.json()
        except Exception:
            dump_debug("badjson", body)
            raise TwitchUpstreamError(f"could not parse JSON from {label}")
    return _retrying(once)


def _http_error_message(resp):
    try:
        body = resp.json()
    except Exception:
        return None
    if isinstance(body, dict):
        message = body.get("message") or body.get("error")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def _error_paths(errors):
    return [tuple(e.get("path") or ()) for e in errors if isinstance(e, dict)]


def _classify_errors(errors, data, label, tolerate):
    """GraphQL `errors[]` next to (possibly partial) `data`.

    * an integrity challenge anywhere -> TwitchBlocked (the wrong client id,
      or Twitch tightening the check)
    * a schema error (field / argument / enum) -> TwitchUpstreamError: the
      query document in queries.py is stale
    * an argument range error ("value must be between 1 and 100") ->
      TwitchBadRequest
    * "unauthenticated" / "server error" on a path listed in `tolerate`
      -> ignored (that member is null in `data`; the caller treats it as
      optional); on any other path -> TwitchBadRequest / TwitchUpstreamError
    """
    tolerate = set(tolerate or ())
    for err in errors:
        if not isinstance(err, dict):
            continue
        message = str(err.get("message") or "")
        code = str(((err.get("extensions") or {}).get("code")) or "")
        path = tuple(str(p) for p in (err.get("path") or ()))
        if code == _INTEGRITY or "integrity" in message.lower():
            dump_debug("integrity", {"label": label, "error": err})
            raise TwitchBlocked(f"{label}: Twitch asked for an integrity token on {'.'.join(path) or 'the query'}")
        if _FIELD_RE.search(message):
            dump_debug("schema", {"label": label, "error": err})
            raise TwitchUpstreamError(f"{label}: Twitch changed its schema ({message[:160]})")
        if _ARGUMENT_RE.search(message):
            raise TwitchBadRequest(f"{message} (on {'.'.join(path) or label})")
        if any(path[:len(t)] == t for t in tolerate if t):
            continue
        low = message.lower()
        if code.lower() == "unauthenticated" or "unauthenticated" in low:
            raise TwitchBadRequest(f"{'.'.join(path) or label} needs a Twitch login")
        if "persistedquerynotfound" in low.replace(" ", ""):
            raise TwitchUpstreamError(f"{label}: persisted query not found")
        if data is None:
            raise TwitchUpstreamError(f"{label}: {message[:200] or code or 'GraphQL error'}")
        # a partial answer with a non-fatal error on some leaf: keep the data
        dump_debug("partial", {"label": label, "error": err})


def gql(query, variables=None, *, label=None, tolerate=None):
    """Run ONE raw GraphQL document -> its `data` dict. `tolerate` lists
    response paths (tuples) whose errors leave that member null instead of
    failing the call ("unauthenticated" on user.mods, "server error" on a
    leaf)."""
    label = label or _label_of(query)
    body = _post({"query": query, "variables": variables or {}}, label)
    if not isinstance(body, dict):
        raise TwitchUpstreamError(f"{label}: unexpected response shape")
    data = body.get("data")
    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        _classify_errors(errors, data, label, tolerate)
    if not isinstance(data, dict):
        raise TwitchUpstreamError(f"{label}: no data in the response")
    return data


def gql_batch(operations, *, tolerate=None):
    """Several {query, variables, label?} in ONE round trip -> [data, ...]
    in the same order. Each operation is classified on its own."""
    if not operations:
        return []
    payload = [{"query": op["query"], "variables": op.get("variables") or {}} for op in operations]
    labels = [op.get("label") or _label_of(op["query"]) for op in operations]
    body = _post(payload, "batch:" + ",".join(labels))
    if not isinstance(body, list) or len(body) != len(operations):
        raise TwitchUpstreamError("batch: unexpected response shape")
    out = []
    for item, label in zip(body, labels):
        data = item.get("data") if isinstance(item, dict) else None
        errors = item.get("errors") if isinstance(item, dict) else None
        if isinstance(errors, list) and errors:
            _classify_errors(errors, data, label, tolerate)
        if not isinstance(data, dict):
            raise TwitchUpstreamError(f"{label}: no data in the response")
        out.append(data)
    return out


def _label_of(query):
    match = re.search(r"(?m)^\s*(?:query|mutation)\s+([A-Za-z0-9_]+)", query or "")
    return match.group(1) if match else "gql"


# ---- usher (HLS master playlists) ----------------------------------------------------

def _usher(url, token):
    params = {
        "sig": token.get("signature"),
        "token": token.get("value"),
        "allow_source": "true",
        "allow_audio_only": "true",
        "fast_bread": "true",
        "player_backend": "mediaplayer",
        "playlist_include_framerate": "true",
        "supported_codecs": "av1,h265,h264",
        "p": random.randint(1_000_000, 9_999_999),
    }

    def once():
        sess = _session()
        try:
            resp = sess.get(url, params=params, headers=USHER_HEADERS, timeout=TIMEOUT)
        except Exception as e:
            raise TwitchUpstreamError(f"request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status == 404:
            # [{"error":"Can not find channel"}] / "transcode_does_not_exist" — offline or unavailable
            raise TwitchNotFound(_usher_message(text) or "playlist not found")
        if status in (403, 429):
            _note_block()
            raise TwitchBlocked(f"HTTP {status} on {url}")
        if status != 200:
            raise TwitchUpstreamError(f"HTTP {status} on {url}")
        if not text.lstrip().startswith("#EXTM3U"):
            dump_debug("usher", text)
            raise TwitchUpstreamError("usher returned something that is not an HLS playlist")
        return text
    return _retrying(once)


def _usher_message(text):
    try:
        body = json.loads(text)
    except Exception:
        return None
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return body[0].get("error") or body[0].get("error_code")
    if isinstance(body, dict):
        return body.get("error") or body.get("error_code")
    return None


def live_playlist(login, token):
    """The live HLS master playlist text for a channel login."""
    return _usher(f"{USHER}/api/channel/hls/{login}.m3u8", token)


def vod_playlist(video_id, token):
    """The VOD HLS master playlist text for a video id."""
    return _usher(f"{USHER}/vod/{video_id}.m3u8", token)


# ---- fan-out ------------------------------------------------------------------------

def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    with ThreadPoolExecutor(max_workers=min(FANOUT_WORKERS, len(fns))) as ex:
        futures = [ex.submit(fn) for fn in fns]
        return [f.result() for f in futures]


if __name__ == "__main__":
    # Smoke test: python twitch/fetch.py [login]
    login = sys.argv[1] if len(sys.argv) > 1 else "xqc"
    data = gql('query Smoke($login:String){ user(login:$login){ id displayName followers{totalCount} stream{viewersCount} } }',
               {"login": login})
    print(json.dumps(data, ensure_ascii=False))
