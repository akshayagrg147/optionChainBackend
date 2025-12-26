# Complete Trade Process Flow - Function by Function

## Demo Data Received from Frontend

```json
{
  "api_key": "abc123xyz",
  "access_token": "token123456789",
  "trading_symbol": "NIFTY24DEC24500CE",
  "trading_symbol_2": "NIFTY24DEC24500PE",
  "index_name": "NIFTY",
  "target_market_price_CE": 24500,
  "target_market_price_PE": 24500,
  "quantityCE": 50,
  "quantityPE": 50,
  "step": 0.5,
  "profit_percent": 5.0,
  "total_amount": 100000,
  "investable_amount": 50000,
  "lot": 50,
  "reverseTrade": "ON"
}
```

---

## Complete Function Call Flow

### **STEP 1: WebSocket Connection**
```
Function: connect()
Location: Line 167
Called: Automatically when WebSocket connects
```

**Demo Input:**
- WebSocket connection established

**What it does:**
- Accepts WebSocket connection
- Sets `self.keep_running = True`
- Stores event loop reference

**Calls Next:** Waits for `receive()` to be called

---

### **STEP 2: Receive Trade Data from Frontend**
```
Function: receive(text_data)
Location: Line 185
Called: When frontend sends JSON message via WebSocket
```

**Demo Input:**
```json
{
  "api_key": "abc123xyz",
  "access_token": "token123456789",
  "trading_symbol": "NIFTY24DEC24500CE",
  "trading_symbol_2": "NIFTY24DEC24500PE",
  "index_name": "NIFTY",
  "target_market_price_CE": 24500,
  "target_market_price_PE": 24500,
  "quantityCE": 50,
  "quantityPE": 50,
  "step": 0.5,
  "profit_percent": 5.0,
  "total_amount": 100000,
  "investable_amount": 50000,
  "lot": 50,
  "reverseTrade": "ON"
}
```

**What it does:**
1. Parses JSON payload
2. Extracts all trading parameters
3. Validates required fields
4. Initializes KiteConnect with API credentials
5. Fetches user profile to verify authentication
6. Stores all parameters in instance variables

**Calls Next:** 
```python
asyncio.create_task(self.fetch_and_stream_data(trading_symbol, trading_symbol_2))
```

---

### **STEP 3: Setup Market Data Stream**
```
Function: fetch_and_stream_data(trading_symbol, trading_symbol_2)
Location: Line 328
Called: From receive() method
```

**Demo Input:**
- `trading_symbol = "NIFTY24DEC24500CE"`
- `trading_symbol_2 = "NIFTY24DEC24500PE"`

**What it does:**
1. Determines exchange type (NSE/BSE) based on index
2. Fetches NSE instruments to find NIFTY 50 token
3. Finds spot/index token (e.g., NIFTY 50 token = 256265)
4. Calls `get_instrument_details_by_trading_symbol()` to get CE/PE tokens
5. Sets up Zerodha WebSocket (KiteTicker)
6. Subscribes to initial tokens: [CE_token, PE_token, NIFTY_token]
7. Sets up callback handlers for market data

**Calls Next:**
- `get_instrument_details_by_trading_symbol()` (Line 370)
- WebSocket `on_ticks` callback → `process_ticks()` (Line 428)

**Demo Output:**
```python
self.ce_token = 12345678
self.ce_trading_symbol = "NIFTY24DEC24500CE"
self.pe_token = 12345679
self.pe_trading_symbol = "NIFTY24DEC24500PE"
self.nifty_token = 256265
```

---

### **STEP 4: Get Instrument Details**
```
Function: get_instrument_details_by_trading_symbol(trading_symbol_input, index_name)
Location: Line 110
Called: From fetch_and_stream_data()
```

**Demo Input:**
- `trading_symbol_input = "NIFTY24DEC24500CE"`
- `index_name = "NIFTY"`

**What it does:**
1. Fetches all NFO instruments from cache
2. Searches for exact match of trading symbol
3. Finds CE token and trading symbol
4. Finds corresponding PE (opposite strike, same expiry)
5. Returns both CE and PE details

**Demo Output:**
```python
{
  "CE": {
    "token": 12345678,
    "trading_symbol": "NIFTY24DEC24500CE"
  },
  "PE": {
    "token": 12345679,
    "trading_symbol": "NIFTY24DEC24500PE"
  }
}
```

**Calls Next:** Returns to `fetch_and_stream_data()`

---

### **STEP 5: Process Market Data Ticks**
```
Function: process_ticks(ticks)
Location: Line 494
Called: Automatically by WebSocket when market data arrives
```

**Demo Input:**
```python
ticks = [
  {
    'instrument_token': 256265,  # NIFTY spot
    'last_price': 24510.5,
    'volume': 1000000,
    'oi': 0,
    'change': 0.5
  },
  {
    'instrument_token': 12345678,  # CE option
    'last_price': 150.25,
    'volume': 50000,
    'oi': 1000000,
    'change': 2.5
  }
]
```

**What it does:**
1. Rate limiting check (process max every 200ms)
2. Iterates through each tick
3. If tick is NIFTY spot:
   - Updates `self.latest_spot_price`
   - Sends spot price to frontend
   - Calls `check_buy_conditions()` if no order placed
4. If tick is bought token:
   - Calls `process_bought_token_tick()`
5. If tick is CE/PE (before order):
   - Sends option data to frontend

**Calls Next:**
- `check_buy_conditions()` (Line 530) - if spot price tick
- `process_bought_token_tick()` (Line 535) - if bought token tick

---

### **STEP 6: Check Buy Conditions**
```
Function: check_buy_conditions(instrument_token, ltp, timestamp)
Location: Line 640
Called: From process_ticks() when NIFTY spot price updates
```

**Demo Input:**
- `instrument_token = 256265` (NIFTY spot)
- `ltp = 24510.5` (current spot price)
- `timestamp = "14:30:25.123"`

**What it does:**
1. Rate limiting (check max every 500ms)
2. Acquires order lock to prevent duplicate orders
3. Checks if order already placed (early exit if yes)
4. **CE Buy Condition:** 
   - If `spot_price >= target_market_priceCE` (24510.5 >= 24500)
   - Sets flags: `order_placedCE = True`, `order_placedPE = True`
   - Calls `place_buy_order()` for CE
5. **PE Buy Condition:**
   - If `spot_price <= target_market_pricePE` (24510.5 <= 24500)
   - Sets flags: `order_placedCE = True`, `order_placedPE = True`
   - Calls `place_buy_order()` for PE

**Demo Scenario:**
- Current spot: 24510.5
- Target CE: 24500
- Condition: 24510.5 >= 24500 ✅ **TRIGGERED**
- Calls: `place_buy_order(12345678, "NIFTY24DEC24500CE", 50, "CE", "14:30:25.123")`

**Calls Next:**
```python
await self.place_buy_order(self.ce_token, self.ce_trading_symbol, self.quantityCE, "CE", timestamp)
```

---

### **STEP 7: Place Buy Order**
```
Function: place_buy_order(token, trading_symbol, quantity, option_type, timestamp)
Location: Line 680
Called: From check_buy_conditions()
```

**Demo Input:**
- `token = 12345678`
- `trading_symbol = "NIFTY24DEC24500CE"`
- `quantity = 50`
- `option_type = "CE"`
- `timestamp = "14:30:25.123"`

**What it does:**
1. Validates trading symbol exists
2. Calls `place_zerodha_order()` to execute buy
3. Waits 1 second for order processing
4. Calls `fetch_order_status()` to verify order
5. If order COMPLETE:
   - Stores buy details: `buy_token`, `buy_quantity`, `buy_in_ltp`
   - Sets reverse token (PE in this case)
   - Updates WebSocket subscription to only bought token + NIFTY
   - Sends success message to frontend
   - Logs order event
6. If order FAILED:
   - Resets flags
   - Sends error message

**Calls Next:**
```python
order_id = await self.place_zerodha_order(
    transaction_type=self.kite.TRANSACTION_TYPE_BUY,
    trading_symbol="NIFTY24DEC24500CE",
    quantity=50,
    order_type=self.kite.ORDER_TYPE_MARKET,
    product=self.kite.PRODUCT_NRML,
    validity=self.kite.VALIDITY_DAY
)
```

**Demo Output:**
```python
order_id = "ORD123456"
self.buy_token = 12345678
self.buy_trading_symbol = "NIFTY24DEC24500CE"
self.buy_quantity = 50
self.buy_in_ltp = 150.50  # Average execution price
self.ltp_at_order = 150.50
self.reverse_token = 12345679  # PE token
self.reverse_trading_symbol = "NIFTY24DEC24500PE"
```

---

### **STEP 8: Execute Zerodha Order (ACTUAL TRADE)**
```
Function: place_zerodha_order(transaction_type, trading_symbol, quantity, order_type, price, product, validity)
Location: Line 267
Called: From place_buy_order()
```

**Demo Input:**
- `transaction_type = KiteConnect.TRANSACTION_TYPE_BUY`
- `trading_symbol = "NIFTY24DEC24500CE"`
- `quantity = 50`
- `order_type = "MARKET"`
- `product = KiteConnect.PRODUCT_NRML`
- `validity = KiteConnect.VALIDITY_DAY`

**What it does:**
1. Determines exchange (NFO for NIFTY)
2. Calls Zerodha KiteConnect API:
   ```python
   order_id = self.kite.place_order(
       variety=self.kite.VARIETY_REGULAR,
       exchange=self.kite.EXCHANGE_NFO,
       tradingsymbol="NIFTY24DEC24500CE",
       transaction_type=self.kite.TRANSACTION_TYPE_BUY,
       quantity=50,
       order_type=self.kite.ORDER_TYPE_MARKET,
       product=self.kite.PRODUCT_NRML,
       validity=self.kite.VALIDITY_DAY
   )
   ```
3. **THIS IS WHERE ACTUAL TRADE HAPPENS** - Order sent to Zerodha exchange
4. Returns order ID

**Demo Output:**
```python
order_id = "ORD123456"
```

**Calls Next:** Returns to `place_buy_order()` which calls `fetch_order_status()`

---

### **STEP 9: Fetch Order Status**
```
Function: fetch_order_status(order_id)
Location: Line 316
Called: From place_buy_order() after order placement
```

**Demo Input:**
- `order_id = "ORD123456"`

**What it does:**
1. Fetches all orders from Zerodha
2. Searches for order with matching order_id
3. Returns order details

**Demo Output:**
```python
{
  'order_id': 'ORD123456',
  'status': 'COMPLETE',
  'average_price': 150.50,
  'quantity': 50,
  'tradingsymbol': 'NIFTY24DEC24500CE',
  'transaction_type': 'BUY',
  'status_message': 'Order filled'
}
```

**Calls Next:** Returns to `place_buy_order()` which processes the result

---

### **STEP 10: Process Bought Token Ticks (After Buy)**
```
Function: process_bought_token_tick(instrument_token, ltp, timestamp, volume, oi, change)
Location: Line 558
Called: From process_ticks() when bought token receives market data
```

**Demo Input:**
- `instrument_token = 12345678` (bought CE token)
- `ltp = 152.75` (current option price)
- `timestamp = "14:31:10.456"`
- `volume = 55000`
- `oi = 1000000`
- `change = 2.25`

**What it does:**
1. Converts LTP to float
2. Sends bought option data to frontend with P&L info
3. Calls `process_trailing_sl()` to check exit conditions

**Calls Next:**
```python
await self.process_trailing_sl(instrument_token, 152.75, "14:31:10.456")
```

---

### **STEP 11: Process Trailing Stop Loss**
```
Function: process_trailing_sl(instrument_token, current_ltp, timestamp)
Location: Line 585
Called: From process_bought_token_tick()
```

**Demo Input:**
- `instrument_token = 12345678`
- `current_ltp = 152.75`
- `timestamp = "14:31:10.456"`

**What it does:**
1. **First Time Setup:**
   - Calculates `step_size = buy_price * step% = 150.50 * 0.5% = 0.7525`
   - Sets `locked_ltp = buy_price - step_size = 150.50 - 0.7525 = 149.7475`
   - Initializes trailing stop loss

2. **Trailing Logic:**
   - If price goes UP: Moves `locked_ltp` up by step_size increments
   - Example: If price reaches 151.50, locked_ltp becomes 150.50
   - If price reaches buy_price, locked_ltp stays one step below

3. **Sell Condition Check:**
   - If `current_ltp <= locked_ltp AND current_ltp < previous_ltp`
   - OR if `current_ltp < locked_ltp`
   - **TRIGGERS SELL**

**Demo Scenario:**
```python
# Initial
buy_price = 150.50
step_size = 0.7525
locked_ltp = 149.7475

# Price moves up to 152.75
# locked_ltp moves up to 151.50 (trailing)

# Price drops to 151.00
# Condition: 151.00 <= 151.50 AND 151.00 < 152.75 ✅
# TRIGGERS SELL
```

**Calls Next:**
```python
await self.place_sell_order(151.00)  # When sell condition met
```

---

### **STEP 12: Place Sell Order**
```
Function: place_sell_order(current_ltp)
Location: Line 766
Called: From process_trailing_sl() when sell condition triggers
```

**Demo Input:**
- `current_ltp = 151.00`

**What it does:**
1. Acquires order lock (prevents duplicate sells)
2. Checks if sell already placed (early exit)
3. Sets `sell_order_placed = True` immediately
4. Calls `place_zerodha_order()` with SELL transaction
5. Waits 1 second
6. Calls `fetch_order_status()` to verify
7. If COMPLETE:
   - Calculates P&L: `((sell_price - buy_price) / buy_price) * 100`
   - Logs sell order event
   - Sends success message to frontend
   - Checks if reverse trade needed

**Demo Calculation:**
```python
buy_price = 150.50
sell_price = 151.00
PnL = ((151.00 - 150.50) / 150.50) * 100 = 0.33%
```

**Calls Next:**
```python
# If reverse trade enabled and PnL < expected profit
if self.reverse_Trade == "ON" and PnL < 5.0:
    await self.execute_reverse_trade(0.33)
else:
    self.reset_trade_flags()  # End trading
```

---

### **STEP 13: Execute Reverse Trade (Optional)**
```
Function: execute_reverse_trade(PnL)
Location: Line 854
Called: From place_sell_order() if conditions met
```

**Demo Input:**
- `PnL = 0.33` (less than expected 5.0%)

**What it does:**
1. Resets trailing SL variables
2. Switches to reverse token (PE in this case)
3. Fetches current LTP of reverse token using `kite.quote()`
4. Calculates new investable amount:
   ```python
   if PnL > 0:
       new_investable = 50000 + (0.33/100) * 50000 = 50165
   else:
       new_investable = 50000 - (abs(-0.33)/100) * 50000 = 49835
   ```
5. Calculates new quantity:
   ```python
   quantity = lot * (new_investable // (ltp * lot))
   quantity = 50 * (50165 // (120.50 * 50)) = 50 * 8 = 400
   ```
6. Calls `place_zerodha_order()` to buy reverse token
7. Updates subscription to reverse token
8. Resets sell flag to continue monitoring

**Demo Output:**
```python
self.buy_token = 12345679  # PE token
self.buy_trading_symbol = "NIFTY24DEC24500PE"
self.buy_quantity = 400
self.buy_in_ltp = 120.50
self.investable_amount = 50165
```

**Calls Next:**
- Returns to `process_ticks()` → `process_bought_token_tick()` → `process_trailing_sl()`
- Cycle repeats for reverse trade

---

## Complete Flow Diagram

```
Frontend sends WebSocket message
    ↓
receive() - Parse and validate
    ↓
fetch_and_stream_data() - Setup market data stream
    ↓
get_instrument_details_by_trading_symbol() - Get tokens
    ↓
WebSocket connects → process_ticks() called repeatedly
    ↓
check_buy_conditions() - Monitor spot price
    ↓ (when condition met)
place_buy_order() - Prepare buy order
    ↓
place_zerodha_order() - ⚡ ACTUAL TRADE EXECUTION ⚡
    ↓
fetch_order_status() - Verify order
    ↓
process_bought_token_tick() - Monitor bought option
    ↓
process_trailing_sl() - Check exit conditions
    ↓ (when sell condition met)
place_sell_order() - Prepare sell order
    ↓
place_zerodha_order() - ⚡ ACTUAL TRADE EXECUTION ⚡
    ↓
fetch_order_status() - Verify order
    ↓
execute_reverse_trade() - (if enabled and PnL < target)
    ↓
place_zerodha_order() - ⚡ ACTUAL TRADE EXECUTION ⚡
    ↓
Cycle repeats for reverse trade...
```

---

## Key Points

1. **Actual Trade Execution Happens In:**
   - `place_zerodha_order()` - Line 267
   - Calls `self.kite.place_order()` - Line 286 or 297
   - This is the ONLY place where real trades are executed

2. **Trade Flow:**
   - Frontend → `receive()` → `fetch_and_stream_data()` → `process_ticks()` → `check_buy_conditions()` → `place_buy_order()` → `place_zerodha_order()` → **TRADE EXECUTED**

3. **Exit Flow:**
   - `process_ticks()` → `process_bought_token_tick()` → `process_trailing_sl()` → `place_sell_order()` → `place_zerodha_order()` → **TRADE EXECUTED**

4. **All Business Logic:**
   - Buy conditions: `check_buy_conditions()` - Line 640
   - Sell conditions: `process_trailing_sl()` - Line 585
   - Reverse trade: `execute_reverse_trade()` - Line 854

