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
    sandbox_token = models.CharField(max_length=500, unique=True, null=True, blank=True)
    api_key = models.CharField(max_length=500, unique=True, null=True, blank=True)
    zerodha_token = models.CharField(max_length=500, unique=True, null=True, blank=True)
    type = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.funds}"


class TradeSession(models.Model):
    """Tracks a simulation/paper trading session"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trade_sessions'
    )
    session_id = models.CharField(max_length=100, unique=True)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    initial_capital = models.DecimalField(max_digits=15, decimal_places=2)
    current_capital = models.DecimalField(max_digits=15, decimal_places=2)
    total_pnl = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"Session {self.session_id} - {self.user}"

class TradeTransaction(models.Model):
    """Tracks individual orders within a session"""
    TRANSACTION_TYPES = (
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    )
    ORDER_STATUS = (
        ('COMPLETE', 'Complete'),
        ('REJECTED', 'Rejected'),
        ('OPEN', 'Open'),
    )
    
    session = models.ForeignKey(
        TradeSession,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    order_id = models.CharField(max_length=100, unique=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    trading_symbol = models.CharField(max_length=50)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=15, decimal_places=2)
    product = models.CharField(max_length=20, default='NRML')
    
    status = models.CharField(max_length=20, choices=ORDER_STATUS, default='COMPLETE')
    status_message = models.TextField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.transaction_type} {self.trading_symbol} ({self.status})"
    

class ZerodhaInstrument(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='zerodha_instruments'
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
    api_key = models.CharField(max_length=500, unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.name} - {self.funds}"