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

symbols = ["XRPUSDT","ADAUSDT"]

interval = Client.KLINE_INTERVAL_15MINUTE

LEVERAGE = 5
RISK_USDT = 1
MAX_TRADES = 1
COOLDOWN_MINUTES = 15
BLOCK_TIME = 10

MIN_SL_PERCENT = 0.004
MAX_DAILY_LOSS = 3

last_trade_time = {}
blocked_symbols = {}
daily_loss = 0
current_day = datetime.now().day

# ================= TELEGRAM =================
def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# ================= BALANCE =================
def get_balance():
    for b in client.futures_account_balance():
        if b["asset"] == "USDT":
            return float(b["balance"])
    return 0

# ================= POSICIÓN =================
def get_position_amt(symbol):
    for p in client.futures_position_information(symbol=symbol):
        if p["symbol"] == symbol:
            return float(p["positionAmt"])
    return 0.0

def get_open_positions_count():
    return sum(1 for s in symbols if abs(get_position_amt(s)) > 0)

# ================= FORMAT =================
exchange_info = client.futures_exchange_info()
symbol_info = {}

def get_decimals(step):
    s = "{:f}".format(step)
    return len(s.rstrip('0').split('.')[1]) if '.' in s else 0

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
    d = symbol_info[symbol]["qtyDecimals"]
    qty = math.floor(qty / step) * step
    return float(f"{qty:.{d}f}")

def format_price(symbol, price):
    tick = symbol_info[symbol]["tickSize"]
    d = symbol_info[symbol]["priceDecimals"]
    price = math.floor(price / tick) * tick
    return float(f"{price:.{d}f}")

# ================= DATA =================
def get_data(symbol):
    k = client.futures_klines(symbol=symbol, interval=interval, limit=200)
    df = pd.DataFrame(k, columns=["t","o","h","l","c","v","ct","q","n","tb","tq","i"])
    df["c"] = df["c"].astype(float)
    df["l"] = df["l"].astype(float)
    df["h"] = df["h"].astype(float)
    return df

# ================= SEÑAL =================
def get_signal(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["c"],50)
    df["ema200"] = ta.trend.ema_indicator(df["c"],200)
    df["rsi"] = ta.momentum.rsi(df["c"],14)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = last["c"]

    if last["ema50"] > last["ema200"] and 40 < last["rsi"] < 55 and last["rsi"] > prev["rsi"]:
        stop = df["l"].tail(5).min()
        if abs(price-stop)/price < MIN_SL_PERCENT:
            return None,None,None
        return "LONG",price,stop

    if last["ema50"] < last["ema200"] and 45 < last["rsi"] < 60 and last["rsi"] < prev["rsi"]:
        stop = df["h"].tail(5).max()
        if abs(price-stop)/price < MIN_SL_PERCENT:
            return None,None,None
        return "SHORT",price,stop

    return None,None,None

# ================= SLTP =================
def place_sl_tp(symbol, side, qty, stop, tp):
    try:
        client.futures_create_order(
            symbol=symbol,
            side=side,
            type="STOP_MARKET",
            stopPrice=stop,
            quantity=qty,
            reduceOnly=True
        )

        time.sleep(1)

        orders = client.futures_get_open_orders(symbol=symbol)
        if len(orders) == 0:
            return False

        client.futures_create_order(
            symbol=symbol,
            side=side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp,
            quantity=qty,
            reduceOnly=True
        )

        return True
    except Exception as e:
        print("SLTP ERROR:", e)
        return False

# ================= TRADE =================
def open_trade():
    global daily_loss, current_day

    if datetime.now().day != current_day:
        daily_loss = 0
        current_day = datetime.now().day

    if daily_loss >= MAX_DAILY_LOSS:
        send_msg("🛑 STOP DIARIO ACTIVADO")
        return

    if get_open_positions_count() >= MAX_TRADES:
        return

    for symbol in symbols:

        if symbol in blocked_symbols and datetime.now() < blocked_symbols[symbol]:
            continue

        if abs(get_position_amt(symbol)) > 0:
            continue

        if symbol in last_trade_time:
            if (datetime.now() - last_trade_time[symbol]).seconds/60 < COOLDOWN_MINUTES:
                continue

        side,entry,stop = get_signal(symbol)
        if side is None:
            continue

        risk = abs(entry - stop)
        qty = RISK_USDT / risk

        qty = format_qty(symbol, qty)
        if qty <= 0:
            continue

        order_side = "BUY" if side=="LONG" else "SELL"
        sl_side = "SELL" if side=="LONG" else "BUY"

        client.futures_create_order(symbol=symbol, side=order_side, type="MARKET", quantity=qty)

        # confirmar posición
        confirmed = False
        for _ in range(5):
            if abs(get_position_amt(symbol)) > 0:
                confirmed = True
                break
            time.sleep(1)

        if not confirmed:
            blocked_symbols[symbol] = datetime.now() + timedelta(minutes=BLOCK_TIME)
            continue

        stop = format_price(symbol, stop)
        tp = format_price(symbol, entry + (entry-stop)*2 if side=="LONG" else entry-(stop-entry)*2)

        if not place_sl_tp(symbol, sl_side, qty, stop, tp):
            send_msg(f"❌ SL FALLÓ {symbol}")
            client.futures_create_order(symbol=symbol, side=sl_side, type="MARKET", quantity=qty)
            blocked_symbols[symbol] = datetime.now() + timedelta(minutes=BLOCK_TIME)
            daily_loss += 1
            return

        last_trade_time[symbol] = datetime.now()
        send_msg(f"🚀 {side} {symbol} | riesgo $1")

        return

# ================= LOOP =================
while True:
    try:
        open_trade()
        time.sleep(120)
    except Exception as e:
        print(e)
        send_msg(f"❌ {e}")
        time.sleep(60)
