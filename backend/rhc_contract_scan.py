"""Contract permission analysis from bytecode (no verified source needed).

* Extracts the 4-byte selectors a contract's dispatcher compares against (PUSH4 operands),
  then matches them against known risky function signatures.
* Detects proxies (EIP-1967 implementation/beacon slots, EIP-1167 minimal proxies) and scans
  the implementation as well.
* Reads owner()/getOwner() to tell whether owner-only powers are still live.

Limits (documented): selector matching cannot see renamed or obfuscated functions, nor
restrictions implemented inside transfer(); the round-trip simulation covers the latter
behaviourally at the moment of screening.
"""
import hashlib
from dataclasses import dataclass, field

from eth_utils import function_signature_to_4byte_selector

from rhc_decoders import ZERO_ADDR

SLOT_1967_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
SLOT_1967_BEACON = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
BURN_OWNERS = {ZERO_ADDR, "0x000000000000000000000000000000000000dead"}

RISKY = {
    "MINT_FN": ["mint(address,uint256)", "mint(uint256)", "mintTo(address,uint256)", "issue(uint256)",
                "mintFor(address,uint256)"],
    "BLACKLIST_FN": ["blacklist(address)", "addBlacklist(address)", "addToBlacklist(address)",
                     "setBlacklist(address,bool)", "blacklistAddress(address,bool)", "setBots(address[],bool)",
                     "addBots(address[])", "setBot(address,bool)", "blockBots(address[])", "setBlacklisted(address,bool)",
                     "addBot(address)", "bots(address)", "isBlacklisted(address)"],
    "PAUSE_FN": ["pause()", "unpause()", "setPaused(bool)"],
    "FEE_SETTER_FN": ["setFee(uint256)", "setFees(uint256,uint256)", "setTaxes(uint256,uint256)",
                      "setBuyFee(uint256)", "setSellFee(uint256)", "setBuyTax(uint256)", "setSellTax(uint256)",
                      "updateFees(uint256,uint256)", "setTaxFeePercent(uint256)", "setTax(uint256)",
                      "updateBuyFees(uint256,uint256,uint256)", "updateSellFees(uint256,uint256,uint256)",
                      "reduceFee(uint256)", "setFee(uint256,uint256)"],
    "MAXTX_SETTER_FN": ["setMaxTxAmount(uint256)", "setMaxWalletSize(uint256)", "setMaxWallet(uint256)",
                        "updateMaxTxnAmount(uint256)", "updateMaxWalletAmount(uint256)", "setMaxTx(uint256)",
                        "setMaxTxPercent(uint256)"],
    "TRADING_TOGGLE_FN": ["enableTrading()", "openTrading()", "setTradingEnabled(bool)", "setTrading(bool)",
                          "startTrading()", "tradingStatus(bool)"],
    "UPGRADE_FN": ["upgradeTo(address)", "upgradeToAndCall(address,bytes)"],
}
SELECTORS = {name: {"0x" + function_signature_to_4byte_selector(s).hex(): s for s in sigs}
             for name, sigs in RISKY.items()}

SEL_OWNER = "0x8da5cb5b"
SEL_GET_OWNER = "0x893d20e8"


def extract_push4(code_hex):
    """Selectors used by the dispatcher: operands of PUSH4, skipping other PUSH data correctly."""
    code = bytes.fromhex(code_hex[2:] if code_hex.startswith("0x") else code_hex)
    out = set()
    i, n = 0, len(code)
    while i < n:
        op = code[i]
        if 0x60 <= op <= 0x7f:
            width = op - 0x5f
            if op == 0x63 and i + 5 <= n:
                out.add("0x" + code[i + 1:i + 5].hex())
            i += 1 + width
        else:
            i += 1
    return out


def minimal_proxy_target(code_hex):
    c = code_hex.lower().removeprefix("0x")
    if c.startswith("363d3d373d3d3d363d73") and len(c) >= 20 + 40:
        return "0x" + c[20:60]
    return None


@dataclass
class ContractReport:
    address: str
    has_code: bool
    code_size: int = 0
    code_hash: str = None
    proxy: str = None                 # eip1967 | beacon | eip1167 | None
    implementation: str = None
    owner: str = None                 # None = no owner() function
    owner_active: bool = False
    functions: dict = field(default_factory=dict)   # flag -> [matched signatures]

    def flags(self):
        f = set(k for k, v in self.functions.items() if v)
        if self.proxy in ("eip1967", "beacon"):
            f.add("UPGRADEABLE_PROXY")
        return f


def classify(report):
    """Pure: map a ContractReport to reason codes."""
    if not report.has_code:
        return ["NO_CODE"]
    codes = []
    f = report.flags()
    # No owner() at all (e.g. role-based access control): renouncement cannot be proven, so
    # owner-only powers are treated as live. Capital preservation over optimism.
    live = report.owner_active or report.owner is None
    if "UPGRADEABLE_PROXY" in f:
        codes.append("UPGRADEABLE")
    if "MINT_FN" in f and live:
        codes.append("MINTABLE")
    if "BLACKLIST_FN" in f and live:
        codes.append("BLACKLIST")
    if "PAUSE_FN" in f and live:
        codes.append("PAUSABLE")
    if "FEE_SETTER_FN" in f and live:
        codes.append("FEE_SETTER")
    if "MAXTX_SETTER_FN" in f and live:
        codes.append("MAXTX_SETTER")
    if "TRADING_TOGGLE_FN" in f and live:
        codes.append("TRADING_TOGGLE")
    if report.owner_active:
        codes.append("OWNER_ACTIVE")
    return codes


def scan_selectors(code_hex):
    present = extract_push4(code_hex)
    return {name: sorted(sigs[s] for s in present if s in sigs) for name, sigs in SELECTORS.items()}


def _word_addr(result):
    if isinstance(result, str) and len(result) >= 66:
        a = "0x" + result[-40:].lower()
        return a
    return None


def scan_contract(rpc, address):
    """Fetch code, proxy slots and owner in two batched round trips."""
    address = address.lower()
    res = rpc.batch([
        ("eth_getCode", [address, "latest"]),
        ("eth_getStorageAt", [address, SLOT_1967_IMPL, "latest"]),
        ("eth_getStorageAt", [address, SLOT_1967_BEACON, "latest"]),
        ("eth_call", [{"to": address, "data": SEL_OWNER}, "latest"]),
        ("eth_call", [{"to": address, "data": SEL_GET_OWNER}, "latest"]),
    ])
    code = res[0] if isinstance(res[0], str) else "0x"
    rep = ContractReport(address=address, has_code=len(code) > 2)
    if not rep.has_code:
        return rep
    rep.code_size = (len(code) - 2) // 2
    rep.code_hash = hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()[:16]
    impl = _word_addr(res[1]) if isinstance(res[1], str) and int(res[1], 16) else None
    beacon = _word_addr(res[2]) if isinstance(res[2], str) and int(res[2], 16) else None
    target = minimal_proxy_target(code)
    codes_to_scan = [code]
    if impl:
        rep.proxy, rep.implementation = "eip1967", impl
    elif beacon:
        rep.proxy, rep.implementation = "beacon", beacon
    elif target:
        rep.proxy, rep.implementation = "eip1167", target
    if rep.implementation and rep.proxy != "beacon":
        icode = rpc.call("eth_getCode", [rep.implementation, "latest"])
        if isinstance(icode, str) and len(icode) > 2:
            codes_to_scan.append(icode)
    merged = {k: [] for k in SELECTORS}
    for c in codes_to_scan:
        for k, v in scan_selectors(c).items():
            merged[k] = sorted(set(merged[k]) | set(v))
    rep.functions = merged
    owner = _word_addr(res[3]) or _word_addr(res[4])
    rep.owner = owner
    rep.owner_active = bool(owner and owner not in BURN_OWNERS)
    return rep
