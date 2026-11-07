"""Probe 3: label factories/hooks via DexScreener; deep log history. Read-only."""
import json, time, collections
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
S = requests.Session()
OUT = {}


def rpc(m, p, timeout=90):
    return S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=timeout).json()


head = int(rpc("eth_blockNumber", [])["result"], 16)
SPAN = 300_000  # ~8h

def logs(addr, t0, frm, to):
    j = rpc("eth_getLogs", [{"address": addr, "fromBlock": hex(frm), "toBlock": hex(to), "topics": [t0]}])
    return j.get("result") or [], j.get("error")

def ds_pair(pair):
    time.sleep(0.4)
    r = S.get(f"https://api.dexscreener.com/latest/dex/pairs/robinhood/{pair}", timeout=20)
    if not r.ok:
        return {"http": r.status_code}
    ps = r.json().get("pairs") or []
    if not ps:
        return {"found": False}
    p = ps[0]
    return {"dexId": p.get("dexId"), "labels": p.get("labels"), "pair": f"{p['baseToken']['symbol']}/{p['quoteToken']['symbol']}",
            "liq": (p.get("liquidity") or {}).get("usd"), "url": p.get("url")}

PAIR = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
POOL3 = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"
INIT4 = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"

labels = {}
for fac in ["0x8bceaa40b9acdfaedf85adf4ff01f5ad6517937f", "0x0d1ebb179cdbca88d74c923c4255cb2b17474afd",
            "0x02a84c1b3bbd7401a5f7fa98a384ebc70bb5749e", "0xfc2e4da3edb2e18100473339c763705d263d20a9"]:
    ls, err = logs(fac, PAIR, head - 864_000, head)
    samples = []
    for l in ls[-3:]:
        pair = "0x" + l["data"][2:66][-40:]
        samples.append(ds_pair(pair))
    labels[f"v2factory {fac}"] = {"pairs_24h": len(ls), "samples": samples, "err": err}

for fac in ["0x1f7d7550b1b028f7571e69a784071f0205fd2efa", "0x221a6239e40709792b0d4bdc140fa36158cd41c7"]:
    ls, err = logs(fac, POOL3, head - 864_000, head)
    samples = []
    for l in ls[-3:]:
        pool = "0x" + l["data"][-40:]
        samples.append(ds_pair(pool))
    labels[f"v3factory {fac}"] = {"pools_24h": len(ls), "samples": samples, "err": err}

ls, err = logs(PM, INIT4, head - SPAN, head)
by_hook = collections.defaultdict(list)
for l in ls:
    words = [l["data"][2:][i:i + 64] for i in range(0, len(l["data"]) - 2, 64)]
    by_hook["0x" + words[2][-40:]].append(l["topics"][1])
for hook in ["0x0000000000000000000000000000000000000000", "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544",
             "0x2c668601193e4a081dd82604785e436aff6a2acc", "0x15e5e7206c661a1e881f5cd33a94eaf2328fa8cc",
             "0x4eb1976978756bd56802d8162f2271844924e0cc", "0x0af57f62982d03066ef917acad87f771c06528ec"]:
    ids = by_hook.get(hook, [])
    labels[f"v4hook {hook}"] = {"pools_8h": len(ids), "samples": [ds_pair(i) for i in ids[-3:]]}
OUT["labels"] = labels

# deep history: do old logs still exist? (v4 Initialize at several historical windows)
for back in [5_000_000, 20_000_000, 50_000_000, 90_000_000]:
    frm = max(1, head - back)
    ls, err = logs(PM, INIT4, frm, frm + 100_000)
    OUT[f"logs_{back}_blocks_back"] = {"n": len(ls), "err": err,
        "approx_days_back": round(back * 0.104 / 86400, 1)}
print(json.dumps(OUT, indent=1, default=str))
