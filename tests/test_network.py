"""Talking to Blizzard: retries, timeouts, tokens and network failures.

urllib.request.urlopen is replaced by a scripted fake, so nothing goes on the internet."""

import io
import json
import os
import urllib.error
import urllib.request

import pytest

import wow_price as wp
import wow_progress as wpr
from conftest import FakeApi


class Reply:
    """What urlopen hands back: a context manager with read()."""

    def __init__(self, data=None, read_error=None):
        self.data, self.read_error = data, read_error

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        if self.read_error:
            raise self.read_error
        return json.dumps(self.data).encode()


def http_error(code, retry_after=None, body="{}"):
    hdrs = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError("https://us.api.blizzard.com/x", code, "err", hdrs, io.BytesIO(body.encode()))


@pytest.fixture
def net(monkeypatch):
    """net(answer, answer, ...): urlopen gives these out in order (exceptions are raised).
    net.calls holds (url, timeout) per call, net.sleeps every pause the retry made."""
    class Net:
        def __init__(self):
            self.script, self.calls, self.sleeps = [], [], []

        def __call__(self, *answers):
            self.script.extend(answers)
            return self

    n = Net()

    def fake_urlopen(req, timeout=None):
        n.calls.append((req.full_url, timeout))
        ans = n.script.pop(0)
        if isinstance(ans, BaseException):
            raise ans
        return ans
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(wp.time, "sleep", n.sleeps.append)
    return n


URL = "https://us.api.blizzard.com/data/wow/item/2770?namespace=static-forever-us"


# ---------------------------------------------------------------- retries

def test_busy_server_is_retried_with_backoff(net):
    net(http_error(503), http_error(502), Reply({"ok": 1}))
    assert wp.http_json(URL) == {"ok": 1}
    assert len(net.calls) == 3 and len(net.sleeps) == 2
    assert net.sleeps[1] > net.sleeps[0] > 0                 # waits longer each time


def test_throttling_waits_as_long_as_blizzard_asks(net):
    net(http_error(429, retry_after=7), Reply({"ok": 1}))
    assert wp.http_json(URL) == {"ok": 1}
    assert net.sleeps == [7]


def test_retry_after_is_capped(net):
    net(http_error(429, retry_after=3600), Reply({"ok": 1}))
    wp.http_json(URL)
    assert net.sleeps[0] <= wp.RETRY_AFTER_MAX


def test_gives_up_after_three_tries_with_the_same_error_as_before(net):
    net(http_error(503), http_error(503), http_error(503, body='{"detail":"down"}'))
    with pytest.raises(wp.ApiError) as e:
        wp.http_json(URL)
    assert e.value.code == 503 and len(net.calls) == 3
    assert str(e.value).startswith("Blizzard API error 503 for https://us.api.blizzard.com/data/wow/item/2770")


def test_not_found_is_not_retried(net):
    net(http_error(404))
    with pytest.raises(wp.ApiError) as e:
        wp.http_json(URL)
    assert e.value.code == 404 and len(net.calls) == 1 and net.sleeps == []


# ---------------------------------------------------------------- network failures

def test_no_connection_is_a_network_error_not_an_exit(net):
    net(*[urllib.error.URLError("getaddrinfo failed")] * 3)
    with pytest.raises(wp.NetworkError) as e:
        wp.http_json(URL)
    assert not isinstance(e.value, (SystemExit, wp.ApiError))
    assert str(e.value) == "Could not reach Blizzard API: getaddrinfo failed"
    assert len(net.calls) == 3


def test_dropped_connection_mid_download_is_retried(net):
    net(Reply(read_error=TimeoutError("timed out")), Reply(read_error=ConnectionResetError(104, "reset")),
        Reply({"ok": 1}))
    assert wp.http_json(URL) == {"ok": 1}


def test_dropped_connection_every_time_is_a_network_error(net):
    net(*[Reply(read_error=TimeoutError("timed out"))] * 3)
    with pytest.raises(wp.NetworkError) as e:
        wp.http_json(URL)
    assert "Could not reach Blizzard API" in str(e.value)


def test_network_errors_are_never_cached_as_missing_items(monkeypatch):
    api = FakeApi({"/data/wow/item/5": wp.NetworkError("Could not reach Blizzard API: down")})
    cache = wp.fetch_items(api, [5])
    assert "forever:5" not in cache                          # asked again next time


def test_item_search_reports_a_network_problem_as_one(monkeypatch):
    api = FakeApi({"/data/wow/search/item": wp.NetworkError("Could not reach Blizzard API: down")})
    with pytest.raises(wp.NetworkError):
        wp.find_items(api, "Copper Ore")


def test_progress_tolerates_a_page_that_cannot_be_reached(fake_api):
    fake_api.routes["/profile/wow/character/a-b"] = {"name": "A", "level": 12}
    fake_api.routes["/profile/wow/character/a-b/quests"] = wp.NetworkError("Could not reach Blizzard API: down")
    snap = wpr.fetch("A", "B")
    assert "quests" in snap["missing"]


# ---------------------------------------------------------------- timeouts

def test_small_calls_time_out_sooner_than_auction_downloads(net):
    api = wp.Blizz("tok", "us", "forever")
    net(Reply({}), Reply({}), Reply({}))
    api.get("/data/wow/item/2770", "static")
    api.get("/data/wow/ruleset/2/auctions/110", "dynamic")
    api.get("/data/wow/ruleset/2/auctions/110/commodities", "dynamic")
    timeouts = [t for _u, t in net.calls]
    assert timeouts == [wp.TIMEOUT_SMALL, wp.TIMEOUT_AUCTIONS, wp.TIMEOUT_AUCTIONS]
    assert wp.TIMEOUT_SMALL < wp.TIMEOUT_AUCTIONS


# ---------------------------------------------------------------- tokens

def token_reply(tok="new-token"):
    return Reply({"access_token": tok, "expires_in": 86399})


def test_damaged_token_cache_counts_as_missing(net):
    path = os.path.join(wp.CACHE_DIR, "token.json")
    with open(path, "w") as f:
        f.write('{"access_tok')
    net(token_reply())
    assert wp.get_token("id", "secret") == "new-token"
    with open(path) as f:
        assert json.load(f)["access_token"] == "new-token"


def test_cached_token_is_reused(net):
    net(token_reply("first"))
    assert wp.get_token("id", "secret") == "first"
    assert wp.get_token("id", "secret") == "first" and len(net.calls) == 1


def test_login_network_failure_is_not_blamed_on_the_key(net):
    net(*[urllib.error.URLError("no internet")] * 3)
    with pytest.raises(wp.NetworkError):
        wp.get_token("id", "secret")


def test_login_rejected_still_says_check_your_key(net):
    net(http_error(401))
    with pytest.raises(SystemExit) as e:
        wp.get_token("id", "secret")
    assert "check your Client ID/Secret" in str(e.value)


def test_rejected_token_is_renewed_once(net, monkeypatch):
    monkeypatch.setattr(wp, "load_credentials", lambda: ("id", "secret"))
    net(token_reply("old"))
    api = wp.connect()
    net(http_error(401), token_reply("fresh"), Reply({"ok": 1}))
    assert api.get("/data/wow/item/1", "static") == {"ok": 1}
    assert api.token == "fresh"
    assert "oauth.battle.net" in net.calls[2][0]


def test_token_rejected_twice_gives_up(net, monkeypatch):
    monkeypatch.setattr(wp, "load_credentials", lambda: ("id", "secret"))
    net(token_reply("old"))
    api = wp.connect()
    net(http_error(401), token_reply("fresh"), http_error(401))
    with pytest.raises(wp.ApiError) as e:
        api.get("/data/wow/item/1", "static")
    assert e.value.code == 401
