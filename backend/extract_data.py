import pandas as pd
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

load_dotenv(override=True)
db_url = os.getenv("DATABASE_URL")
engine = create_engine(db_url)

df_pos = pd.read_sql("SELECT * FROM sniper_position", engine)
df_token = pd.read_sql("SELECT token_address, liquidity_usd FROM sniper_token", engine)
df = df_pos.merge(df_token, on="token_address", how="left")

bins = [0, 10000, 15000, 20000, 30000, float('inf')]
labels = ['<10K', '10K-15K', '15K-20K', '20K-30K', '30K+']
df['liq_band'] = pd.cut(df['liquidity_usd'], bins=bins, labels=labels)
df['is_win'] = df['realized_pnl'] > 0
df['pnl_pct'] = df['return_pct']

# Slippage approximation: Does SniperPosition track expected price?
# Let's check columns of df_pos
print("Columns in SniperPosition:", df_pos.columns.tolist())

df_trades = pd.read_sql("SELECT * FROM sniper_trade", engine)
print("\nFee per size distribution:")
df_trades['fee_pct'] = (df_trades['fee'] / df_trades['usd_value']) * 100
df_trades['size_band'] = pd.cut(df_trades['usd_value'], bins=[0, 10, 20, 25, 30, 50, 100, float('inf')], 
                                 labels=['<10', '10-20', '20-25', '25-30', '30-50', '50-100', '100+'])

fee_agg = df_trades.groupby('size_band').agg(
    trades=('id', 'count'),
    avg_fee_pct=('fee_pct', 'mean')
).reset_index()
print(fee_agg)

