import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from models import CopyWebhookRaw, CopyWalletEvent, CopySignal

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))
Session = sessionmaker(bind=engine)
session = Session()

print("=== LATEST CopyWebhookRaw ===")
r = session.query(CopyWebhookRaw).order_by(CopyWebhookRaw.id.desc()).first()
if r: print(f"ID: {r.id}, Date: {r.received_at}")

print("\n=== LATEST CopyWalletEvent (BUY) ===")
eb = session.query(CopyWalletEvent).filter_by(side='buy').order_by(CopyWalletEvent.id.desc()).first()
if eb: print(f"ID: {eb.id}, Wallet: {eb.wallet}, Date: {eb.received_at}, BlockTime: {eb.block_time}")
else: print("NO BUY EVENTS FOUND")

print("\n=== LATEST CopyWalletEvent (SELL) ===")
es = session.query(CopyWalletEvent).filter_by(side='sell').order_by(CopyWalletEvent.id.desc()).first()
if es: print(f"ID: {es.id}, Wallet: {es.wallet}, Date: {es.received_at}, BlockTime: {es.block_time}")
else: print("NO SELL EVENTS FOUND")

print("\n=== LATEST CopySignal ===")
s = session.query(CopySignal).order_by(CopySignal.id.desc()).first()
if s: print(f"ID: {s.id}, Date: {s.fired_at}")

session.close()
