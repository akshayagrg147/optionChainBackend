# Simulated Trade Flow Documentation

This document details the complete trade flow when `is_simulation` is enabled. In this mode, the system interacts with a local simulator (`kite_simulator.py`) instead of the real Zerodha Kite Connect API.

## 1. Input Data Structure (Frontend -> Backend)

When the frontend initiates a trade session with simulation enabled, it sends a JSON payload via WebSocket.

**Example Payload:**

```json
{
  "is_simulation": true,
  "users": [
    {
      "api_key": "sim_user_key_123",
      "access_token": "sim_access_token_abc",
      "trading_symbol": "NIFTY24DEC24500CE",
      "trading_symbol_2": "NIFTY24DEC24500PE",
      "index_name": "NIFTY",
      "target_market_price_CE": 24500.0,
      "target_market_price_PE": 24500.0,
      "quantityCE": 50,
      "quantityPE": 50,
      "step": 0.5,
      "profit_percent": 5.0,
      "total_amount": 100000,
      "investable_amount": 50000,
      "lot": 50,
      "reverseTrade": "ON"
    }
  ]
}
```

## 2. System Initialization Loop

### Step 2.1: Receive & Validate
- **File:** `copy_trading/zerodhaconsumer.py`
- **Function:** `receive(text_data)`
- **Action:**
  - Detects `is_simulation: true`.
  - Validates user parameters.
  - Instantiates `KiteConnectSimulator` instead of `KiteConnect`.

```python
# Pseudo-code representation of the switch
if is_simulation:
    kite = KiteConnectSimulator(api_key=..., base_url="http://simulator:8001")
    # Authentication is simulated; no real request to Zerodha
else:
    kite = KiteConnect(api_key=...)
```

### Step 2.2: Instrument Lookup
- **Action:** The system queries the simulator's instrument list.
- **Simulator Action:** `KiteConnectSimulator.instruments("NFO")` returns a mock list of instruments matching the requested symbols (`NIFTY24DEC24500CE`).

## 3. WebSocket Connection (Simulated Market Data)

### Step 3.1: Connect to Simulator Stream
- **File:** `copy_trading/zerodhaconsumer.py`
- **Function:** `fetch_and_stream_data`
- **Action:** connect to `ws://simulator:8001/ws` (via `KiteTickerSimulator`).

### Step 3.2: Subscription
- The backend subscribes to:
  - **Spot Token:** e.g., NIFTY 50 (Token `256265`)
  - **CE Token:** e.g., `12345678`
  - **PE Token:** e.g., `12345679`

## 4. Trade Execution Logic

### Scenario: CE Buy Trigger

**1. Simulated Tick Arrives**
The simulator sends a tick for the NIFTY 50 Spot price.
```json
{
  "instrument_token": 256265,
  "last_price": 24510.0,
  "timestamp": "2024-12-24 10:00:01"
}
```

**2. Condition Check (`zerodhaconsumer.py`)**
- `target_market_price_CE` is `24500.0`.
- `latest_spot_price` is `24510.0`.
- **Condition Met:** `24510.0 >= 24500.0` -> **BUY SIGNAL**.

**3. Placing the Order**
- **Function:** `place_zerodha_order()`
- **Call:** `user_state.kite.place_order(...)`
- Since `user_state.kite` is a `KiteConnectSimulator` instance, it sends a POST request to the simulator backend.

**Request to Simulator:**
```http
POST /orders/regular
Host: simulator:8001
Content-Type: application/json

{
  "exchange": "NFO",
  "tradingsymbol": "NIFTY24DEC24500CE",
  "transaction_type": "BUY",
  "quantity": 50,
  "order_type": "MARKET",
  "product": "NRML",
  "validity": "DAY",
  "variety": "regular"
}
```

**4. Simulator Response**
```json
{
  "status": "success",
  "data": {
    "order_id": "SIM_ORD_1001"
  }
}
```

## 5. Post-Trade Monitoring (Trailing SL)

Once the order is placed (`COMPLETED`), the system tracks the verified position.

**1. Simulated Option Price Update**
Simulator sends a tick for the bought option.
```json
{
  "instrument_token": 12345678,
  "last_price": 160.0,  // Bought at ~150.0
  "change": 6.66
}
```

**2. Trailing Logic (`process_trailing_sl`)**
- **Initial Lock:** `150.0 - (0.5% step)` = `149.25`
- **New Price:** `160.0`
- **Action:** Move lock up. New lock might be `159.25` (depending on exact step logic).

**3. Sell Trigger**
- Price drops to `159.0` (below lock `159.25`).
- **Action:** `place_sell_order()`.

**Request to Simulator:**
```http
POST /orders/regular
Host: simulator:8001
{
  "tradingsymbol": "NIFTY24DEC24500CE",
  "transaction_type": "SELL",
  "quantity": 50,
  ...
}
```

## 6. Reverse Trade (If Enabled)

If the P&L from the sell trade is negative (or below the `profit_percent` target) and `reverseTrade` is "ON":
1. The system calculates the new quantity based on remaining capital.
2. It immediately places a **BUY** order for the *opposite* instrument (`NIFTY24DEC24500PE`).
3. The cycle repeats from Step 5 with the new instrument.
