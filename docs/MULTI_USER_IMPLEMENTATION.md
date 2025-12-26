# Multi-User Trading Implementation

## Overview

The Zerodha consumer has been refactored to support **multiple users trading simultaneously** with **parallel order execution** for faster trade execution.

## Key Changes

### 1. **UserState Class** (New)
- Created a `@dataclass` to track each user's individual trading state
- Each user has their own:
  - KiteConnect instance
  - Trading parameters (quantities, targets, etc.)
  - Order flags and state
  - Trailing stop loss state
  - Individual locks for thread safety

### 2. **Shared WebSocket Connection**
- **Single WebSocket connection** for market data (since all users watch same instruments)
- Reduces resource usage and improves efficiency
- All users share the same spot price and option data stream

### 3. **Parallel Order Execution**
- Buy orders for multiple users execute **simultaneously** using `asyncio.gather()`
- Reduced delays (0.5s instead of 1s) for faster execution
- All users' buy orders hit the exchange at the same time (within milliseconds)

### 4. **Multi-User Processing**
- `process_ticks()` handles all users simultaneously
- Each user's trailing SL and sell conditions are checked independently
- User-specific data is sent to frontend with `user_id` and `account_name`

## Frontend Usage

### Single User (Backward Compatible)
```javascript
// Still works - single user
const message = {
    api_key: 'user1_key',
    access_token: 'user1_token',
    trading_symbol: 'NIFTY25JAN2419800CE',
    // ... other fields
};

ws.send(JSON.stringify(message));
```

### Multiple Users (New)
```javascript
// Send array of users
const users = [
    {
        api_key: 'user1_key',
        access_token: 'user1_token',
        trading_symbol: 'NIFTY25JAN2419800CE',  // Same for all
        trading_symbol_2: 'NIFTY25JAN2419800PE', // Same for all
        index_name: 'NIFTY',
        target_market_price_CE: 19800,  // Same for all
        target_market_price_PE: 19700,  // Same for all
        quantityCE: 50,  // Can be different per user
        quantityPE: 50,  // Can be different per user
        step: 1.0,  // Same for all
        profit_percent: 10.0,  // Same for all
        total_amount: 50000,
        investable_amount: 50000,
        lot: 50,
        reverseTrade: "ON"  // Can be ON/OFF per user
    },
    {
        api_key: 'user2_key',
        access_token: 'user2_token',
        trading_symbol: 'NIFTY25JAN2419800CE',  // Same
        trading_symbol_2: 'NIFTY25JAN2419800PE', // Same
        index_name: 'NIFTY',
        target_market_price_CE: 19800,  // Same
        target_market_price_PE: 19700,  // Same
        quantityCE: 100,  // Different quantity
        quantityPE: 100,  // Different quantity
        step: 1.0,  // Same
        profit_percent: 10.0,  // Same
        total_amount: 100000,
        investable_amount: 100000,
        lot: 50,
        reverseTrade: "OFF"  // Different setting
    },
    // More users...
];

// Option 1: Send as array
ws.send(JSON.stringify(users));

// Option 2: Send as object with 'users' key
ws.send(JSON.stringify({ users: users }));
```

## Important Requirements

### All Users Must Have:
- ✅ **Same trading symbols** (`trading_symbol`, `trading_symbol_2`)
- ✅ **Same target prices** (`target_market_price_CE`, `target_market_price_PE`)
- ✅ **Same index** (`index_name`)

### Can Be Different Per User:
- ✅ `quantityCE` and `quantityPE`
- ✅ `total_amount` and `investable_amount`
- ✅ `reverseTrade` (ON/OFF)
- ✅ `api_key` and `access_token` (obviously)

## Response Format

All responses now include `user_id` and `account_name` to identify which user the message is for:

```json
{
    "message": "Order placed successfully...Waiting for square off",
    "user_id": "abc123xyz_123456789",
    "account_name": "User Name",
    "BUY_LTP": 150.50,
    "Type": "CE"
}
```

## Performance Improvements

### Before:
- Sequential processing: User 1 → User 2 → User 3
- Each user gets separate WebSocket connection
- Orders placed one after another
- Total time: ~3 seconds for 3 users

### After:
- Parallel processing: All users simultaneously
- Single shared WebSocket connection
- All buy orders execute in parallel
- Total time: ~0.5 seconds for 3 users (6x faster!)

## Example Flow

1. **Frontend sends array of 10 users**
2. **Backend validates all users** (same symbols/targets)
3. **Single WebSocket connection** established
4. **Market data streams** to all users
5. **When buy condition met:**
   - All 10 users' buy orders execute **simultaneously** using `asyncio.gather()`
   - All orders hit exchange within milliseconds of each other
6. **Each user's trailing SL** monitored independently
7. **Sell orders** execute independently when each user's condition is met

## Error Handling

- If one user's order fails, others continue normally
- Each user's errors are logged separately
- Frontend receives user-specific error messages with `user_id`

## Testing

To test with multiple users:

```javascript
// Test with 3 users
const testUsers = [
    { /* user 1 data */ },
    { /* user 2 data */ },
    { /* user 3 data */ }
];

ws.send(JSON.stringify(testUsers));
```

All 3 users will:
- Share the same market data stream
- Execute buy orders simultaneously when condition is met
- Track their own trailing stop loss independently
- Execute sell orders independently

## Migration Notes

- **Backward compatible**: Single user format still works
- **No breaking changes**: Existing frontend code continues to work
- **Gradual migration**: Can start using multi-user format when ready

