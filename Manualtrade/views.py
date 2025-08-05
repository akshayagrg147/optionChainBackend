from django.shortcuts import render

from rest_framework.response import Response
from rest_framework.decorators import APIView
import os
from django.conf import settings
import csv
from rest_framework import status

import json
import requests
from .logger import write_log_to_txt
from datetime import datetime


buy_order_successful = False
buy_order_price = 0.0


class GetTradingSymbolsAndToken(APIView):
    def post(self, request):
        option_requests = request.data.get("options")

        if not isinstance(option_requests, list) or len(option_requests) == 0:
            return Response({"error": "Payload must contain a non-empty 'options' list"}, status=status.HTTP_400_BAD_REQUEST)

        csv_path = os.path.join(settings.BASE_DIR, 'nse.csv')

        try:
            with open(csv_path, newline='') as csvfile:
                reader = list(csv.DictReader(csvfile))
                results = []

                for option in option_requests:
                    name = option.get("name")
                    expiry = option.get("expiry")
                    option_type = option.get("option_type")
                    strike = option.get("strike")

                    if not all([name, expiry, option_type, strike]):
                        return Response({"error": "Each option must contain name, expiry, option_type, and strike"}, status=status.HTTP_400_BAD_REQUEST)

                    match_found = False
                    for row in reader:
                        if (
                            str(row.get("name")).strip().upper() == str(name).strip().upper() and
                            str(row.get("expiry")).strip() == str(expiry).strip() and
                            str(row.get("option_type")).strip().upper() == str(option_type).strip().upper() and
                            float(row.get("strike")) == float(strike)
                        ):
                            results.append({
                                "name": name,
                                "expiry": expiry,
                                "option_type": option_type,
                                "strike": strike,
                                "tradingsymbol": row.get("tradingsymbol"),
                                "instrument_key":row.get("instrument_key")
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

        except FileNotFoundError:
            return Response({"error": "CSV file not found"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"error": f"Unexpected error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PlaceUpstoxBuyOrderAPIView(APIView):
    def fetch_upstox_user_name(self, access_token):
        try:
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            response = requests.get("https://api.upstox.com/v2/user/profile", headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data['data']['user_name']
            else:
                write_log_to_txt(f"❌ Error fetching user name: {response.status_code} {response.text}")
                return "Unknown User"
        except Exception as e:
            write_log_to_txt(f"❌ Exception while fetching user name: {str(e)}")
            return "Unknown User"
    
    def post(self, request):
        global buy_order_successful, buy_order_price
        quantity = request.data.get("quantity")
        instrument_token = request.data.get("instrument_token")
        access_token = request.data.get("access_token")
        total_amount = request.data.get("total_amount")
        investable_amount = request.data.get('investable_amount')
        
        user_name = self.fetch_upstox_user_name(access_token)

        if not quantity or not instrument_token or not access_token:
            return Response({
                "success": False,
                "message": "Fields 'quantity', 'instrument_token', and 'access_token' are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        order_data = {
            "quantity": quantity,
            "instrument_token": instrument_token,
            "product": "I",
            "validity": "DAY",
            "price": 0,
            "tag": "string",
            "order_type": "MARKET",
            "transaction_type": "BUY",
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
            "slice": True
        }

        url = "https://api-sandbox.upstox.com/v3/order/place"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(order_data))
            order_response = response.json()
            
            buy_order_successful = True
            
            
            if order_response.get("status") == "success":
                order_id = order_response["data"]["order_ids"][0]
                
                
                details_url = f"https://api-sandbox.upstox.com/v2/order/details?order_id={order_id}"

                detail_headers = {
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {access_token}'
                }

                detail_resp = requests.get(details_url, headers=detail_headers)
                detail_data = detail_resp.json()
               

                if detail_data.get("status") == "success":
                    price = detail_data["data"].get("price")
                    buy_order_price = float(price)
                    
                    write_log_to_txt(
                        f" ✅ BUY ORDER PLACED |  User:{user_name} , Quantity: {quantity}, | Token: {instrument_token}, BUY IN LTP: {price}, Total Amount: {total_amount} , Investable Amount: {investable_amount} | Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
                    return Response({
                        "success": True,
                        "message": f"Order placed successfully at price ₹{price}",
                        "order_id": order_id,
                        "price": price
                    }, status=200)
                else:
                    return Response({
                        "success": False,
                        "message": "Order placed, but failed to fetch order details.",
                        "order_id": order_id
                    }, status=200)

            else:
                return Response(order_response, status=response.status_code)

        except requests.exceptions.RequestException as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            

class PlaceUpstoxSellOrderAPIView(APIView):
    def fetch_upstox_user_name(self, access_token):
        try:
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            response = requests.get("https://api.upstox.com/v2/user/profile", headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data['data']['user_name']
            else:
                print(f"❌ Error fetching user name: {response.status_code} {response.text}")
                return "Unknown User"
        except Exception as e:
            print(f"❌ Exception while fetching user name: {str(e)}")
            return "Unknown User"
    def post(self, request):
        global buy_order_successful, buy_order_price
        quantity = request.data.get("quantity")
        instrument_token = request.data.get("instrument_token")
        access_token = request.data.get("access_token")
        total_amount = request.data.get("total_amount")
        investable_amount = request.data.get('investable_amount')
        
        user_name = self.fetch_upstox_user_name(access_token)


        if not quantity or not instrument_token or not access_token:
            return Response({
                "success": False,
                "message": "Fields 'quantity', 'instrument_token', and 'access_token' are required."
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if not buy_order_successful: 
            return Response({
                "success": False,
                "message": "You haven't placed a successful buy order yet."
            }, status=status.HTTP_400_BAD_REQUEST)

        order_data = {
            "quantity": quantity,
            "instrument_token": instrument_token,
            "product": "I",
            "validity": "DAY",
            "price": 0,
            "tag": "string",
            "order_type": "MARKET",
            "transaction_type": "SELL",  
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
            "slice": True
        }

        url = "https://api-sandbox.upstox.com/v3/order/place"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(order_data))
            response_data = response.json()

            if response_data.get("status") == "success":
                order_id = response_data["data"]["order_ids"][0]

                details_url = f"https://api-sandbox.upstox.com/v2/order/details?order_id={order_id}"
                detail_headers = {
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {access_token}'
                }
                user_name = self.fetch_upstox_user_name(access_token)

                detail_resp = requests.get(details_url, headers=detail_headers)
                detail_data = detail_resp.json()
                
                if detail_data.get("status") == "success":
                    price = detail_data["data"].get("price")
                    sell_price = float(price)
                    if buy_order_price and buy_order_price != 0:
                        pnl_percent = ((sell_price - buy_order_price) / buy_order_price) * 100
                        pnl_percent = round(pnl_percent, 2)
                    else:
                        pnl_percent = 0.0
     
                    write_log_to_txt(f"✅ SELL ORDER PLACED | User: {user_name} | Qty: {quantity} | Token: {instrument_token} | SELL IN LTP: ₹{price} |PnL: {pnl_percent}% | Total Amount: {total_amount} | Investable Amount: {investable_amount}| Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                    return Response({
                        "success": True,
                        "message": f"Sell order placed successfully at price ₹{price}",
                        "order_id": order_id,
                        "price": price
                    }, status=200)
                else:
                    write_log_to_txt(f"SELL ORDER DETAIL FETCH FAILED | Order ID: {order_id} | Response: {detail_data}")

                    return Response({
                        "success": True,
                        "message": "Sell order placed, but failed to fetch order details.",
                        "order_id": order_id
                    }, status=200)
            else:
                write_log_to_txt(f"SELL ORDER FAILED | Qty: {quantity} | Token: {instrument_token} | Response: {response_data}")
                return Response(response_data, status=response.status_code)

        except requests.exceptions.RequestException as e:
            write_log_to_txt(f"SELL ORDER REQUEST EXCEPTION | Qty: {quantity} | Token: {instrument_token} | Error: {str(e)}")
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    