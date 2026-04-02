import time
import requests
import pandas as pd
from binance.client import Client
from datetime import datetime
import math

# ===== CONFIG =====
API_KEY = "4j8dMbSNzJUdYecnZhsPAyqV5TYdZycvmd9RSNPBuUdzMyC8LkhD4n3Zg3enEHxD".strip()
API_SECRET = "9DSGmVB5kvIYDvngB9X16BO62ASQwozngCTroDP2eEBA6ie7IVn8354kItF7wEEJ".strip()

TELEGRAM_TOKEN = "8541274469:AAE4b38i0W6OuirqKUi6x9TOES-zxILTwfU"
CHAT_ID = "392160869"

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT"]

RISK_PER_TRADE = 3  # 🔥 subido a $3 (mínimo viable)
LEVERAGE = 5

client = Client(API_KEY, API_SECRET)

daily_pnl = 0
last_day = datetime.now().day


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

    df["rsi"] = 100 - (100 / (1 + df["close"].pct_change().rolling(14).mean()))

    df["atr"] = (df["high"] - df["low"]).rolling(14).mean()

    return df


# ===== BALANCE =====
def get_balance():
    balance = client.futures_account_balance()
    for b in balance:
        if b["asset"] == "USDT":
            return float(b["balance"])
    return 0


# ===== SIZE =====
def calculate_qty(price, atr):
    sl_distance = atr
    qty = RISK_PER_TRADE / sl_distance
    return qty


# ===== TRADE =====
def open_trade(symbol, side, price, atr):
    global daily_pnl

    balance = get_balance()
    qty = calculate_qty(price, atr)

    notional = qty * price

    # 🔴 filtro mínimo Binance
    if notional < 20:
        print(f"⛔ {symbol} omitido: menor a $20")
        return

    # 🔴 filtro margen
    required_margin = notional / LEVERAGE
    if required_margin > balance:
        print(f"⛔ {symbol} sin margen")
        return

    qty = round(qty, 3)

    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty
        )

        sl = price - atr if side == "BUY" else price + atr
        tp = price + (2 * atr) if side == "BUY" else price - (2 * atr)

        msg = f"🚀 {side} {symbol}\nQty: {qty}\nSL: {sl:.4f}\nTP: {tp:.4f}"
        print(msg)
        send_telegram(msg)

    except Exception as e:
        print(f"❌ ERROR {symbol}: {e}")
        send_telegram(f"❌ ERROR {symbol}: {e}")


# ===== SIGNAL =====
def check_signal(df):
    last = df.iloc[-1]

    if last["ema20"] > last["ema50"] and last["rsi"] < 70:
        return "BUY"
    elif last["ema20"] < last["ema50"] and last["rsi"] > 30:
        return "SELL"
    return None


# ===== DAILY REPORT =====
def check_daily_report():
    global daily_pnl, last_day

    today = datetime.now().day

    if today != last_day:
        msg = f"📊 PnL Diario: {round(daily_pnl,2)} USDT"
        send_telegram(msg)
        daily_pnl = 0
        last_day = today


# ===== MAIN LOOP =====
print("🚀 BOT PRO ACTIVO (CON TELEGRAM)")

while True:
    try:
        check_daily_report()

        for symbol in SYMBOLS:
            df = get_klines(symbol)
            df = calculate_indicators(df)

            signal = check_signal(df)
            price = df["close"].iloc[-1]
            atr = df["atr"].iloc[-1]

            if signal:
                open_trade(symbol, signal, price, atr)

        time.sleep(60)

    except Exception as e:
        print(f"⚠️ ERROR GENERAL: {e}")
        send_telegram(f"⚠️ ERROR GENERAL: {e}")
        time.sleep(60)
