import pytest
import requests

from rhc_rpc import RpcClient, RpcError, RpcTransportError
from rhc_util import TTLCache, TokenBucket, ceil_to, floor_to


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Resp:
    def __init__(self, data, status=200):
        self._d = data
        self.status_code = status

    def json(self):
        return self._d


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return self.handler(url, json)


def client(handler, urls=("http://a",), **kw):
    clk = Clock()
    return RpcClient(list(urls), max_rps=1000, retries=kw.pop("retries", 2), session=FakeSession(handler),
                     sleep=clk.sleep, clock=clk, **kw), clk


def test_token_bucket_rate():
    clk = Clock()
    b = TokenBucket(2.0, capacity=2, clock=clk, sleep=clk.sleep)
    assert b.try_acquire() and b.try_acquire() and not b.try_acquire()
    clk.t += 0.5
    assert b.try_acquire() and not b.try_acquire()
    assert b.acquire(timeout=10) and clk.t >= 0.99


def test_token_bucket_timeout():
    clk = Clock()
    b = TokenBucket(0.01, capacity=1, clock=clk, sleep=clk.sleep)
    assert b.try_acquire()
    assert b.acquire(timeout=5) is False


def test_ttl_cache():
    clk = Clock()
    c = TTLCache(10, max_items=2, clock=clk)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)                    # evicts oldest
    assert c.get("a") is None and c.get("c") == 3
    clk.t += 11
    assert c.get("c") is None


def test_floor_ceil():
    assert floor_to(601, 300) == 600 and ceil_to(601, 300) == 900 and ceil_to(600, 300) == 600


def test_call_and_rpc_error():
    def h(url, body):
        if body["method"] == "bad":
            return Resp({"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32000, "message": "nope"}})
        return Resp({"jsonrpc": "2.0", "id": body["id"], "result": "0x10"})
    c, _ = client(h)
    assert c.call("eth_blockNumber", []) == "0x10"
    with pytest.raises(RpcError):
        c.call("bad", [])


def test_retry_then_failover():
    seen = []

    def h(url, body):
        seen.append(url)
        if url == "http://a":
            raise requests.ConnectionError("down")
        return Resp({"jsonrpc": "2.0", "id": body["id"], "result": "0x1"})
    c, _ = client(h, urls=("http://a", "http://b"))
    assert c.call("eth_blockNumber", []) == "0x1"
    assert seen[:2] == ["http://a", "http://b"]
    assert c.health["http://a"]["err"] == 1 and c.health["http://b"]["ok"] == 1


def test_gives_up_after_retries_on_429():
    c, _ = client(lambda u, b: Resp({}, status=429), retries=2)
    with pytest.raises(RpcTransportError):
        c.call("eth_blockNumber", [])


def test_batch_alignment_and_item_errors():
    def h(url, body):
        out = []
        for item in reversed(body):           # out-of-order response
            if item["method"] == "bad":
                out.append({"id": item["id"], "error": {"code": 1, "message": "x"}})
            else:
                out.append({"id": item["id"], "result": item["params"][0]})
        return Resp(out)
    c, _ = client(h, batch_size=2)
    res = c.batch([("echo", ["a"]), ("bad", []), ("echo", ["c"])])
    assert res[0] == "a" and isinstance(res[1], RpcError) and res[2] == "c"


def test_batch_split_on_429_for_large_batches():
    sizes = []

    def h(url, body):
        sizes.append(len(body))
        if len(body) > 10:                        # node rejects big batches with 429
            return Resp({}, status=429)
        return Resp([{"id": it["id"], "result": it["params"][0]} for it in body])
    c, _ = client(h, batch_size=40)
    res = c.batch([("echo", [i]) for i in range(40)])
    assert res == list(range(40))
    assert sizes == [40, 20, 10, 10, 20, 10, 10]   # halves until accepted, order preserved


def test_items_limiter_counts_calls_inside_batches():
    c, clk = client(lambda u, b: Resp([{"id": it["id"], "result": 1} for it in b]), batch_size=40,
                    max_items_per_s=20.0)
    c.batch([("x", [])] * 40)                    # burst capacity = 40
    t_before = clk.t
    c.batch([("x", [])] * 40)                    # must wait ~2 s for 40 more item tokens
    assert clk.t - t_before >= 1.9


def test_get_logs_splits_on_too_many_results_and_span():
    calls = []

    def h(url, body):
        q = body["params"][0]
        frm, to = int(q["fromBlock"], 16), int(q["toBlock"], 16)
        calls.append((frm, to))
        if to - frm + 1 > 250:
            return Resp({"id": body["id"], "error": {"code": -32000,
                                                     "message": "logs matched by query exceeds limit of 10000"}})
        return Resp({"id": body["id"], "result": [{"b": b} for b in range(frm, to + 1, 100)]})
    c, _ = client(h)
    logs = c.get_logs({"topics": []}, 0, 999, max_span=600)
    # max_span pre-splits into [0,599] and [600,999]; "exceeds limit" splits further
    assert all(to - frm + 1 <= 600 for frm, to in calls)
    got = sorted(x["b"] for x in logs)
    assert got == sorted(got) and len(got) == len(set(got))
    assert min(got) == 0 and max(got) <= 999


def test_get_logs_uses_span_limit_reported_by_node():
    calls = []

    def h(url, body):
        q = body["params"][0]
        frm, to = int(q["fromBlock"], 16), int(q["toBlock"], 16)
        calls.append(to - frm + 1)
        if to - frm + 1 > 100:
            return Resp({"id": body["id"], "error": {"code": -32602, "message":
                         f"query spans {to - frm + 1} blocks, but only 100 are allowed for this request"}})
        return Resp({"id": body["id"], "result": []})
    c, _ = client(h)
    c.get_logs({}, 1, 1000, max_span=10_000)
    assert calls[0] == 1000 and calls[1:] == [100] * 10     # one refusal, then straight to 100-block pieces


def test_get_logs_raises_non_split_errors():
    c, _ = client(lambda u, b: Resp({"id": b["id"], "error": {"code": -1, "message": "boom"}}))
    with pytest.raises(RpcError):
        c.get_logs({}, 0, 10, max_span=100)


def test_health_summary_never_exposes_urls():
    c, _ = client(lambda u, b: Resp({"id": b["id"], "result": "0x1"}), urls=("https://rpc.example/key=SECRET",))
    c.call("eth_blockNumber", [])
    assert "SECRET" not in str(c.health_summary())
