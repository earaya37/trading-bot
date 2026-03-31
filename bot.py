from binance.client import Client
import os

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

client = Client(API_KEY, API_SECRET)

symbol = "BTCUSDT"

try:
    print("🚀 Intentando abrir trade REAL...")

    client.futures_change_leverage(symbol=symbol, leverage=5)

    order = client.futures_create_order(
        symbol=symbol,
        side="BUY",
        type="MARKET",
        quantity=0.001
    )

    print("✅ ORDEN EJECUTADA:", order)

except Exception as e:
    print("❌ ERROR REAL:", e)
