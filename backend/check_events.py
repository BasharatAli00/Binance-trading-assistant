import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print("Checking latest Helius and QuickNode valid events in copy_wallet_event...")
    query = text("SELECT source, MAX(block_time) FROM copy_wallet_event GROUP BY source")
    result = db.execute(query).fetchall()
    
    for row in result:
        print(f"Source: {row[0]} -> Latest valid trade event: {row[1]} (UTC)")
        
finally:
    db.close()
