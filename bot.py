import time
import math
import requests
import numpy as np
import pandas as pd
from binance.client import Client
from binance.enums import *

# ===== CONFIG =====
API_KEY = "4j8dMbSNzJUdYecnZhsPAyqV5TYdZycvmd9RSNPBuUdzMyC8LkhD4n3Zg3enEHxD".strip()
API_SECRET = "9DSGmVB5kvIYDvngB9X16BO62ASQwozngCTroDP2eEBA6ie7IVn8354kItF7wEEJ".strip()
SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT",
    "XRPUSDT","ADAUSDT","DOGEUSDT"
]

TIMEFRAME = "5m"
LEVERAGE = 5

RISK_PER_TRADE = 1  # 🔥 riesgo REAL en USDT

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
ATR_PERIOD = 14

client = Client(API_KEY, API_SECRET)

# ===== PRECISIÓN =====
def get_precision(symbol):
    info = client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            step = float(s['filters'][2]['stepSize'])
            return int(round(-math.log(step, 10), 0))
    return 3

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
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR
    df["tr"] = np.maximum(df["high"] - df["low"],
              np.maximum(abs(df["high"] - df["close"].shift()),
                         abs(df["low"] - df["close"].shift())))
    df["atr"] = df["tr"].rolling(ATR_PERIOD).mean()

    return df

# ===== POSICIÓN =====
def get_position(symbol):
    try:
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            if float(p["positionAmt"]) != 0:
                return True
    except:
        return False
    return False

# ===== CÁLCULO PRO =====
def calculate_trade(symbol, price, atr, side):
    precision = get_precision(symbol)

    # distancia SL (1 ATR)
    sl_distance = atr

    if sl_distance == 0:
        return None

    # qty basada en riesgo real
    qty = RISK_PER_TRADE / sl_distance

    # ajustar leverage
    qty = qty / price * LEVERAGE

    qty = round(qty, precision)

    # SL y TP
    if side == "LONG":
        sl = price - sl_distance
        tp = price + (sl_distance * 2)
    else:
        sl = price + sl_distance
        tp = price - (sl_distance * 2)

    return qty, sl, tp

# ===== ORDEN =====
def open_trade(symbol, side, price, atr):
    data = calculate_trade(symbol, price, atr, side)

    if not data:
        return

    qty, sl, tp = data

    try:
        print(f"🚀 {side} {symbol} | Qty: {qty}")

        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

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

        print(f"✅ Trade abierto | SL: {sl:.4f} | TP: {tp:.4f}")

    except Exception as e:
        print(f"❌ ERROR {symbol}: {e}")

# ===== LÓGICA =====
def check_signal(df):
    last = df.iloc[-1]

    if math.isnan(last["rsi"]) or math.isnan(last["atr"]):
        return None

    if last["ema20"] > last["ema50"] and last["rsi"] > 50:
        return "LONG"

    if last["ema20"] < last["ema50"] and last["rsi"] < 50:
        return "SHORT"

    return None

# ===== LOOP =====
def run():
    print("🚀 BOT PRO ACTIVO (RIESGO REAL $1)")

    while True:
        for symbol in SYMBOLS:
            try:
                df = get_klines(symbol)
                df = calculate_indicators(df)

                signal = check_signal(df)

                if signal and not get_position(symbol):
                    price = df.iloc[-1]["close"]
                    atr = df.iloc[-1]["atr"]

                    open_trade(symbol, signal, price, atr)

            except Exception as e:
                print(f"❌ LOOP {symbol}: {e}")

        time.sleep(15)

if __name__ == "__main__":
    run()
