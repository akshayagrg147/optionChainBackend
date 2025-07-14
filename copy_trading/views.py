# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests
import csv
import requests
import pandas as pd
from .models import UpstoxFund , InstrumentCSV ,FundInstrument
from django.shortcuts import get_object_or_404
from .serializers import UpstoxFundSerializer ,InstrumentCSVSerializer , FundInstrumentSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from django.conf import settings
import os
import json
import datetime


class OptionChainAPIView(APIView):
    def post(self, request):
        instrument_key = request.data.get('instrument_key')
        expiry_date = request.data.get('expiry_date')
        auth_header = request.headers.get('Authorization')

      
        if not instrument_key or not expiry_date or not auth_header:
            return Response(
                {'error': 'instrument_key, expiry_date, and Authorization header are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        url = "https://api.upstox.com/v2/option/chain"
        headers = {
            'Authorization': auth_header,
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        params = {
            'instrument_key': instrument_key,
            'expiry_date': expiry_date
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return Response(response.json(), status=response.status_code)
        except requests.RequestException as e:
            return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)




class UpstoxMultiAccountFundsFromXLSX(APIView):
    def get(self, request):
        try:
           
            df = pd.read_csv('tokens.csv')  

            funds_data = []

            for _, row in df.iterrows():
                name = row['name']
                access_token = row['access_token']

                url = "https://api.upstox.com/v2/user/get-funds-and-margin"
                headers = {
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {access_token}'
                }
  
                try:
                    response = requests.get(url, headers=headers)
                    data = response.json()
                    print(f"{name} -> Bearer Token: {access_token}")
                    print(f"Authorization Header: Bearer {access_token}")
                

                    if response.status_code == 200 and data.get("status") == "success":
                        funds = data.get("data", {})
                        funds_data.append({
                            'name': name,
                            'funds': funds
                        })
                    else:
                        funds_data.append({
                            'name': name,
                            'error': data.get("errors", data)
                        })

                except Exception as e:
                    funds_data.append({
                        'name': name,
                        'error': str(e)
                    })

            return Response({"status": "success", "results": funds_data}, status=status.HTTP_200_OK)

        except FileNotFoundError:
            return Response({"error": "tokens.csv file not found"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        
class UpstoxMarginAPIView(APIView):
    authentication_classes = []            
    permission_classes = [AllowAny] 
    def get(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response(
                {"error": "Authorization header with Bearer token is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        access_token = auth_header.split("Bearer ")[1]

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

   
        profile_url = "https://api.upstox.com/v2/user/profile"
        profile_response = requests.get(profile_url, headers=headers)

        if profile_response.status_code != 200:
            return Response({
                "success": False,
                "message": "Failed to fetch user profile",
                "error": profile_response.json()
            }, status=profile_response.status_code)

        user_data = profile_response.json().get("data", {})
        user_name = user_data.get("user_name", "Unknown User")

       
        margin_url = "https://api.upstox.com/v2/user/get-funds-and-margin"
        margin_response = requests.get(margin_url, headers=headers)

        if margin_response.status_code == 200:
            margin_data = margin_response.json()
            equity = margin_data.get("data", {}).get("equity", {})
            
            available_margin = equity.get("availableMargin", 0.00)
            
       
            return Response({
                "success": True,
                "user_name": user_name,
                "margins": {
                    "available_margin": equity.get("availableMargin"),
                    "used_margin": equity.get("usedMargin"),
                    "net_margin": equity.get("net")
                }
            })

       
        if margin_response.status_code == 400:
            error_code = margin_response.json().get("errors", [{}])[0].get("errorCode")
            if error_code == "UDAPI100072":
                return Response({
                    "success": False,
                    "user_name": user_name,
                    "message": "Funds service is accessible from 5:30 AM to 12:00 AM IST only. Please try again later."
                }, status=403)

  
        return Response({
            "success": False,
            "user_name": user_name,
            "message": "Failed to fetch margin",
            "error": margin_response.json()
        }, status=margin_response.status_code)
        
        
        
class UpstoxFundListCreateView(APIView):
    def get(self, request):
        funds = UpstoxFund.objects.all()
        serializer = UpstoxFundSerializer(funds, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = UpstoxFundSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UpstoxFundDetailUpdateView(APIView):
    def get(self, request, pk):
        fund = get_object_or_404(UpstoxFund, pk=pk)
        serializer = UpstoxFundSerializer(fund)
        return Response(serializer.data)

    def patch(self, request, pk):
        fund = get_object_or_404(UpstoxFund, pk=pk)
        serializer = UpstoxFundSerializer(fund, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    
class UpstoxFundAllView(APIView):
    def get(self, request):
        all_funds = UpstoxFund.objects.all()
        serializer = UpstoxFundSerializer(all_funds, many=True)
        return Response(serializer.data)
    
    
class InstrumentCSVReplaceView(APIView):

    def post(self, request):
       
        existing_csv = InstrumentCSV.objects.first()
        if existing_csv:
            if existing_csv.file:
                existing_csv.file.delete(save=False)
            existing_csv.delete()

    
        serializer = InstrumentCSVSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'New CSV uploaded and old one replaced.'}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    
    
class FundInstrumentView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        data = request.data.copy()
        data['user'] = request.user.id
        serializer = FundInstrumentSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'FundInstrument created successfully', 'data': serializer.data}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        instance = get_object_or_404(FundInstrument, pk=pk,user=request.user)
        serializer = FundInstrumentSerializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'FundInstrument updated successfully', 'data': serializer.data}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    
    def delete(self, request, pk):
        instance = get_object_or_404(FundInstrument, pk=pk, user=request.user)
        instance.delete()
        return Response({'message': 'FundInstrument deleted successfully'}, status=status.HTTP_200_OK)
    
    
    def get(self, request):
        queryset = FundInstrument.objects.filter(user=request.user)
        serializer = FundInstrumentSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    
    
    
class GetUpstoxFundsAPIView(APIView):
    authentication_classes = []            
    permission_classes = [AllowAny]   

    def get(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response(
                {"error": "Authorization header with Bearer token is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        access_token = auth_header.split("Bearer ")[1].strip()

        url = "https://api.upstox.com/v2/user/get-funds-and-margin"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return Response({"status": "success", "data": data}, status=status.HTTP_200_OK)

        except requests.exceptions.HTTPError as http_err:
            return Response({
                "status": "error",
                "message": f"HTTP error occurred: {str(http_err)}",
                "upstox_response": response.json()
            }, status=response.status_code)

        except Exception as err:
            return Response({
                "status": "error",
                "message": f"Other error occurred: {str(err)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            
            
class GetTradingSymbol(APIView):
    def post(self, request):
        name = request.data.get("name")
        expiry = request.data.get("expiry")
        option_type = request.data.get("option_type")
        strike = request.data.get("strike")
        
        
        
        
        

        if not all([name, expiry, option_type, strike]):
            return Response({"error": "All fields are required"}, status=status.HTTP_400_BAD_REQUEST)

        json_path = os.path.join(settings.BASE_DIR, 'nse.json')
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                for item in data:
                    if (
                            str(item.get("exchange")).strip().upper() == str(name).strip().upper() and
                            str(item.get("expiry")) == str(expiry) and
                            str(item.get("instrument_type")).strip().upper() == str(option_type).strip().upper() and
                            float(item.get("strike_price")) == float(strike)
                        ):
                        
                        return Response({"tradingsymbol": item.get("trading_symbol")}, status=status.HTTP_200_OK)
                        
                        

            return Response({"error": "Matching record not found"}, status=status.HTTP_404_NOT_FOUND)

        except FileNotFoundError:
            return Response({"error": "JSON file not found"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON format"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class GetTradingSymbolsCSV(APIView):
    def post(self, request):
        option_requests = request.data.get("options")  # Expecting a list

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
                                "tradingsymbol": row.get("tradingsymbol")
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