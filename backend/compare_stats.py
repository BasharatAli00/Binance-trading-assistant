import sys
import os
from sqlalchemy.orm import Session
from database import SessionLocal
from sqlalchemy import text
from datetime import datetime

db = SessionLocal()
try:
    print("--- Sim vs Live Positions ---")
    query = text("""
        SELECT p.portfolio_id, pf.name, COUNT(*) as trades, 
               AVG(p.cost_basis) as avg_invested, 
               SUM(p.realized_pnl) as total_pnl
        FROM copy_position p
        JOIN copy_portfolio pf ON p.portfolio_id = pf.id
        GROUP BY p.portfolio_id, pf.name
    """)
    result = db.execute(query).fetchall()
    for r in result:
        print(f"Portfolio {r.portfolio_id} ({r.name}): {r.trades} trades | Avg Invested: ${r.avg_invested:.2f} | Total PNL: ${r.total_pnl:.2f}")

    print("\n--- Recent Trades (Sim vs Live on Same Mint) ---")
    query2 = text("""
        SELECT p1.mint, 
               p1.cost_basis as sim_inv, p1.realized_pnl as sim_pnl, p1.return_pct as sim_roi,
               p2.cost_basis as live_inv, p2.realized_pnl as live_pnl, p2.return_pct as live_roi
        FROM copy_position p1
        JOIN copy_position p2 ON p1.mint = p2.mint AND p1.portfolio_id = 1 AND p2.portfolio_id = 2
        ORDER BY p1.entry_time DESC LIMIT 5
    """)
    res2 = db.execute(query2).fetchall()
    for r in res2:
        sim_inv = r.sim_inv or 0
        sim_pnl = r.sim_pnl or 0
        sim_roi = r.sim_roi or 0
        live_inv = r.live_inv or 0
        live_pnl = r.live_pnl or 0
        live_roi = r.live_roi or 0
        print(f"Mint {r.mint[:8]}... | SIM: ${sim_inv:.2f} inv -> ${sim_pnl:.2f} PNL ({sim_roi:.1f}%) | LIVE: ${live_inv:.2f} inv -> ${live_pnl:.2f} PNL ({live_roi:.1f}%)")

except Exception as e:
    print(e)
finally:
    db.close()
