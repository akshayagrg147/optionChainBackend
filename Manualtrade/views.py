from django.shortcuts import render

from rest_framework.response import Response
from rest_framework.decorators import APIView
import os
from django.conf import settings
import csv
from rest_framework import status

import json
import requests
from .logger import buy_logger as logger
from .logger import sell_logger as loggers


buy_order_successful = False


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
    def post(self, request):
        global buy_order_successful
        quantity = request.data.get("quantity")
        instrument_token = request.data.get("instrument_token")
        access_token = request.data.get("access_token")

        if not quantity or not instrument_token or not access_token:
            return Response({
                "success": False,
                "message": "Fields 'quantity', 'instrument_token', and 'access_token' are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        order_data = {
            "quantity": quantity,
            "instrument_token": instrument_token,
            "product": "D",
            "validity": "DAY",
            "price": 0,
            "tag": "BackendInitiatedOrder",
            "order_type": "MARKET",
            "transaction_type": "BUY",
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
            "slice": True
        }

        # url = "https://api-sandbox.upstox.com/v3/order/place"
        # headers = {
        #     'Content-Type': 'application/json',
        #     'Authorization': f'Bearer {access_token}'
        # }

        # try:
        #     response = requests.post(url, headers=headers, data=json.dumps(order_data))
        #     response_data = response.json()

        #     # ✅ Log to file
        logger.info(f"SUCCESS | Qty: {quantity} | Token: {instrument_token} | Order: {order_data}")
        buy_order_successful = True

        #     return Response(response_data, status=response.status_code)

        # except requests.exceptions.RequestException as e:
        #     # ✅ Log to file on error
        #     logger.error(f"FAILED | Qty: {quantity} | Token: {instrument_token} | Error: {str(e)}")
        #     return Response({
        #         "success": False,
        #         "error": str(e)
        #     }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            "success": True,
            "msg":"OrderPlaced Successfully"
        },status=200)

        
class PlaceUpstoxSellOrderAPIView(APIView):
    def post(self, request):
        global buy_order_successful
        quantity = request.data.get("quantity")
        instrument_token = request.data.get("instrument_token")
        access_token = request.data.get("access_token")

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
            "product": "D",
            "validity": "DAY",
            "price": 0,
            "tag": "BackendSellOrder",
            "order_type": "MARKET",
            "transaction_type": "SELL",  
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
            "slice": True
        }

        # url = "https://api-sandbox.upstox.com/v3/order/place"
        # headers = {
        #     'Content-Type': 'application/json',
        #     'Authorization': f'Bearer {access_token}'
        # }

        # try:
        #     response = requests.post(url, headers=headers, data=json.dumps(order_data))
        #     response_data = response.json()
        loggers.info(f"SUCCESS | SELL | Qty: {quantity} | Token: {instrument_token} | Response: {order_data}")
        #     return Response(response_data, status=response.status_code)
        # except requests.exceptions.RequestException as e:
        #     logger.error(f"FAILED | SELL | Qty: {quantity} | Token: {instrument_token} | Error: {str(e)}")
        #     return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            "success": True,
            "msg":"OrderSell Successfully"
        },status=200)
