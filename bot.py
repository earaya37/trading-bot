import time
import requests

TELEGRAM_TOKEN = "TU_TOKEN"
CHAT_ID = "TU_CHAT_ID"

def send(msg):
    print(f"📩 {msg}")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ Telegram error: {e}")

def run():
    print("🚀 BOT TEST INICIADO")
    send("✅ BOT FUNCIONANDO")

    while True:
        print("🔁 Loop activo...")
        send("ping")
        time.sleep(10)

if __name__ == "__main__":
    run()
