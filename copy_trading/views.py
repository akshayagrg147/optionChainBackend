from django.shortcuts import render

# Create your views here.
from django.http import JsonResponse

import json

# def get_live_option_chain(request):
#     data = redis_client.get("live_option_chain")
#     if data:
#         return JsonResponse(json.loads(data), safe=False)
#     return JsonResponse({"message": "No data yet"}, status=404)


import requests
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import urllib.parse
import redis
import json


redis_client = redis.StrictRedis(host='127.0.0.1', port=6379, db=0)

@api_view(['GET'])
def get_option_chain(request):
    access_token = request.headers.get('Authorization')
    if not access_token:
        return Response({'error': 'Authorization header missing'}, status=status.HTTP_400_BAD_REQUEST)
    instrument_key = request.GET.get('instrument_key')
    expiry_date = request.GET.get('expiry_date')

    if not instrument_key or not expiry_date:
        return Response({'error': 'instrument_key and expiry_date are required'}, status=status.HTTP_400_BAD_REQUEST)

    
    encoded_key = urllib.parse.quote(instrument_key)
    url = f"https://api.upstox.com/v2/option/chain?instrument_key={encoded_key}&expiry_date={expiry_date}"

    headers = {"Authorization": access_token}

    try:
      
        response = requests.get(url, headers=headers)
        option_data = response.json()
        data_list = option_data.get('data', [])
        instrument_tokens = []
        
        for row in data_list:
            call = row.get("call_options", {})
            put = row.get("put_options", {})

            if call.get("instrument_key"):
                instrument_tokens.append(call["instrument_key"])
            if put.get("instrument_key"):
                instrument_tokens.append(put["instrument_key"])
        redis_client.set(f"option_chain_tokens:{expiry_date}", json.dumps(instrument_tokens))
        
        
       
        
        return Response(response.json(), status=response.status_code)

    except Exception as e:
        return Response({'error': 'Request failed', 'details': str(e)}, status=500)