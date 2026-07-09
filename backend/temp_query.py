import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from sqlalchemy import text
from datetime import datetime

db = SessionLocal()
try:
    print("--- Top 5 most recent records in copy_webhook_raw ---")
    query = text("SELECT id, received_at, event_type, LENGTH(payload::text) as payload_size FROM copy_webhook_raw ORDER BY received_at DESC LIMIT 5")
    result = db.execute(query).fetchall()
    
    for row in result:
        print(f"ID: {row[0]} | Received: {row[1]} | Type: {row[2]} | Payload Size: {row[3]} bytes")
        
    print("\n--- Summary of event types ---")
    summary_query = text("SELECT event_type, COUNT(*) FROM copy_webhook_raw GROUP BY event_type")
    summary = db.execute(summary_query).fetchall()
    for row in summary:
        print(f"Source: {row[0]} -> {row[1]} records")
        
finally:
    db.close()
