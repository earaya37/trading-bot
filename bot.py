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

symbols = ["BTCUSDT", "ETHUSDT", "BCHUSDT", "SOLUSDT", "XRPUSDT"]
interval = Client.KLINE_INTERVAL_15MINUTE

RISK_PER_TRADE = 0.01
LEVERAGE = 5

last_positions = {}
wins = 0
losses = 0
cycle_count = 0

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

def get_balance():
    balance = client.futures_account_balance()
    for b in balance:
        if b["asset"] == "USDT":
            return float(b["balance"])

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
    precision = int(round(-math.log(step, 10), 0))
    qty = math.floor(qty / step) * step
    return float(f"{qty:.{precision}f}")

def adjust_price(symbol, price):
    tick = symbol_info[symbol]["tickSize"]
    precision = int(round(-math.log(tick, 10), 0))
    price = math.floor(price / tick) * tick
    return float(f"{price:.{precision}f}")

def has_position(symbol):
    positions = client.futures_position_information(symbol=symbol)
    return positions and float(positions[0]["positionAmt"]) != 0

def has_any_position():
    for symbol in symbols:
        if has_position(symbol):
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

# 🧠 ANALIZA Y CALIFICA
def analyze_symbol(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]

    score = 0

    if last["ema50"] > last["ema200"]:
        trend = "LONG"
        score += 1
    elif last["ema50"] < last["ema200"]:
        trend = "SHORT"
        score += 1
    else:
        print(f"{symbol} → ❌ sin tendencia")
        return None

    if trend == "LONG" and last["rsi"] < 40:
        score += (40 - last["rsi"]) / 10
    elif trend == "SHORT" and last["rsi"] > 60:
        score += (last["rsi"] - 60) / 10
    else:
        print(f"{symbol} → ❌ RSI no válido ({round(last['rsi'],2)})")
        return None

    print(f"{symbol} → score {round(score,2)}")

    entry = last["close"]
    stop = df["low"].tail(5).min() if trend == "LONG" else df["high"].tail(5).max()

    return {
        "symbol": symbol,
        "side": trend,
        "entry": entry,
        "stop": stop,
        "score": score
    }

# 🧠 ELIGE EL MEJOR
def get_best_trade():
    candidates = []

    for symbol in symbols:
        result = analyze_symbol(symbol)
        if result:
            candidates.append(result)

    if not candidates:
        print("⏳ Ninguna señal válida")
        return None

    best = max(candidates, key=lambda x: x["score"])
    print(f"🏆 Mejor trade: {best['symbol']} ({round(best['score'],2)})")

    return best

# 📊 MÉTRICAS
def check_closed_trades():
    global last_positions, wins, losses

    for symbol in symbols:
        positions = client.futures_position_information(symbol=symbol)
        if not positions:
            continue

        pos = positions[0]
        amt = float(pos["positionAmt"])
        entry_price = float(pos["entryPrice"])
        mark_price = float(pos["markPrice"])

        if symbol in last_positions and amt == 0:
            old = last_positions[symbol]

            entry = old["entry"]
            side = old["side"]
            qty = abs(old["qty"])

            pnl = (mark_price - entry) * qty if side == "LONG" else (entry - mark_price) * qty

            if pnl > 0:
                wins += 1
                emoji = "💰"
            else:
                losses += 1
                emoji = "❌"

            total = wins + losses
            winrate = (wins / total) * 100 if total > 0 else 0

            msg = f"""{emoji} TRADE CERRADO {symbol}
PnL: {round(pnl,2)} USDT
Winrate: {round(winrate,2)}%
Trades: {total}
"""
            print(msg)
            send_msg(msg)

            del last_positions[symbol]

        elif amt != 0:
            side = "LONG" if amt > 0 else "SHORT"

            last_positions[symbol] = {
                "entry": entry_price,
                "qty": amt,
                "side": side
            }

# 🚀 EJECUCIÓN
def open_trade():
    if has_any_position():
        print("🔒 Ya hay posición activa")
        return

    best = get_best_trade()

    if not best:
        return

    symbol = best["symbol"]
    side = best["side"]
    entry = best["entry"]
    stop = best["stop"]

    balance = get_balance()
    risk = balance * RISK_PER_TRADE
    distance = abs(entry - stop)

    if distance == 0:
        return

    qty = (risk / distance) * LEVERAGE
    max_position = balance * 0.2
    qty = min(qty, max_position / entry)

    qty = adjust_qty(symbol, qty)

    if qty * entry < 21:
        print(f"{symbol} → ❌ menor a mínimo")
        return

    client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

    if side == "LONG":
        client.futures_create_order(symbol=symbol, side="BUY", type="MARKET", quantity=qty)
        sl_side = "SELL"
    else:
        client.futures_create_order(symbol=symbol, side="SELL", type="MARKET", quantity=qty)
        sl_side = "BUY"

    stop = adjust_price(symbol, stop)

    client.futures_create_order(symbol=symbol, side=sl_side, type="STOP_MARKET", stopPrice=stop, closePosition=True)

    send_msg(f"🚀 {side} {symbol} (BEST)")

# 🔁 LOOP
while True:
    try:
        cycle_count += 1
        print(f"\n--- CICLO {cycle_count} ---")

        if cycle_count % 10 == 0:
            send_msg("🤖 Bot activo y analizando mercado")

        check_closed_trades()
        open_trade()

        time.sleep(180)

    except Exception as e:
        print("Error:", e)
        send_msg(f"❌ {e}")
        time.sleep(60)
