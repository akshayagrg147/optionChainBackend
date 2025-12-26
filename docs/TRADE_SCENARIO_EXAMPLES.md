# Trade Scenarios: A Beginner’s Guide (10-Minute Examples)

This document explains how our automated trading system works using simple, real-world examples over a short 10-minute window.

## Key Terms Explained
- **NIFTY Spot**: The current actual price of the NIFTY index (like the "price tag" of the market right now).
- **CE (Call Option)**: You buy this if you think the market will go **UP**.
- **PE (Put Option)**: You buy this if you think the market will go **DOWN**.
- **Trailing Stop Loss (SL)**: A safety net. If you buy at ₹100, the system sets a "sell if it drops" price (e.g., ₹99.50). If the price goes up to ₹102, the safety net moves up to ₹101.50 automatically. It "trails" the price to lock in profits.

---

## Scenario A: Making Money When Market Goes Up (CE Profit)
**Goal:** The system buys because the market price hit our target, and we sell when the profit stops growing.

### 1. The Setup
- **Target Price:** 24,500 (We wait for NIFTY to cross this line before buying).
- **Initial Cash:** ₹50,000

### 2. The 10-Minute Story

| Time | NIFTY Price | Option Price | What Happened? | Profit/Loss |
| :--- | :--- | :--- | :--- | :--- |
| **10:00** | 24,490 | ₹95.00 | **Waiting...** The market is below our target (24,500). No action. | - |
| **10:01** | **24,505** | **₹100.00** | **BUY!** The market crossed 24,500. System buys 500 shares at ₹100. <br>System sets a "Safety Net" (Stop Loss) at ₹99.50. | 0% |
| **10:02** | 24,510 | ₹100.40 | **Waiting.** Price went up a bit. We are safe above the net. | +0.4% |
| **10:03** | 24,525 | **₹101.00** | **Safety Net Moves Up!** Price jumped to ₹101. The system moves the safety net higher, from ₹99.50 → **₹100.50**. Now, even if it drops, we make money! | +1.0% |
| **10:04** | 24,530 | ₹102.00 | **Net Moves Up Again.** Price is ₹102. Net moves to **₹101.50**. We are locking in more profit. | +2.0% |
| **10:05** | 24,520 | ₹101.20 | **SELL!** The price dropped to ₹101.20, hitting our safety net (₹101.50). System sells immediately to save the profit. | **+1.2% Profit** |

### 3. The Result
- **Bought at:** ₹100.00
- **Sold at:** ₹101.20
- **Total Profit:** You made ₹1.20 on every share.

---

## Scenario B: Recovering From a Loss (Reverse Trade)
**Goal:** We bet the market would go down (bought PE), but it went up (Loss). The system quickly switches sides (buys CE) to make the money back.

### 1. The Setup
- **Target Price:** 24,480 (We buy if market drops below this).
- **Reverse Trade:** **ON** (Start a backup plan if the first trade fails).

### 2. The 10-Minute Story

| Time | NIFTY Price | PE Price (Down Bet) | CE Price (Up Bet) | What Happened? |
| :--- | :--- | :--- | :--- | :--- |
| **10:00** | 24,490 | ₹100.00 | ₹150.00 | **Waiting...** |
| **10:01** | **24,475** | **₹100.00** | ₹150.00 | **BUY PE.** Market dropped below 24,480. We bet it will keep falling. Bought PE at ₹100. Safety net at ₹99.50. |
| **10:02** | 24,485 | **₹99.00** | ₹155.00 | **OH NO! (Loss)** The market suddenly went UP. PE price dropped to ₹99. Hits our safety net. We sell at a loss (-1%). |
| **10:02:05**| - | - | - | **BACKUP PLAN TRIGGERED!** We lost money faster than expected. The system immediately switches sides. It takes the remaining cash (₹49,500) to buy the "Up Bet" (CE). |
| **10:02:10**| 24,485 | ₹99.00 | **₹155.00** | **BUY CE (Reverse Trade).** System buys CE at ₹155. It sets a new safety net just below that. |
| **10:05** | 24,510 | ₹95.00 | **₹160.00** | **Winning.** The market is indeed going up now. CE price hits ₹160. Safety net trails up to **₹159.20**. |
| **10:10** | 24,500 | ₹90.00 | **₹159.00** | **EXIT.** Price touches the net at ₹159. System sells for a profit. |

### 3. The Result
- **Trade 1 (PE):** Lost ₹500 (Bad guess)
- **Trade 2 (CE):** Made ₹1,200 (Good switch)
- **Final Result:** **+₹700 Profit** (Recovered the loss and made extra!)
