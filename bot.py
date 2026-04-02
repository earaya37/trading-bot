from binance.client import Client

API_KEY = "TU_API_KEY"
API_SECRET = "TU_API_SECRET"

client = Client(API_KEY, API_SECRET)

try:
    print("SPOT TEST:")
    print(client.get_account())

    print("\nFUTURES TEST:")
    print(client.futures_account_balance())

except Exception as e:
    print("ERROR:", e)
