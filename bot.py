from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests
import math
from datetime import datetime

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = Client(API_KEY, API_SECRET)

symbol = "XRPUSDT"
interval = Client.KLINE_INTERVAL_15MINUTE

RISK_USDT = 1
MIN_SL_PERCENT = 0.006
MIN_NOTIONAL = 5

last_error = None
error_count = 0
MAX_ERRORS = 5

# ================= TELEGRAM =================
def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# ================= HELPERS =================
def is_valid(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))

# ================= MARKET =================
def get_mark_price():
    try:
        return float(client.futures_mark_price(symbol=symbol)["markPrice"])
    except:
        return None

# ================= POSICIÓN =================
def get_position_amt():
    try:
        for p in client.futures_position_information(symbol=symbol):
            return float(p["positionAmt"])
    except:
        return 0.0

# ================= FORMAT =================
info = client.futures_exchange_info()
filters = next(s for s in info["symbols"] if s["symbol"] == symbol)["filters"]

step = float(next(f for f in filters if f["filterType"]=="LOT_SIZE")["stepSize"])
tick = float(next(f for f in filters if f["filterType"]=="PRICE_FILTER")["tickSize"])

def format_qty(q):
    return math.floor(q / step) * step

# ================= DATA =================
def get_data():
    try:
        k = client.futures_klines(symbol=symbol, interval=interval, limit=200)
        df = pd.DataFrame(k, columns=["t","o","h","l","c","v","ct","q","n","tb","tq","i"])
        df["c"] = df["c"].astype(float)
        df["l"] = df["l"].astype(float)
        df["h"] = df["h"].astype(float)
        return df
    except:
        return None

# ================= SEÑAL =================
def get_signal():
    df = get_data()

    if df is None or len(df) < 200:
        return None,None,None

    df["ema50"] = ta.trend.ema_indicator(df["c"],50)
    df["ema200"] = ta.trend.ema_indicator(df["c"],200)
    df["rsi"] = ta.momentum.rsi(df["c"],14)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = last["c"]

    if not is_valid(price):
        return None,None,None

    if last["ema50"] > last["ema200"] and 40 < last["rsi"] < 55 and last["rsi"] > prev["rsi"]:
        stop = df["l"].tail(5).min()
        if not is_valid(stop):
            return None,None,None
        if abs(price-stop)/price < MIN_SL_PERCENT:
            return None,None,None
        return "LONG",price,stop

    if last["ema50"] < last["ema200"] and 45 < last["rsi"] < 60 and last["rsi"] < prev["rsi"]:
        stop = df["h"].tail(5).max()
        if not is_valid(stop):
            return None,None,None
        if abs(price-stop)/price < MIN_SL_PERCENT:
            return None,None,None
        return "SHORT",price,stop

    return None,None,None

# ================= TRADE =================
def open_trade():
    side,entry,stop = get_signal()

    if side is None or not is_valid(entry) or not is_valid(stop):
        return

    risk = abs(entry - stop)
    if not is_valid(risk) or risk == 0:
        return

    qty = RISK_USDT / risk
    qty = format_qty(qty)

    if qty <= 0:
        return

    if qty * entry < MIN_NOTIONAL:
        return

    if abs(get_position_amt()) > 0:
        return

    order_side = "BUY" if side=="LONG" else "SELL"

    client.futures_create_order(
        symbol=symbol,
        side=order_side,
        type="MARKET",
        quantity=qty
    )

    send_msg(f"✅ TRADE LIMPIO {side}")

# ================= LOOP =================
while True:
    try:
        open_trade()
        time.sleep(120)

    except Exception as e:
        error = str(e)

        # evitar spam
        if error != last_error:
            send_msg(f"❌ {error}")

        error_count += 1

        if error_count >= MAX_ERRORS:
            send_msg("🛑 BOT DETENIDO POR ERRORES")
            break

        time.sleep(60)
