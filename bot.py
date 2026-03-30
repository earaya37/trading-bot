from binance.client import Client
import pandas as pd
import ta
import time
import os

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

client = Client(API_KEY, API_SECRET)

symbol = "BTCUSDT"
interval = Client.KLINE_INTERVAL_1HOUR

RISK_PER_TRADE = 0.01
LEVERAGE = 5

# Obtener balance real
def get_balance():
    balance = client.futures_account_balance()
    for b in balance:
        if b["asset"] == "USDT":
            return float(b["balance"])

# Ver si hay posición
def has_position():
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        if float(p["positionAmt"]) != 0:
            return True
    return False

# Obtener datos
def get_data():
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=200)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])
    df["close"] = df["close"].astype(float)
    df["low"] = df["low"].astype(float)
    return df

# 🔥 CÁLCULO PRO REAL
def calculate_qty(balance, entry, stop):
    risk_usdt = balance * RISK_PER_TRADE
    distance = abs(entry - stop)

    if distance == 0:
        return None

    # tamaño en BTC basado en riesgo real
    qty = risk_usdt / distance

    # ajuste por leverage (Binance usa margen, no qty directa)
    qty = qty * LEVERAGE

    # redondeo seguro
    return round(qty, 3)

# Señal
def get_signal():
    df = get_data()

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

# Ejecutar trade
def open_trade():
    if has_position():
        print("Ya hay posición abierta")
        return

    entry, stop = get_signal()

    if entry is None:
        print("Sin señal")
        return

    balance = get_balance()
    qty = calculate_qty(balance, entry, stop)

    if qty is None or qty <= 0:
        print("Cantidad inválida")
        return

    print(f"Balance: {balance} | Qty: {qty}")

    client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

    # BUY
    client.futures_create_order(
        symbol=symbol,
        side="BUY",
        type="MARKET",
        quantity=qty
    )

    # STOP LOSS
    client.futures_create_order(
        symbol=symbol,
        side="SELL",
        type="STOP_MARKET",
        stopPrice=round(stop, 2),
        closePosition=True
    )

    # TAKE PROFIT
    tp = entry + (entry - stop) * 2

    client.futures_create_order(
        symbol=symbol,
        side="SELL",
        type="TAKE_PROFIT_MARKET",
        stopPrice=round(tp, 2),
        closePosition=True
    )

    print(f"Trade abierto → Entry: {entry} | SL: {stop} | TP: {tp}")

# Loop
while True:
    try:
        open_trade()
        time.sleep(300)
    except Exception as e:
        print("Error:", e)
        time.sleep(60)
