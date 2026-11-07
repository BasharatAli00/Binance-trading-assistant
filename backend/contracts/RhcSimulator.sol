// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title RhcSimulator: read-only buy -> sell round-trip simulator
/// @notice NEVER deployed. It is injected at a throw-away address through eth_call
///         state overrides, so every effect is discarded after the call. It needs no keys
///         and moves no real funds. It measures, at the intended trade size and through the
///         pool's own contract:
///           r[0] status    0 ok | 1 buy reverted | 2 token transfer to pool reverted (sell blocked)
///                          3 sell swap reverted | 4 bought zero tokens
///           r[1] tokens the pool says it sent on the buy
///           r[2] tokens actually received        -> buy (receive) tax = 1 - r2/r1
///           r[3] tokens the pool actually got     -> sell (send) tax   = 1 - r3/r2
///           r[4] quote the pool says it sent on the sell
///           r[5] quote actually received          -> round-trip cost   = 1 - r5/amountIn
///           r[6] gas used by the buy, r[7] gas used by the sell
contract RhcSimulator {
    uint160 internal constant MIN_SQRT = 4295128740;
    uint160 internal constant MAX_SQRT = 1461446703485210103287273052203988822378723970341;

    error Stage(uint256 code, uint256[8] r);

    receive() external payable {}

    // ── helpers ──────────────────────────────────────────────────────────────
    function _bal(address token, address who) internal view returns (uint256) {
        if (token == address(0)) return who.balance;
        (bool ok, bytes memory d) = token.staticcall(abi.encodeWithSelector(0x70a08231, who));
        return ok && d.length >= 32 ? abi.decode(d, (uint256)) : 0;
    }

    function _transfer(address token, address to, uint256 v) internal returns (bool) {
        (bool ok, bytes memory d) = token.call(abi.encodeWithSelector(0xa9059cbb, to, v));
        return ok && (d.length == 0 || (d.length >= 32 && abi.decode(d, (bool))));
    }

    function _out(uint256 amountIn, uint256 rIn, uint256 rOut, uint256 feeBps) internal pure returns (uint256) {
        if (amountIn == 0 || rIn == 0 || rOut == 0) return 0;
        uint256 inWithFee = amountIn * (10000 - feeBps);
        return (inWithFee * rOut) / (rIn * 10000 + inWithFee);
    }

    // ── Uniswap v2-style pairs ───────────────────────────────────────────────
    function simV2(address pair, address quote, address token, uint256 amountIn, uint256 feeBps)
        external
        returns (uint256[8] memory r)
    {
        bool quoteIs0 = IV2Pair(pair).token0() == quote;
        (uint112 a, uint112 b,) = IV2Pair(pair).getReserves();
        (uint256 rq, uint256 rt) = quoteIs0 ? (uint256(a), uint256(b)) : (uint256(b), uint256(a));
        uint256 out = _out(amountIn, rq, rt, feeBps);
        r[1] = out;
        uint256 g = gasleft();
        if (!_transfer(quote, pair, amountIn)) { r[0] = 1; return r; }
        uint256 before = _bal(token, address(this));
        try IV2Pair(pair).swap(quoteIs0 ? 0 : out, quoteIs0 ? out : 0, address(this), "") {}
        catch { r[0] = 1; return r; }
        r[2] = _bal(token, address(this)) - before;
        r[6] = g - gasleft();
        if (r[2] == 0) { r[0] = 4; return r; }

        g = gasleft();
        (a, b,) = IV2Pair(pair).getReserves();
        (rq, rt) = quoteIs0 ? (uint256(a), uint256(b)) : (uint256(b), uint256(a));
        if (!_transfer(token, pair, r[2])) { r[0] = 2; return r; }
        uint256 effIn = _bal(token, pair) - rt;           // what the pair will count as input
        r[3] = effIn;
        uint256 qOut = _out(effIn, rt, rq, feeBps);
        r[4] = qOut;
        uint256 qb = _bal(quote, address(this));
        try IV2Pair(pair).swap(quoteIs0 ? qOut : 0, quoteIs0 ? 0 : qOut, address(this), "") {}
        catch { r[0] = 3; return r; }
        r[5] = _bal(quote, address(this)) - qb;
        r[7] = g - gasleft();
    }

    /// Sell-only (exit simulation): the simulator already holds `amount` tokens via a balance override.
    /// Returns r[3] tokens the pair counted, r[4] quote the pair sent, r[5] quote received, r[7] gas.
    function simSellV2(address pair, address quote, address token, uint256 amount, uint256 feeBps)
        external
        returns (uint256[8] memory r)
    {
        bool quoteIs0 = IV2Pair(pair).token0() == quote;
        uint256 g = gasleft();
        (uint112 a, uint112 b,) = IV2Pair(pair).getReserves();
        (uint256 rq, uint256 rt) = quoteIs0 ? (uint256(a), uint256(b)) : (uint256(b), uint256(a));
        r[2] = amount;
        if (!_transfer(token, pair, amount)) { r[0] = 2; return r; }
        uint256 effIn = _bal(token, pair) - rt;
        r[3] = effIn;
        uint256 qOut = _out(effIn, rt, rq, feeBps);
        r[4] = qOut;
        uint256 qb = _bal(quote, address(this));
        try IV2Pair(pair).swap(quoteIs0 ? qOut : 0, quoteIs0 ? 0 : qOut, address(this), "") {}
        catch { r[0] = 3; return r; }
        r[5] = _bal(quote, address(this)) - qb;
        r[7] = g - gasleft();
    }

    // ── Uniswap v3-style pools (also Pancake v3 / Algebra callbacks) ─────────
    function simSellV3(address pool, address quote, address token, uint256 amount)
        external
        returns (uint256[8] memory r)
    {
        bool quoteIs0 = uint160(quote) < uint160(token);
        uint256 g = gasleft();
        r[2] = amount;
        uint256 qb = _bal(quote, address(this));
        try IV3Pool(pool).swap(address(this), !quoteIs0, int256(amount), quoteIs0 ? MAX_SQRT : MIN_SQRT,
                               abi.encode(token)) returns (int256 d0, int256 d1) {
            int256 dq = quoteIs0 ? d0 : d1;
            int256 dt = quoteIs0 ? d1 : d0;
            r[4] = dq < 0 ? uint256(-dq) : 0;
            r[3] = dt > 0 ? uint256(dt) : 0;
        } catch { r[0] = 3; return r; }
        r[5] = _bal(quote, address(this)) - qb;
        r[7] = g - gasleft();
    }
    function simV3(address pool, address quote, address token, uint256 amountIn)
        external
        returns (uint256[8] memory r)
    {
        bool quoteIs0 = uint160(quote) < uint160(token);
        uint256 g = gasleft();
        uint256 before = _bal(token, address(this));
        try IV3Pool(pool).swap(address(this), quoteIs0, int256(amountIn), quoteIs0 ? MIN_SQRT : MAX_SQRT,
                               abi.encode(quote)) returns (int256 d0, int256 d1) {
            int256 dt = quoteIs0 ? d1 : d0;
            r[1] = dt < 0 ? uint256(-dt) : 0;
        } catch { r[0] = 1; return r; }
        r[2] = _bal(token, address(this)) - before;
        r[6] = g - gasleft();
        if (r[2] == 0) { r[0] = 4; return r; }

        g = gasleft();
        uint256 qb = _bal(quote, address(this));
        try IV3Pool(pool).swap(address(this), !quoteIs0, int256(r[2]), quoteIs0 ? MAX_SQRT : MIN_SQRT,
                               abi.encode(token)) returns (int256 d0, int256 d1) {
            int256 dq = quoteIs0 ? d0 : d1;
            int256 dt = quoteIs0 ? d1 : d0;
            r[4] = dq < 0 ? uint256(-dq) : 0;
            r[3] = dt > 0 ? uint256(dt) : 0;
        } catch { r[0] = 3; return r; }
        r[5] = _bal(quote, address(this)) - qb;
        r[7] = g - gasleft();
    }

    function _pay(int256 d0, int256 d1, bytes calldata data) internal {
        address payToken = abi.decode(data, (address));
        uint256 amt = uint256(d0 > 0 ? d0 : d1);
        require(_transfer(payToken, msg.sender, amt), "pay");
    }

    function uniswapV3SwapCallback(int256 d0, int256 d1, bytes calldata data) external { _pay(d0, d1, data); }
    function pancakeV3SwapCallback(int256 d0, int256 d1, bytes calldata data) external { _pay(d0, d1, data); }
    function algebraSwapCallback(int256 d0, int256 d1, bytes calldata data) external { _pay(d0, d1, data); }

    // ── Uniswap v4 (PoolManager singleton) ───────────────────────────────────
    function simV4(address pm, PoolKey calldata key, bool quoteIs0, uint256 amountIn)
        external
        payable
        returns (uint256[8] memory r)
    {
        return _runV4(pm, key, quoteIs0, amountIn, false);
    }

    /// Sell-only (exit simulation) for v4: the simulator holds `amount` tokens via a balance override.
    function simSellV4(address pm, PoolKey calldata key, bool quoteIs0, uint256 amount)
        external
        returns (uint256[8] memory r)
    {
        return _runV4(pm, key, quoteIs0, amount, true);
    }

    function _runV4(address pm, PoolKey calldata key, bool quoteIs0, uint256 amount, bool sellOnly)
        internal
        returns (uint256[8] memory r)
    {
        try IPoolManager(pm).unlock(abi.encode(key, quoteIs0, amount, sellOnly)) returns (bytes memory res) {
            r = abi.decode(res, (uint256[8]));
        } catch (bytes memory err) {
            if (err.length >= 4 && bytes4(err) == Stage.selector) {
                bytes memory body = new bytes(err.length - 4);
                for (uint256 i = 0; i < body.length; i++) body[i] = err[i + 4];
                (uint256 code, uint256[8] memory partialR) = abi.decode(body, (uint256, uint256[8]));
                r = partialR;
                r[0] = code;
            } else {
                r[0] = 1;   // reverted before our first checkpoint (e.g. hook rejected the caller)
            }
        }
    }

    function _settle(IPoolManager pm, address currency, uint256 amount) internal returns (uint256 paid) {
        if (currency == address(0)) return pm.settle{value: amount}();
        pm.sync(currency);
        if (!_transfer(currency, address(pm), amount)) return type(uint256).max;
        return pm.settle();
    }

    function _amounts(int256 delta) internal pure returns (int128 a0, int128 a1) {
        a0 = int128(delta >> 128);
        a1 = int128(delta);
    }

    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        (PoolKey memory key, bool quoteIs0, uint256 amountIn, bool sellOnly) =
            abi.decode(data, (PoolKey, bool, uint256, bool));
        IPoolManager pm = IPoolManager(msg.sender);
        uint256[8] memory r;
        if (sellOnly) {
            r[2] = amountIn;
            _sellV4(pm, key, quoteIs0, r);
            return abi.encode(r);
        }
        address quote = quoteIs0 ? key.currency0 : key.currency1;
        address token = quoteIs0 ? key.currency1 : key.currency0;

        // Buy: credit the quote, swap exact-in, take the tokens.
        uint256 g = gasleft();
        if (_settle(pm, quote, amountIn) == type(uint256).max) revert Stage(1, r);
        int256 delta;
        try pm.swap(key, SwapParams(quoteIs0, -int256(amountIn), quoteIs0 ? MIN_SQRT : MAX_SQRT), "")
            returns (int256 d) { delta = d; } catch { revert Stage(1, r); }
        (int128 b0, int128 b1) = _amounts(delta);
        int128 tokD = quoteIs0 ? b1 : b0;
        int128 quoteD = quoteIs0 ? b0 : b1;
        r[1] = tokD > 0 ? uint256(int256(tokD)) : 0;
        uint256 before = _bal(token, address(this));
        if (r[1] > 0) pm.take(token, address(this), r[1]);
        r[2] = _bal(token, address(this)) - before;
        uint256 spent = quoteD < 0 ? uint256(int256(-quoteD)) : 0;
        if (spent < amountIn) pm.take(quote, address(this), amountIn - spent);   // partial fill refund
        r[6] = g - gasleft();
        if (r[2] == 0) revert Stage(4, r);

        _sellV4(pm, key, quoteIs0, r);
        return abi.encode(r);
    }

    /// Sell r[2] tokens: credit them (a transfer tax shows up as paid < sent), swap exact-in, take the quote.
    function _sellV4(IPoolManager pm, PoolKey memory key, bool quoteIs0, uint256[8] memory r) internal {
        address quote = quoteIs0 ? key.currency0 : key.currency1;
        address token = quoteIs0 ? key.currency1 : key.currency0;
        uint256 g = gasleft();
        uint256 paid = _settle(pm, token, r[2]);
        if (paid == type(uint256).max) revert Stage(2, r);
        r[3] = paid;
        int256 delta;
        try pm.swap(key, SwapParams(!quoteIs0, -int256(paid), quoteIs0 ? MAX_SQRT : MIN_SQRT), "")
            returns (int256 d2) { delta = d2; } catch { revert Stage(3, r); }
        (int128 b0, int128 b1) = _amounts(delta);
        int128 quoteD = quoteIs0 ? b0 : b1;
        int128 tokD = quoteIs0 ? b1 : b0;
        r[4] = quoteD > 0 ? uint256(int256(quoteD)) : 0;
        uint256 used = tokD < 0 ? uint256(int256(-tokD)) : 0;
        uint256 qb = _bal(quote, address(this));
        if (r[4] > 0) pm.take(quote, address(this), r[4]);
        r[5] = _bal(quote, address(this)) - qb;
        if (used < paid) pm.take(token, address(this), paid - used);
        r[7] = g - gasleft();
    }
}

struct PoolKey {
    address currency0;
    address currency1;
    uint24 fee;
    int24 tickSpacing;
    address hooks;
}

struct SwapParams {
    bool zeroForOne;
    int256 amountSpecified;
    uint160 sqrtPriceLimitX96;
}

interface IV2Pair {
    function token0() external view returns (address);
    function getReserves() external view returns (uint112, uint112, uint32);
    function swap(uint256 amount0Out, uint256 amount1Out, address to, bytes calldata data) external;
}

interface IV3Pool {
    function swap(address recipient, bool zeroForOne, int256 amountSpecified, uint160 sqrtPriceLimitX96,
                  bytes calldata data) external returns (int256, int256);
}

interface IPoolManager {
    function unlock(bytes calldata data) external returns (bytes memory);
    function swap(PoolKey memory key, SwapParams memory params, bytes calldata hookData) external returns (int256);
    function settle() external payable returns (uint256);
    function sync(address currency) external;
    function take(address currency, address to, uint256 amount) external;
}
