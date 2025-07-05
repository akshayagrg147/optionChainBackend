from rest_framework import serializers
from .models import UpstoxFund

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