# ⚙️ CONFIG EXTRA
COOLDOWN_MINUTES = 15
last_trade_time = {}
active_symbols = set()
last_positions = {}

MIN_SL_PERCENT = 0.002  # 0.2%
MAX_NOTIONAL_PER_TRADE = 120


# 📈 DATA
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


# 🧠 SEÑAL
def get_signal(symbol):
    df = get_data(symbol)

    if df is None or len(df) < 200:
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

    # 🟢 LONG
    if ema50 > ema200 and 40 < rsi < 55 and rsi > prev_rsi:
        stop = df["low"].tail(5).min()

        if abs(price - stop) / price < MIN_SL_PERCENT:
            return None, None, None, None

        return "LONG", price, stop, rsi

    # 🔴 SHORT
    if ema50 < ema200 and 45 < rsi < 60 and rsi < prev_rsi:
        stop = df["high"].tail(5).max()

        if abs(price - stop) / price < MIN_SL_PERCENT:
            return None, None, None, None

        return "SHORT", price, stop, rsi

    return None, None, None, None


# 🔒 FORZAR ISOLATED + LEVERAGE
def set_margin(symbol):
    try:
        client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
    except:
        pass

    try:
        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)
    except:
        pass


# 🚀 ORDEN SEGURA
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


# 🔔 GESTIÓN (CIERRES REALES)
def manage_positions():
    global trade_data, daily_profit, wins, losses

    for symbol in symbols:
        amt = get_position_amt(symbol)

        # detectar cierre REAL
        if symbol in last_positions:
            if last_positions[symbol] != 0 and amt == 0:

                if symbol in trade_data:

                    entry = trade_data[symbol]["entry"]
                    qty = trade_data[symbol]["qty"]
                    side = trade_data[symbol]["side"]

                    # 🔥 usamos mark price actual
                    ticker = client.futures_mark_price(symbol=symbol)
                    price = float(ticker["markPrice"])

                    if side == "LONG":
                        profit = (price - entry) * qty
                    else:
                        profit = (entry - price) * qty

                    profit = round(profit, 2)

                    daily_profit += profit

                    if profit > 0:
                        wins += 1
                    else:
                        losses += 1

                    send_msg(f"""📊 TRADE CERRADO {symbol}

💰 Resultado: {profit} USDT
📈 Balance día: {round(daily_profit,2)}
""")

                    del trade_data[symbol]

        last_positions[symbol] = amt


# 🚀 ABRIR TRADE
def open_trade():
    global active_symbols, last_trade_time

    if get_open_positions_count() >= MAX_TRADES:
        return

    balance = get_balance()

    for symbol in symbols:

        # ❌ evitar duplicados
        if abs(get_position_amt(symbol)) > 0:
            continue

        # ❌ cooldown
        if symbol in last_trade_time:
            elapsed = (datetime.now() - last_trade_time[symbol]).seconds / 60
            if elapsed < COOLDOWN_MINUTES:
                continue

        side, entry, stop, rsi = get_signal(symbol)

        if side is None:
            continue

        set_margin(symbol)

        risk_usdt = balance * RISK_PERCENT
        risk_per_unit = abs(entry - stop)

        if risk_per_unit == 0:
            continue

        qty = risk_usdt / risk_per_unit
        notional = qty * entry

        # 🔒 limitar tamaño
        if notional > MAX_NOTIONAL_PER_TRADE:
            qty = MAX_NOTIONAL_PER_TRADE / entry

        qty = float(format_qty(symbol, qty))

        if qty <= 0:
            continue

        # 🚀 ejecutar
        if side == "LONG":
            ok = safe_order(symbol, "BUY", qty)
            sl_side = "SELL"
            tp = entry + (risk_per_unit * 2)
        else:
            ok = safe_order(symbol, "SELL", qty)
            sl_side = "BUY"
            tp = entry - (risk_per_unit * 2)

        if not ok:
            continue

        stop = format_price(symbol, stop)
        tp = format_price(symbol, tp)

        # 🛑 SL
        client.futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="STOP_MARKET",
            stopPrice=stop,
            closePosition=True
        )

        # 🎯 TP
        client.futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp,
            closePosition=True
        )

        trade_data[symbol] = {
            "entry": entry,
            "qty": qty,
            "side": side
        }

        last_trade_time[symbol] = datetime.now()

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


# 🔁 LOOP
while True:
    try:
        manage_positions()
        open_trade()
        time.sleep(120)
    except Exception as e:
        print(e)
        send_msg(f"❌ {e}")
        time.sleep(60)
