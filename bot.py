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

LOOKBACK = 20
ATR_PERIOD = 14
ATR_MIN = 0.0002

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
    klines = client.futures_klines(symbol=symbol, interval=TIMEFRAME, limit=200)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "_","_","_","_","_","_"
    ])
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df

# ===== INDICADORES =====
def calculate_indicators(df):
    df["max_high"] = df["high"].rolling(LOOKBACK).max()
    df["min_low"] = df["low"].rolling(LOOKBACK).min()

    df["vol_avg"] = df["volume"].rolling(20).mean()

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
    try:
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            amt = float(p["positionAmt"])
            if amt != 0:
                return amt
    except:
        return 0
    return 0

# ===== TAMAÑO =====
def calc_qty(price):
    return round((RISK_USDT * LEVERAGE) / price, 3)

# ===== ORDEN =====
def open_trade(symbol, side, price, atr):
    qty = calc_qty(price)

    try:
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        sl = price - atr if side == "LONG" else price + atr
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
        print(f"❌ {symbol} order error: {e}")

# ===== LÓGICA BREAKOUT =====
def check_signal(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if not all(map(safe, [
        last["max_high"], last["min_low"], last["atr"], last["vol_avg"]
    ])):
        return None

    if last["atr"] < ATR_MIN:
        return None

    # LONG breakout
    if last["close"] > prev["max_high"]:
        if last["volume"] > last["vol_avg"]:
            return "LONG"

    # SHORT breakout
    if last["close"] < prev["min_low"]:
        if last["volume"] > last["vol_avg"]:
            return "SHORT"

    return None

# ===== LOOP =====
def run():
    print("🚀 BREAKOUT BOT ACTIVO")

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

        time.sleep(20)

if __name__ == "__main__":
    run()
