import time
import requests

def fetch_order_status(order_id, access_token, interval=1):
   
    details_url = f"https://api.upstox.com/v2/order/details?order_id={order_id}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }

    while True:
        try:
            resp = requests.get(details_url, headers=headers)
            data = resp.json()
            print(f"🔄 Polling order status: {data}")
            if data.get("status") == "success":
                order_status = data["data"]["status"]
                print(order_status)

                if order_status in ["complete", "cancelled", "rejected", "failed"]:
                    return data
            else:
                return data  

        except Exception as e:
            print(f"❌ Error polling order status: {e}")
            return None

        time.sleep(interval)