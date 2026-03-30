from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests

# 🔐 KEYS
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = Client(API_KEY, API_SECRET)

symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
interval = Client.KLINE_INTERVAL_1HOUR

RISK_PER_TRADE = 0.01
LEVERAGE = 5

# 📩 TELEGRAM
def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# 💰 BALANCE
def get_balance():
    balance = client.futures_account_balance()
    for b in balance:
        if b["asset"] == "USDT":
            return float(b["balance"])

# 📊 POSICIÓN ABIERTA GLOBAL
def has_position():
    positions = client.futures_position_information()
    for p in positions:
        if float(p["positionAmt"]) != 0:
            return True
    return False

# 📈 DATA
def get_data(symbol):
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=200)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])
    df["close"] = df["close"].astype(float)
    df["low"] = df["low"].astype(float)
    return df

# 🔥 CÁLCULO PRO
def calculate_qty(balance, entry, stop):
    risk_usdt = balance * RISK_PER_TRADE
    distance = abs(entry - stop)

    if distance == 0:
        return None

    qty = (risk_usdt / distance) * LEVERAGE
    return round(qty, 3)

# 📊 SEÑAL
def get_signal(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    trend = last["ema50"] > last["ema200"]
    pullback = prev["close"] <= prev["ema50"]
    confirm = last["close"] > last["ema50"]

    if trend and pullback and confirm:
        entry = last["close"]
        stop = df["low"].tail(5).min()
        return entry, stop

    return None, None

# 🚀 TRADE
def open_trade():
    if has_position():
        print("Ya hay posición abierta")
        return

    for symbol in symbols:
        entry, stop = get_signal(symbol)

        if entry is None:
            print(f"{symbol} → sin señal")
            continue

        balance = get_balance()
        qty = calculate_qty(balance, entry, stop)

        if qty is None or qty <= 0:
            continue

        print(f"ENTRANDO EN {symbol} | Qty: {qty}")

        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

        # 🟢 COMPRA
        client.futures_create_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=qty
        )

        # 🔴 STOP LOSS
        client.futures_create_order(
            symbol=symbol,
            side="SELL",
            type="STOP_MARKET",
            stopPrice=round(stop, 2),
            closePosition=True
        )

        # 🎯 TAKE PROFIT
        tp = entry + (entry - stop) * 2

        client.futures_create_order(
            symbol=symbol,
            side="SELL",
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp, 2),
            closePosition=True
        )

        msg = f"""🟢 TRADE ABIERTO
Par: {symbol}
Entry: {entry}
SL: {stop}
TP: {round(tp,2)}
Qty: {qty}
"""

        print(msg)
        send_msg(msg)

        return  # 🔥 SOLO 1 TRADE

    send_msg("⏳ Sin señal en ningún par")

# 🔁 LOOP
while True:
    try:
        open_trade()
        time.sleep(300)
    except Exception as e:
        print("Error:", e)
        send_msg(f"❌ Error: {e}")
        time.sleep(60)
