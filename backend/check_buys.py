import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from models import CopyWalletEvent, CopySignal

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))
Session = sessionmaker(bind=engine)
session = Session()

print("=== ALL BUY EVENTS in CopyWalletEvent ===")
buys = session.query(CopyWalletEvent).filter(CopyWalletEvent.side == 'buy').all()
for b in buys:
    print(f"ID: {b.id} | Wallet: {b.wallet} | Mint: {b.mint} | BlockTime: {b.block_time} | ReceivedAt: {b.received_at}")
    
print("\n=== ALL SIGNALS ===")
signals = session.query(CopySignal).all()
for s in signals:
    print(f"ID: {s.id} | Mint: {s.mint} | Wallets: {s.wallets} | Status: {s.status} | Reason: {s.reason}")

session.close()
