"""Twitch transport egress (2026-11-11): calls leave from the server's own
IP; after a refusal (403 / 429) new sessions step to the gateway exit
(config.TWITCH_FALLBACK_EXIT), and only when that is refused too to the
residential exit (config.TWITCH_FALLBACK_PROXY_COUNTRY). Offline, no network.

    python -m pytest twitch/test_fetch.py -q
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from twitch import fetch as F  # noqa: E402
from scraper_utils.testing import hosted_only

RESI = "http://resi-us:1"
QUERY = "query Smoke($login:String){ user(login:$login){ login } }"
PLAYLIST = "#EXTM3U\n#EXT-X-TWITCH-INFO:NODE=\"x\"\n"


class Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def json(self):
        import json
        return json.loads(self.text)


class Session:
    """What egress.new_session() hands out, answering per exit from `plan`
    (exit -> a status, a list of them, or an exception to raise)."""

    def __init__(self, exit, plan, seen):
        self.exit, self.plan, self.seen = exit, plan, seen

    def _answer(self, ok):
        self.seen.append(self.exit)
        answer = self.plan[self.exit]
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, Exception):
            raise answer
        return Resp(answer, ok if answer == 200 else "<html>refused</html>")

    def post(self, url, headers=None, data=None, **kwargs):
        assert url == F.GQL_URL and headers["client-id"] == config.TWITCH_CLIENT_ID
        return self._answer('{"data": {"user": {"login": "xqc"}}}')

    def get(self, url, **kwargs):
        assert url.startswith(F.USHER)
        return self._answer(PLAYLIST)

    def close(self):
        pass


@pytest.fixture
def ladder(monkeypatch):
    """(plan, seen): the exits' answers and the exit of every request sent."""
    plan, seen = {}, []
    monkeypatch.setattr(F, "_fallback_until", 0.0)
    monkeypatch.setattr(F, "_fallback_step", 1)
    monkeypatch.setattr(F._local, "session", None, raising=False)
    monkeypatch.setattr(F._local, "past_gateway", False, raising=False)
    monkeypatch.setattr(F.egress, "new_session", lambda exit=None, impersonate=None: Session(exit, plan, seen))
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "residential_proxy", lambda c, states=None: f"http://resi-{c}:1")
    monkeypatch.setattr(config, "MAX_RETRIES", 3)
    monkeypatch.setattr(config, "TWITCH_PROXY_COUNTRY", None)
    monkeypatch.setattr(config, "TWITCH_FALLBACK_EXIT", "gateway")
    monkeypatch.setattr(config, "TWITCH_FALLBACK_PROXY_COUNTRY", "us")
    return plan, seen


def user():
    return F.gql(QUERY, {"login": "xqc"})["user"]["login"]


@hosted_only
def test_default_is_own_ip_then_the_gateway_then_residential():
    assert config.TWITCH_PROXY_COUNTRY is None
    assert config.TWITCH_FALLBACK_EXIT == "gateway"
    assert config.TWITCH_FALLBACK_PROXY_COUNTRY == "us"


@hosted_only
def test_fallback_steps(ladder, monkeypatch):
    assert config.twitch_proxy() is None
    assert [config.twitch_fallback_proxy(step) for step in (1, 2, 3)] == ["gateway", RESI, None]
    monkeypatch.setattr(config, "TWITCH_FALLBACK_EXIT", None)          # the ladder before the gateway
    assert [config.twitch_fallback_proxy(step) for step in (1, 2)] == [RESI, None]
    assert config.twitch_fallback_proxy() == RESI
    monkeypatch.setattr(config, "TWITCH_FALLBACK_PROXY_COUNTRY", None)
    assert config.twitch_fallback_proxy() is None and config.twitch_fallback_exits() == []
    monkeypatch.setattr(config, "TWITCH_PROXY_COUNTRY", "gateway")          # the main knob takes the gateway too
    assert config.twitch_proxy() == "gateway"
    monkeypatch.setattr(config, "TWITCH_PROXY_COUNTRY", "gb")
    assert config.twitch_proxy() == "http://resi-gb:1"


@hosted_only
def test_a_refused_own_ip_costs_gateway_requests_not_residential(ladder):
    plan, seen = ladder
    plan.update({None: 403, "gateway": 200})
    assert user() == "xqc"
    assert seen == [None, "gateway"]
    assert user() == "xqc"                                  # new sessions stay on the gateway for the cooldown
    assert F.live_playlist("xqc", {"signature": "s", "value": "{}"}) == PLAYLIST
    assert seen == [None, "gateway", "gateway", "gateway"] and F._step() == 1
    F._fallback_until = time.time() - 1                     # cooldown over: the own IP again
    plan[None] = 200
    user()
    assert seen[-1] is None


@hosted_only
def test_a_refused_gateway_steps_on_to_residential_and_stays(ladder):
    plan, seen = ladder
    plan.update({None: 429, "gateway": 403, RESI: 200})
    assert user() == "xqc"
    assert seen == [None, "gateway", RESI]
    user()
    assert seen == [None, "gateway", RESI, RESI]
    plan[RESI] = [403, 200]                                 # refused on the last step: a fresh exit of that step
    user()
    assert seen[-2:] == [RESI, RESI] and F._step() == 2


@hosted_only
def test_last_retry_of_a_call_the_gateway_keeps_failing_rides_residential(ladder):
    plan, seen = ladder
    plan.update({None: 403, "gateway": 200, RESI: 200})
    user()                                                  # sessions are on the gateway step now
    del seen[:]
    plan["gateway"] = [RuntimeError("GatewayError: gateway 504"), 502, 200]
    assert user() == "xqc"
    assert seen == ["gateway", "gateway", RESI]
    assert user() == "xqc"                                  # for that call only: no cooldown on the paid exit
    assert seen == ["gateway", "gateway", RESI, "gateway"]
    assert F._step() == 1
    # a refusal of that borrowed residential exit is no verdict on the gateway: sessions stay on it
    del seen[:]
    plan.update({"gateway": [RuntimeError("GatewayError: gateway 504"), 502, 200], RESI: 403})
    with pytest.raises(F.TwitchBlocked):
        user()
    assert seen == ["gateway", "gateway", RESI] and F._step() == 1
    assert user() == "xqc" and seen[-1] == "gateway"


@hosted_only
def test_without_the_gateway_step_a_refusal_goes_straight_to_residential(ladder, monkeypatch):
    plan, seen = ladder
    monkeypatch.setattr(config, "TWITCH_FALLBACK_EXIT", None)
    plan.update({None: 403, RESI: [RuntimeError("reset"), 200]})
    assert user() == "xqc"
    assert seen == [None, RESI, RESI]                       # the ladder it always had
    monkeypatch.setattr(config, "TWITCH_FALLBACK_PROXY_COUNTRY", None)
    F._fallback_until = 0.0
    F._drop_session()
    del seen[:]
    plan[None] = [403, 200]
    assert user() == "xqc"                                  # no fallback at all: just a rebuilt session
    assert seen == [None, None] and F._step() == 0


@hosted_only
def test_a_pinned_exit_still_carries_every_call(ladder, monkeypatch):
    plan, seen = ladder
    monkeypatch.setattr(config, "TWITCH_PROXY_COUNTRY", "gateway")
    plan.update({"gateway": [403, 200]})
    assert user() == "xqc"
    assert seen == ["gateway", "gateway"]
