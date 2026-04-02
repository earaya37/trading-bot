import time
import math
import os
import requests
import numpy as np
import pandas as pd
from binance.client import Client
from binance.enums import *

# ===== ENV VARIABLES (RAILWAY) =====
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Limpieza extra por seguridad
if API_KEY:
    API_KEY = API_KEY.strip()
if API_SECRET:
    API_SECRET = API_SECRET.strip()

# ===== CONFIG =====
SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT"
]

TIMEFRAME = "5m"
LEVERAGE = 5
RISK_USDT = 1

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14

client = Client(API_KEY, API_SECRET)

# ===== TELEGRAM =====
def send(msg):
    print(f"📩 {msg}")
    try:
        if TELEGRAM_TOKEN and CHAT_ID:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ Telegram error: {e}")

# ===== TEST API =====
def test_api():
    try:
        print("🧪 Probando API Binance...")
        client.futures_account_balance()
        print("✅ API OK - Railway conectado")
        send("🤖 Bot conectado correctamente en Railway")
    except Exception as e:
        print(f"❌ ERROR API: {e}")
        send(f"❌ API ERROR: {e}")
        exit()

# ===== DATA =====
def get_klines(symbol):
    klines = client.futures_klines(symbol=symbol, interval=TIMEFRAME, limit=150)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "_","_","_","_","_","_"
    ])
    df["close"] = df["close"].astype(float)
    return df

# ===== INDICADORES =====
def calculate_indicators(df):
    df["ema20"] = df["close"].ewm(span=EMA_FAST).mean()
    df["ema50"] = df["close"].ewm(span=EMA_SLOW).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    return df

# ===== POSICIÓN =====
def get_position(symbol):
    try:
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            if float(p["positionAmt"]) != 0:
                return True
    except Exception as e:
        print(f"❌ Error posición {symbol}: {e}")
    return False

# ===== TAMAÑO =====
def calc_qty(price):
    return round((RISK_USDT * LEVERAGE) / price, 3)

# ===== ORDEN =====
def open_trade(symbol, side, price):
    qty = calc_qty(price)

    try:
        print(f"🚀 {side} {symbol} | Qty: {qty}")

        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        sl = price * 0.997 if side == "LONG" else price * 1.003
        tp = price * 1.004 if side == "LONG" else price * 0.996

        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == "LONG" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=round(sl, 4),
            closePosition=True
        )

        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if side == "LONG" else SIDE_BUY,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=round(tp, 4),
            closePosition=True
        )

        send(f"{side} {symbol} | Qty: {qty}")

    except Exception as e:
        print(f"❌ ERROR ORDEN {symbol}: {e}")
        send(f"❌ Error {symbol}: {e}")

# ===== LÓGICA =====
def check_signal(df):
    last = df.iloc[-1]

    if math.isnan(last["rsi"]):
        return None

    price = last["close"]

    if last["ema20"] > last["ema50"] and price > last["ema20"] and last["rsi"] > 50:
        return "LONG"

    if last["ema20"] < last["ema50"] and price < last["ema20"] and last["rsi"] < 50:
        return "SHORT"

    return None

# ===== LOOP =====
def run():
    print("🚀 BOT SCALPING EN RAILWAY")

    test_api()

    while True:
        for symbol in SYMBOLS:
            try:
                df = get_klines(symbol)
                df = calculate_indicators(df)

                signal = check_signal(df)

                if signal and not get_position(symbol):
                    price = df.iloc[-1]["close"]
                    open_trade(symbol, signal, price)

            except Exception as e:
                print(f"❌ LOOP ERROR {symbol}: {e}")

        time.sleep(15)

if __name__ == "__main__":
    run()
