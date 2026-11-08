"""Phase 0 read-only probe of indexer APIs for Robinhood Chain. No keys."""
import json, time, collections
import requests

S = requests.Session()
S.headers["User-Agent"] = "rh-chain-probe/0.1"
OUT = {}


def get(url, **kw):
    t = time.time()
    try:
        r = S.get(url, timeout=25, **kw)
        dt = round((time.time() - t) * 1000)
        try:
            body = r.json()
        except Exception:
            body = r.text[:300]
        hdr = {k: v for k, v in r.headers.items() if any(x in k.lower() for x in ("limit", "retry", "cache-control"))}
        return r.status_code, body, dt, hdr
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", None, {}


def short(x, n=400):
    s = json.dumps(x, default=str) if not isinstance(x, str) else x
    return s[:n]


# ---------------- GeckoTerminal
GT = "https://api.geckoterminal.com/api/v2"
nets, page, found = [], 1, None
while page < 15:
    c, b, dt, h = get(f"{GT}/networks?page={page}")
    if c != 200 or not isinstance(b, dict) or not b.get("data"):
        break
    for n in b["data"]:
        nm = (n["attributes"].get("name") or "").lower()
        if "robinhood" in nm or "robinhood" in n["id"]:
            found = {"id": n["id"], "name": n["attributes"]["name"]}
    page += 1
OUT["gt_network"] = found
OUT["gt_headers"] = h
net = (found or {}).get("id", "robinhood")
c, b, dt, h = get(f"{GT}/networks/{net}/dexes?page=1")
OUT["gt_dexes"] = [d["attributes"]["name"] + " [" + d["id"] + "]" for d in (b.get("data") or [])] if c == 200 else f"{c} {short(b)}"
OUT["gt_dexes_latency_ms"] = dt
# paginate dexes
if c == 200:
    for p in range(2, 5):
        c2, b2, _, _ = get(f"{GT}/networks/{net}/dexes?page={p}")
        if c2 == 200 and b2.get("data"):
            OUT["gt_dexes"] += [d["attributes"]["name"] + " [" + d["id"] + "]" for d in b2["data"]]
        else:
            break

c, b, dt, h = get(f"{GT}/networks/{net}/pools?page=1&sort=h24_volume_usd_desc")
top_pools = []
if c == 200:
    for p in b.get("data", [])[:20]:
        a = p["attributes"]
        top_pools.append({
            "addr": a["address"], "name": a["name"], "dex": p["relationships"]["dex"]["data"]["id"],
            "liq": a.get("reserve_in_usd"), "vol24": (a.get("volume_usd") or {}).get("h24"),
            "created": a.get("pool_created_at"),
            "tx24": (a.get("transactions") or {}).get("h24"),
        })
OUT["gt_top_pools"] = top_pools if top_pools else f"{c} {short(b)}"

c, b, dt, h = get(f"{GT}/networks/{net}/new_pools?page=1")
if c == 200:
    np_ = b.get("data", [])
    OUT["gt_new_pools_count_page1"] = len(np_)
    OUT["gt_new_pools_sample"] = [(p["attributes"]["name"], p["relationships"]["dex"]["data"]["id"], p["attributes"]["pool_created_at"]) for p in np_[:8]]
    OUT["gt_new_pools_dex_mix"] = dict(collections.Counter(p["relationships"]["dex"]["data"]["id"] for p in np_))
else:
    OUT["gt_new_pools"] = f"{c} {short(b)}"

# OHLCV depth on top pool
if top_pools:
    pa = top_pools[0]["addr"]
    for tf, agg in [("minute", 1), ("minute", 5), ("day", 1)]:
        c, b, dt, h = get(f"{GT}/networks/{net}/pools/{pa}/ohlcv/{tf}?aggregate={agg}&limit=1000")
        if c == 200:
            lst = b["data"]["attributes"]["ohlcv_list"]
            if lst:
                OUT[f"gt_ohlcv_{tf}{agg}"] = {"candles": len(lst),
                    "oldest": time.strftime("%Y-%m-%d %H:%M", time.gmtime(lst[-1][0])),
                    "newest": time.strftime("%Y-%m-%d %H:%M", time.gmtime(lst[0][0]))}
            else:
                OUT[f"gt_ohlcv_{tf}{agg}"] = "empty"
        else:
            OUT[f"gt_ohlcv_{tf}{agg}"] = f"{c} {short(b, 200)}"
    c, b, dt, h = get(f"{GT}/networks/{net}/pools/{pa}/trades")
    OUT["gt_trades_endpoint"] = f"{c} rows={len(b.get('data', []))}" if c == 200 else f"{c} {short(b, 200)}"

# rate limit: 35 quick calls
codes = collections.Counter()
t = time.time()
for _ in range(35):
    c, _, _, h = get(f"{GT}/networks/{net}/trending_pools")
    codes[c] += 1
OUT["gt_burst35"] = {"codes": dict(codes), "secs": round(time.time() - t, 1)}

# ---------------- DexScreener
DS = "https://api.dexscreener.com"
c, b, dt, h = get(f"{DS}/latest/dex/search?q=WETH%20robinhood")
OUT["ds_search_latency_ms"] = dt
pairs = [p for p in (b.get("pairs") or []) if p.get("chainId") == "robinhood"] if c == 200 else []
OUT["ds_search_robinhood_pairs"] = len(pairs)
if top_pools:
    c, b, dt, h = get(f"{DS}/latest/dex/pairs/robinhood/{top_pools[0]['addr']}")
    pr = (b.get("pairs") or [None])[0] if c == 200 and isinstance(b, dict) else None
    OUT["ds_pair_lookup"] = {"status": c, "dexId": pr and pr.get("dexId"), "labels": pr and pr.get("labels"),
                             "fields": sorted(pr.keys()) if pr else None, "latency_ms": dt}
    if pr:
        OUT["ds_vs_gt_price"] = {"ds_priceUsd": pr.get("priceUsd"), "ds_liq": (pr.get("liquidity") or {}).get("usd")}
c, b, dt, h = get(f"{DS}/token-profiles/latest/v1")
if c == 200 and isinstance(b, list):
    OUT["ds_token_profiles_latest_robinhood"] = sum(1 for x in b if x.get("chainId") == "robinhood")
    OUT["ds_token_profiles_chains_seen"] = dict(collections.Counter(x.get("chainId") for x in b).most_common(8))
c, b, dt, h = get(f"{DS}/token-boosts/latest/v1")
if c == 200 and isinstance(b, list):
    OUT["ds_boosts_robinhood"] = sum(1 for x in b if x.get("chainId") == "robinhood")
OUT["ds_headers"] = h
codes = collections.Counter()
t = time.time()
for _ in range(40):
    c, _, _, _ = get(f"{DS}/latest/dex/search?q=robinhood")
    codes[c] += 1
OUT["ds_burst40"] = {"codes": dict(codes), "secs": round(time.time() - t, 1)}

# ---------------- Blockscout
BS = "https://robinhoodchain.blockscout.com/api"
c, b, dt, h = get(f"{BS}/v2/stats")
OUT["bs_stats"] = {k: b.get(k) for k in ("total_blocks", "total_transactions", "total_addresses", "average_block_time", "network_utilization_percentage")} if c == 200 else f"{c} {short(b)}"
OUT["bs_stats_latency_ms"] = dt
OUT["bs_headers"] = h
c, b, dt, h = get(f"{BS}/v2/tokens?type=ERC-20")
OUT["bs_tokens_page1"] = [(t.get("symbol"), t.get("address_hash") or t.get("address"), t.get("holders_count") or t.get("holders")) for t in (b.get("items") or [])[:12]] if c == 200 else f"{c} {short(b)}"
first_tok = None
if c == 200 and b.get("items"):
    first_tok = b["items"][0].get("address_hash") or b["items"][0].get("address")
if first_tok:
    c, b, dt, h = get(f"{BS}/v2/tokens/{first_tok}/holders")
    OUT["bs_token_holders_endpoint"] = f"{c} rows={len(b.get('items', []))}" if c == 200 else f"{c}"
    c, b, dt, h = get(f"{BS}/v2/smart-contracts/{first_tok}")
    OUT["bs_smart_contract_endpoint"] = {"status": c, "is_verified": b.get("is_verified") if c == 200 else None, "name": b.get("name") if c == 200 else None}
c, b, dt, h = get(f"{BS}/v2/smart-contracts?q=Factory")
OUT["bs_verified_factories"] = [(x.get("name"), (x.get("address") or {}).get("hash")) for x in (b.get("items") or [])][:30] if c == 200 else f"{c} {short(b)}"
c, b, dt, h = get(f"{BS}/v2/smart-contracts?q=Router")
OUT["bs_verified_routers"] = [(x.get("name"), (x.get("address") or {}).get("hash")) for x in (b.get("items") or [])][:30] if c == 200 else f"{c} {short(b)}"
c, b, dt, h = get(f"{BS}?module=block&action=eth_block_number")
OUT["bs_etherscan_compat_api"] = f"{c} {short(b, 120)}"
codes = collections.Counter()
t = time.time()
for _ in range(30):
    c, _, _, _ = get(f"{BS}/v2/stats")
    codes[c] += 1
OUT["bs_burst30"] = {"codes": dict(codes), "secs": round(time.time() - t, 1)}

# ---------------- DefiLlama
c, b, dt, h = get("https://api.llama.fi/v2/chains")
if c == 200:
    m = [x for x in b if "robinhood" in (x.get("name") or "").lower()]
    OUT["llama_chain"] = m
c, b, dt, h = get("https://api.llama.fi/overview/dexs/Robinhood?excludeTotalDataChart=true")
OUT["llama_dex_overview"] = f"{c} " + (short({k: b.get(k) for k in ("total24h", "total7d")}) if c == 200 and isinstance(b, dict) else short(b, 150))
if c == 200 and isinstance(b, dict):
    OUT["llama_dex_protocols"] = [(p.get("name"), p.get("total24h")) for p in (b.get("protocols") or [])][:20]

# ---------------- Relay (used by existing desk for execution)
c, b, dt, h = get("https://api.relay.link/chains")
if c == 200 and isinstance(b, dict):
    ch = [x for x in b.get("chains", []) if x.get("id") == 4663]
    OUT["relay_chain_4663"] = {"supported": bool(ch), "name": ch[0].get("displayName") if ch else None}

# ---------------- Bitquery / StalkChain (no keys)
c, b, dt, h = get("https://streaming.bitquery.io/graphql")
OUT["bitquery_no_key"] = f"{c} {short(b, 150)}"

print(json.dumps(OUT, indent=1, default=str))
