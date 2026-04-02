import time
import math
import requests
import numpy as np
import pandas as pd
from binance.client import Client
from binance.enums import *

# ===== CONFIG =====
API_KEY = "TU_API_KEY"
API_SECRET = "TU_API_SECRET"

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
TELEGRAM_TOKEN = "TU_TOKEN"
CHAT_ID = "TU_CHAT_ID"

def send(msg):
    print(f"📩 {msg}")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ Telegram error: {e}")

# ===== DATA =====
def get_klines(symbol):
    klines = client.futures_klines(symbol=symbol, interval=TIMEFRAME, limit=150)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "_","_","_","_","_","_"
    ])
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    return df

# ===== INDICADORES =====
def calculate_indicators(df):
    df["ema20"] = df["close"].ewm(span=EMA_FAST).mean()
    df["ema50"] = df["close"].ewm(span=EMA_SLOW).mean()

    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    return df

# ===== VALIDACIÓN =====
def safe(val):
    return val is not None and not (isinstance(val, float) and math.isnan(val))

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
    return False

# ===== TAMAÑO =====
def calc_qty(price):
    return round((RISK_USDT * LEVERAGE) / price, 3)

# ===== ORDEN =====
def open_trade(symbol, side, price):
    qty = calc_qty(price)

    try:
        print(f"🚀 Ejecutando {side} {symbol} | Qty: {qty}")

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

        msg = f"{side} {symbol}\nQty: {qty}\nSL: {round(sl,4)}\nTP: {round(tp,4)}"
        send(msg)

    except Exception as e:
        print(f"❌ ERROR ORDEN {symbol}: {e}")
        send(f"❌ Error {symbol}: {e}")

# ===== LÓGICA =====
def check_signal(df):
    last = df.iloc[-1]

    if not all(map(safe, [
        last["ema20"], last["ema50"], last["rsi"]
    ])):
        return None

    price = last["close"]

    if last["ema20"] > last["ema50"] and price > last["ema20"] and last["rsi"] > 50:
        return "LONG"

    if last["ema20"] < last["ema50"] and price < last["ema20"] and last["rsi"] < 50:
        return "SHORT"

    return None

# ===== LOOP =====
def run():
    print("🚀 BOT SCALPING ACTIVO")

    try:
        send("🤖 Bot iniciado correctamente")
    except:
        pass

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
                print(f"❌ ERROR LOOP {symbol}: {e}")

        time.sleep(15)

# ===== START =====
if __name__ == "__main__":
    run()
