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

# 🔥 PARES OPTIMIZADOS PARA POCO CAPITAL
symbols = ["XRPUSDT", "ADAUSDT", "DOGEUSDT", "SOLUSDT"]

interval = Client.KLINE_INTERVAL_15MINUTE

RISK_PER_TRADE = 0.01
LEVERAGE = 5

cycle_count = 0

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("Telegram error:", e)

def get_balance():
    balance = client.futures_account_balance()
    for b in balance:
        if b["asset"] == "USDT":
            return float(b["balance"])

# 🔍 PRECISIÓN BINANCE
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
    return math.floor(price / tick) * tick

def has_position(symbol):
    pos = client.futures_position_information(symbol=symbol)
    return pos and float(pos[0]["positionAmt"]) != 0

def has_any_position():
    for s in symbols:
        if has_position(s):
            return True
    return False

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

# 🧠 ESTRATEGIA SIMPLE (YA FUNCIONA)
def get_signal(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]

    ema50 = last["ema50"]
    ema200 = last["ema200"]
    rsi = last["rsi"]

    print(f"{symbol} → RSI {round(rsi,1)}")

    if ema50 > ema200 and rsi < 60:
        return "LONG", last["close"], df["low"].tail(5).min()

    if ema50 < ema200 and rsi > 40:
        return "SHORT", last["close"], df["high"].tail(5).max()

    return None, None, None

# 🚀 EJECUCIÓN
def open_trade():
    if has_any_position():
        print("🔒 Ya hay trade activo")
        return

    for symbol in symbols:

        side, entry, stop = get_signal(symbol)

        if side is None:
            continue

        balance = get_balance()

        # 🔥 FORZAR MÍNIMO BINANCE
        qty = 21 / entry

        # 🔧 ajuste precisión
        qty = adjust_qty(symbol, qty)

        if qty <= 0:
            continue

        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

        try:
            if side == "LONG":
                client.futures_create_order(symbol=symbol, side="BUY", type="MARKET", quantity=qty)
                sl_side = "SELL"
            else:
                client.futures_create_order(symbol=symbol, side="SELL", type="MARKET", quantity=qty)
                sl_side = "BUY"

            stop = adjust_price(symbol, stop)

            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="STOP_MARKET",
                stopPrice=stop,
                closePosition=True
            )

            msg = f"🚀 {side} {symbol}\nQty: {qty}"
            print(msg)
            send_msg(msg)

            return

        except Exception as e:
            print("Error trade:", e)

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
        print("Error:", e)
        send_msg(f"❌ {e}")
        time.sleep(60)
