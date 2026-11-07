"""Record real Robinhood Chain logs + pool metadata as offline test fixtures.

Read-only. Run from repo root:
    backend/.venv/Scripts/python.exe backend/tests/fixtures/record_rhc_fixtures.py
Writes backend/tests/fixtures/rhc_logs.json. Re-running replaces the fixture.
"""
import json
import os
import requests

RPC = os.getenv("RHC_FIXTURE_RPC", "https://rpc.mainnet.chain.robinhood.com")
S = requests.Session()
PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
REF_V3 = "0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca"  # USDG/WETH 0.01% Uniswap v3
T = {
    "v2_pair_created": "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9",
    "v2_swap": "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
    "v2_sync": "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1",
    "v2_mint": "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f",
    "v3_pool_created": "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
    "v3_swap": "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
    "v4_initialize": "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438",
    "v4_swap": "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f",
    "v4_modify_liquidity": "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec",
}


def rpc(m, p):
    j = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=90).json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]


def call(to, data):
    return rpc("eth_call", [{"to": to, "data": data}, "latest"])


def addr(word):
    return "0x" + word[-40:]


def decimals(token):
    if token == "0x" + "0" * 40:
        return 18
    return int(call(token, "0x313ce567"), 16)


head = int(rpc("eth_blockNumber", []), 16)
out = {"recorded_at_block": head, "logs": {}, "meta": {}}

def logs(flt, frm, to):
    return rpc("eth_getLogs", [dict(flt, fromBlock=hex(frm), toBlock=hex(to))])

# v3 reference pool swaps
out["logs"]["v3_swap"] = logs({"address": REF_V3, "topics": [T["v3_swap"]]}, head - 3000, head - 30)[:3]
t0, t1 = addr(call(REF_V3, "0x0dfe1681")), addr(call(REF_V3, "0xd21220a7"))
out["meta"][REF_V3] = {"token0": t0, "token1": t1, "dec0": decimals(t0), "dec1": decimals(t1)}

# v3 pool creation
out["logs"]["v3_pool_created"] = logs({"topics": [T["v3_pool_created"]]}, head - 29_000, head - 30)[:2]

# v2: a pair with Swap + Sync in the same tx
sw = logs({"topics": [T["v2_swap"]]}, head - 20_000, head - 30)
chosen = None
for s in sw:
    sy = [l for l in logs({"address": s["address"], "topics": [T["v2_sync"]]}, int(s["blockNumber"], 16), int(s["blockNumber"], 16))
          if l["transactionHash"] == s["transactionHash"]]
    if sy:
        chosen = (s, sy[-1])
        break
if chosen:
    out["logs"]["v2_swap"] = [chosen[0]]
    out["logs"]["v2_sync"] = [chosen[1]]
    pair = chosen[0]["address"]
    a0, a1 = addr(call(pair, "0x0dfe1681")), addr(call(pair, "0xd21220a7"))
    out["meta"][pair] = {"token0": a0, "token1": a1, "dec0": decimals(a0), "dec1": decimals(a1),
                         "factory": addr(call(pair, "0xc45a0155"))}
out["logs"]["v2_pair_created"] = logs({"topics": [T["v2_pair_created"]]}, head - 29_000, head - 30)[:2]
out["logs"]["v2_mint"] = logs({"topics": [T["v2_mint"]]}, head - 29_000, head - 30)[:1]

# v4
out["logs"]["v4_initialize"] = logs({"address": PM, "topics": [T["v4_initialize"]]}, head - 20_000, head - 30)[:3]
v4s = logs({"address": PM, "topics": [T["v4_swap"]]}, head - 600, head - 30)
out["logs"]["v4_swap"] = v4s[:4]
out["logs"]["v4_modify_liquidity"] = logs({"address": PM, "topics": [T["v4_modify_liquidity"]]}, head - 3000, head - 30)[:2]

# decimals for v4 currencies in fixtures
for l in out["logs"]["v4_initialize"]:
    c0, c1 = addr(l["topics"][2]), addr(l["topics"][3])
    out["meta"][l["topics"][1]] = {"token0": c0, "token1": c1, "dec0": decimals(c0), "dec1": decimals(c1)}

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rhc_logs.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print("wrote", path, {k: len(v) for k, v in out["logs"].items()})
