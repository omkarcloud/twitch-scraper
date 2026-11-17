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

Blocks: none seen. If the pod's egress ever starts answering 403/429, new
sessions move one fallback step down for config.TWITCH_BLOCK_COOLDOWN
seconds: since 2026-11-11 first to the shared gateway
(config.TWITCH_FALLBACK_EXIT = "gateway", exit_gateway.py: a fresh gateway address on
nearly every request; the numbers are in config.py's Twitch block), and only
when that is refused too to a sticky residential exit
(config.TWITCH_FALLBACK_PROXY_COUNTRY). A call the gateway keeps failing
makes its LAST retry on the residential exit, for that call only. When the
cooldown ends the next call is back on the server's own IP. The same shape
as the reed / threads / soundcloud transports.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  TwitchUpstreamError  transport failure / 5xx / GQL "server error"   — retryable
  TwitchBlocked        403 / 429 / integrity challenge                 — retryable on a new exit
  TwitchBadRequest     GQL argument error / auth-only field at the root — never retried
  TwitchNotFound       entity is null                                  — never retried
"""
import json
import fastjson
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import debug, fanout, ladder, retry, sessions

GQL_URL = "https://gql.twitch.tv/gql"
USHER = "https://usher.ttvnw.net"
SITE = "https://www.twitch.tv"
IMPERSONATE = "chrome"

TIMEOUT = 45
FANOUT_WORKERS = 6

HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("twitch"),
    "content-type": "application/json",
    "origin": SITE,
    "referer": SITE + "/",
}
USHER_HEADERS = {
    "accept": "application/x-mpegURL, application/vnd.apple.mpegurl, application/json, text/plain",
    "accept-language": egress.site_accept_language("twitch"),
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
# One session per worker thread (egress.new_session: curl_cffi, or the gateway
# exit's look-alike). Direct egress by default; after a block the sessions
# move down the fallback steps (config.twitch_fallback_exits(): the gateway
# exit, then a sticky residential exit) until `_fallback_until`, then go
# back to direct.
_local = threading.local()
_fallback_until = 0.0
_fallback_step = 1              # which fallback exit serves while the cooldown runs (1 = the first)
_fallback_lock = threading.Lock()


def _gateway_step(step):
    """True when fallback step `step` is the gateway exit with another exit
    configured behind it."""
    exits = config.twitch_fallback_exits()
    return 0 < step < len(exits) and bool(config.gateway_exit(exits[step - 1]))


def _step():
    """The fallback step a session built NOW rides: 0 = the configured exit
    (the server's own IP), 1, 2 = config.twitch_fallback_proxy(step) while
    the cooldown runs; one step past the gateway for the last retry of a
    call (_retrying)."""
    return ladder.current_step(_fallback_step, _fallback_until, _local, _gateway_step)


def _proxy_for_new_session(step=None):
    forced = config.twitch_proxy()
    if forced:
        return forced
    step = _step() if step is None else step
    return config.twitch_fallback_proxy(step) if step else None


def _session():
    sess = getattr(_local, "session", None)
    step = _step()
    if sess is not None and getattr(sess, "_tw_step", 0) != step:
        # 2026-11-11: a session follows its step. Before, a thread that took a
        # fallback exit during a cooldown stayed on it until that exit failed.
        _drop_session()
        sess = None
    if sess is None:
        # None (direct), a proxy URL, or the gateway exit ("gateway")
        sess = egress.new_session(_proxy_for_new_session(step), impersonate=IMPERSONATE)
        sess._tw_step = step
        _local.session = sess
    return sess


def _drop_session():
    sessions.drop(_local)


def _note_block():
    """The exit this thread's session rides was refused (403 / 429): new
    sessions move one fallback step down for a cooldown (own IP -> the gateway
    exit -> residential; on the last step they stay there, each on a
    fresh exit). No-op when no fallback is configured."""
    global _fallback_until, _fallback_step
    exits = config.twitch_fallback_exits()
    if not exits:
        return
    own = getattr(getattr(_local, "session", None), "_tw_step", _step())
    step = min(own + 1, len(exits))
    with _fallback_lock:
        # a refusal of the LAST exit names no step behind it: the residential
        # exit a call borrowed for its last retry must not pull the sessions
        # off the gateway step, which was not refused
        if time.time() >= _fallback_until or (step > _fallback_step and own < len(exits)):
            _fallback_step = step
        _fallback_until = time.time() + config.TWITCH_BLOCK_COOLDOWN
    if len(exits) > 1:      # how often each step is refused is the number to watch
        print(f"twitch: exit refused, sessions on fallback step {_fallback_step} "
              f"({exits[_fallback_step - 1]}) for {config.TWITCH_BLOCK_COOLDOWN} s")


def dump_debug(name, text):
    """Keep the last body of each failure kind when TWITCH_DEBUG_DIR is set."""
    debug.dump("TWITCH_DEBUG_DIR", name, text, render=lambda body: json.dumps(body, ensure_ascii=False))


# ---- GraphQL ---------------------------------------------------------------------

_INTEGRITY = "IntegrityCheckFailed"
_ARGUMENT_RE = re.compile(r"argument '([^']+)' value must be", re.I)
_FIELD_RE = re.compile(r"Cannot query field|Unknown argument|is not defined by type|must not have a selection|Field \"[^\"]+\" of type", re.I)


def _retrying(fn):
    """Run fn() under the shared retry policy, each retry on a fresh session
    / exit. While the sessions are on the gateway exit step the LAST retry of
    a call rides the next step (the residential exit), for that call only:
    a gateway failure then costs latency, not the call."""
    return retry.run_flagged(fn, config, TwitchUpstreamError, lambda e: _drop_session(), _local)


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
        body = fastjson.loads(text)
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
    return fanout.per_call(fns, FANOUT_WORKERS)


if __name__ == "__main__":
    # Smoke test: python twitch/fetch.py [login]
    login = sys.argv[1] if len(sys.argv) > 1 else "xqc"
    data = gql('query Smoke($login:String){ user(login:$login){ id displayName followers{totalCount} stream{viewersCount} } }',
               {"login": login})
    print(json.dumps(data, ensure_ascii=False))
