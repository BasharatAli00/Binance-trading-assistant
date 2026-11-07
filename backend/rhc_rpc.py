"""JSON-RPC client for Robinhood Chain with retries, failover, rate limiting,
batching and adaptive eth_getLogs range splitting.

Isolated from robinhood_wallet._rpc so the existing manual desk is untouched.
"""
import itertools
import logging
import re
import threading
import time

import requests

from rhc_util import TokenBucket

log = logging.getLogger("rhc.rpc")

_SPLIT_HINTS = ("exceeds limit", "query spans", "narrow the block range", "too many results",
                "response size", "block range")


class RpcError(Exception):
    def __init__(self, code, message, method=None):
        super().__init__(f"{method or 'rpc'}: [{code}] {message}")
        self.code = code
        self.message = str(message)
        self.method = method

    @property
    def allowed_span(self):
        """Parse 'but only N are allowed' from the node's span-limit error."""
        m = re.search(r"only (\d+) are allowed", self.message)
        return int(m.group(1)) if m else None

    @property
    def wants_split(self):
        m = self.message.lower()
        return any(h in m for h in _SPLIT_HINTS)


class RpcTransportError(Exception):
    pass


class RpcBatchTooLarge(Exception):
    """The node rejected a batch with HTTP 429; the caller splits it and retries."""


class RpcClient:
    def __init__(self, urls, timeout=20.0, max_rps=8.0, retries=4, batch_size=40, max_items_per_s=20.0,
                 session=None, sleep=time.sleep, clock=time.monotonic):
        if not urls:
            raise ValueError("at least one RPC URL is required")
        self.urls = list(urls)
        self.timeout = timeout
        self.retries = retries
        # Measured 2026-11-07: a batch of 80 calls -> HTTP 429, 40 -> OK.
        self.batch_size = max(1, batch_size)
        self._session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._bucket = TokenBucket(max_rps, capacity=max(2.0, max_rps), clock=clock, sleep=sleep)
        # Counts every call inside a batch, not just HTTP requests.
        self._items = TokenBucket(max_items_per_s, capacity=max(float(self.batch_size), max_items_per_s),
                                  clock=clock, sleep=sleep)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._active = 0
        self.health = {u: {"ok": 0, "err": 0, "last_err": None, "last_ok_ts": None, "latency_ms": None}
                       for u in self.urls}

    # ── transport ────────────────────────────────────────────────────────────
    @property
    def active_url(self):
        return self.urls[self._active % len(self.urls)]

    def _rotate(self):
        with self._lock:
            self._active = (self._active + 1) % len(self.urls)

    def _post(self, payload, retries=None):
        last_exc = None
        n_items = len(payload) if isinstance(payload, list) else 1
        for attempt in range((self.retries if retries is None else retries) + 1):
            url = self.active_url
            self._bucket.acquire()
            self._items.acquire(min(n_items, self._items.capacity))
            t0 = self._clock()
            try:
                r = self._session.post(url, json=payload, timeout=self.timeout)
                status = getattr(r, "status_code", 200)
                if status == 429 and n_items > 1:
                    raise RpcBatchTooLarge(f"HTTP 429 for batch of {n_items}")
                if status == 429 or status >= 500:
                    raise RpcTransportError(f"HTTP {status}")
                data = r.json()
                h = self.health[url]
                h["ok"] += 1
                h["last_ok_ts"] = int(time.time())
                h["latency_ms"] = round((self._clock() - t0) * 1000)
                return data
            except RpcBatchTooLarge:
                self.health[url]["err"] += 1
                self.health[url]["last_err"] = f"HTTP 429 (batch of {n_items})"
                raise
            except (requests.RequestException, ValueError, RpcTransportError) as e:
                last_exc = e
                h = self.health[url]
                h["err"] += 1
                h["last_err"] = str(e)[:200]
                if len(self.urls) > 1:
                    self._rotate()
                self._sleep(min(0.5 * (2 ** attempt), 8.0))
        raise RpcTransportError(f"RPC unreachable after {self.retries + 1} attempts: {last_exc}")

    # ── calls ────────────────────────────────────────────────────────────────
    def call(self, method, params):
        data = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params})
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise RpcError(err.get("code"), err.get("message"), method)
        return data.get("result") if isinstance(data, dict) else None

    def batch(self, calls):
        """calls: list of (method, params). Returns list aligned with input; each item is the
        result or an RpcError instance (never raises for per-item errors)."""
        out = []
        for i in range(0, len(calls), self.batch_size):
            out.extend(self._batch_chunk(calls[i:i + self.batch_size]))
        return out

    def _batch_chunk(self, chunk, depth=0):
        ids = [next(self._ids) for _ in chunk]
        payload = [{"jsonrpc": "2.0", "id": rid, "method": m, "params": p} for rid, (m, p) in zip(ids, chunk)]
        try:
            data = self._post(payload)
        except RpcBatchTooLarge:
            if len(chunk) > 1 and depth < 6:
                self._sleep(1.0)
                mid = len(chunk) // 2
                return self._batch_chunk(chunk[:mid], depth + 1) + self._batch_chunk(chunk[mid:], depth + 1)
            raise RpcTransportError("HTTP 429 even for a single call")
        by_id = {}
        if isinstance(data, list):
            by_id = {d.get("id"): d for d in data if isinstance(d, dict)}
        out = []
        for rid, (m, _) in zip(ids, chunk):
            d = by_id.get(rid)
            if d is None:
                out.append(RpcError(None, "missing batch response", m))
            elif d.get("error"):
                out.append(RpcError(d["error"].get("code"), d["error"].get("message"), m))
            else:
                out.append(d.get("result"))
        return out

    def block_number(self):
        return int(self.call("eth_blockNumber", []), 16)

    def get_block(self, number):
        return self.call("eth_getBlockByNumber", [hex(number), False])

    def eth_call(self, to, data, block="latest"):
        return self.call("eth_call", [{"to": to, "data": data}, block])

    def get_logs(self, flt, frm, to, max_span, _depth=0):
        """Fetch logs for [frm, to], splitting the range when the node refuses it."""
        if frm > to:
            return []
        if to - frm + 1 > max_span:
            mid = frm + max_span - 1
            return self.get_logs(flt, frm, mid, max_span) + self.get_logs(flt, mid + 1, to, max_span)
        q = dict(flt)
        q["fromBlock"] = hex(frm)
        q["toBlock"] = hex(to)
        try:
            return self.call("eth_getLogs", [q]) or []
        except RpcError as e:
            allowed = e.allowed_span
            if allowed and allowed < to - frm + 1 and _depth < 40:
                # The node told us its span limit: split straight to it instead of halving.
                return self.get_logs(flt, frm, to, max_span=allowed, _depth=_depth + 1)
            if e.wants_split and to > frm and _depth < 40:
                mid = (frm + to) // 2
                return (self.get_logs(flt, frm, mid, max_span, _depth + 1)
                        + self.get_logs(flt, mid + 1, to, max_span, _depth + 1))
            raise

    def health_summary(self):
        return {"active_url_index": self._active % len(self.urls), "urls": len(self.urls),
                "per_url": [{"index": i, **h} for i, h in enumerate(self.health.values())]}
