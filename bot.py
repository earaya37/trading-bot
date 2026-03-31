from binance.client import Client
import os
import time

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

client = Client(API_KEY, API_SECRET)

symbol = "BTCUSDT"

while True:
    try:
        print("Intentando abrir trade de prueba...")

        client.futures_change_leverage(symbol=symbol, leverage=5)

        client.futures_create_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=0.001
        )

        print("✅ TRADE DE PRUEBA EJECUTADO")

        break

    except Exception as e:
        print("❌ ERROR:", e)

    time.sleep(5)
