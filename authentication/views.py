from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import APIView
from.serializers import RegisterSerializer , LoginSerializer
from rest_framework.response import Response
from .models import User
from rest_framework_simplejwt.tokens import RefreshToken



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