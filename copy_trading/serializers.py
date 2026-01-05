from rest_framework import serializers
from .models import UpstoxFund,InstrumentCSV,FundInstrument , ZerodhaInstrument

class UpstoxFundSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpstoxFund
        fields = ['id', 'name', 'funds', 'percentage', 'investable_amount']
        read_only_fields = ['investable_amount']

    def create(self, validated_data):
        funds = validated_data.get('funds', 0)
        percentage = validated_data.get('percentage', 0)
        validated_data['investable_amount'] = (funds * percentage) / 100
        return super().create(validated_data)

    def update(self, instance, validated_data):
        instance.name = validated_data.get('name', instance.name)
        instance.funds = validated_data.get('funds', instance.funds)
        instance.percentage = validated_data.get('percentage', instance.percentage)
        instance.investable_amount = (instance.funds * instance.percentage) / 100
        instance.save()
        return instance
    
    
from rest_framework import serializers
from .models import InstrumentCSV 

class InstrumentCSVSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstrumentCSV
        fields = ['id', 'file', 'uploaded_at']


class FundInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FundInstrument
        fields = '__all__'
    
    def validate(self, data):
        # Get user from context (request) - this is the most reliable source
        user = None
        if 'request' in self.context:
            user = self.context['request'].user
        elif 'user' in data:
            # If user is an ID, get the user object
            user_id = data['user']
            if isinstance(user_id, int):
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    user = User.objects.get(id=user_id)
                except User.DoesNotExist:
                    pass
            else:
                user = user_id
        
        if not user:
            return data
        
        instance = self.instance
        
        # Validate name uniqueness per user
        name = data.get('name') if 'name' in data else (instance.name if instance else None)
        if name:
            queryset = FundInstrument.objects.filter(user=user, name=name)
            if instance:
                queryset = queryset.exclude(pk=instance.pk)
            if queryset.exists():
                raise serializers.ValidationError({'name': 'fund instrument with this name already exists.'})
        
        # Validate token uniqueness per user (if provided)
        token = data.get('token') if 'token' in data else (instance.token if instance else None)
        if token:
            queryset = FundInstrument.objects.filter(user=user, token=token)
            if instance:
                queryset = queryset.exclude(pk=instance.pk)
            if queryset.exists():
                raise serializers.ValidationError({'token': 'fund instrument with this token already exists.'})
        
        # Validate api_key uniqueness per user (if provided)
        api_key = data.get('api_key') if 'api_key' in data else (instance.api_key if instance else None)
        if api_key:
            queryset = FundInstrument.objects.filter(user=user, api_key=api_key)
            if instance:
                queryset = queryset.exclude(pk=instance.pk)
            if queryset.exists():
                raise serializers.ValidationError({'api_key': 'fund instrument with this api key already exists.'})
        
        # Validate zerodha_token uniqueness per user (if provided)
        zerodha_token = data.get('zerodha_token') if 'zerodha_token' in data else (instance.zerodha_token if instance else None)
        if zerodha_token:
            queryset = FundInstrument.objects.filter(user=user, zerodha_token=zerodha_token)
            if instance:
                queryset = queryset.exclude(pk=instance.pk)
            if queryset.exists():
                raise serializers.ValidationError({'zerodha_token': 'fund instrument with this zerodha token already exists.'})
        
        return data


class ZerodhaInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZerodhaInstrument
        fields = '__all__'