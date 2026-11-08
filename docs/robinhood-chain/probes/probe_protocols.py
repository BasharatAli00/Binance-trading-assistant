"""Phase 0 probe round 2: protocol map, archive depth, WS, paced GeckoTerminal. Read-only."""
import json, time, collections, asyncio
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
S = requests.Session()
S.headers["User-Agent"] = "rh-chain-probe/0.1"
OUT = {}


def rpc(method, params, timeout=60):
    r = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
    return r.json()


def call(to, data, block="latest"):
    j = rpc("eth_call", [{"to": to, "data": data}, block])
    return j.get("result")


def addr_from_word(w):
    return "0x" + w[-40:]


def sym(token):
    r = call(token, "0x95d89b41")  # symbol()
    if not r or r == "0x":
        return None
    try:
        b = bytes.fromhex(r[2:])
        if len(b) >= 96:
            ln = int.from_bytes(b[32:64], "big")
            return b[64:64 + ln].decode("utf-8", "replace")
        return b.rstrip(b"\x00").decode("utf-8", "replace")
    except Exception:
        return r[:20]


head = int(rpc("eth_blockNumber", [])["result"], 16)
OUT["head"] = head

# --- archive depth: binary search on how far back eth_getBalance works
lo, hi = 1, 50_000_000  # blocks back
def ok_at(back):
    j = rpc("eth_getBalance", ["0x0000000000000000000000000000000000000000", hex(head - back)])
    return "result" in j
for back in [100, 1000, 10_000, 100_000, 300_000, 600_000]:
    OUT[f"state_available_{back}_blocks_back"] = ok_at(back)

# --- signature lookup
UNKNOWN = [
    "0x29e088dffd7bf6815d088137a59f364d6747163baa7ff4bc47f316a1ad1b9586",
    "0xe90cf9cc0a552cf52ea6ff74ece0f1c8ae8cc9ad630d3181f55ac43ca076b7d6",
    "0x37e7f0db430edc9dd31bc66f25f8449353aa0818f503b906747dd8f286cd3802",
    "0x79538f348255ddb6da30bd8902cdf9f3bdfbbe9714a23efc2feee97234bc62a2",
    "0xc532c43b3423e14ef72748f1c8291238829ca0af8ba9b67975ad1483485a4b4d",
    "0x49435801cf735ac077f83ed90d053b54c89f865de1791ad128ff92af1ac09507",
    "0xd2e719716e95a3112954ea7472be10119a0092e9425d8a994371473f46ab1ebc",
    "0xc67210912d144f2004380430cf6eff8648e06c1ac9d5f1367dc8e1eb28646acc",
    "0x2c1616bb389f23b6bf33d95f9435bf5a2a8fcd183529b5319c3d1836e7f8af2a",
    "0xf8e1a15aba9398e019f0b49df1a4fde98ee17ae345cb5f6b5e2c27f5033e8ce7",
    "0x6bacc01dbe442496068f7d234edd811f1a5f833243e0aec824f86ab861f3c90d",
    "0x41b532d633b984408c6cb99e0de889a69f64dac4d263e6771fb826cacfa84b6d",
    "0x6c703791f399558807424f489ccd811c72b4ff0b74af547264fad7c646776df0",
    "0x1b3d7edb2e9c0b0e7c525b20aaaef0f5940d2ed71663c7d39266ecafac728859",
    "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec",
]
try:
    r = S.get("https://api.openchain.xyz/signature-database/v1/lookup",
              params={"event": ",".join(UNKNOWN), "filter": "true"}, timeout=20)
    ev = r.json().get("result", {}).get("event", {})
    OUT["event_signatures"] = {k: [x["name"] for x in (v or [])][:2] for k, v in ev.items()}
except Exception as e:
    OUT["event_signatures"] = f"ERR {e}"

# --- known pool-creation events over ~1 day window (864k blocks @0.1s)
DAY = 864_000
EV = {
    "v2_PairCreated": "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9",
    "v3_PoolCreated": "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
    "v4_Initialize": "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438",
    "algebra_Pool": "0x91ccaa7a278130b65168c3a0c8d3bcae84cf5e43704342bd3ec0b59e59c036db",
    "v2_Swap": "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
}
creations = {}
for name, t0 in EV.items():
    logs, err = [], None
    step = DAY if name != "v2_Swap" else 50_000
    frm = head - (DAY if name != "v2_Swap" else 50_000)
    while frm < head:
        to = min(head, frm + step)
        j = rpc("eth_getLogs", [{"fromBlock": hex(frm), "toBlock": hex(to), "topics": [t0]}], timeout=120)
        if "error" in j:
            if step > 20_000:
                step //= 4
                continue
            err = j["error"]
            break
        logs += j["result"]
        frm = to + 1
    em = collections.Counter(l["address"].lower() for l in logs)
    creations[name] = logs
    OUT[f"{name}_last24h"] = {"count": len(logs), "emitters": em.most_common(8), "err": err}

# v4 Initialize: decode currencies + hooks
QUOTES = collections.Counter()
HOOKS = collections.Counter()
for l in creations["v4_Initialize"]:
    c0, c1 = addr_from_word(l["topics"][2]), addr_from_word(l["topics"][3])
    data = l["data"][2:]
    words = [data[i:i + 64] for i in range(0, len(data), 64)]
    # data: fee(uint24), tickSpacing(int24), hooks(address), sqrtPriceX96, tick
    hooks = addr_from_word(words[2]) if len(words) > 2 else None
    QUOTES[c0] += 1
    HOOKS[hooks] += 1
OUT["v4_currency0_top"] = [(a, n, sym(a) if a != "0x" + "0" * 40 else "ETH(native)") for a, n in QUOTES.most_common(6)]
OUT["v4_hooks_top"] = [(h, n) for h, n in HOOKS.most_common(10)]

# v3 PoolCreated: factory + quote mix
q3 = collections.Counter()
for l in creations["v3_PoolCreated"]:
    for w in (l["topics"][1], l["topics"][2]):
        q3[addr_from_word(w)] += 1
OUT["v3_token_top"] = [(a, n, sym(a)) for a, n in q3.most_common(6)]
q2 = collections.Counter()
for l in creations["v2_PairCreated"]:
    for w in (l["topics"][1], l["topics"][2]):
        q2[addr_from_word(w)] += 1
OUT["v2_token_top"] = [(a, n, sym(a)) for a, n in q2.most_common(6)]

# top emitter of unknown launchpad-ish topic: is it a contract? symbol?
for a in ["0xe844701934d9c6085b292e428f41b911cc0b3872", "0x8366a39cc670b4001a1121b8f6a443a643e40951",
          "0x0bd7d308f8e1639fab988df18a8011f41eacad73", "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044",
          "0xbef9c77ec3c1a0d92c4cb6264f8923b37a63eae0", "0x4857db576ee0e45f10525ec59527bfd10beec60b"]:
    code = rpc("eth_getCode", [a, "latest"]).get("result", "0x")
    OUT[f"contract_{a}"] = {"code_bytes": (len(code) - 2) // 2, "symbol": sym(a)}

# --- WebSocket endpoint test
async def ws_test():
    import websockets
    for url in ["wss://rpc.mainnet.chain.robinhood.com", "wss://rpc.mainnet.chain.robinhood.com/ws", "wss://ws.mainnet.chain.robinhood.com"]:
        try:
            async with websockets.connect(url, open_timeout=8) as ws:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]}))
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                OUT[f"ws_{url}"] = msg[:200]
        except Exception as e:
            OUT[f"ws_{url}"] = f"ERR {type(e).__name__}: {str(e)[:120]}"
asyncio.run(ws_test())

# --- GeckoTerminal paced (~1 call / 2.5s)
GT = "https://api.geckoterminal.com/api/v2/networks/robinhood"
def gt(path):
    time.sleep(2.5)
    r = S.get(GT + path, timeout=25)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200])

c, b = gt("/pools?page=1&sort=h24_volume_usd_desc")
top = []
if c == 200:
    for p in b["data"][:15]:
        a = p["attributes"]
        top.append({"addr": a["address"], "name": a["name"], "dex": p["relationships"]["dex"]["data"]["id"],
                    "liq": round(float(a.get("reserve_in_usd") or 0)), "vol24": round(float((a.get("volume_usd") or {}).get("h24") or 0)),
                    "created": a.get("pool_created_at")})
OUT["gt_top_pools"] = top or f"{c} {str(b)[:200]}"
c, b = gt("/new_pools?page=1")
if c == 200:
    d = b["data"]
    OUT["gt_new_pools"] = {"n": len(d), "dex_mix": dict(collections.Counter(p["relationships"]["dex"]["data"]["id"] for p in d)),
                           "newest": d[0]["attributes"]["pool_created_at"] if d else None,
                           "oldest_on_page": d[-1]["attributes"]["pool_created_at"] if d else None}
else:
    OUT["gt_new_pools"] = f"{c}"
pick = next((p for p in top if p["dex"] not in ("uniswap-v3-robinhood",)), top[0] if top else None)
if pick:
    for tf, agg in [("minute", 1), ("minute", 5)]:
        c, b = gt(f"/pools/{pick['addr']}/ohlcv/{tf}?aggregate={agg}&limit=1000")
        if c == 200:
            lst = b["data"]["attributes"]["ohlcv_list"]
            OUT[f"gt_ohlcv_{tf}{agg}"] = {"pool": pick["name"], "candles": len(lst),
                "oldest": time.strftime("%Y-%m-%d %H:%M", time.gmtime(lst[-1][0])) if lst else None,
                "newest": time.strftime("%Y-%m-%d %H:%M", time.gmtime(lst[0][0])) if lst else None}
        else:
            OUT[f"gt_ohlcv_{tf}{agg}"] = c
    c, b = gt(f"/pools/{pick['addr']}/trades")
    OUT["gt_trades"] = f"{c} rows={len(b.get('data', []))}" if c == 200 else c
    c, b = gt(f"/pools/{pick['addr']}/ohlcv/minute?aggregate=1&limit=1000&before_timestamp={int(time.time()) - 3 * 86400}")
    OUT["gt_ohlcv_minute_3d_ago"] = (len(b["data"]["attributes"]["ohlcv_list"]) if c == 200 else c)

print(json.dumps(OUT, indent=1, default=str))
