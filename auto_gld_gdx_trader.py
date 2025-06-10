import os
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone
import alpaca_trade_api as tradeapi
import time

# Load Alpaca credentials from environment variables or your secrets manager
API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
BASE_URL = "https://paper-api.alpaca.markets"

# Strategy parameters (match your research)
CAPITAL = 1_000_000
GLD_TICKER = "GLD"
GDX_TICKER = "GDX"
GAP_THRESHOLD = 0.01
VOLUME_MULTIPLIER = 1.2
USE_VOL_SIZING = True
MAX_LEVERAGE = 3
LOOKBACK = 20
HOLD_DAYS = 1  # 1-day hold

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

def get_latest_data():
    # Download last 21 days to get 20-day rolling stats
    df = yf.download([GLD_TICKER, GDX_TICKER], period=f"{LOOKBACK+1}d", interval="1d")
    price = df['Close'].dropna()
    vol = df['Volume'].dropna()
    price.columns = ['GLD', 'GDX']
    vol.columns = ['GLD_vol', 'GDX_vol']
    df = price.join(vol)
    df['GLD_ret'] = df['GLD'].pct_change()
    df['GDX_ret'] = df['GDX'].pct_change()
    df['GLD_gap'] = df['GLD'].pct_change()
    df['RVOL'] = df['GLD_vol'] / df['GLD_vol'].rolling(LOOKBACK).mean()
    df['Spread'] = df['GLD'] - df['GDX']
    df['ZScore'] = (df['Spread'] - df['Spread'].rolling(LOOKBACK).mean()) / df['Spread'].rolling(LOOKBACK).std()
    df['GLD_volatility'] = df['GLD_ret'].rolling(LOOKBACK).std()
    df['GDX_volatility'] = df['GDX_ret'].rolling(LOOKBACK).std()
    return df.dropna()

def get_open_position():
    try:
        positions = api.list_positions()
        gld = [p for p in positions if p.symbol == GLD_TICKER]
        gdx = [p for p in positions if p.symbol == GDX_TICKER]
        return gld, gdx
    except Exception as e:
        print("Error fetching positions:", e)
        return [], []

def place_trade(qty_gld, qty_gdx):
    # Place orders: buy GLD, sell GDX (short)
    try:
        # Place GLD BUY
        api.submit_order(
            symbol=GLD_TICKER, qty=qty_gld, side="buy",
            type="market", time_in_force="gtc"
        )
        # Place GDX SELL (short)
        api.submit_order(
            symbol=GDX_TICKER, qty=qty_gdx, side="sell",
            type="market", time_in_force="gtc"
        )
        print(f"Orders sent: BUY {qty_gld} {GLD_TICKER}, SELL {qty_gdx} {GDX_TICKER}")
    except Exception as e:
        print("Order error:", e)

def close_trade(qty_gld, qty_gdx):
    # Close both legs (sell GLD, buy to cover GDX)
    try:
        api.submit_order(
            symbol=GLD_TICKER, qty=qty_gld, side="sell",
            type="market", time_in_force="gtc"
        )
        api.submit_order(
            symbol=GDX_TICKER, qty=qty_gdx, side="buy",
            type="market", time_in_force="gtc"
        )
        print(f"Closing trade: SELL {qty_gld} {GLD_TICKER}, BUY {qty_gdx} {GDX_TICKER}")
    except Exception as e:
        print("Close order error:", e)

def main():
    df = get_latest_data()
    today = df.index[-1]
    row = df.iloc[-1]
    print(f"Latest date: {today.date()} | Price GLD: {row['GLD']} | GDX: {row['GDX']}")

    # Signal logic (match research)
    signal = (
        (row['GLD_gap'] > GAP_THRESHOLD) and
        (row['GDX_ret'] < row['GLD_ret'] / 2) and
        (row['RVOL'] > VOLUME_MULTIPLIER) and
        (row['ZScore'] > 1)
    )

    gld_pos, gdx_pos = get_open_position()
    have_open_trade = bool(gld_pos and gdx_pos)

    # Trade sizing
    if signal and not have_open_trade:
        # Calculate sizing
        if USE_VOL_SIZING:
            scale = 1 / (row['GLD_volatility'] + row['GDX_volatility'])
            scale = min(scale, MAX_LEVERAGE)
        else:
            scale = 1
        notional = CAPITAL * scale
        qty_gld = int(notional / row['GLD'])
        qty_gdx = int(notional / row['GDX'])
        print(f"Signal detected: placing trade with scale {scale:.2f}, {qty_gld} GLD, {qty_gdx} GDX")
        place_trade(qty_gld, qty_gdx)
        # Log trade
        with open("live_trade_log.csv", "a") as f:
            f.write(f"{today},{'open'},{qty_gld},{qty_gdx},{row['GLD']},{row['GDX']}\n")
    elif have_open_trade:
        # Check if time to close (e.g., after HOLD_DAYS)
        opened_at = datetime.strptime(gld_pos[0].asset_class, "%Y-%m-%d") if hasattr(gld_pos[0], 'asset_class') else today - timedelta(days=HOLD_DAYS)
        if (today - opened_at).days >= HOLD_DAYS:
            qty_gld = int(float(gld_pos[0].qty))
            qty_gdx = int(float(gdx_pos[0].qty))
            close_trade(qty_gld, qty_gdx)
            with open("live_trade_log.csv", "a") as f:
                f.write(f"{today},{'close'},{qty_gld},{qty_gdx},{row['GLD']},{row['GDX']}\n")
        else:
            print("Trade open, waiting to close.")
    else:
        print("No signal, no action.")

if __name__ == "__main__":
    main()