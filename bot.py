import time
import requests
import pandas as pd
from binance.client import Client
from datetime import datetime

# ===== CONFIG =====
API_KEY = "TU_API_KEY"
API_SECRET = "TU_SECRET"

TELEGRAM_TOKEN = "TU_TOKEN"
CHAT_ID = "TU_CHAT_ID"

# SOLO PARES SEGUROS (sin ONG/ONT)
SYMBOLS = ["ETHUSDT","SOLUSDT","XRPUSDT","ADAUSDT"]

RISK_PERCENT = 0.05   # 5% del balance
LEVERAGE = 5

client = Client(API_KEY, API_SECRET)

open_positions = {}

# ===== TELEGRAM =====
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ===== DATA =====
def get_klines(symbol):
    klines = client.futures_klines(symbol=symbol, interval="5m", limit=100)
    df = pd.DataFrame(klines)
    df = df.iloc[:, :6]
    df.columns = ["time","open","high","low","close","volume"]
    df = df.astype(float)
    return df

# ===== INDICADORES =====
def calculate_indicators(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    df["tr"] = df.apply(lambda x: max(
        x["high"] - x["low"],
        abs(x["high"] - x["close"]),
        abs(x["low"] - x["close"])
    ), axis=1)
    df["atr"] = df["tr"].rolling(14).mean()

    return df

# ===== PRECISION (FIX REAL) =====
def adjust_qty(symbol, qty):
    info = client.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    step = float(f["stepSize"])
                    qty = (qty // step) * step
                    return round(qty, 8)
    return qty

# ===== BALANCE =====
def get_balance():
    balance = client.futures_account_balance()
    for b in balance:
        if b["asset"] == "USDT":
            return float(b["balance"])
    return 0

# ===== SIZE (FIX MARGIN) =====
def calculate_qty(symbol, price):
    balance = get_balance()

    max_trade_usdt = balance * RISK_PERCENT
    notional = max_trade_usdt * LEVERAGE

    qty = notional / price
    qty = adjust_qty(symbol, qty)

    return qty

# ===== CHECK POSITION =====
def has_position(symbol):
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        if float(p["positionAmt"]) != 0:
            return True
    return False

# ===== OPEN TRADE =====
def open_trade(symbol, side, atr):
    if has_position(symbol):
        return

    try:
        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

        ticker = client.futures_symbol_ticker(symbol=symbol)
        price = float(ticker["price"])

        qty = calculate_qty(symbol, price)

        if qty <= 0:
            return

        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty
        )

        if side == "BUY":
            sl = price - atr
            tp = price + (1.5 * atr)
            exit_side = "SELL"
        else:
            sl = price + atr
            tp = price - (1.5 * atr)
            exit_side = "BUY"

        client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="STOP_MARKET",
            stopPrice=round(sl, 4),
            closePosition=True
        )

        client.futures_create_order(
            symbol=symbol,
            side=exit_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp, 4),
            closePosition=True
        )

        msg = f"🚀 {side} {symbol}\nEntry: {price:.4f}\nSL: {sl:.4f}\nTP: {tp:.4f}"
        print(msg)
        send_telegram(msg)

    except Exception as e:
        print(f"❌ ERROR {symbol}: {e}")
        send_telegram(f"❌ ERROR {symbol}: {e}")

# ===== SIGNAL =====
def check_signal(df):
    last = df.iloc[-1]

    if last["ema20"] > last["ema50"] and last["rsi"] > 55:
        return "BUY"

    if last["ema20"] < last["ema50"] and last["rsi"] < 45:
        return "SELL"

    return None

# ===== MAIN =====
print("🚀 BOT PRO V3 ACTIVO")

while True:
    try:
        for symbol in SYMBOLS:
            df = get_klines(symbol)
            df = calculate_indicators(df)

            signal = check_signal(df)
            atr = df["atr"].iloc[-1]

            if signal and not pd.isna(atr):
                open_trade(symbol, signal, atr)

        time.sleep(60)

    except Exception as e:
        print(f"⚠️ ERROR GENERAL: {e}")
        send_telegram(f"⚠️ ERROR GENERAL: {e}")
        time.sleep(60)
