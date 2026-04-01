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
    "XRPUSDT","ADAUSDT","DOGEUSDT",
    "AVAXUSDT","MATICUSDT","LINKUSDT"
]

TIMEFRAME = "15m"
LEVERAGE = 5
RISK_USDT = 1

EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_MIN = 0.0005

client = Client(API_KEY, API_SECRET)

# ===== TELEGRAM =====
TELEGRAM_TOKEN = "TU_TOKEN"
CHAT_ID = "TU_CHAT_ID"

def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ===== DATA =====
def get_klines(symbol):
    klines = client.futures_klines(symbol=symbol, interval=TIMEFRAME, limit=300)
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
    df["ema50"] = df["close"].ewm(span=EMA_FAST).mean()
    df["ema200"] = df["close"].ewm(span=EMA_SLOW).mean()

    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    df["tr"] = np.maximum(df["high"] - df["low"],
              np.maximum(abs(df["high"] - df["close"].shift()),
                         abs(df["low"] - df["close"].shift())))
    df["atr"] = df["tr"].rolling(ATR_PERIOD).mean()

    return df

# ===== VALIDACIÓN =====
def safe(val):
    return val is not None and not (isinstance(val, float) and math.isnan(val))

# ===== POSICIÓN =====
def get_position(symbol):
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        amt = float(p["positionAmt"])
        if amt != 0:
            return amt
    return 0

# ===== TAMAÑO =====
def calc_qty(price):
    qty = (RISK_USDT * LEVERAGE) / price
    return round(qty, 3)

# ===== ORDEN =====
def open_trade(symbol, side, price, atr):
    qty = calc_qty(price)

    if qty <= 0:
        return

    try:
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        sl = price - atr*1.2 if side == "LONG" else price + atr*1.2
        tp = price + atr*2 if side == "LONG" else price - atr*2

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

        msg = f"{side} {symbol}\nQty: {qty}"
        print(msg)
        send(msg)

    except Exception as e:
        print(f"❌ {symbol} error: {e}")

# ===== LÓGICA =====
def check_signal(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if not all(map(safe, [
        last["ema50"], last["ema200"], last["rsi"], last["atr"]
    ])):
        return None

    if last["atr"] < ATR_MIN:
        return None

    price = last["close"]

    if last["ema50"] > last["ema200"]:
        if price > last["ema50"] and prev["close"] <= prev["ema50"]:
            if last["rsi"] > 45:
                return "LONG"

    if last["ema50"] < last["ema200"]:
        if price < last["ema50"] and prev["close"] >= prev["ema50"]:
            if last["rsi"] < 55:
                return "SHORT"

    return None

# ===== LOOP =====
def run():
    print("🚀 MULTI-PAIR BOT ACTIVO")

    while True:
        for symbol in SYMBOLS:
            try:
                df = get_klines(symbol)
                df = calculate_indicators(df)

                signal = check_signal(df)

                if signal and get_position(symbol) == 0:
                    price = df.iloc[-1]["close"]
                    atr = df.iloc[-1]["atr"]

                    open_trade(symbol, signal, price, atr)

            except Exception as e:
                print(f"❌ {symbol} loop error: {e}")

        time.sleep(30)

if __name__ == "__main__":
    run()
