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

# 🔍 PRECISIÓN
exchange_info = client.futures_exchange_info()
symbol_info = {}

for s in exchange_info["symbols"]:
    filters = {f["filterType"]: f for f in s["filters"]}
    symbol_info[s["symbol"]] = {
        "stepSize": float(filters["LOT_SIZE"]["stepSize"]),
        "tickSize": float(filters["PRICE_FILTER"]["tickSize"]),
    }

def adjust_qty(symbol, qty):
    step = symbol_info[symbol]["stepSize"]
    return math.floor(qty / step) * step

def adjust_price(symbol, price):
    tick = symbol_info[symbol]["tickSize"]
    return round(math.floor(price / tick) * tick, 6)

# 🔒 POSICIONES SEGURAS
def get_position_amt(symbol):
    try:
        pos = client.futures_position_information(symbol=symbol)

        if not pos:
            return 0.0

        for p in pos:
            if p["symbol"] == symbol:
                return float(p["positionAmt"])

        return 0.0

    except Exception as e:
        print("Error getting position:", e)
        return 0.0

def has_position(symbol):
    return abs(get_position_amt(symbol)) > 0

def has_any_position():
    try:
        for s in symbols:
            if has_position(s):
                return True
        return False
    except:
        return False

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
    except Exception as e:
        print(f"Error data {symbol}:", e)
        return None

# 🧠 SEÑAL MEJORADA
def get_signal(symbol):
    df = get_data(symbol)

    if df is None or len(df) < 50:
        return None, None, None, None

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]

    ema50 = last["ema50"]
    ema200 = last["ema200"]
    rsi = last["rsi"]
    price = last["close"]

    print(f"{symbol} → RSI {round(rsi,1)}")

    # LONG
    if ema50 > ema200 and 35 < rsi < 50:
        stop = df["low"].tail(5).min()
        return "LONG", price, stop, rsi

    # SHORT
    if ema50 < ema200 and 50 < rsi < 65:
        stop = df["high"].tail(5).max()
        return "SHORT", price, stop, rsi

    return None, None, None, None

# 🚀 ORDEN SEGURA (ANTI TIMEOUT)
def safe_order(symbol, side, qty):
    client_id = str(uuid.uuid4())

    try:
        client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty,
            newClientOrderId=client_id
        )
        return True

    except Exception as e:
        if "-1007" in str(e):
            print("⚠️ Timeout - verificando orden...")

            time.sleep(2)

            if has_position(symbol):
                print("✅ Orden ejecutada")
                return True

            print("❌ Orden NO ejecutada")
            return False

        print("Error orden:", e)
        return False

# 🚀 TRADE
def open_trade():
    if has_any_position():
        print("🔒 trade activo")
        return

    balance = get_balance()

    if balance <= 0:
        print("⚠️ Sin balance")
        return

    for symbol in symbols:

        side, entry, stop, rsi = get_signal(symbol)

        if side is None:
            continue

        risk_usdt = balance * 0.05
        qty = adjust_qty(symbol, risk_usdt / entry)

        if qty <= 0:
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

        stop = adjust_price(symbol, stop)
        tp = adjust_price(symbol, tp)

        try:
            # STOP LOSS
            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="STOP_MARKET",
                stopPrice=stop,
                closePosition=True
            )

            # TAKE PROFIT
            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp,
                closePosition=True
            )

        except Exception as e:
            print("Error SL/TP:", e)

        msg = f"""🚀 TRADE {side}
Par: {symbol}

💰 Entry: {round(entry,4)}
🛑 SL: {round(stop,4)}
🎯 TP: {round(tp,4)}
📦 Qty: {qty}

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
