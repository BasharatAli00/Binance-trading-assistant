"""Offline fakes + ABI encoders for RHC tests (no network, no database)."""
import json
import math
import os

from rhc_decoders import TOPICS

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "rhc_logs.json")

PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
ETH = "0x" + "0" * 40
MEME = "0x" + "ab" * 20
REF = "0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca"
V3_FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
MEME_POOL_ID = "0x" + "cd" * 32
T0 = 1_780_000_000 - (1_780_000_000 % 300)      # aligned to 5 minutes


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def wu(v):
    return format(v % (1 << 256), "064x")


def wa(a):
    return "0" * 24 + a[2:].lower()


def topic_addr(a):
    return "0x" + wa(a)


def topic_u(v):
    return "0x" + wu(v)


def mklog(address, topics, words, block, tx=None, li=0):
    return {"address": address, "topics": topics, "data": "0x" + "".join(words),
            "blockNumber": hex(block), "transactionHash": tx or ("0x" + format(block * 1000 + li, "064x")),
            "logIndex": hex(li), "blockHash": "0x" + format(block, "064x"), "removed": False}


def sqrt_x96(price1_per_0_human, dec0, dec1):
    raw = price1_per_0_human / (10 ** (dec0 - dec1))
    return int(math.sqrt(raw) * (2 ** 96))


def v3_swap(pool, a0_pool, a1_pool, sqrtp, block, li=0, liq=10 ** 18, tx=None):
    """a0_pool/a1_pool are RAW v3 amounts (pool perspective)."""
    return mklog(pool, [TOPICS["v3_swap"], topic_addr("0x" + "11" * 20), topic_addr("0x" + "22" * 20)],
                 [wu(a0_pool), wu(a1_pool), wu(sqrtp), wu(liq), wu(0)], block, tx=tx, li=li)


def v4_init(pool_id, c0, c1, sqrtp, block, li=0, hooks=ETH):
    return mklog(PM, [TOPICS["v4_initialize"], pool_id, topic_addr(c0), topic_addr(c1)],
                 [wu(3000), wu(60), wa(hooks), wu(sqrtp), wu(0)], block, li=li)


def v4_swap(pool_id, a0_user, a1_user, sqrtp, block, li=0, liq=10 ** 20, tx=None):
    """a0_user/a1_user are RAW v4 amounts (negative = user paid)."""
    return mklog(PM, [TOPICS["v4_swap"], pool_id, topic_addr("0x" + "33" * 20)],
                 [wu(a0_user), wu(a1_user), wu(sqrtp), wu(liq), wu(0), wu(3000)], block, tx=tx, li=li)


class FakeRpc:
    """Deterministic chain: block b has timestamp T0 + b // 10 (0.1 s blocks)."""

    def __init__(self, logs=(), head=100_000, calls=None, start_block=0):
        self.logs = list(logs)
        self.head = head
        self.start_block = start_block
        self.calls = calls or {}
        self.n_calls = 0
        self.fail_ts_blocks = set()

    def ts(self, b):
        return T0 + (b - self.start_block) // 10

    def _block(self, b):
        return {"number": hex(b), "timestamp": hex(self.ts(b)), "hash": "0x" + format(b, "064x")}

    def _one(self, method, params):
        self.n_calls += 1
        if method == "eth_blockNumber":
            return hex(self.head)
        if method == "eth_getBlockByNumber":
            b = int(params[0], 16)
            return None if b in self.fail_ts_blocks else self._block(b)
        if method == "eth_call":
            to, data = params[0]["to"].lower(), params[0]["data"]
            return self.calls.get((to, data), "0x")
        if method == "eth_getTransactionByHash":
            return {"hash": params[0], "from": "0x" + params[0][-40:]}
        raise ValueError(method)

    def batch(self, calls):
        return [self._one(m, p) for m, p in calls]

    def call(self, method, params):
        return self._one(method, params)

    def block_number(self):
        return self.head

    def get_block(self, n):
        return self._block(n)

    def eth_call(self, to, data, block="latest"):
        return self.calls.get((to.lower(), data), "0x")

    def get_logs(self, flt, frm, to, max_span=None):
        self.n_calls += 1
        topics = flt.get("topics") or []
        t0 = topics[0] if topics else None
        t0s = set(t0) if isinstance(t0, list) else ({t0} if t0 else None)
        t1 = topics[1] if len(topics) > 1 else None
        t1s = set(t1) if isinstance(t1, list) else ({t1} if t1 else None)
        out = []
        for lg in self.logs:
            b = int(lg["blockNumber"], 16)
            if b < frm or b > to:
                continue
            if flt.get("address") and lg["address"].lower() != flt["address"].lower():
                continue
            if t0s and lg["topics"][0] not in t0s:
                continue
            if t1s and (len(lg["topics"]) < 2 or lg["topics"][1] not in t1s):
                continue
            out.append(lg)
        return out


def standard_calls(eth_usd=3000.0):
    sp = sqrt_x96(eth_usd, 18, 6)
    return {
        (REF, "0x0dfe1681"): "0x" + wa(WETH), (REF, "0xd21220a7"): "0x" + wa(USDG),
        (REF, "0xc45a0155"): "0x" + wa(V3_FACTORY), (REF, "0xddca3f43"): "0x" + wu(100),
        (REF, "0x3850c7bd"): "0x" + wu(sp) + wu(0) * 6,
        (WETH, "0x313ce567"): "0x" + wu(18), (USDG, "0x313ce567"): "0x" + wu(6), (MEME, "0x313ce567"): "0x" + wu(18),
    }


class FakeStore:
    def __init__(self):
        self.checkpoints = {}
        self.tokens = {}
        self.pools = {}          # pool_id -> dict
        self.candles = {}        # (pk, tf, bucket) -> row
        self.liq = {}
        self.swaps = {}
        self.gaps = []
        self._pk = 0
        self.writes = 0

    def load_checkpoint(self, stream):
        return self.checkpoints.get(stream)

    def save_checkpoint(self, stream, block, block_ts, block_hash, resume_from_ts):
        self.checkpoints[stream] = {"block": block, "block_ts": block_ts, "block_hash": block_hash,
                                    "resume_from_ts": resume_from_ts}

    def load_tokens(self, addrs):
        return {a: self.tokens[a] for a in addrs if a in self.tokens}

    def upsert_tokens(self, rows):
        for r in rows:
            self.tokens[r["address"]] = (r["decimals"], r["symbol"])

    def upsert_pools(self, metas, created=None):
        out = {}
        for m in metas:
            if m.pool_id not in self.pools:
                self._pk += 1
                self.pools[m.pool_id] = {"pk": self._pk, "meta": m, "tracked": False}
            out[m.pool_id] = self.pools[m.pool_id]["pk"]
        return out

    def _metas(self, pool_ids):
        import copy
        res = []
        for pid in pool_ids:
            p = self.pools.get(pid)
            if p:
                m = copy.copy(p["meta"])
                m.pk = p["pk"]
                m.tracked = p["tracked"]
                res.append(m)
        return res

    def load_pools_by_ids(self, ids):
        return self._metas(ids)

    def load_active_pools(self, since_ts):
        return self._metas(list(self.pools))

    def set_tracked(self, added, removed, ts):
        for p in self.pools.values():
            if p["pk"] in added:
                p["tracked"] = True
            if p["pk"] in removed:
                p["tracked"] = False

    def update_last_swap(self, m):
        pass

    def upsert_candles(self, rows):
        for r in rows:
            self.candles[(r["pool_pk"], r["tf"], r["bucket"])] = dict(r)
        self.writes += len(rows)
        return len(rows)

    def insert_liquidity(self, rows):
        for r in rows:
            self.liq.setdefault((r["tx_hash"], r["log_index"]), r)

    def insert_swaps(self, rows):
        for r in rows:
            self.swaps.setdefault((r["tx_hash"], r["log_index"]), r)

    def record_gap(self, stream, a, b, reason):
        self.gaps.append((stream, a, b, reason))
        return len(self.gaps)
