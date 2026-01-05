# Generated manually to fix unique constraints per user

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('copy_trading', '0010_trade_session_and_transaction'),
    ]

    operations = [
        # Remove unique constraint from name
        migrations.AlterField(
            model_name='fundinstrument',
            name='name',
            field=models.CharField(max_length=100),
        ),
        # Remove unique constraint from token
        migrations.AlterField(
            model_name='fundinstrument',
            name='token',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        # Remove unique constraint from sandbox_token
        migrations.AlterField(
            model_name='fundinstrument',
            name='sandbox_token',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        # Remove unique constraint from api_key
        migrations.AlterField(
            model_name='fundinstrument',
            name='api_key',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        # Remove unique constraint from zerodha_token
        migrations.AlterField(
            model_name='fundinstrument',
            name='zerodha_token',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        # Add unique constraint for (user, name)
        migrations.AddConstraint(
            model_name='fundinstrument',
            constraint=models.UniqueConstraint(fields=['user', 'name'], name='unique_user_name'),
        ),
    ]

