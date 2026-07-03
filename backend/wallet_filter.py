import os
import sys
from datetime import datetime
import json
from collections import defaultdict
from sqlalchemy.orm import Session

# Allow importing backend modules
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from database import SessionLocal
from models import CopyPosition, CopyWatchedWallet, CopyBannedWallet, CopySuperstarWallet

def analyze_wallets():
    print(f"[{datetime.utcnow().isoformat()}] Starting wallet filter purge...")
    db = SessionLocal()
    try:
        # Get all closed positions
        positions = db.query(CopyPosition).filter(CopyPosition.status == 'closed').all()
        
        wallet_stats = defaultdict(lambda: {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
        })
        
        for pos in positions:
            if not pos.trigger_wallets:
                continue
            
            wallets = pos.trigger_wallets
            if isinstance(wallets, str):
                try:
                    wallets = json.loads(wallets)
                except:
                    wallets = []
                    
            for w in wallets:
                st = wallet_stats[w]
                st['total_trades'] += 1
                st['total_pnl'] += (pos.realized_pnl or 0.0)
                if (pos.realized_pnl or 0.0) > 0:
                    st['wins'] += 1
                else:
                    st['losses'] += 1
                    
        now = datetime.utcnow()
        
        banned_count = 0
        superstar_count = 0
        
        for wallet, stats in wallet_stats.items():
            if stats['total_trades'] < 3:
                continue # Grace period
                
            win_rate = (stats['wins'] / stats['total_trades']) * 100
            
            # Rule: Ban if Win Rate < 50% OR Total Pnl < 0 OR 3 trades and 0% win rate
            should_ban = False
            reason = ""
            if stats['total_trades'] == 3 and stats['wins'] == 0:
                should_ban = True
                reason = "3 strikes (0% win rate on 3 trades)"
            elif win_rate < 50.0:
                should_ban = True
                reason = f"Win rate too low: {win_rate:.1f}%"
            elif stats['total_pnl'] <= 0.0:
                should_ban = True
                reason = f"Unprofitable: ${stats['total_pnl']:.2f}"
                
            if should_ban:
                # Add to banned table if not exists
                if not db.query(CopyBannedWallet).filter_by(wallet=wallet).first():
                    db.add(CopyBannedWallet(wallet=wallet, banned_at=now, reason=reason))
                    banned_count += 1
                    print(f"BANNED: {wallet} ({reason})")
                    
                # Remove from superstar if they fell from grace
                s_row = db.query(CopySuperstarWallet).filter_by(wallet=wallet).first()
                if s_row:
                    db.delete(s_row)
                    
                # Remove from current watchlist
                w_row = db.query(CopyWatchedWallet).filter_by(wallet=wallet).first()
                if w_row:
                    db.delete(w_row)
                    
            else:
                # Check for superstar
                if win_rate >= 80.0 and stats['total_trades'] > 3:
                    if not db.query(CopySuperstarWallet).filter_by(wallet=wallet).first():
                        db.add(CopySuperstarWallet(
                            wallet=wallet, 
                            promoted_at=now, 
                            win_rate=win_rate, 
                            total_trades=stats['total_trades']
                        ))
                        superstar_count += 1
                        print(f"SUPERSTAR: {wallet} ({win_rate:.1f}% on {stats['total_trades']} trades)")
                else:
                    # They passed but aren't superstar. If they were superstar, maybe demote them?
                    # For now, let's strictly demote if they fall below 80% (but stay above 50%)
                    s_row = db.query(CopySuperstarWallet).filter_by(wallet=wallet).first()
                    if s_row and win_rate < 80.0:
                        db.delete(s_row)
                        print(f"DEMOTED SUPERSTAR: {wallet} (Fell to {win_rate:.1f}%)")

        db.commit()
        print(f"Purge complete. Banned: {banned_count}. New Superstars: {superstar_count}.")
        
    finally:
        db.close()

if __name__ == "__main__":
    analyze_wallets()
