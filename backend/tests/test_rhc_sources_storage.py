import pytest

from rhc_sources import (DexScreenerSource, GeckoTerminalSource, SourceError, SourceHub, deviation_pct)
from rhc_storage import decide


class Resp:
    def __init__(self, data, status=200, headers=None):
        self._d = data
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._d


class Sess:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


DS_PAIR = {"chainId": "robinhood", "pairAddress": "0xPOOL", "dexId": "uniswap", "labels": ["v4"],
           "priceUsd": "0.002", "priceNative": "0.000001",
           "baseToken": {"address": "0xMEME", "symbol": "MEME"}, "quoteToken": {"address": "0xWETH", "symbol": "WETH"},
           "liquidity": {"usd": 50000}, "volume": {"h24": 1234}}


def test_dexscreener_normalise_prices_both_tokens():
    n = DexScreenerSource.normalise(DS_PAIR)
    assert n["pool_id"] == "0xpool" and n["price_usd"] == 0.002 and n["liquidity_usd"] == 50000
    assert n["token_prices_usd"]["0xmeme"] == 0.002
    assert n["token_prices_usd"]["0xweth"] == pytest.approx(2000.0)


def test_geckoterminal_normalise_maps_token_ids():
    item = {"attributes": {"address": "0xP", "base_token_price_usd": "1.0", "quote_token_price_usd": "3000",
                           "reserve_in_usd": "100"},
            "relationships": {"dex": {"data": {"id": "uniswap-v3-robinhood"}},
                              "base_token": {"data": {"id": "robinhood_0xUSDG"}},
                              "quote_token": {"data": {"id": "robinhood_0xWETH"}}}}
    n = GeckoTerminalSource.normalise(item)
    assert n["token_prices_usd"] == {"0xusdg": 1.0, "0xweth": 3000.0} and n["dex_id"] == "uniswap-v3-robinhood"


def test_429_retry_honours_retry_after_then_caches():
    slept = []
    s = Sess([Resp({}, 429, {"Retry-After": "2"}), Resp({"pairs": [DS_PAIR]})])
    ds = DexScreenerSource(session=s, sleep=slept.append)
    out = ds.pools(["0xpool"])
    assert "0xpool" in out and slept == [2.0]
    assert ds.health["err_count"] == 1 and ds.health["ok_count"] == 1
    ds.pools(["0xpool"])                            # served from cache: no new HTTP call
    assert len(s.calls) == 2


def test_hard_http_error_raises_and_records():
    ds = DexScreenerSource(session=Sess([Resp({}, 404)]), sleep=lambda s: None)
    with pytest.raises(SourceError):
        ds.pools(["0xabc"])
    assert ds.health["err_count"] == 1


def test_deviation_pct():
    assert deviation_pct(105, 100) == pytest.approx(5.0)
    assert deviation_pct(None, 100) is None and deviation_pct(1, 0) is None


class StubStore:
    def __init__(self):
        self.rows = []

    def latest_close_usd(self, pks):
        return {1: (0.0021, 0), 2: (3000.0, 0)}

    def insert_snapshots(self, rows):
        self.rows.extend(rows)


class StubDS:
    name = "dexscreener"

    def pools(self, ids):
        return {"0xpool": DexScreenerSource.normalise(DS_PAIR),
                "0xref": {"pool_id": "0xref", "token_prices_usd": {"0xweth": 2900.0, "0xusdg": 1.0}}}

    def health_row(self):
        return {"source": self.name}


class StubGT(StubDS):
    name = "geckoterminal"

    def pools(self, ids):
        raise SourceError("down")


def test_snapshot_cycle_compares_same_token_and_survives_source_failure():
    st = StubStore()
    hub = SourceHub(st, sources={"dexscreener": StubDS(), "geckoterminal": StubGT(), "defillama": StubDS(),
                                 "relay": StubDS()})
    res = hub.snapshot_cycle([(1, "0xpool", "0xMEME"), (2, "0xref", "0xweth")])
    assert res["snapshots"] == 2
    by_pk = {r["pool_pk"]: r for r in st.rows}
    assert by_pk[1]["dev_pct"] == pytest.approx(5.0)          # 0.0021 vs 0.002
    assert by_pk[2]["price_usd"] == 2900.0                     # WETH price, not USDG's
    assert res["flagged"] == 0                                 # 5.0 is not > 5.0


def test_flag_requires_two_consecutive_deviations_and_uses_latest_trade_price():
    st = StubStore()
    hub = SourceHub(st, sources={"dexscreener": StubDS(), "geckoterminal": StubGT(), "defillama": StubDS(),
                                 "relay": StubDS()})
    tracked = [(1, "0xpool", "0xMEME")]
    ours_far = {1: (0.004, 0)}                     # 100% off the source's 0.002
    assert hub.snapshot_cycle(tracked, ours=ours_far)["flagged"] == 0     # first time: noise, not flagged
    assert hub.snapshot_cycle(tracked, ours=ours_far)["flagged"] == 1     # persists: flagged
    assert hub.snapshot_cycle(tracked, ours={1: (0.002, 0)})["flagged"] == 0
    assert st.rows[-1]["our_price_usd"] == 0.002   # the supplied latest trade price was used


@pytest.mark.parametrize("size,paused,expect", [
    (100, False, ("normal", False)),
    (285, False, ("prune", False)),
    (365, False, ("critical", True)),
    (330, True, ("critical", True)),     # stays paused until below resume threshold
    (310, True, ("prune", False)),
    (100, True, ("normal", False)),
])
def test_storage_decide(size, paused, expect):
    assert decide(size, 400, paused, 70, 90, 80) == expect
