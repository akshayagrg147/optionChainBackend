from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import APIView
from.serializers import RegisterSerializer , LoginSerializer
from rest_framework.response import Response
from .models import User
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from copy_trading.models import FundInstrument



class RegisterViewSet(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                'success': True,
                'message': "Registration Successful",
                'data': serializer.data
            }, status=200)
        return Response({'success': False, 'error': serializer.errors}, status=400)
    
    
class LoginViewSet(APIView):
    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        if email and password:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({'success': False, 'message': 'User does not exist'}, status=404)

            if user.check_password(password):
                refresh = RefreshToken.for_user(user)
                user_data = LoginSerializer(user).data

                return Response({
                    'success': True,
                    'message': 'Login Successful',
                    'data': {
                        'refresh': str(refresh),
                        'access': str(refresh.access_token),
                        'user': user_data
                    }
                }, status=200)
            else:
                return Response({'success': False, 'message': 'Invalid credentials'}, status=400)
        else:
            return Response({'success': False, 'message': 'Email and password are required'}, status=400)


class LogoutViewSet(APIView):
    """
    Logout view that blacklists all tokens for the authenticated user.
    This will invalidate all sessions and force re-authentication.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            # Get the refresh token from the request
            refresh_token = request.data.get('refresh_token')
            
            if not refresh_token:
                return Response({
                    'success': False, 
                    'message': 'Refresh token is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Blacklist the specific refresh token
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            # Additionally, blacklist ALL outstanding tokens for this user
            # This ensures all sessions are invalidated
            user = request.user
            outstanding_tokens = OutstandingToken.objects.filter(user=user)
            
            for outstanding_token in outstanding_tokens:
                if not BlacklistedToken.objects.filter(token=outstanding_token).exists():
                    BlacklistedToken.objects.create(token=outstanding_token)
            
            # Clear fund instrument data for the user (but keep user data)
            fund_instruments_deleted = FundInstrument.objects.filter(user=user).count()
            FundInstrument.objects.filter(user=user).delete()
            
            return Response({
                'success': True,
                'message': f'Successfully logged out. All sessions have been invalidated. Cleared {fund_instruments_deleted} fund instrument records.',
                'fund_instruments_cleared': fund_instruments_deleted
            }, status=status.HTTP_200_OK)
            
        except TokenError:
            return Response({
                'success': False,
                'message': 'Invalid refresh token'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Logout failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LogoutAllViewSet(APIView):
    """
    Logout from all devices - blacklists all tokens for the authenticated user.
    This is useful when user wants to logout from all devices at once.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            user = request.user
            
            # Get all outstanding tokens for this user
            outstanding_tokens = OutstandingToken.objects.filter(user=user)
            
            # Blacklist all outstanding tokens
            blacklisted_count = 0
            for outstanding_token in outstanding_tokens:
                if not BlacklistedToken.objects.filter(token=outstanding_token).exists():
                    BlacklistedToken.objects.create(token=outstanding_token)
                    blacklisted_count += 1
            
            # Clear fund instrument data for the user (but keep user data)
            fund_instruments_deleted = FundInstrument.objects.filter(user=user).count()
            FundInstrument.objects.filter(user=user).delete()
            
            return Response({
                'success': True,
                'message': f'Successfully logged out from all devices. {blacklisted_count} sessions invalidated. Cleared {fund_instruments_deleted} fund instrument records.',
                'blacklisted_sessions': blacklisted_count,
                'fund_instruments_cleared': fund_instruments_deleted
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Logout from all devices failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)