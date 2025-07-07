from django.db import models
from django.conf import settings 
        
        
from django.core.validators import MinValueValidator, MaxValueValidator

class UpstoxFund(models.Model):
    name = models.CharField(max_length=100, unique=True)
    funds = models.DecimalField(max_digits=15, decimal_places=2) 
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    investable_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)

    def __str__(self):
        return self.name
    
    
from django.db import models

class InstrumentCSV(models.Model):
    file = models.FileField(upload_to='csv_files/')
    uploaded_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"CSV uploaded at {self.uploaded_at}"
    
    def save(self, *args, **kwargs):
        InstrumentCSV.objects.all().delete()  
        super().save(*args, **kwargs)
        

    
class FundInstrument(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='fund_instruments'
    )
    name = models.CharField(max_length=100, unique=True)
    funds = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)])
    invest_amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)])
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage of total funds to be invested"
    )
    investable_amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)])
    call_lot = models.PositiveIntegerField(default=0)
    put_lot = models.PositiveIntegerField(default=0)
    token = models.CharField(max_length=500, unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.funds}"