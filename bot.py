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

symbols = ["BTCUSDT", "ETHUSDT", "BCHUSDT"]
interval = Client.KLINE_INTERVAL_15MINUTE

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

# 📊 POSICIÓN ABIERTA
def has_position():
    positions = client.futures_position_information()
    return any(float(p["positionAmt"]) != 0 for p in positions)

# 📈 DATA
def get_data(symbol):
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=200)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])
    df["close"] = df["close"].astype(float)
    df["low"] = df["low"].astype(float)
    df["high"] = df["high"].astype(float)
    return df

# 🔥 CÁLCULO FINAL CORREGIDO
def calculate_qty(balance, entry, stop):
    risk = balance * RISK_PER_TRADE
    distance = abs(entry - stop)

    if distance == 0:
        return None

    qty = (risk / distance) * LEVERAGE

    # 🔥 límite máximo (20% capital)
    max_position_usdt = balance * 0.2
    max_qty = max_position_usdt / entry
    qty = min(qty, max_qty)

    # 🔥 mínimo Binance ($20)
    min_notional = 20
    min_qty = min_notional / entry

    if qty < min_qty:
        qty = min_qty

    return round(qty, 3)

# 📊 SEÑAL (EMA + RSI)
def get_signal(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]

    # 🟢 LONG
    if last["ema50"] > last["ema200"] and last["rsi"] < 40:
        entry = last["close"]
        stop = df["low"].tail(5).min()
        return "LONG", entry, stop

    # 🔴 SHORT
    if last["ema50"] < last["ema200"] and last["rsi"] > 60:
        entry = last["close"]
        stop = df["high"].tail(5).max()
        return "SHORT", entry, stop

    return None, None, None

# 🚀 EJECUCIÓN
def open_trade():
    if has_position():
        return

    for symbol in symbols:
        side, entry, stop = get_signal(symbol)

        if side is None:
            continue

        balance = get_balance()
        qty = calculate_qty(balance, entry, stop)

        if qty is None or qty <= 0:
            continue

        print(f"Trade en {symbol} | Qty: {qty}")

        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

        if side == "LONG":
            client.futures_create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=qty
            )
            sl_side = "SELL"
            tp_side = "SELL"
            tp = entry + (entry - stop) * 2

        else:
            client.futures_create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=qty
            )
            sl_side = "BUY"
            tp_side = "BUY"
            tp = entry - (stop - entry) * 2

        # STOP LOSS
        client.futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="STOP_MARKET",
            stopPrice=round(stop, 2),
            closePosition=True
        )

        # TAKE PROFIT
        client.futures_create_order(
            symbol=symbol,
            side=tp_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp, 2),
            closePosition=True
        )

        msg = f"""🚀 TRADE {side}
Par: {symbol}
Entry: {entry}
SL: {stop}
TP: {round(tp,2)}
Qty: {qty}
"""

        print(msg)
        send_msg(msg)

        return

    send_msg("⏳ Sin señal")

# 🔁 LOOP
while True:
    try:
        open_trade()
        time.sleep(180)
    except Exception as e:
        print("Error:", e)
        send_msg(f"❌ Error: {e}")
        time.sleep(60)
