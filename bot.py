from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests
import math
import uuid
from datetime import datetime

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = Client(API_KEY, API_SECRET, requests_params={"timeout": 10})

symbols = ["XRPUSDT","ADAUSDT","DOGEUSDT","SOLUSDT","MATICUSDT","TRXUSDT","LTCUSDT"]

interval = Client.KLINE_INTERVAL_15MINUTE
LEVERAGE = 5

RISK_PERCENT = 0.10
MIN_NOTIONAL = 15
MAX_TRADES = 3
MAX_NOTIONAL_PER_TRADE = 120  # 🔥 límite para no sobreapalancarte

last_positions = {}
trade_data = {}

daily_profit = 0
wins = 0
losses = 0

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

def get_balance():
    try:
        balance = client.futures_account_balance()
        for b in balance:
            if b["asset"] == "USDT":
                return float(b["balance"])
    except:
        return 0

# 🔥 CONFIGURAR ISOLATED + LEVERAGE
def set_margin(symbol):
    try:
        client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
    except:
        pass
    try:
        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)
    except:
        pass

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
    return float(f"{qty:.{decimals}f}")

def format_price(symbol, price):
    tick = symbol_info[symbol]["tickSize"]
    decimals = symbol_info[symbol]["priceDecimals"]
    price = math.floor(price / tick) * tick
    return float(f"{price:.{decimals}f}")

def get_position_amt(symbol):
    try:
        pos = client.futures_position_information(symbol=symbol)
        for p in pos:
            if p["symbol"] == symbol:
                return float(p["positionAmt"])
        return 0.0
    except:
        return 0.0

def get_open_positions_count():
    return sum(1 for s in symbols if abs(get_position_amt(s)) > 0)

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
        return "LONG", price, stop, rsi

    if ema50 < ema200 and 50 < rsi < 65 and rsi < prev_rsi:
        stop = df["high"].tail(5).max()
        return "SHORT", price, stop, rsi

    return None, None, None, None

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

        set_margin(symbol)  # 🔥 CLAVE

        risk_usdt = balance * RISK_PERCENT
        risk_per_unit = abs(entry - stop)

        if risk_per_unit == 0:
            continue

        qty = risk_usdt / risk_per_unit

        notional = qty * entry

        # 🔥 limitar tamaño máximo
        if notional > MAX_NOTIONAL_PER_TRADE:
            qty = MAX_NOTIONAL_PER_TRADE / entry

        qty = format_qty(symbol, qty)

        if qty <= 0:
            continue

        if side == "LONG":
            ok = safe_order(symbol, "BUY", qty)
            sl_side = "SELL"
            tp = entry + (abs(entry - stop) * 2)
        else:
            ok = safe_order(symbol, "SELL", qty)
            sl_side = "BUY"
            tp = entry - (abs(entry - stop) * 2)

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

        send_msg(f"""🚀 TRADE {side}
Par: {symbol}

💰 Entry: {round(entry,4)}
🛑 SL: {stop}
🎯 TP: {tp}
📦 Qty: {qty}
💵 Notional: {round(qty*entry,2)}

📊 RSI: {round(rsi,2)}
""")

        return

while True:
    try:
        open_trade()
        time.sleep(120)
    except Exception as e:
        print(e)
        send_msg(f"❌ {e}")
        time.sleep(60)
