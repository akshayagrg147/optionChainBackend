# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests
import csv
import requests
import pandas as pd
from .models import UpstoxFund
from django.shortcuts import get_object_or_404
from .serializers import UpstoxFundSerializer


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
            
            obj, created = UpstoxFund.objects.update_or_create(
                name=user_name,
                defaults={
                    "funds": available_margin,
                    
                }
            )

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