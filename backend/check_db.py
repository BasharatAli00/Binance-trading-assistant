import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from models import CopyWebhookRaw, CopyWalletEvent, CopySignal

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

print("=== CopyWebhookRaw (Last 3) ===")
raws = session.query(CopyWebhookRaw).order_by(CopyWebhookRaw.id.desc()).limit(3).all()
if not raws:
    print("No raw webhooks found.")
else:
    for r in raws:
        print(f"ID: {r.id} | Type: {r.event_type} | Received: {r.received_at}")
        # Only print first 200 chars of payload
        payload_str = str(r.payload)[:200]
        print(f"  Payload snippet: {payload_str}...")

print("\n=== CopyWalletEvent (Last 3) ===")
events = session.query(CopyWalletEvent).order_by(CopyWalletEvent.id.desc()).limit(3).all()
if not events:
    print("No wallet events found.")
else:
    for e in events:
        print(f"ID: {e.id} | Wallet: {e.wallet} | Side: {e.side} | Mint: {e.mint} | BlockTime: {e.block_time}")

print("\n=== CopySignal (Last 3) ===")
signals = session.query(CopySignal).order_by(CopySignal.id.desc()).limit(3).all()
if not signals:
    print("No signals found.")
else:
    for s in signals:
        print(f"ID: {s.id} | Mint: {s.mint} | Wallets: {s.unique_wallets} | LastSignal: {s.last_signal_time}")

session.close()
