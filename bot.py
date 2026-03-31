from binance.client import Client
import os
import time

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

client = Client(API_KEY, API_SECRET)

symbol = "BCHUSDT"

print("🚀 INICIO TEST ORDEN REAL")

while True:
    try:
        balance = client.futures_account_balance()
        print("💰 Balance:", balance)

        client.futures_change_leverage(symbol=symbol, leverage=5)

        print("📤 Enviando orden...")

        order = client.futures_create_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=0.001
        )

        print("✅ ORDEN EJECUTADA:", order)
        break

    except Exception as e:
        print("❌ ERROR REAL BINANCE:", e)

    time.sleep(5)
