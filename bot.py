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

# 🔥 CONFIG HEDGE
RISK_PERCENT = 0.10
MIN_NOTIONAL = 15
MAX_TRADES = 3

last_positions = {}
trade_data = {}

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

def get_open_positions_count():
    count = 0
    for s in symbols:
        if abs(get_position_amt(s)) > 0:
            count += 1
    return count

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

# 🧠 SEÑAL
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

    if ema50 > ema200 and 35 < rsi < 50 and rsi > prev_rsi:
        stop = df["low"].tail(5).min()
        if abs(price - stop)/price < 0.004:
            return None, None, None, None
        return "LONG", price, stop, rsi

    if ema50 < ema200 and 50 < rsi < 65 and rsi < prev_rsi:
        stop = df["high"].tail(5).max()
        if abs(price - stop)/price < 0.004:
            return None, None, None, None
        return "SHORT", price, stop, rsi

    return None, None, None, None

# 🚀 ORDEN
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
    except:
        return False

# 🔔 TRACKING + TRAILING + BREAKEVEN
def manage_positions():
    global last_positions, trade_data

    for symbol in symbols:
        amt = get_position_amt(symbol)

        if symbol in trade_data and amt != 0:
            entry = trade_data[symbol]["entry"]
            side = trade_data[symbol]["side"]

            price = float(get_data(symbol)["close"].iloc[-1])

            # 🔥 break even
            if not trade_data[symbol].get("be"):

                if (side == "LONG" and price > entry * 1.01) or \
                   (side == "SHORT" and price < entry * 0.99):

                    trade_data[symbol]["be"] = True

                    client.futures_create_order(
                        symbol=symbol,
                        side="SELL" if side=="LONG" else "BUY",
                        type="STOP_MARKET",
                        stopPrice=format_price(symbol, entry),
                        closePosition=True
                    )

                    send_msg(f"🔒 Break-even activado en {symbol}")

        # 🔥 detectar cierre
        if symbol in last_positions:
            if last_positions[symbol] != 0 and amt == 0:

                if symbol in trade_data:
                    data = trade_data[symbol]

                    price = float(get_data(symbol)["close"].iloc[-1])

                    if data["side"] == "LONG":
                        profit = price - data["entry"]
                    else:
                        profit = data["entry"] - price

                    profit_usdt = round(profit * data["qty"], 2)

                    send_msg(f"📊 Trade cerrado {symbol} → {profit_usdt} USDT")

                    del trade_data[symbol]

        last_positions[symbol] = amt

# 🚀 TRADE
def open_trade():
    if get_open_positions_count() >= MAX_TRADES:
        return

    balance = get_balance()

    for symbol in symbols:

        if get_open_positions_count() >= MAX_TRADES:
            return

        if abs(get_position_amt(symbol)) > 0:
            continue

        side, entry, stop, rsi = get_signal(symbol)

        if side is None:
            continue

        risk_usdt = max(balance * RISK_PERCENT, MIN_NOTIONAL)

        qty = format_qty(symbol, risk_usdt / entry)

        if float(qty) <= 0:
            continue

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

        trade_data[symbol] = {
            "entry": entry,
            "qty": float(qty),
            "side": side
        }

        send_msg(f"🚀 {side} {symbol} | Qty: {qty}")

# 🔁 LOOP
while True:
    try:
        cycle_count += 1
        print(f"Ciclo {cycle_count}")

        manage_positions()
        open_trade()

        time.sleep(120)

    except Exception as e:
        print(e)
        send_msg(f"❌ {e}")
        time.sleep(60)
