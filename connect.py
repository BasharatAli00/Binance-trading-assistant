import os
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_SECRET_KEY')

def main():
    if not api_key or not api_secret or api_key == 'your_api_key_here':
        print("Error: BINANCE_API_KEY or BINANCE_SECRET_KEY not set in .env file.")
        print("Please update the .env file with your actual API keys and run the script again.")
        return

    print("Connecting to Binance...")
    
    try:
        # Initialize the Binance client
        client = Client(api_key, api_secret)
        
        # Test connection by pinging the server
        client.ping()
        print("Successfully connected to Binance!\n")
        
        # Fetch account balances
        print("--- Account Balances ---")
        account_info = client.get_account()
        balances = account_info.get('balances', [])
        
        has_balance = False
        for balance in balances:
            free = float(balance['free'])
            locked = float(balance['locked'])
            if free > 0 or locked > 0:
                print(f"{balance['asset']}: Free = {free}, Locked = {locked}")
                has_balance = True
                
        if not has_balance:
            print("No balances found (all zero).")
            
        print("\n--- Live Prices ---")
        # Fetch live price of BTCUSDT
        btc_price = client.get_symbol_ticker(symbol="BTCUSDT")
        print(f"BTCUSDT: ${btc_price['price']}")
        
        # Fetch live price of ETHUSDT
        eth_price = client.get_symbol_ticker(symbol="ETHUSDT")
        print(f"ETHUSDT: ${eth_price['price']}")
        
    except BinanceAPIException as e:
        print(f"\nBinance API Error: {e}")
        print("Check if your API keys are correct and have the necessary permissions.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
