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

symbols = ["BTCUSDT","ETHUSDT","BCHUSDT","SOLUSDT","XRPUSDT","ADAUSDT","BNBUSDT","DOGEUSDT"]
interval = Client.KLINE_INTERVAL_15MINUTE

RISK_PER_TRADE = 0.01
LEVERAGE = 5

last_positions = {}
wins = 0
losses = 0
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
    precision = int(round(-math.log(step, 10), 0))
    qty = math.floor(qty / step) * step
    return float(f"{qty:.{precision}f}")

def adjust_price(symbol, price):
    tick = symbol_info[symbol]["tickSize"]
    precision = int(round(-math.log(tick, 10), 0))
    price = math.floor(price / tick) * tick
    return float(f"{price:.{precision}f}")

# 🔒 CONTROL
def has_any_position():
    for symbol in symbols:
        pos = client.futures_position_information(symbol=symbol)
        if pos and float(pos[0]["positionAmt"]) != 0:
            return True
    return False

# 📈 DATA
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

# 🧠 ESTRATEGIA (ACTIVA DE VERDAD)
def analyze_symbol(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]

    ema50 = last["ema50"]
    ema200 = last["ema200"]
    price = last["close"]
    rsi = last["rsi"]

    distance = abs(price - ema50) / price

    print(f"{symbol} → RSI {round(rsi,1)} | dist {round(distance,4)}")

    # 🔥 LONG
    if ema50 > ema200 and 30 < rsi < 65 and distance < 0.015:
        score = (65 - rsi) + (0.015 - distance)*100
        return {
            "symbol": symbol,
            "side": "LONG",
            "entry": price,
            "stop": df["low"].tail(5).min(),
            "score": score
        }

    # 🔥 SHORT
    if ema50 < ema200 and 35 < rsi < 70 and distance < 0.015:
        score = (rsi - 35) + (0.015 - distance)*100
        return {
            "symbol": symbol,
            "side": "SHORT",
            "entry": price,
            "stop": df["high"].tail(5).max(),
            "score": score
        }

    return None

# 🏆 MEJOR TRADE
def get_best_trade():
    candidates = []

    for symbol in symbols:
        result = analyze_symbol(symbol)
        if result:
            candidates.append(result)

    if not candidates:
        print("⏳ Sin señales válidas")
        return None

    best = max(candidates, key=lambda x: x["score"])

    print(f"🏆 MEJOR: {best['symbol']} | score {round(best['score'],2)}")

    return best

# 📊 MÉTRICAS
def check_closed_trades():
    global last_positions, wins, losses

    for symbol in symbols:
        pos = client.futures_position_information(symbol=symbol)
        if not pos:
            continue

        p = pos[0]
        amt = float(p["positionAmt"])

        if symbol in last_positions and amt == 0:
            old = last_positions[symbol]

            entry = old["entry"]
            price = float(p["markPrice"])
            qty = abs(old["qty"])
            side = old["side"]

            pnl = (price - entry)*qty if side=="LONG" else (entry - price)*qty

            if pnl > 0:
                wins += 1
                emoji = "💰"
            else:
                losses += 1
                emoji = "❌"

            total = wins + losses
            winrate = (wins/total)*100 if total else 0

            msg = f"{emoji} {symbol} {round(pnl,2)} USDT | WR {round(winrate,1)}%"
            print(msg)
            send_msg(msg)

            del last_positions[symbol]

        elif amt != 0:
            last_positions[symbol] = {
                "entry": float(p["entryPrice"]),
                "qty": amt,
                "side": "LONG" if amt>0 else "SHORT"
            }

# 🚀 EJECUCIÓN
def open_trade():
    if has_any_position():
        print("🔒 trade activo")
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
    qty = min(qty, (balance*0.2)/entry)
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

    msg = f"🚀 {side} {symbol}"
    print(msg)
    send_msg(msg)

# 🔁 LOOP
while True:
    try:
        cycle_count += 1
        print(f"\n--- CICLO {cycle_count} ---")

        if cycle_count % 10 == 0:
            send_msg("🤖 Bot activo y funcionando")

        check_closed_trades()
        open_trade()

        time.sleep(180)

    except Exception as e:
        print("Error:", e)
        send_msg(f"❌ {e}")
        time.sleep(60)
