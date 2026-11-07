"""Phase 0 read-only probe of Robinhood Chain RPC. No transactions, no keys."""
import json, time, statistics, sys, collections
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
S = requests.Session()
OUT = {}


def rpc(method, params, timeout=20):
    t = time.time()
    r = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
    dt = (time.time() - t) * 1000
    try:
        j = r.json()
    except Exception:
        return {"http": r.status_code, "text": r.text[:300]}, dt
    return j, dt


def res(method, params, **kw):
    j, dt = rpc(method, params, **kw)
    if isinstance(j, dict) and "error" in j:
        raise RuntimeError(f"{method}: {j['error']}")
    return j.get("result"), dt


# --- basics
cid, dt = res("eth_chainId", [])
OUT["chain_id"] = int(cid, 16)
OUT["chainId_latency_ms"] = round(dt)
try:
    OUT["client_version"], _ = res("web3_clientVersion", [])
except Exception as e:
    OUT["client_version"] = f"ERR {e}"
head_hex, _ = res("eth_blockNumber", [])
head = int(head_hex, 16)
OUT["head_block"] = head

# latency sample
lat = []
for _ in range(10):
    _, dt = rpc("eth_blockNumber", [])
    lat.append(dt)
OUT["latency_ms_p50"] = round(statistics.median(lat))
OUT["latency_ms_max"] = round(max(lat))

# block time over last 2000 blocks + over last day
b_head, _ = res("eth_getBlockByNumber", [hex(head), False])
b_old, _ = res("eth_getBlockByNumber", [hex(head - 2000), False])
ts_h, ts_o = int(b_head["timestamp"], 16), int(b_old["timestamp"], 16)
OUT["avg_block_time_s_last2000"] = round((ts_h - ts_o) / 2000, 4)
OUT["head_timestamp_utc"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts_h))
OUT["head_has_baseFee"] = "baseFeePerGas" in b_head
OUT["head_tx_count"] = len(b_head.get("transactions", []))

# genesis / block 1
b1, _ = res("eth_getBlockByNumber", ["0x1", False])
OUT["block1_timestamp_utc"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(b1["timestamp"], 16))) if b1 else None

# archive test: eth_getBalance / eth_call at an old block
for label, blk in [("block_1000", 1000), ("head_minus_1M", max(1, head - 1_000_000)), ("head_minus_10M", max(1, head - 10_000_000))]:
    j, _ = rpc("eth_getBalance", ["0x0000000000000000000000000000000000000000", hex(blk)])
    OUT[f"archive_getBalance_{label}"] = "ok" if "result" in j else f"ERR {j.get('error')}"

# eth_getLogs range limits (no filter on address -> worst case)
for rng in [100, 1000, 5000, 10000, 50000]:
    t = time.time()
    j, dt = rpc("eth_getLogs", [{"fromBlock": hex(head - rng), "toBlock": hex(head)}], timeout=60)
    if "result" in j:
        OUT[f"getLogs_range_{rng}"] = f"ok {len(j['result'])} logs in {round(dt)}ms"
    else:
        OUT[f"getLogs_range_{rng}"] = f"ERR {json.dumps(j.get('error', j))[:200]}"

# topic histogram over the last 5000 blocks (chunked 1000)
topics = collections.Counter()
emitters = collections.defaultdict(collections.Counter)
for start in range(head - 5000, head, 1000):
    j, _ = rpc("eth_getLogs", [{"fromBlock": hex(start), "toBlock": hex(start + 999)}], timeout=60)
    for lg in j.get("result", []) or []:
        if lg.get("topics"):
            t0 = lg["topics"][0]
            topics[t0] += 1
            emitters[t0][lg["address"].lower()] += 1
OUT["topic_hist_last5000"] = [
    {"topic0": t, "count": c, "distinct_emitters": len(emitters[t]),
     "top_emitter": emitters[t].most_common(1)[0]}
    for t, c in topics.most_common(25)
]

# burst rate-limit test: 60 rapid calls
codes = collections.Counter()
t = time.time()
for _ in range(60):
    try:
        r = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, timeout=10)
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        codes[f"http{r.status_code}{'_rpcerr' if 'error' in j else ''}"] += 1
    except Exception as e:
        codes[type(e).__name__] += 1
OUT["burst_60_calls"] = dict(codes)
OUT["burst_60_seconds"] = round(time.time() - t, 2)
OUT["rate_limit_headers"] = {k: v for k, v in r.headers.items() if "limit" in k.lower() or "retry" in k.lower()}

# eth_call simulation works? (WETH-ish: call decimals() on a top emitter of Transfer)
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
if TRANSFER in emitters:
    tok = emitters[TRANSFER].most_common(1)[0][0]
    j, _ = rpc("eth_call", [{"to": tok, "data": "0x313ce567"}, "latest"])
    OUT["eth_call_decimals_top_transfer_token"] = {"token": tok, "result": j.get("result"), "error": j.get("error")}
    # state override support (needed for honeypot sims without funds)
    j, _ = rpc("eth_call", [{"to": tok, "data": "0x313ce567"}, "latest",
                            {"0x1111111111111111111111111111111111111111": {"balance": "0xde0b6b3a7640000"}}])
    OUT["eth_call_state_override"] = "ok" if "result" in j else f"ERR {j.get('error')}"
# debug/trace availability
for m, p in [("debug_traceCall", [{"to": "0x0000000000000000000000000000000000000000", "data": "0x"}, "latest", {}]),
             ("trace_block", [hex(head)]),
             ("eth_subscribe", ["newHeads"])]:
    j, _ = rpc(m, p)
    OUT[f"method_{m}"] = "ok" if "result" in j else f"ERR {json.dumps(j.get('error'))[:150]}"

print(json.dumps(OUT, indent=1, default=str))
