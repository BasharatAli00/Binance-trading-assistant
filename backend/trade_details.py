import sys
import os
from sqlalchemy.orm import Session
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    query = text("""
        SELECT portfolio_id, mint, entry_time, exit_time, entry_price, exit_price, qty, position_usd, cost_basis, realized_pnl, return_pct
        FROM copy_position 
        WHERE mint LIKE '2SxXQssY%'
        ORDER BY portfolio_id
    """)
    res = db.execute(query).fetchall()
    for r in res:
        print(f"PF: {r.portfolio_id} | Entry: {r.entry_time} @ ${r.entry_price:.6f} | Exit: {r.exit_time} @ ${r.exit_price:.6f} | Qty: {r.qty:.2f} | PNL: ${r.realized_pnl:.2f} ({r.return_pct:.1f}%)")

except Exception as e:
    print(e)
finally:
    db.close()
