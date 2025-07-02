# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests


class OptionChainAPIView(APIView):
    def post(self, request):
        instrument_key = request.data.get('instrument_key')
        expiry_date = request.data.get('expiry_date')
        auth_header = request.headers.get('Authorization')

        # Check required fields
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
