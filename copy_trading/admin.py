from django.contrib import admin

# Register your models here.
from .models import UpstoxFund , FundInstrument
admin.site.register(UpstoxFund)
admin.site.register(FundInstrument)