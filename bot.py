from binance.client import Client
import pandas as pd
import ta
import time
import os
import requests

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

client = Client(API_KEY, API_SECRET)

symbols = ["ETHUSDT", "BCHUSDT"]
interval = Client.KLINE_INTERVAL_15MINUTE

RISK_PER_TRADE = 0.01
LEVERAGE = 5

# 📊 MÉTRICAS
last_positions = {}
wins = 0
losses = 0

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

# 🔒 POSICIÓN POR PAR
def has_position(symbol):
    try:
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            if float(p["positionAmt"]) != 0:
                return True
    except:
        return False
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

# 🔥 CÁLCULO
def calculate_qty(balance, entry, stop):
    risk = balance * RISK_PER_TRADE
    distance = abs(entry - stop)

    if distance == 0:
        return None

    qty = (risk / distance) * LEVERAGE

    max_position_usdt = balance * 0.2
    max_qty = max_position_usdt / entry
    qty = min(qty, max_qty)

    min_notional = 20
    min_qty = min_notional / entry

    if qty < min_qty:
        qty = min_qty

    return round(qty, 3)

# 📊 SEÑAL
def get_signal(symbol):
    df = get_data(symbol)

    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    last = df.iloc[-1]

    if last["ema50"] > last["ema200"] and last["rsi"] < 40:
        entry = last["close"]
        stop = df["low"].tail(5).min()
        return "LONG", entry, stop

    if last["ema50"] < last["ema200"] and last["rsi"] > 60:
        entry = last["close"]
        stop = df["high"].tail(5).max()
        return "SHORT", entry, stop

    return None, None, None

# 🧠 DETECTAR CIERRES
def check_closed_trades():
    global last_positions, wins, losses

    for symbol in symbols:
        try:
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

                if side == "LONG":
                    pnl = (mark_price - entry) * qty
                else:
                    pnl = (entry - mark_price) * qty

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

        except Exception as e:
            print(f"Error chequeando {symbol}: {e}")

# 🚀 EJECUCIÓN
def open_trade():

    # 🔒 SOLO 1 TRADE GLOBAL REAL
    for s in symbols:
        if has_position(s):
            print("Ya hay una posición activa, no se abre otra")
            return

    for symbol in symbols:

        side, entry, stop = get_signal(symbol)

        if side is None:
            continue

        balance = get_balance()
        qty = calculate_qty(balance, entry, stop)

        if qty is None or qty <= 0:
            continue

        notional = qty * entry
        if notional < 21:
            print(f"{symbol} ignorado por mínimo notional")
            continue

        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

        if side == "LONG":
            client.futures_create_order(symbol=symbol, side="BUY", type="MARKET", quantity=qty)
            sl_side = tp_side = "SELL"
            tp = entry + (entry - stop) * 2
        else:
            client.futures_create_order(symbol=symbol, side="SELL", type="MARKET", quantity=qty)
            sl_side = tp_side = "BUY"
            tp = entry - (stop - entry) * 2

        client.futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="STOP_MARKET",
            stopPrice=round(stop, 2),
            closePosition=True
        )

        client.futures_create_order(
            symbol=symbol,
            side=tp_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp, 2),
            closePosition=True
        )

        msg = f"""🚀 TRADE {side}
Par: {symbol}
Entry: {entry}
SL: {stop}
TP: {round(tp,2)}
Qty: {qty}
"""
        print(msg)
        send_msg(msg)

        return
