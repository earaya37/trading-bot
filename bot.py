from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests
import math
from datetime import datetime, timedelta

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
MAX_DAILY_LOSS = 3

daily_loss = 0
current_day = datetime.now().day

# ================= TELEGRAM =================
def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

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

def format_price(p):
    return math.floor(p / tick) * tick

# ================= DATA =================
def get_data():
    k = client.futures_klines(symbol=symbol, interval=interval, limit=200)
    df = pd.DataFrame(k, columns=["t","o","h","l","c","v","ct","q","n","tb","tq","i"])
    df["c"] = df["c"].astype(float)
    df["l"] = df["l"].astype(float)
    df["h"] = df["h"].astype(float)
    return df

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

    if last["ema50"] > last["ema200"] and 40 < last["rsi"] < 55 and last["rsi"] > prev["rsi"]:
        stop = df["l"].tail(5).min()
        if stop is None:
            return None,None,None
        if abs(price-stop)/price < MIN_SL_PERCENT:
            return None,None,None
        return "LONG",price,stop

    if last["ema50"] < last["ema200"] and 45 < last["rsi"] < 60 and last["rsi"] < prev["rsi"]:
        stop = df["h"].tail(5).max()
        if stop is None:
            return None,None,None
        if abs(price-stop)/price < MIN_SL_PERCENT:
            return None,None,None
        return "SHORT",price,stop

    return None,None,None

# ================= VALIDACIÓN =================
def validate_trade(side, entry, stop, qty):

    if entry is None or stop is None:
        return False

    mark = get_mark_price()
    if mark is None:
        return False

    if side == "LONG" and stop >= mark:
        return False

    if side == "SHORT" and stop <= mark:
        return False

    if qty * entry < MIN_NOTIONAL:
        return False

    return True

# ================= TRADE =================
def open_trade():
    global daily_loss, current_day

    if datetime.now().day != current_day:
        daily_loss = 0
        current_day = datetime.now().day

    if daily_loss >= MAX_DAILY_LOSS:
        send_msg("🛑 STOP DIARIO")
        return

    if abs(get_position_amt()) > 0:
        return

    side,entry,stop = get_signal()

    # 🔥 VALIDACIÓN CRÍTICA
    if side is None or entry is None or stop is None:
        return

    risk = abs(entry - stop)
    if risk == 0:
        return

    qty = RISK_USDT / risk
    qty = format_qty(qty)

    if qty <= 0:
        return

    if not validate_trade(side, entry, stop, qty):
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
        send_msg(f"❌ {e}")
        time.sleep(60)
