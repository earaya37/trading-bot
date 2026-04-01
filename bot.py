from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests
import math

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = Client(API_KEY, API_SECRET)

symbol = "XRPUSDT"
interval = Client.KLINE_INTERVAL_15MINUTE

RISK_USDT = 1
MIN_SL_PERCENT = 0.003
MIN_NOTIONAL = 5

last_error = None

def send_msg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

def safe(x):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return float(x)
    except:
        return None

def get_data():
    try:
        k = client.futures_klines(symbol=symbol, interval=interval, limit=200)
        df = pd.DataFrame(k, columns=["t","o","h","l","c","v","ct","q","n","tb","tq","i"])
        df["c"] = pd.to_numeric(df["c"], errors='coerce')
        df["l"] = pd.to_numeric(df["l"], errors='coerce')
        df["h"] = pd.to_numeric(df["h"], errors='coerce')
        df = df.dropna()
        return df if len(df) >= 200 else None
    except:
        return None

def get_signal():
    df = get_data()
    if df is None:
        return None,None,None

    df["ema50"] = ta.trend.ema_indicator(df["c"],50)
    df["ema200"] = ta.trend.ema_indicator(df["c"],200)
    df["rsi"] = ta.momentum.rsi(df["c"],14)

    df = df.dropna()

    last = df.iloc[-1]

    price = safe(last["c"])
    rsi = safe(last["rsi"])
    ema50 = safe(last["ema50"])
    ema200 = safe(last["ema200"])

    if None in (price, rsi, ema50, ema200):
        return None,None,None

    # LONG (más flexible)
    if ema50 > ema200 * 0.998 and 30 < rsi < 65:
        stop = safe(df["l"].tail(5).min())
        if stop and abs(price-stop)/price > MIN_SL_PERCENT:
            return "LONG", price, stop

    # SHORT (más flexible)
    if ema50 < ema200 * 1.002 and 35 < rsi < 70:
        stop = safe(df["h"].tail(5).max())
        if stop and abs(price-stop)/price > MIN_SL_PERCENT:
            return "SHORT", price, stop

    return None,None,None

def get_position():
    try:
        for p in client.futures_position_information(symbol=symbol):
            return float(p["positionAmt"])
    except:
        return 0.0

def open_trade():
    try:
        side, entry, stop = get_signal()
        if side is None:
            return

        entry, stop = safe(entry), safe(stop)
        if entry is None or stop is None:
            return

        risk = abs(entry - stop)
        if risk == 0:
            return

        qty = RISK_USDT / risk

        if qty * entry < MIN_NOTIONAL:
            return

        if abs(get_position()) > 0:
            return

        order_side = "BUY" if side=="LONG" else "SELL"

        client.futures_create_order(
            symbol=symbol,
            side=order_side,
            type="MARKET",
            quantity=qty
        )

        send_msg(f"🚀 {side} XRP")

    except Exception as e:
        global last_error
        err = str(e)
        if err != last_error:
            send_msg(f"❌ {err}")
            last_error = err

while True:
    open_trade()
    time.sleep(120)
