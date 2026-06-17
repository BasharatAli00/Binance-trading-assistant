# Crypto Trading Bot — Module Integration Prompts
# Use ONE prompt at a time. Only move to next after current one works perfectly.

---

## MODULE 1 — Fear & Greed Index API

You are an expert algorithmic trading bot developer working inside an existing crypto trading bot project built with Python backend and React frontend.

Integrate the **Fear & Greed Index API** into the current system.

API endpoint: `https://api.alternative.me/fng/`
- No API key required
- Returns a score from 0 to 100
- Updates once daily
- Free forever

**What to do:**
- Explore the existing project structure first and understand how it is currently organized
- Find the most appropriate place to add a new fetcher for this API
- Create an isolated fetcher function or module for this data source only
- Add proper error handling and timeout so if this API fails the rest of the system is unaffected
- Cache the response for 24 hours to avoid unnecessary repeated calls
- Store the fetched value in whatever storage or database already exists in the project
- Expose the latest Fear & Greed value through an existing or new API endpoint so the frontend can read it
- Log every API call with timestamp and response status
- Use the existing coding style, naming conventions, and patterns in the project
- Do not modify or break any existing functionality
- Do not introduce any new libraries unless absolutely necessary

**Signal logic for this module:**
- Score below 25 = Extreme Fear = BUY signal
- Score 25 to 45 = Fear = weak BUY signal
- Score 46 to 55 = Neutral = HOLD
- Score 56 to 75 = Greed = weak SELL signal
- Score above 75 = Extreme Greed = SELL signal

**On the React frontend:**
- Add a small widget or card in the existing dashboard that shows the current score and its label
- Match existing UI style exactly, do not introduce new UI libraries

After completing and testing, show:
```
✅ Module 1 — Fear & Greed Index Complete
📦 What was added: ...
📁 Files modified: ...
🧪 Test result: ...
⏭️ Waiting for "next" to proceed to Module 2
```

Stop here and wait for confirmation before doing anything else.

---

## MODULE 2 — Binance Public API Enhancements

You are an expert algorithmic trading bot developer working inside an existing crypto trading bot project built with Python backend and React frontend.

Enhance the existing **Binance Public API** integration in the current system.

- No authentication required for all endpoints below
- All endpoints are completely free

**What to do:**
- Explore the existing project and find where Binance data is currently being fetched
- Enhance or extend it — do not replace or rewrite what already works
- Add the following additional data points if not already present:
  - Order book depth (top 10 bids and asks)
  - Aggregate trades (last 50 trades)
  - 24hr ticker price change statistics
  - Real-time average price
- Normalize all new data into the same format already used in the project
- Store new data points in existing storage
- Expose new data through existing or new endpoint for frontend consumption
- Add caching where appropriate to avoid rate limits
- Log all new API calls with timestamps
- Do not break any existing Binance data fetching

**On the React frontend:**
- Extend existing BTC data display to show order book summary (top 3 bids and asks)
- Show 24hr price change percentage with green/red color
- Match existing UI style exactly

After completing and testing, show:
```
✅ Module 2 — Binance Public API Enhancements Complete
📦 What was added: ...
📁 Files modified: ...
🧪 Test result: ...
⏭️ Waiting for "next" to proceed to Module 3
```

Stop here and wait for confirmation before doing anything else.

---

## MODULE 3 — CryptoCompare News API

You are an expert algorithmic trading bot developer working inside an existing crypto trading bot project built with Python backend and React frontend.

Integrate the **CryptoCompare News API** into the current system.

API endpoint: `https://min-api.cryptocompare.com/data/v2/news/?lang=EN&categories=BTC`
- Free tier available
- API key required — read from environment variable `CRYPTOCOMPARE_API_KEY`
- Add this key to the existing environment config file

**What to do:**
- Explore the existing project structure and find the best place to add this fetcher
- Create an isolated fetcher function or module for this API only
- Fetch the latest 10 Bitcoin news articles
- Perform basic sentiment detection on each headline:
  - Positive words (surge, rally, bullish, rise, gain, breakout) = positive sentiment
  - Negative words (crash, drop, bearish, fall, loss, dump, fear) = negative sentiment
  - Neither = neutral
- Cache results for 1 hour to stay within free tier limits
- Store latest news and sentiment in existing storage
- Expose latest news with sentiment through an endpoint for the frontend
- Log all API calls with timestamps and status
- Add API key to existing env file with a comment explaining what it is
- Do not modify or break any existing functionality

**Signal logic:**
- More than 5 positive headlines in latest 10 = +1 BUY signal
- More than 5 negative headlines in latest 10 = +1 SELL signal
- Mixed or neutral = no signal contribution

**On the React frontend:**
- Show latest 3 news headlines with sentiment badge (Positive / Negative / Neutral)
- Match existing UI style exactly, no new libraries

After completing and testing, show:
```
✅ Module 3 — CryptoCompare News API Complete
📦 What was added: ...
📁 Files modified: ...
🧪 Test result: ...
⏭️ Waiting for "next" to proceed to Module 4
```

Stop here and wait for confirmation before doing anything else.

---

## MODULE 4 — Blockchain.info On-Chain API

You are an expert algorithmic trading bot developer working inside an existing crypto trading bot project built with Python backend and React frontend.

Integrate the **Blockchain.info API** into the current system.

API endpoint: `https://blockchain.info/stats?format=json`
- Completely free
- No API key required
- Returns live Bitcoin network statistics

**What to do:**
- Explore the existing project and find the best place to add this fetcher
- Create an isolated fetcher function or module for this API only
- Fetch the following fields from the response:
  - `n_tx` — number of transactions today
  - `total_fees_btc` — total miner fees
  - `hash_rate` — current network hash rate
  - `difficulty` — current mining difficulty
  - `estimated_transaction_volume_usd` — USD volume on chain
- Cache the response for 1 hour
- Calculate a 7-day rolling average of transaction volume if historical data is already stored, otherwise start collecting from now
- Detect volume spike: if today's volume is 30% above the 7-day average, flag it as elevated activity
- Store all fetched values in existing storage
- Expose values through an endpoint for frontend consumption
- Log all API calls with timestamps

**Signal logic:**
- Transaction volume spike above 30% of 7-day average = +1 BUY signal
- Hash rate significantly dropping = warning flag (do not trade)
- Normal activity = no signal contribution

**On the React frontend:**
- Show a small on-chain stats card with transaction count, volume, and activity status badge (Normal / Elevated / High)
- Match existing UI style exactly

After completing and testing, show:
```
✅ Module 4 — Blockchain.info On-Chain API Complete
📦 What was added: ...
📁 Files modified: ...
🧪 Test result: ...
⏭️ Waiting for "next" to proceed to Module 5
```

Stop here and wait for confirmation before doing anything else.

---

## MODULE 5 — Taapi.io Technical Indicators API

You are an expert algorithmic trading bot developer working inside an existing crypto trading bot project built with Python backend and React frontend.

Integrate the **Taapi.io free tier API** into the current system.

API base URL: `https://api.taapi.io`
- Free tier: 1 request per 15 seconds
- API key required — read from environment variable `TAAPI_API_KEY`
- Add this key to the existing environment config file

**What to do:**
- Explore the existing project and find where RSI and other indicators are currently calculated
- Add Taapi.io as a supplementary source alongside existing calculations — do not replace existing indicator logic
- Fetch the following indicators for BTC/USDT on the 1h timeframe:
  - RSI: `GET /rsi?secret={key}&exchange=binance&symbol=BTC/USDT&interval=1h`
  - MACD: `GET /macd?secret={key}&exchange=binance&symbol=BTC/USDT&interval=1h`
  - EMA 20: `GET /ema?secret={key}&exchange=binance&symbol=BTC/USDT&interval=1h&period=20`
- Strictly respect the 15 second rate limit — add a queue or delay between requests
- Cache each indicator for 15 minutes minimum
- Store fetched values in existing storage
- Expose values through an endpoint for the frontend
- Log all API calls
- Add API key to existing env file

**Signal logic:**
- Taapi RSI below 30 = +1 BUY signal
- Taapi RSI above 70 = +1 SELL signal
- MACD line crossing above signal line = +1 BUY signal
- MACD line crossing below signal line = +1 SELL signal

**On the React frontend:**
- Add Taapi indicator values alongside existing indicator display if present
- Show RSI value with color (green below 30, red above 70, white otherwise)
- Match existing UI style exactly

After completing and testing, show:
```
✅ Module 5 — Taapi.io Indicators API Complete
📦 What was added: ...
📁 Files modified: ...
🧪 Test result: ...
⏭️ Waiting for "next" to proceed to Module 6
```

Stop here and wait for confirmation before doing anything else.

---

## MODULE 6 — Google Trends via pytrends

You are an expert algorithmic trading bot developer working inside an existing crypto trading bot project built with Python backend and React frontend.

Integrate **Google Trends** data using the `pytrends` Python library into the current system.

- Install: `pip install pytrends`
- Completely free, no API key required
- Fetches search interest for "Bitcoin" keyword

**What to do:**
- Explore the existing project and find the best place to add this fetcher
- Create an isolated fetcher function or module for Google Trends only
- Fetch weekly search interest for the keyword "Bitcoin" for the past 3 months
- Extract the latest week's value and compare it to the previous week
- Calculate week-over-week percentage change
- Cache results for 24 hours — Google Trends has strict rate limiting
- Add retry logic with exponential backoff in case of rate limit errors
- Store the latest trend score and change percentage in existing storage
- Expose values through an endpoint for frontend consumption
- Log all fetch attempts with timestamps
- Do not introduce any new libraries other than pytrends

**Signal logic:**
- Trend score rising more than 10% week over week = +1 BUY signal
- Trend score falling more than 10% week over week = mild SELL pressure (not full signal)
- Stable or unclear = no signal contribution

**On the React frontend:**
- Show current Google Trends score for "Bitcoin" and week-over-week change with up/down arrow
- Match existing UI style exactly

After completing and testing, show:
```
✅ Module 6 — Google Trends Complete
📦 What was added: ...
📁 Files modified: ...
🧪 Test result: ...
⏭️ All 6 modules done! Ready for unified signal engine prompt.
```

Stop here and wait for confirmation before doing anything else.

