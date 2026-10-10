import asyncio
import json
import websockets
from datetime import datetime

# Import our strategy modules
import liquidity_wallet
from liquidity_scalper import ScalpFSM, on_tick, Position
from liquidity_context import MarketContext

# Binance Multiplex WebSocket endpoint for BTCUSDT
BINANCE_WS_URL = "wss://stream.binance.com:9443/stream?streams=btcusdt@kline_1m/btcusdt@kline_5m/btcusdt@aggTrade"

# Global state for UI polling
LIQUIDITY_STATE = {
    "status": "IDLE",
    "message": "Waiting for market data...",
    "sweep_level": None,
    "last_update": ""
}

class MockBar:
    """A simple container to pass bar data to the FSM"""
    def __init__(self, ts, open_p, high, low, close_p, vol):
        self.ts = ts
        self.open = open_p
        self.high = high
        self.low = low
        self.close = close_p
        self.vol = vol

async def run_liquidity_engine():
    global LIQUIDITY_STATE
    print("========================================")
    print("🚀 Starting Liquidity Scalper Engine (Isolated Paper Wallet)")
    print("========================================")

    # Initialize Isolated Engine
    liquidity_wallet.ensure_initialized()
    
    # Initialize the Strategy FSM and Context
    ctx = MarketContext(liquidity_wallet)
    fsm = ScalpFSM()

    # Track open positions from FSM locally
    active_position = None

    print(f"🔗 Connecting to Binance WebSocket: {BINANCE_WS_URL}")
    
    async with websockets.connect(BINANCE_WS_URL) as ws:
        print("✅ Connected! Listening for 1m/5m candles and aggTrades...")
        LIQUIDITY_STATE["status"] = "IDLE"
        LIQUIDITY_STATE["message"] = "Connected, building data..."
        
        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                
                stream = data.get("stream")
                payload = data.get("data")
                
                if not stream or not payload:
                    continue
                    
                # ---------------------------------------------
                # 1. Handle Tick Data (aggTrade)
                # ---------------------------------------------
                if stream == "btcusdt@aggTrade":
                    price = float(payload['p'])
                    qty = float(payload['q'])
                    is_buyer_maker = payload['m']
                    ts = payload['E']
                    
                    # Update Order Flow (CVD) Math
                    ctx.flow.update_tick(price, qty, is_buyer_maker, ts)
                    
                    # Update FSM on tick if we have an active position
                    if active_position:
                        on_tick(active_position, price, ctx)
                        
                        # Check if position was closed by execution wrapper
                        pos_check = liquidity_wallet.get_position("BTCUSDT")
                        if not pos_check:
                            print(f"[ENGINE] Position closed. Resetting FSM.")
                            active_position = None
                            fsm.reset("Position exited")
                            LIQUIDITY_STATE["status"] = "IDLE"
                            LIQUIDITY_STATE["message"] = "Position closed. Waiting for new sweep..."
                
                # ---------------------------------------------
                # 2. Handle 1m Kline Closes
                # ---------------------------------------------
                elif stream == "btcusdt@kline_1m":
                    k = payload['k']
                    is_closed = k['x']
                    
                    if is_closed:
                        # Extract 1m bar data
                        bar = MockBar(
                            ts=k['t'],
                            open_p=float(k['o']),
                            high=float(k['h']),
                            low=float(k['l']),
                            close_p=float(k['c']),
                            vol=float(k['v'])
                        )
                        
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 1m close: {bar.close} | Vol: {bar.vol}")
                        
                        # Feed the math engine
                        ctx.update_1m(bar)

                        # Step the FSM
                        fsm.on_1m_close(bar, ctx)
                        
                        LIQUIDITY_STATE["status"] = fsm.state
                        LIQUIDITY_STATE["last_update"] = datetime.utcnow().strftime('%H:%M:%S')
                        if fsm.state == "SWEPT":
                            LIQUIDITY_STATE["message"] = f"Pool Swept! Waiting for Micro-MSS..."
                            LIQUIDITY_STATE["sweep_level"] = getattr(fsm.sweep, 'level', None)
                        
                        # Check if FSM armed a plan and we need to create a position
                        if fsm.state == "ARMED" and fsm.active_plan and not active_position:
                            print("[ENGINE] FSM is ARMED. Creating active position tracker...")
                            LIQUIDITY_STATE["message"] = f"ARMED! Limit placed at {fsm.active_plan.entry}"
                            active_position = Position(fsm.active_plan, bar.ts, ctx.ESTIMATED_FEES)
                            ctx.exec.place_post_only(fsm.active_plan, ttl_bars=8)
                            fsm.state = "IN_POSITION"
                            LIQUIDITY_STATE["status"] = "IN_POSITION"

                # ---------------------------------------------
                # 3. Handle 5m Kline Closes (Context Updates)
                # ---------------------------------------------
                elif stream == "btcusdt@kline_5m":
                    k = payload['k']
                    is_closed = k['x']
                    
                    if is_closed:
                        # Extract 5m bar data
                        bar_5m = MockBar(
                            ts=k['t'],
                            open_p=float(k['o']),
                            high=float(k['h']),
                            low=float(k['l']),
                            close_p=float(k['c']),
                            vol=float(k['v'])
                        )
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 5m close: {bar_5m.close}. Updating Liquidity Map...")
                        # Update the 5m liquidity map in ctx
                        ctx.update_5m(bar_5m)

            except Exception as e:
                print(f"Error processing websocket message: {e}")
                await asyncio.sleep(1)

def run_liquidity_thread():
    """Wrapper to run the async loop in a background thread from main.py"""
    asyncio.run(run_liquidity_engine())

if __name__ == "__main__":
    try:
        asyncio.run(run_liquidity_engine())
    except KeyboardInterrupt:
        print("Engine stopped by user.")
