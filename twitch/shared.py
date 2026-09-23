"""Small helpers shared by the /twitch/* endpoint modules."""
import threading
import time

from twitch import parsers as P
from twitch import queries as Q
from twitch import refs
from twitch.fetch import TwitchNotFound, gql

_LOGIN_TTL = 6 * 3600
_logins = {}
_lock = threading.Lock()


def not_found(ref):
    return TwitchNotFound(f"channel '{refs.ref_label(ref)}' not found")


def login_of(ref):
    """A resolved channel ref -> its login (one lookup per numeric id,
    remembered for a few hours; documents that take a login only —
    playback tokens, viewer cards — need it)."""
    if ref.get("login"):
        return ref["login"]
    uid = ref.get("id")
    with _lock:
        hit = _logins.get(uid)
        if hit and hit[1] > time.time():
            return hit[0]
    data = gql(Q.USER_ID_LOOKUP, refs.user_args(ref))
    user = data.get("user")
    if not isinstance(user, dict) or not user.get("login"):
        raise not_found(ref)
    login = P.lower(user["login"])
    with _lock:
        _logins[uid] = (login, time.time() + _LOGIN_TTL)
    return login


def user_of(data, ref):
    """`data["user"]` or TwitchNotFound."""
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict) or not user.get("id"):
        raise not_found(ref)
    return user


def upper_langs(codes):
    return [c.upper() for c in codes] if codes else None


def lower_langs(codes):
    return [c.lower() for c in codes] if codes else None
