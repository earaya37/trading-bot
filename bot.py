from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests
import math
from datetime import datetime

# ================== CONFIG ==================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = Client(API_KEY, API_SECRET)

symbols = ["XRPUSDT","ADAUSDT","DOGEUSDT","SOLUSDT","MATICUSDT"]  # 🔥 TRX fuera por estabilidad

interval = Client.KLINE_INTERVAL_15MINUTE

LEVERAGE = 5
RISK_PERCENT = 0.03
MAX_TRADES = 3
COOLDOWN_MINUTES = 15

MIN_SL_PERCENT = 0.004   # 🔥 aumentado para evitar errores
MAX_NOTIONAL_PER_TRADE = 120

# ================== CONTROL ==================
last_trade_time = {}
last_positions = {}
trade_data = {}

daily_profit = 0
wins = 0
losses = 0

# ================== TELEGRAM ==================
def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# ================== BALANCE ==================
def get_balance():
    try:
        balance = client.futures_account_balance()
        for b in balance:
            if b["asset"] == "USDT":
                return float(b["balance"])
    except:
        return 0

# ================== POSICIONES ==================
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

# ================== PRECISIÓN ==================
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

# ================== DATA ==================
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

# ================== SEÑAL ==================
def get_signal(symbol):
    df = get_data(symbol)
    if df is None or len(df) < 200:
        return None, None, None, None

    df["ema50"] = ta.trend.ema_indicator(df["close"], 50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], 200)
    df["rsi"] = ta.momentum.rsi(df["close"], 14)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = last["close"]
    rsi = last["rsi"]

    if last["ema50"] > last["ema200"] and 40 < rsi < 55 and rsi > prev["rsi"]:
        stop = df["low"].tail(5).min()
        if abs(price - stop)/price < MIN_SL_PERCENT:
            return None,None,None,None
        return "LONG", price, stop, rsi

    if last["ema50"] < last["ema200"] and 45 < rsi < 60 and rsi < prev["rsi"]:
        stop = df["high"].tail(5).max()
        if abs(price - stop)/price < MIN_SL_PERCENT:
            return None,None,None,None
        return "SHORT", price, stop, rsi

    return None,None,None,None

# ================== MARGIN ==================
def set_margin(symbol):
    try:
        client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
    except:
        pass
    try:
        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)
    except:
        pass

# ================== SLTP ==================
def place_sl_tp(symbol, sl_side, stop, tp):
    try:
        client.futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="STOP_MARKET",
            stopPrice=stop,
            closePosition=True,
            workingType="MARK_PRICE"
        )
        client.futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp,
            closePosition=True,
            workingType="MARK_PRICE"
        )
        return True
    except Exception as e:
        print("SLTP error:", e)
        return False

def verify_sl_tp(symbol):
    try:
        orders = client.futures_get_open_orders(symbol=symbol)
        return any(o["type"]=="STOP_MARKET" for o in orders) and any(o["type"]=="TAKE_PROFIT_MARKET" for o in orders)
    except:
        return False

# ================== GESTIÓN ==================
def manage_positions():
    global daily_profit,wins,losses

    for symbol in symbols:
        amt = get_position_amt(symbol)

        if symbol in last_positions and last_positions[symbol]!=0 and amt==0:
            if symbol in trade_data:
                data = trade_data[symbol]
                price = float(client.futures_mark_price(symbol=symbol)["markPrice"])

                profit = (price-data["entry"])*data["qty"] if data["side"]=="LONG" else (data["entry"]-price)*data["qty"]
                profit = round(profit,2)

                daily_profit += profit
                wins += profit>0
                losses += profit<=0

                send_msg(f"📊 TRADE CERRADO {symbol}\n💰 {profit} USDT")

                del trade_data[symbol]

        last_positions[symbol]=amt

# ================== TRADE ==================
def open_trade():
    if get_open_positions_count()>=MAX_TRADES:
        return

    balance = get_balance()

    for symbol in symbols:

        if abs(get_position_amt(symbol))>0:
            continue

        if symbol in last_trade_time:
            if (datetime.now()-last_trade_time[symbol]).seconds/60 < COOLDOWN_MINUTES:
                continue

        side,entry,stop,rsi = get_signal(symbol)
        if side is None:
            continue

        set_margin(symbol)

        risk = balance*RISK_PERCENT
        risk_unit = abs(entry-stop)
        qty = risk/risk_unit

        if qty*entry > MAX_NOTIONAL_PER_TRADE:
            qty = MAX_NOTIONAL_PER_TRADE/entry

        qty = format_qty(symbol,qty)
        if qty<=0:
            continue

        order_side = "BUY" if side=="LONG" else "SELL"
        sl_side = "SELL" if side=="LONG" else "BUY"

        client.futures_create_order(symbol=symbol,side=order_side,type="MARKET",quantity=qty)

        stop = format_price(symbol,stop)
        tp = format_price(symbol, entry + (entry-stop)*2 if side=="LONG" else entry-(stop-entry)*2)

        time.sleep(2)  # 🔥 importante

        place_sl_tp(symbol,sl_side,stop,tp)

        if not verify_sl_tp(symbol):
            time.sleep(1)
            place_sl_tp(symbol,sl_side,stop,tp)

        if not verify_sl_tp(symbol):
            send_msg(f"❌ SL/TP FALLÓ {symbol}")
            client.futures_create_order(symbol=symbol,side=sl_side,type="MARKET",quantity=qty)
            return

        trade_data[symbol]={"entry":entry,"qty":qty,"side":side}
        last_trade_time[symbol]=datetime.now()

        send_msg(f"🚀 {side} {symbol}\nEntry:{entry}\nSL:{stop}\nTP:{tp}")

        return

# ================== LOOP ==================
while True:
    try:
        manage_positions()
        open_trade()
        time.sleep(120)
    except Exception as e:
        print(e)
        send_msg(f"❌ {e}")
        time.sleep(60)
