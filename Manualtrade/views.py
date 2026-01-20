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
from .logger2 import write_log_to_txt2
from datetime import datetime
from .utils import fetch_order_status
from .logger import LOG_FILE_PATH
from .logger2 import LOG_FILE_PATH2
import re
from collections import defaultdict
from django.http import FileResponse
from rest_framework.renderers import JSONRenderer


buy_order_successful = False
buy_order_price = 0.0
buy_order_successful_testing = False


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
                print(data['data']['user_name'])
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
            "slice": False
        }

        url = "https://api-hft.upstox.com/v3/order/place"  # real trade api 
        #url = "https://api-sandbox.upstox.com/v3/order/place"  #sandbox token 
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(order_data))
            order_response = response.json()
            print('placed',order_response)
            
            
            
            
            if order_response.get("status") == "success":
                
                order_id = order_response["data"]["order_ids"][0]
                print('order_id',order_id)
                detail_data = fetch_order_status(order_id, access_token)
                
                
        
                if detail_data and detail_data.get("status") == "success":
                    order_status = detail_data["data"]["status"]

                    if order_status == "complete":
                    
                        price = detail_data["data"]["average_price"]
                  
                        buy_order_successful = True
                    
                  
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
                        error_message = detail_data["data"]["status_message"]
                        write_log_to_txt(
                                    f"❌ BUY ORDER FAILED | User: {user_name} | Quantity: {quantity} | "
                                    f"Token: {instrument_token} Total Amount: {total_amount} | "
                                    f"Investable Amount: {investable_amount} | Error: {error_message} | "
                                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                        
                        return Response({
                            "success": False,
                            "message": error_message,
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
            "slice": False
        }

        url = "https://api-hft.upstox.com/v3/order/place" # real trade api 
        
        
        
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(order_data))
            response_data = response.json()
            print(response_data)

            if response_data.get("status") == "success":
            
                order_id = response_data["data"]["order_ids"][0]
                
                detail_data = fetch_order_status(order_id, access_token)
                
                if detail_data and detail_data.get("status") == "success":
                    order_status = detail_data["data"]["status"]
                    
                    
                    if order_status == "complete":
                        price = detail_data["data"]["average_price"]
                        sell_price = float(price)
                        if buy_order_price and buy_order_price != 0:
                            pnl_percent = ((sell_price - buy_order_price) / buy_order_price) * 100
                            pnl_percent = round(pnl_percent, 2)
                        else:
                            pnl_percent = 0.0
                        buy_order_successful = False
                        write_log_to_txt(f"✅ SELL ORDER PLACED | User: {user_name} | Qty: {quantity} | Token: {instrument_token} | SELL IN LTP: ₹{price} |PnL: {pnl_percent}% | Total Amount: {total_amount} | Investable Amount: {investable_amount}| Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                        return Response({
                            "success": True,
                            "message": f"Sell order placed successfully at price ₹{price}",
                            "order_id": order_id,
                            "price": price
                        }, status=200)
                    else:
                        error_message = detail_data["data"]["status_message"]
                        write_log_to_txt(
                                    f"❌ SELL ORDER FAILED | User: {user_name} | Quantity: {quantity} | "
                                    f"Token: {instrument_token}  | Total Amount: {total_amount} | "
                                    f"Investable Amount: {investable_amount} | Error: {error_message} | "
                                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                        return Response({
                            "success": False,
                            "message": detail_data["data"]["status_message"],
                            "order_id": order_id
                        }, status=200)
            else:
                write_log_to_txt(f"SELL ORDER FAILED | Qty: {quantity} | Token: {instrument_token} | Response: {response_data}")
                return Response(response_data, status=response.status_code)

        except requests.exceptions.RequestException as e:
            write_log_to_txt(f"SELL ORDER REQUEST EXCEPTION | Qty: {quantity} | Token: {instrument_token} | Error: {str(e)}")
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    
from django.http import FileResponse, Http404   
class DownloadUpstoxLogAPIView(APIView):
    def get(self, request):
        if not os.path.exists(LOG_FILE_PATH):
            return Response({"error": "Log file not found"}, status=404)
        
        try:
            # Send the file as a downloadable response
            response = FileResponse(
                open(LOG_FILE_PATH, 'rb'),
                as_attachment=True,
                filename='upstox_orders.txt'
            )
            return response
        except Exception as e:
            return Response({"error": f"Failed to download log: {str(e)}"}, status=500)
        
class log(APIView):
    def get(self, request):
        return Response({'msg': "Happy"})
    
    
class PlaceUpstoxBuyOrderAPIViewTesting(APIView):
    def fetch_upstox_user_name(self, access_token):
        try:
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            response = requests.get("https://api.upstox.com/v2/user/profile", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(data['data']['user_name'])
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
        sandbox_token = request.data.get("sandbox_token")
        
        user_name = self.fetch_upstox_user_name(access_token)
        

        if not quantity or not instrument_token or not access_token or not sandbox_token:
            return Response({
                "success": False,
                "message": "Fields 'quantity', 'instrument_token',,'sandbox_token' and 'access_token' are required."
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
            "slice": False
        }

       
        url = "https://api-sandbox.upstox.com/v3/order/place"  #sandbox token 
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {sandbox_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(order_data))
            order_response = response.json()
            print('placed',order_response)

            if order_response.get("status") == "success":
                
                order_id = order_response["data"]["order_ids"][0]
                print('order_id',order_id)
                url = f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={instrument_token}"
                
                headers = {
                    'Accept':'application/json',
                    'Authorization' :f'Bearer {access_token}'
                }
                try:
                    response = requests.get(url , headers = headers)
                    response = response.json()
                    print(response)
                    if response.get("status") == "success":
                        
                        buy_order_successful_testing = True
                        instrument_key = list(response["data"].keys())[0]
                        price =response["data"][instrument_key]["last_price"]
                        print("LTP:",price)
                        return Response({
                            "success": True,
                            "message": f"Order placed successfully at price ₹{price}",
                            "order_id": order_id,
                            "price": price
                        }, status=200)
                except Exception as e:
                    return Response({
                        "success": False,
                        "error": str(e)
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except requests.exceptions.RequestException as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            

class PlaceUpstoxSellOrderAPIViewTesting(APIView):
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
        sandbox_token = request.data.get("sandbox_token")
        
        user_name = self.fetch_upstox_user_name(access_token)


        if not quantity or not instrument_token or not access_token:
            return Response({
                "success": False,
                "message": "Fields 'quantity', 'instrument_token', and 'access_token' are required."
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if not buy_order_successful_testing: 
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
            "slice": False
        }

        url =  "https://api-sandbox.upstox.com/v3/order/place"
        
        
        
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {sandbox_token}'
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(order_data))
            response_data = response.json()
            print(response_data)

            if response_data.get("status") == "success":
            
                order_id = response_data["data"]["order_ids"][0]
                
                url = f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={instrument_token}"
                
                headers = {
                    'Accept':'application/json',
                    'Authorization' :f'Bearer {access_token}'
                }
                try:
                    response = requests.get(url , headers = headers)
                    response = response.json()
                    print(response)
                    if response.get("status") == "success":
                        instrument_key = list(response["data"].keys())[0]
                        price =response["data"][instrument_key]["last_price"]
                        sell_price = float(price)
                        if buy_order_price and buy_order_price != 0:
                            pnl_percent = ((sell_price - buy_order_price) / buy_order_price) * 100
                            pnl_percent = round(pnl_percent, 2)
                        else:
                            pnl_percent = 0.0
                        buy_order_successful_testing = False
                        

                        return Response({
                            "success": True,
                            "message": f"Sell order placed successfully at price ₹{price}",
                            "order_id": order_id,
                            'pnl-percent':pnl_percent,
                            "price": price
                        }, status=200)
                        
                except Exception as e:
                    return Response({
                        "success": False,
                        "error": str(e)
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except requests.exceptions.RequestException as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
   

    def get(self, request):
        if not os.path.exists(LOG_FILE_PATH):
            return Response({"error": "Log file not found"}, status=404)
        
        user_orders = defaultdict(lambda: {"buy": [], "sell": []})

        try:
            with open(LOG_FILE_PATH, "r") as f:
                lines = f.readlines()
            
            # Corrected regex patterns
            buy_pattern = re.compile(
                r"(?P<time>[\d-]+\s[\d:]+) - ✅ BUY ORDER PLACED \|  User:(?P<user>[^,]+) , Quantity: (?P<qty>\d+), \| Token: (?P<token>[^,]+), BUY IN LTP: (?P<buy_ltp>[\d.]+), Total Amount: (?P<total>[^,]+) , Investable Amount: (?P<investable>[^|]+) \| Time: .+"
            )
            sell_pattern = re.compile(
                r"(?P<time>[\d-]+\s[\d:]+) - ✅ SELL ORDER PLACED \| User: (?P<user>[^|]+) \| Qty: (?P<qty>\d+) \| Token: (?P<token>[^|]+) \| SELL IN LTP: ₹?(?P<sell_ltp>[\d.]+) \|PnL: (?P<pnl>[-\d.]+%) \| Total Amount: (?P<total>[^|]+) \| Investable Amount: (?P<investable>[^|]+)\| Time: .+"
            )
            
            for line in lines:
                line = line.strip()
                buy_match = buy_pattern.match(line)
                sell_match = sell_pattern.match(line)
                
                if buy_match:
                    data = buy_match.groupdict()
                    user_orders[data["user"].strip()]["buy"].append(data)
                elif sell_match:
                    data = sell_match.groupdict()
                    user_orders[data["user"].strip()]["sell"].append(data)

            csv_file_path = os.path.join(settings.BASE_DIR, "upstox_orders.csv")
            with open(csv_file_path, "w", newline="") as csvfile:
                fieldnames = [
                    "User",
                    "Buy Time", "Buy Quantity", "Buy Token", "Buy LTP", "Buy Total Amount", "Buy Investable Amount",
                    "Sell Time", "Sell Quantity", "Sell Token", "Sell LTP", "PnL", "Sell Total Amount", "Sell Investable Amount"
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for user, orders in user_orders.items():
                    row = {"User": user}
                    
                    if orders["buy"]:
                        buy_order = orders["buy"][0]
                        row.update({
                            "Buy Time": buy_order["time"],
                            "Buy Quantity": buy_order["qty"],
                            "Buy Token": buy_order["token"],
                            "Buy LTP": buy_order["buy_ltp"],
                            "Buy Total Amount": buy_order["total"],
                            "Buy Investable Amount": buy_order["investable"]
                        })
                    if orders["sell"]:
                        sell_order = orders["sell"][0]
                        row.update({
                            "Sell Time": sell_order["time"],
                            "Sell Quantity": sell_order["qty"],
                            "Sell Token": sell_order["token"],
                            "Sell LTP": sell_order["sell_ltp"],
                            "PnL": sell_order["pnl"],
                            "Sell Total Amount": sell_order["total"],
                            "Sell Investable Amount": sell_order["investable"]
                        })
                    
                    writer.writerow(row)

            return FileResponse(open(csv_file_path, 'rb'), as_attachment=True, filename="upstox_orders.csv")
        
        except Exception as e:
            return Response({"error": f"Failed to generate CSV: {str(e)}"}, status=500)
                
                
                
           
import os
import csv
import re
from collections import defaultdict
from django.http import FileResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from django.conf import settings



class DownloadUpstoxCSVAPIView(APIView):
    """
    API to convert upstox_orders.txt log into CSV and download it.
    """
    renderer_classes = [JSONRenderer]  # Ensures error responses are JSON, no HTML template needed

    def get(self, request, *args, **kwargs):
        if not os.path.exists(LOG_FILE_PATH):
            return Response({"error": "Log file not found"}, status=404)

        user_orders = defaultdict(lambda: {"buy": [], "sell": []})

        try:
            # Read log lines
            with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Improved regex patterns to match log entries
            buy_pattern = re.compile(
    r"(?P<time>[\d-]+\s[\d:]+)\s+-\s+✅ BUY ORDER PLACED \|\s*User:\s*(?P<user>.+?)\s*,\s*Quantity:\s*(?P<qty>\d+),\s*\|\s*Token:\s*(?P<token>[^,]+),\s*BUY IN LTP:\s*₹?(?P<buy_ltp>[\d.]+),\s*Total Amount:\s*(?P<total>[^,]+)\s*,\s*Investable Amount:\s*(?P<investable>[^|]+)\s*\|"
            )

            sell_pattern = re.compile(
                r"(?P<time>[\d-]+\s[\d:]+)\s+-\s+✅ SELL ORDER PLACED \|\s*User:\s*(?P<user>.+?)\s*\|\s*Qty:\s*(?P<qty>\d+)\s*\|\s*Token:\s*(?P<token>.+?)\s*\|\s*SELL IN LTP:\s*₹?(?P<sell_ltp>[\d.]+)\s*\|PnL:\s*(?P<pnl>[-\d.]+%)\s*\| Total Amount:\s*(?P<total>.+?)\s*\| Investable Amount:\s*(?P<investable>.+?)\s*\|"
            )

            # Parse log lines
            for line in lines:
                line = line.strip()
                buy_match = buy_pattern.match(line)
                sell_match = sell_pattern.match(line)

                if buy_match:
                    data = buy_match.groupdict()
                    user_orders[data["user"].strip()]["buy"].append(data)
                elif sell_match:
                    data = sell_match.groupdict()
                    user_orders[data["user"].strip()]["sell"].append(data)

           
            csv_file_path = os.path.join(settings.BASE_DIR,"upstox_orders.csv")
            with open(csv_file_path, "w", newline="", encoding="utf-8") as csvfile:
                fieldnames = [
                    "User",
                    "Buy Time", "Buy Quantity", "Buy Token", "Buy LTP", "Buy Total Amount", "Buy Investable Amount",
                    "Sell Time", "Sell Quantity", "Sell Token", "Sell LTP", "PnL", "Sell Total Amount", "Sell Investable Amount"
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for user, orders in user_orders.items():
                    row = {"User": user}

                    # Take first BUY order if exists
                    if orders["buy"]:
                        buy_order = orders["buy"][0]
                        row.update({
                            "Buy Time": buy_order["time"],
                            "Buy Quantity": buy_order["qty"],
                            "Buy Token": buy_order["token"],
                            "Buy LTP": buy_order["buy_ltp"],
                            "Buy Total Amount": buy_order["total"],
                            "Buy Investable Amount": buy_order["investable"]
                        })

                    # Take first SELL order if exists
                    if orders["sell"]:
                        sell_order = orders["sell"][0]
                        row.update({
                            "Sell Time": sell_order["time"],
                            "Sell Quantity": sell_order["qty"],
                            "Sell Token": sell_order["token"],
                            "Sell LTP": sell_order["sell_ltp"],
                            "PnL": sell_order["pnl"],
                            "Sell Total Amount": sell_order["total"],
                            "Sell Investable Amount": sell_order["investable"]
                        })

                    writer.writerow(row)

            # Return CSV as download
            return FileResponse(
                open(csv_file_path, "rb"),
                as_attachment=True,
                filename="upstox_orders.csv"
            )

        except Exception as e:
            return Response({"error": f"Failed to generate CSV: {str(e)}"}, status=500)
        


from kiteconnect import KiteConnect

buy_order_successful = False
buy_order_price = 0.0



# Helper: Fetch Zerodha user profile name
def fetch_zerodha_user_name(access_token, api_key):
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        profile = kite.profile()
        return profile.get("user_name", "Unknown User")
    except Exception as e:
        write_log_to_txt2(f"❌ Error fetching Zerodha user: {str(e)}")
        return "Unknown User"



import logging

# Global variables as specified
buy_zerodha_order_successful = False
buy_zerodha_order_price = 0.0


def fetch_zerodha_user_name(access_token, api_key):
    """Fetch user name from Zerodha API"""
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        profile = kite.profile()
        return profile.get('user_name', 'Unknown')
    except Exception as e:
        write_log_to_txt2(f"Error fetching user name: {str(e)}")
        return 'Unknown'

class PlaceZerodhaBuyOrderAPIView(APIView):
    def post(self, request):
        global buy_zerodha_order_successful, buy_zerodha_order_price

        api_key = request.data.get("api_key")
        access_token = request.data.get("access_token")
        quantity = request.data.get("quantity")
        tradingsymbol = request.data.get("tradingsymbol")
        exchange = request.data.get("exchange", "NSE")
        total_amount = request.data.get("total_amount")
        investable_amount = request.data.get("investable_amount")

        # Validation
        if not all([api_key, access_token, tradingsymbol, quantity]):
            return Response({
                "success": False,
                "message": "Fields 'api_key', 'access_token', 'tradingsymbol', and 'quantity' are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_name = fetch_zerodha_user_name(access_token, api_key)
            
            # Initialize KiteConnect
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)

            # Place market buy order
            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=int(quantity),
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_NRML
            )

            write_log_to_txt2(f"📤 Buy Order Placed (Pending) | User: {user_name} | Symbol: {tradingsymbol} | Qty: {quantity} | Time: {datetime.now()}")

            # Check order status
            order_details = kite.order_history(order_id)
            final_status = order_details[-1].get("status")
            average_price = order_details[-1].get("average_price", 0.0)

            if final_status and final_status.lower() == "complete":
                # Update global variables
                buy_zerodha_order_successful = True
                buy_zerodha_order_price = float(average_price)

                write_log_to_txt2(
                    f"✅ BUY ORDER COMPLETE | User: {user_name} | Symbol: {tradingsymbol} | Qty: {quantity} | "
                    f"Price: ₹{average_price} | Total: {total_amount} | Investable: {investable_amount} | Time: {datetime.now()}"
                )

                write_log_to_txt2(f"📊 Global variables updated - buy_zerodha_order_successful: {buy_zerodha_order_successful}, buy_zerodha_order_price: {buy_zerodha_order_price}")

                return Response({
                    "success": True,
                    "message": f"Buy order placed successfully at ₹{average_price}",
                    "order_id": order_id,
                    "price": average_price,
                    "global_status": {
                        "buy_order_successful": buy_zerodha_order_successful,
                        "buy_order_price": buy_zerodha_order_price
                    }
                }, status=status.HTTP_200_OK)

            else:
                # Reset global variables on failure
                buy_zerodha_order_successful = False
                buy_zerodha_order_price = 0.0
                
                write_log_to_txt2(f"❌ BUY ORDER FAILED | User: {user_name} | Symbol: {tradingsymbol} | Status: {final_status}")
                write_log_to_txt2(f"📊 Global variables reset - buy_zerodha_order_successful: {buy_zerodha_order_successful}, buy_zerodha_order_price: {buy_zerodha_order_price}")
                
                return Response({
                    "success": False,
                    "message": f"Buy order not completed, status: {final_status}",
                    "order_id": order_id,
                    "global_status": {
                        "buy_order_successful": buy_zerodha_order_successful,
                        "buy_order_price": buy_zerodha_order_price
                    }
                }, status=status.HTTP_200_OK)

        except Exception as e:
            # Reset global variables on exception
            buy_zerodha_order_successful = False
            buy_zerodha_order_price = 0.0
            
            write_log_to_txt2(f"❌ Exception placing Zerodha buy order: {str(e)}")
            write_log_to_txt2(f"📊 Global variables reset due to exception - buy_zerodha_order_successful: {buy_zerodha_order_successful}, buy_zerodha_order_price: {buy_zerodha_order_price}")
            
            return Response({
                "success": False, 
                "error": str(e),
                "global_status": {
                    "buy_order_successful": buy_zerodha_order_successful,
                    "buy_order_price": buy_zerodha_order_price
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlaceZerodhaSellOrderAPIView(APIView):
    def post(self, request):
        global buy_zerodha_order_successful, buy_zerodha_order_price

        api_key = request.data.get("api_key")
        access_token = request.data.get("access_token")
        quantity = request.data.get("quantity")
        tradingsymbol = request.data.get("tradingsymbol")
        exchange = request.data.get("exchange", "NFO")
        total_amount = request.data.get("total_amount")
        investable_amount = request.data.get("investable_amount")

        # Validation
        if not all([api_key, access_token, tradingsymbol, quantity]):
            return Response({
                "success": False,
                "message": "Fields 'api_key', 'access_token', 'tradingsymbol', and 'quantity' are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check if we have a successful buy order
        if not buy_zerodha_order_successful:
            write_log_to_txt2(f"❌ SELL ORDER REJECTED - No successful buy order found | Global status: buy_zerodha_order_successful={buy_zerodha_order_successful}, buy_zerodha_order_price={buy_zerodha_order_price}")
            return Response({
                "success": False,
                "message": "No successful buy order found. Please place a buy order first.",
                "global_status": {
                    "buy_order_successful": buy_zerodha_order_successful,
                    "buy_order_price": buy_zerodha_order_price
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_name = fetch_zerodha_user_name(access_token, api_key)
            
            # Initialize KiteConnect
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)

            # Place market sell order
            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=kite.TRANSACTION_TYPE_SELL,
                quantity=int(quantity),
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_NRML
            )

            write_log_to_txt2(f"📤 Sell Order Placed (Pending) | User: {user_name} | Symbol: {tradingsymbol} | Qty: {quantity} | Buy Price: ₹{buy_zerodha_order_price} | Time: {datetime.now()}")

            # Check order status
            order_details = kite.order_history(order_id)
            final_status = order_details[-1].get("status")
            average_price = order_details[-1].get("average_price", 0.0)

            if final_status and final_status.lower() == "complete":
                sell_price = float(average_price)
                
                # Calculate PnL
                pnl_percent = 0.0
                if buy_zerodha_order_price > 0:
                    pnl_percent = round(((sell_price - buy_zerodha_order_price) / buy_zerodha_order_price) * 100, 2)

                # Store previous buy price for logging before resetting
                previous_buy_price = buy_zerodha_order_price
                
                # Reset global variables after successful sell
                buy_zerodha_order_successful = False
                buy_zerodha_order_price = 0.0

                write_log_to_txt2(
                    f"✅ SELL ORDER COMPLETE | User: {user_name} | Symbol: {tradingsymbol} | Qty: {quantity} | "
                    f"Sell Price: ₹{sell_price} | Buy Price: ₹{previous_buy_price} | PnL: {pnl_percent}% | Time: {datetime.now()}"
                )
                write_log_to_txt2(f"📊 Global variables reset after sell - buy_zerodha_order_successful: {buy_zerodha_order_successful}, buy_zerodha_order_price: {buy_zerodha_order_price}")

                return Response({
                    "success": True,
                    "message": f"Sell order placed successfully at ₹{sell_price}",
                    "order_id": order_id,
                    "price": sell_price,
                    "pnl_percent": pnl_percent,
                    "buy_price": previous_buy_price,
                    "global_status": {
                        "buy_order_successful": buy_zerodha_order_successful,
                        "buy_order_price": buy_zerodha_order_price
                    }
                }, status=status.HTTP_200_OK)

            else:
                write_log_to_txt2(f"❌ SELL ORDER FAILED | User: {user_name} | Symbol: {tradingsymbol} | Status: {final_status}")
                return Response({
                    "success": False,
                    "message": f"Sell order not completed, status: {final_status}",
                    "order_id": order_id,
                    "global_status": {
                        "buy_order_successful": buy_zerodha_order_successful,
                        "buy_order_price": buy_zerodha_order_price
                    }
                }, status=status.HTTP_200_OK)

        except Exception as e:
            write_log_to_txt2(f"❌ Exception placing Zerodha sell order: {str(e)}")
            return Response({
                "success": False, 
                "error": str(e),
                "global_status": {
                    "buy_order_successful": buy_zerodha_order_successful,
                    "buy_order_price": buy_zerodha_order_price
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CheckZerodhaOrderStatusAPIView(APIView):
    """API to check current global order status"""
    def get(self, request):
        global buy_zerodha_order_successful, buy_zerodha_order_price
        
        return Response({
            "success": True,
            "global_status": {
                "buy_order_successful": buy_zerodha_order_successful,
                "buy_order_price": buy_zerodha_order_price
            },
            "message": f"Current status - Buy Order Successful: {buy_zerodha_order_successful}, Buy Price: {buy_zerodha_order_price}"
        }, status=status.HTTP_200_OK)


class ResetZerodhaOrderStatusAPIView(APIView):
    """API to reset global order status"""
    def post(self, request):
        global buy_zerodha_order_successful, buy_zerodha_order_price
        
        # Reset global variables
        buy_zerodha_order_successful = False
        buy_zerodha_order_price = 0.0
        
        write_log_to_txt2(f"🔄 Global variables manually reset - buy_zerodha_order_successful: {buy_zerodha_order_successful}, buy_zerodha_order_price: {buy_zerodha_order_price}")
        
        return Response({
            "success": True,
            "message": "Global order status reset successfully",
            "global_status": {
                "buy_order_successful": buy_zerodha_order_successful,
                "buy_order_price": buy_zerodha_order_price
            }
        }, status=status.HTTP_200_OK)


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from kiteconnect import KiteConnect
import os
from django.conf import settings

class GetTradingSymbolsAndTokenZerodha(APIView):
    """
    Fetch instrument_token and tradingsymbol for given option parameters (name, expiry, strike, option_type)
    directly from Zerodha instruments — not from CSV.
    """

    def post(self, request):
        api_key = request.data.get("api_key")
        access_token = request.data.get("access_token")
        option_requests = request.data.get("options")

        # ✅ Validate
        if not api_key or not access_token:
            return Response({"error": "api_key and access_token are required"}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(option_requests, list) or len(option_requests) == 0:
            return Response({"error": "Payload must contain a non-empty 'options' list"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # ✅ Initialize KiteConnect
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)

            # ✅ Fetch NSE instruments (you can also fetch others like NFO if needed)
            instruments = kite.instruments("NFO")

            results = []
            for option in option_requests:
                name = option.get("name")
                expiry = option.get("expiry")
                option_type = option.get("option_type")
                strike = option.get("strike")

                if not all([name, expiry, option_type, strike]):
                    return Response({"error": "Each option must contain name, expiry, option_type, and strike"}, status=status.HTTP_400_BAD_REQUEST)

                # ✅ Search in Zerodha instruments
                match = next(
                    (
                        inst for inst in instruments
                        if inst["name"].strip().upper() == name.strip().upper()
                        and str(inst["expiry"]) == expiry.strip()
                        and inst["instrument_type"].strip().upper() == option_type.strip().upper()
                        and float(inst["strike"]) == float(strike)
                    ),
                    None
                )

                if match:
                    results.append({
                        "name": name,
                        "expiry": expiry,
                        "option_type": option_type,
                        "strike": strike,
                        "tradingsymbol": match["tradingsymbol"],
                        "instrument_token": match["instrument_token"]
                    })
                else:
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



class DownloadZerodhaLogAPIView(APIView):
    def get(self, request):
        if not os.path.exists(LOG_FILE_PATH2):
            return Response({"error": "Log file not found"}, status=404)
        
        try:
            # Send the file as a downloadable response
            response = FileResponse(
                open(LOG_FILE_PATH2, 'rb'),
                as_attachment=True,
                filename='upstox_orders.txt'
            )
            return response
        except Exception as e:
            return Response({"error": f"Failed to download log: {str(e)}"}, status=500)

class PlaceGenericZerodhaOrderAPIView(APIView):
    def post(self, request):
        api_key = request.data.get("api_key")
        access_token = request.data.get("access_token")
        
        # Order params
        tradingsymbol = request.data.get("tradingsymbol")
        exchange = request.data.get("exchange")
        transaction_type = request.data.get("transaction_type")
        order_type = request.data.get("order_type")
        quantity = request.data.get("quantity")
        product = request.data.get("product")
        validity = request.data.get("validity")
        
        price = request.data.get("price")
        trigger_price = request.data.get("trigger_price")
        tag = request.data.get("tag")
        variety = request.data.get("variety", "regular")

        if not all([api_key, access_token, tradingsymbol, exchange, transaction_type, order_type, quantity, product]):
             return Response({"status": "error", "message": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            
            order_id = kite.place_order(
                variety=variety,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=int(quantity),
                product=product,
                order_type=order_type,
                price=float(price) if price and price != "" else None,
                trigger_price=float(trigger_price) if trigger_price and trigger_price != "" else None,
                validity=validity,
                tag=tag
            )
            
            return Response({
                "status": "success", 
                "data": {"order_id": order_id}
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            write_log_to_txt2(f"❌ Generic Order Failed: {str(e)}")
            return Response({"status": "failed", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)