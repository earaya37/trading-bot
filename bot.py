import time
import math
import requests
import numpy as np
import pandas as pd
from binance.client import Client
from binance.enums import *

API_KEY = "TU_API_KEY"
API_SECRET = "TU_API_SECRET"

SYMBOLS = ["BTCUSDT","ETHUSDT","XRPUSDT"]

TIMEFRAME = "5m"
LEVERAGE = 5
RISK_USDT = 1

client = Client(API_KEY, API_SECRET)

TELEGRAM_TOKEN = "TU_TOKEN"
CHAT_ID = "TU_CHAT_ID"

def send(msg):
    print(f"📩 TELEGRAM: {msg}")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ Telegram error: {e}")

def get_klines(symbol):
    print(f"📊 Obteniendo datos {symbol}")
    klines = client.futures_klines(symbol=symbol, interval=TIMEFRAME, limit=100)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "_","_","_","_","_","_"
    ])
    df["close"] = df["close"].astype(float)
    return df

def calculate_indicators(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    return df

def check_signal(df):
    last = df.iloc[-1]

    print(f"🔎 Precio: {last['close']} | RSI: {last['rsi']}")

    if math.isnan(last["rsi"]):
        print("⚠️ RSI inválido")
        return None

    if last["ema20"] > last["ema50"] and last["rsi"] > 50:
        print("🟢 Señal LONG detectada")
        return "LONG"

    if last["ema20"] < last["ema50"] and last["rsi"] < 50:
        print("🔴 Señal SHORT detectada")
        return "SHORT"

    print("⏸ Sin señal")
    return None

def run():
    print("🚀 BOT DEBUG ACTIVO")
    send("🤖 Bot iniciado correctamente")

    while True:
        for symbol in SYMBOLS:
            try:
                df = get_klines(symbol)
                df = calculate_indicators(df)

                signal = check_signal(df)

                if signal:
                    send(f"🔥 {signal} {symbol}")

            except Exception as e:
                print(f"❌ ERROR {symbol}: {e}")

        time.sleep(10)

if __name__ == "__main__":
    run()
