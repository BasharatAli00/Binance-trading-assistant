import requests
from datetime import datetime
from sqlalchemy.orm import Session

from database import SessionLocal
from models import OnChainStats

def fetch_and_store_onchain_stats():
    """Fetches live Bitcoin network statistics and stores them in the database."""
    url = "https://blockchain.info/stats?format=json"
    
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        n_tx = data.get('n_tx', 0)
        total_fees_btc = data.get('total_fees_btc', 0.0)
        # Often provided in smaller units, we leave it as API gives or convert if necessary.
        # blockchain.info/stats returns total_fees_btc usually as btc but sometimes satoshis depending on endpoint.
        # The prompt specifically lists total_fees_btc, hash_rate, difficulty, estimated_transaction_volume_usd.
        
        # It's actually 'total_fees_btc' in the JSON, but let's safely get it.
        # To be completely safe against missing keys, we use .get with default 0.0.
        hash_rate = data.get('hash_rate', 0.0)
        difficulty = data.get('difficulty', 0.0)
        estimated_transaction_volume_usd = data.get('estimated_transaction_volume_usd', 0.0)
        
        db: Session = SessionLocal()
        try:
            # Check if we already fetched recently (e.g. within last 30 minutes) to avoid dupes, 
            # or just rely on the hourly scheduler.
            new_stats = OnChainStats(
                timestamp=datetime.utcnow(),
                n_tx=n_tx,
                total_fees_btc=total_fees_btc / 100000000.0 if data.get('total_fees_btc', 0) > 1000 else total_fees_btc, # Some APIs return satoshis
                hash_rate=hash_rate,
                difficulty=difficulty,
                estimated_transaction_volume_usd=estimated_transaction_volume_usd
            )
            
            db.add(new_stats)
            db.commit()
            print("Fetched and stored new Blockchain on-chain stats.")
            
        finally:
            db.close()
            
    except Exception as e:
        print(f"Failed to fetch or store on-chain stats: {e}")

if __name__ == "__main__":
    fetch_and_store_onchain_stats()
