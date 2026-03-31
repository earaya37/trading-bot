from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests
import math
import uuid

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = Client(API_KEY, API_SECRET, requests_params={"timeout": 10})

symbols = ["XRPUSDT","ADAUSDT","DOGEUSDT","SOLUSDT","MATICUSDT","TRXUSDT","LTCUSDT"]

interval = Client.KLINE_INTERVAL_15MINUTE
LEVERAGE = 5
cycle_count = 0

# 🔥 CONFIGURACIÓN NUEVA
RISK_PERCENT = 0.12       # 12% por trade
MIN_NOTIONAL = 15         # mínimo real
MAX_TRADES = 1            # evitar sobretrading

# 📩 TELEGRAM
def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# 💰 BALANCE
def get_balance():
    try:
        balance = client.futures_account_balance()
        for b in balance:
            if b["asset"] == "USDT":
                return float(b["balance"])
    except:
        return 0

# 🔍 PRECISION
exchange_info = client.futures_exchange_info()
symbol_info = {}

def get_decimals(step):
    step_str = "{:f}".format(step)
    return len(step_str.rstrip('0').split('.')[1]) if '.' in step_str else 0

for s in exchange_info["symbols"]:
    filters = {f["filterType"]: f for f in s["filters"]}
    step = float(filters["LOT_SIZE"]["stepSize"])
    tick = float(filters["PRICE_FILTER"]["tickSize"])

    symbol_info[s["symbol"]] = {
        "stepSize": step,
        "tickSize": tick,
        "qtyDecimals": get_decimals(step),
        "priceDecimals": get_decimals(tick)
    }

def format_qty(symbol, qty):
    step = symbol_info[symbol]["stepSize"]
    decimals = symbol_info[symbol]["qtyDecimals"]
    qty = math.floor(qty / step) * step
    return f"{qty:.{decimals}f}"

def format_price(symbol, price):
    tick = symbol_info[symbol]["tickSize"]
    decimals = symbol_info[symbol]["priceDecimals"]
    price = math.floor(price / tick) * tick
    return f"{price:.{decimals}f}"

# 🔒 POSICIONES
def get_position_amt(symbol):
    try:
        pos = client.futures_position_information(symbol=symbol)
        if not pos:
            return 0.0
        for p in pos:
            if p["symbol"] == symbol:
                return float(p["positionAmt"])
        return 0.0
    except:
        return 0.0

def has_position(symbol):
    return abs(get_position_amt(symbol)) > 0

def has_any_position():
    count = 0
    for s in symbols:
        if has_position(s):
            count += 1
    return count >= MAX_TRADES

# 📈 DATA
def get_data(symbol):
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=200)
        df = pd.DataFrame(klines, columns=[
            "time","open","high","low","close","volume",
            "close_time","qav","trades","tbbav","tbqav","ignore"
        ])
        df["close"] = df["close"].astype(float)
        df["low"] = df["low"].astype(float)
        df["high"] = df["high"].astype(float)
        return df
    except:
        return None

# 🧠 SEÑAL MEJORADA (CON CONFIRMACIÓN)
def get_signal(symbol):
    df = get_data(symbol)

    if df is None or len(df) < 50:
        return None, None, None, None

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    ema50 = last["ema50"]
    ema200 = last["ema200"]
    rsi = last["rsi"]
    prev_rsi = prev["rsi"]
    price = last["close"]

    print(f"{symbol} → RSI {round(rsi,1)}")

    # LONG con confirmación
    if ema50 > ema200 and 35 < rsi < 50 and rsi > prev_rsi:
        stop = df["low"].tail(5).min()
        if abs(price - stop)/price < 0.004:
            return None, None, None, None
        return "LONG", price, stop, rsi

    # SHORT con confirmación
    if ema50 < ema200 and 50 < rsi < 65 and rsi < prev_rsi:
        stop = df["high"].tail(5).max()
        if abs(price - stop)/price < 0.004:
            return None, None, None, None
        return "SHORT", price, stop, rsi

    return None, None, None, None

# 🚀 ORDEN SEGURA
def safe_order(symbol, side, qty):
    try:
        client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty,
            newClientOrderId=str(uuid.uuid4())
        )
        return True
    except Exception as e:
        if "-1007" in str(e):
            time.sleep(2)
            if has_position(symbol):
                return True
            return False
        print("Order error:", e)
        return False

# 🚀 TRADE
def open_trade():
    if has_any_position():
        print("🔒 trade activo")
        return

    balance = get_balance()
    if balance <= 0:
        return

    for symbol in symbols:

        side, entry, stop, rsi = get_signal(symbol)

        if side is None:
            continue

        # 🔥 NUEVO RIESGO
        risk_usdt = balance * RISK_PERCENT

        if risk_usdt < MIN_NOTIONAL:
            risk_usdt = MIN_NOTIONAL

        qty = format_qty(symbol, risk_usdt / entry)

        if float(qty) <= 0:
            continue

        try:
            client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)
        except:
            pass

        if side == "LONG":
            ok = safe_order(symbol, "BUY", qty)
            sl_side = "SELL"
            risk = entry - stop
            tp = entry + (risk * 2)
        else:
            ok = safe_order(symbol, "SELL", qty)
            sl_side = "BUY"
            risk = stop - entry
            tp = entry - (risk * 2)

        if not ok:
            continue

        stop = format_price(symbol, stop)
        tp = format_price(symbol, tp)

        try:
            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="STOP_MARKET",
                stopPrice=stop,
                closePosition=True
            )

            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp,
                closePosition=True
            )
        except Exception as e:
            print("SL/TP error:", e)

        msg = f"""🚀 TRADE {side}
Par: {symbol}

💰 Entry: {round(entry,4)}
🛑 SL: {stop}
🎯 TP: {tp}
📦 Qty: {qty}
💵 Notional: ~{round(float(qty)*entry,2)} USDT

📊 RSI: {round(rsi,2)}
"""
        print(msg)
        send_msg(msg)

        return

    print("⏳ Sin señal")

# 🔁 LOOP
while True:
    try:
        cycle_count += 1
        print(f"\n--- CICLO {cycle_count} ---")

        if cycle_count % 10 == 0:
            send_msg("🤖 Bot activo")

        open_trade()

        time.sleep(180)

    except Exception as e:
        print("Error loop:", e)
        send_msg(f"❌ {e}")
        time.sleep(60)
