from django.shortcuts import render

# Create your views here.
import requests
import time
import json
from datetime import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

import csv
import os
from django.conf import settings




KITE_API_KEY = "a44a8d2b1l25cwq4"  

def fetch_order_status(order_id, access_token, interval=1):
    url = f"https://api.kite.trade/orders/{order_id}"
    headers = {
        "Authorization": f"token {KITE_API_KEY}:{access_token}"
    }
    while True:
        try:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            print("🔄 Polling order:", data)

            if "status" in data and data["status"] == "success":
                order_data = data["data"]
                order_status = order_data.get("status")

                if order_status in ["COMPLETE", "REJECTED", "CANCELLED", "FAILED"]:
                    return order_data

            return data
        except Exception as e:
            print(f"❌ Error fetching status: {e}")
            return None
        time.sleep(interval)

buy_order_successful = False
buy_order_price = 0.0
class ZerodhaBuyOrderAPIView(APIView):
    def post(self, request):
        global buy_order_successful, buy_order_price
        quantity = request.data.get("quantity")
        tradingsymbol = request.data.get("tradingsymbol")   
        access_token = request.data.get("access_token")
        name = request.data.get("name", "NSE")      

        if not quantity or not tradingsymbol or not access_token:
            return Response({
                "success": False,
                "message": "Fields 'quantity', 'tradingsymbol', and 'access_token' are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        url = "https://api.kite.trade/orders/regular"
        headers = {
            "Authorization": f"token {KITE_API_KEY}:{access_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        order_data = {
            "exchange": name,
            "tradingsymbol": tradingsymbol,
            "transaction_type": "BUY",
            "quantity": quantity,
            "product": "MIS",          # MIS for intraday
            "order_type": "MARKET",
            "validity": "DAY"
        }

        try:
            response = requests.post(url, headers=headers, data=order_data)
            order_response = response.json()
            print("BUY placed:", order_response)

            if order_response.get("status") == "success":
                order_id = order_response["data"]["order_id"]
                detail_data = fetch_order_status(order_id, access_token)

                if detail_data and detail_data.get("status") == "COMPLETE":
                    price = detail_data["average_price"]
                    buy_order_successful = True
                    buy_order_price = float(price)
                    return Response({
                        "success": True,
                        "message": f"BUY order placed at ₹{price}",
                        "order_id": order_id,
                        "price": price
                    }, status=200)

                return Response({
                    "success": False,
                    "message": detail_data.get("status_message", "Order not complete"),
                    "order_id": order_id
                }, status=200)

            return Response(order_response, status=response.status_code)

        except requests.exceptions.RequestException as e:
            return Response({"success": False, "error": str(e)}, status=500)
        


class ZerodhaSellOrderAPIView(APIView):
    def post(self, request):
        global buy_order_successful, buy_order_price
        quantity = request.data.get("quantity")
        tradingsymbol = request.data.get("tradingsymbol")
        access_token = request.data.get("access_token")
        name = request.data.get("name", "NSE")

        if not quantity or not tradingsymbol or not access_token:
            return Response({
                "success": False,
                "message": "Fields 'quantity', 'tradingsymbol', and 'access_token' are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        if not buy_order_successful:
            return Response({
                "success": False,
                "message": "No successful buy order found."
            }, status=status.HTTP_400_BAD_REQUEST)

        url = "https://api.kite.trade/orders/regular"
        headers = {
            "Authorization": f"token {KITE_API_KEY}:{access_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        order_data = {
            "exhange": name,
            "tradingsymbol": tradingsymbol,
            "transaction_type": "SELL",
            "quantity": quantity,
            "product": "MIS",
            "order_type": "MARKET",
            "validity": "DAY"
        }

        try:
            response = requests.post(url, headers=headers, data=order_data)
            order_response = response.json()
            print("SELL placed:", order_response)

            if order_response.get("status") == "success":
                order_id = order_response["data"]["order_id"]
                detail_data = fetch_order_status(order_id, access_token)

                if detail_data and detail_data.get("status") == "COMPLETE":
                    sell_price = float(detail_data["average_price"])
                    pnl_percent = 0.0
                    if buy_order_price > 0:
                        pnl_percent = round(((sell_price - buy_order_price) / buy_order_price) * 100, 2)

                    buy_order_successful = False
                    return Response({
                        "success": True,
                        "message": f"SELL order placed at ₹{sell_price}, PnL: {pnl_percent}%",
                        "order_id": order_id,
                        "price": sell_price
                    }, status=200)

                return Response({
                    "success": False,
                    "message": detail_data.get("status_message", "Order not complete"),
                    "order_id": order_id
                }, status=200)

            return Response(order_response, status=response.status_code)

        except requests.exceptions.RequestException as e:
            return Response({"success": False, "error": str(e)}, status=500)





ZERODHA_INSTRUMENTS_URL = "https://api.kite.trade/instruments"

class GetZerodhaTradingSymbol(APIView):
    def download_and_update_csv(self, api_key, access_token):
        """Download the Zerodha instruments.csv and save as zerodha.csv"""
        headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}"
        }

        response = requests.get(ZERODHA_INSTRUMENTS_URL, headers=headers, stream=True)
        if response.status_code != 200:
            raise Exception(f"Failed to download instruments: {response.status_code} {response.text}")

        csv_path = os.path.join(os.path.dirname(__file__), "zerodha.csv")

        # Overwrite old file with new
        with open(csv_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return csv_path

    def post(self, request):
        option_requests = request.data.get("options")
        api_key = request.data.get("api_key")
        access_token = request.data.get("access_token")

        if not api_key or not access_token:
            return Response({"error": "api_key and access_token are required"}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(option_requests, list) or len(option_requests) == 0:
            return Response({"error": "Payload must contain a non-empty 'options' list"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Always update zerodha.csv before reading
            csv_path = self.download_and_update_csv(api_key, access_token)

            with open(csv_path, newline='') as csvfile:
                reader = list(csv.DictReader(csvfile))
                results = []

                for option in option_requests:
                    name = option.get("name")
                    expiry = option.get("expiry")
                    option_type = option.get("option_type")  
                    strike = option.get("strike")

                    if not all([name, expiry, option_type, strike]):
                        return Response({"error": "Each option must contain name, expiry, option_type, strike"}, status=status.HTTP_400_BAD_REQUEST)

                    match_found = False
                    for row in reader:
                        if (
                            str(row.get("name")).strip().upper() == str(name).strip().upper() and
                            str(row.get("expiry")).strip() == str(expiry).strip() and
                            str(row.get("instrument_type")).strip().upper() == str(option_type).strip().upper() and
                            float(row.get("strike") or 0) == float(strike)
                        ):
                            results.append({
                                "name": name,
                                "expiry": expiry,
                                "option_type": option_type,
                                "strike": strike,
                                "tradingsymbol": row.get("tradingsymbol"),
                                "instrument_token": row.get("instrument_token"),
                                "exchange": row.get("exchange"),
                                "lot_size": row.get("lot_size"),
                            })
                            match_found = True
                            break

                    if not match_found:
                        results.append({
                            "name": name,
                            "expiry": expiry,
                            "option_type": option_type,
                            "strike": strike,
                            "error": "Not found"
                        })

                return Response({"results": results}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": f"Unexpected error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
