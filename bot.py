from binance.client import Client
from binance.enums import *

API_KEY = "TU_API_KEY"
API_SECRET = "TU_API_SECRET"

client = Client(API_KEY, API_SECRET)

SYMBOL = "XRPUSDT"

def test_order():
    try:
        print("🚀 Enviando orden REAL...")

        order = client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=5  # pequeño
        )

        print("✅ ORDEN EJECUTADA")
        print(order)

    except Exception as e:
        print(f"❌ ERROR REAL: {e}")

if __name__ == "__main__":
    test_order()
