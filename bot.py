from binance.client import Client
import os
import time

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

client = Client(API_KEY, API_SECRET)

symbol = "BCHUSDT"

print("🚀 TEST ORDEN CORREGIDO")

while True:
    try:
        client.futures_change_leverage(symbol=symbol, leverage=5)

        print("📤 Enviando orden válida...")

        order = client.futures_create_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=0.002   # 🔥 MÁS GRANDE
        )

        print("✅ ORDEN EJECUTADA:", order)
        break

    except Exception as e:
        print("❌ ERROR:", e)

    time.sleep(5)
