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

symbols = ["ETHUSDT", "BCHUSDT", "BNBUSDT", "BTCUSDT"]
interval = Client.KLINE_INTERVAL_15MINUTE

RISK_PER_TRADE = 0.01
LEVERAGE = 5

last_positions = {}
wins = 0
losses = 0

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

def get_signal(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]

    if last["ema50"] > last["ema200"] and last["rsi"] < 40:
        return "LONG", last["close"], df["low"].tail(5).min()

    if last["ema50"] < last["ema200"] and last["rsi"] > 60:
        return "SHORT", last["close"], df["high"].tail(5).max()

    return None, None, None

# 🧠 DETECTAR CIERRES (🔥 REGRESA MÉTRICAS)
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

# 🔥 TRAILING PRO
def manage_trailing():
    for symbol in symbols:
        positions = client.futures_position_information(symbol=symbol)
        if not positions:
            continue

        pos = positions[0]
        amt = float(pos["positionAmt"])

        if amt == 0:
            continue

        entry = float(pos["entryPrice"])
        price = float(pos["markPrice"])

        side = "LONG" if amt > 0 else "SHORT"
        profit = (price - entry) if side == "LONG" else (entry - price)

        if profit <= 0:
            continue

        if profit < entry * 0.002:
            factor = 0.0
        elif profit < entry * 0.005:
            factor = 0.3
        else:
            factor = 0.6

        if side == "LONG":
            new_sl = entry + profit * factor
            sl_side = "SELL"
        else:
            new_sl = entry - profit * factor
            sl_side = "BUY"

        new_sl = adjust_price(symbol, new_sl)

        try:
            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type="STOP_MARKET",
                stopPrice=new_sl,
                closePosition=True
            )
        except:
            pass

def open_trade():
    if has_any_position():
        return

    for symbol in symbols:
        side, entry, stop = get_signal(symbol)

        if side is None:
            continue

        balance = get_balance()
        risk = balance * RISK_PER_TRADE
        distance = abs(entry - stop)

        if distance == 0:
            continue

        qty = (risk / distance) * LEVERAGE
        max_position = balance * 0.2
        qty = min(qty, max_position / entry)

        qty = adjust_qty(symbol, qty)

        if qty * entry < 21:
            continue

        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

        if side == "LONG":
            client.futures_create_order(symbol=symbol, side="BUY", type="MARKET", quantity=qty)
            sl_side = "SELL"
        else:
            client.futures_create_order(symbol=symbol, side="SELL", type="MARKET", quantity=qty)
            sl_side = "BUY"

        stop = adjust_price(symbol, stop)

        client.futures_create_order(symbol=symbol, side=sl_side, type="STOP_MARKET", stopPrice=stop, closePosition=True)

        send_msg(f"🚀 {side} {symbol}")

        return

while True:
    try:
        print("Bot vivo...")
        check_closed_trades()
        manage_trailing()
        open_trade()
        time.sleep(180)
    except Exception as e:
        print("Error:", e)
        send_msg(f"❌ {e}")
        time.sleep(60)
