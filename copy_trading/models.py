from django.db import models

class UpstoxFund(models.Model):
    name = models.CharField(max_length=100, unique=True)
    funds = models.DecimalField(max_digits=15, decimal_places=2)  # available_margin
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    investable_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)

    def __str__(self):
        return self.name