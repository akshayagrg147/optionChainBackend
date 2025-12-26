# Postman Collection Guide

## Importing the Collection

1. Open Postman
2. Click **Import** button (top left)
3. Select `OptionsChainBackend.postman_collection.json`
4. The collection will be imported with all endpoints organized by category

## Collection Structure

The collection is organized into the following folders:

### 1. Authentication
- **Register** - Create a new user account
- **Login** - Authenticate and get JWT tokens (automatically saves tokens to collection variables)

### 2. Copy Trading - Options
- **Get Option Chain** - Fetch option chain data from Upstox
- **Get Quote** - Get last traded price from Zerodha

### 3. Copy Trading - Upstox Funds
- Multiple endpoints for managing Upstox funds and margins

### 4. Copy Trading - Instruments
- Upload CSV files
- Manage fund instruments (CRUD operations)
- Get trading symbols

### 5. Copy Trading - Zerodha
- Manage Zerodha instruments
- Get Zerodha funds

### 6. Copy Trading - Logs
- Download log files

### 7. Manual Trade - Upstox
- Place buy/sell orders
- Get trading symbols and tokens
- Download logs

### 8. Manual Trade - Zerodha
- Place Zerodha buy/sell orders
- Get tokens
- Download logs

## Configuration

### Collection Variables

The collection includes these variables (set at collection level):

- `base_url` - Default: `http://localhost:8000`
- `access_token` - JWT access token (auto-populated after login)
- `refresh_token` - JWT refresh token (auto-populated after login)

### Authentication

1. **JWT Authentication (Default)**: 
   - Most endpoints use Bearer token authentication
   - Token is automatically set from the Login response
   - Collection-level auth is configured to use `{{access_token}}`

2. **No Authentication**:
   - Some endpoints (like Register, Login, Option Chain) don't require JWT
   - They may require Upstox/Zerodha API tokens in headers or body

3. **Upstox/Zerodha Tokens**:
   - Replace `YOUR_UPSTOX_ACCESS_TOKEN` and `YOUR_ZERODHA_ACCESS_TOKEN` with actual tokens
   - These are broker-specific API tokens, not JWT tokens

## Usage Tips

1. **First Time Setup**:
   - Update `base_url` if your server is running on a different host/port
   - Register a new user or use existing credentials
   - Login to get JWT tokens (automatically saved)

2. **Testing Endpoints**:
   - Most endpoints have example request bodies
   - Replace placeholder values with actual data
   - Check response status codes and messages

3. **File Uploads**:
   - For CSV upload endpoints, use the file selector in Postman
   - Ensure files match expected format

4. **Environment Variables** (Optional):
   - Create a Postman Environment for different environments (dev, staging, prod)
   - Override `base_url` per environment

## Important Notes

- **JWT Tokens**: Login endpoint automatically saves tokens to collection variables
- **Bearer Token Format**: Collection uses `Bearer {{access_token}}` format
- **Upstox/Zerodha Tokens**: These are separate from JWT tokens and need to be obtained from respective broker APIs
- **Testing Endpoints**: Some endpoints have `/testing/` variants for safe testing

## Troubleshooting

1. **401 Unauthorized**: 
   - Ensure you've logged in and tokens are set
   - Check if token has expired (login again)

2. **404 Not Found**:
   - Verify `base_url` is correct
   - Ensure Django server is running

3. **400 Bad Request**:
   - Check request body format
   - Verify all required fields are present
   - Check data types match expected format

4. **500 Internal Server Error**:
   - Check server logs
   - Verify database is accessible
   - Check Redis connection (for WebSocket features)

## Updating the Collection

If you add new endpoints:
1. Export the collection from Postman
2. Update the JSON file
3. Re-import or share with team

