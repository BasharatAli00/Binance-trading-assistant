import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print("Checking latest QuickNode events in database...")
    query = text("SELECT received_at FROM copy_webhook_raw WHERE event_type = 'quicknode_stream' ORDER BY received_at DESC LIMIT 1")
    result = db.execute(query).fetchone()
    
    if result:
        print(f"Latest QuickNode event received at: {result[0]} (UTC)")
    else:
        print("No QuickNode events found in database.")
finally:
    db.close()
