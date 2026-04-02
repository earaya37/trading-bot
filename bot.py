from binance.client import Client

API_KEY = "TU_API_KEY"
API_SECRET = "TU_API_SECRET"

client = Client(API_KEY, API_SECRET)

try:
    print(client.futures_account_balance())
    print("✅ API FUNCIONANDO")
except Exception as e:
    print("❌ ERROR:", e)
