import sys
import os
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from copytrade_helius import sync_watched_wallets
from database import SessionLocal
from models import CopyWatchedWallet

print("Testing sync_watched_wallets()...")
wallets = sync_watched_wallets()
print(f"Returned {len(wallets)} wallets.")

db = SessionLocal()
w_rows = db.query(CopyWatchedWallet).all()
print("Top 5 in DB by score:")
ranked = sorted(w_rows, key=lambda w: w.score, reverse=True)
for w in ranked[:5]:
    print(f"{w.wallet}: {w.score} ({w.source_window})")
db.close()
