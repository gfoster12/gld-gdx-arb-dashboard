import os
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone
import alpaca_trade_api as tradeapi

st.set_page_config(page_title="GLD/GDX Auto-Trader", layout="wide")
st.title("GLD/GDX Arbitrage Automated Trading Dashboard")

# --- Parameters ---
GLD_TICKER = "GLD"
GDX_TICKER = "GDX"
CAPITAL = 1_000_000
GAP_THRESHOLD = 0.01
VOLUME_MULTIPLIER = 1.2
USE_VOL_SIZING = True
MAX_LEVERAGE = 3
LOOKBACK = 20
HOLD_DAYS = 1

# --- Alpaca credentials ---
API_KEY = st.secrets.get("API_KEY", os.getenv("APCA_API_KEY_ID", ""))
SECRET_KEY = st.secrets.get("SECRET_KEY", os.getenv("APCA_API_SECRET_KEY", ""))
BASE_URL = st.secrets.get("BASE_URL", os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets"))

if not API_KEY or not SECRET_KEY:
    st.warning("No Alpaca keys configured. Add in Streamlit secrets for live trading.")

# --- Helper functions ---
@st.cache_data(ttl=600)
def get_latest_data():
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

def get_alpaca_api():
    if not API_KEY or not SECRET_KEY:
        return None
    return tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

def get_open_position(api):
    try:
        positions = api.list_positions()
        gld = [p for p in positions if p.symbol == GLD_TICKER]
        gdx = [p for p in positions if p.symbol == GDX_TICKER]
        return gld, gdx
    except Exception as e:
        st.error(f"Error fetching Alpaca positions: {e}")
        return [], []

def log_action(action, details=""):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts},{action},{details}\n"
    with open("trade_system_log.csv", "a") as f:
        f.write(line)

def log_trade(event, qty_gld, qty_gdx, price_gld, price_gdx):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts},{event},{qty_gld},{qty_gdx},{price_gld},{price_gdx}\n"
    with open("trade_log.csv", "a") as f:
        f.write(line)

def place_trade(api, qty_gld, qty_gdx):
    try:
        api.submit_order(symbol=GLD_TICKER, qty=qty_gld, side="buy", type="market", time_in_force="gtc")
        api.submit_order(symbol=GDX_TICKER, qty=qty_gdx, side="sell", type="market", time_in_force="gtc")
        log_action("TRADE_OPEN", f"BUY {qty_gld} GLD, SELL {qty_gdx} GDX")
        st.success(f"Orders sent: BUY {qty_gld} {GLD_TICKER}, SELL {qty_gdx} {GDX_TICKER}")
    except Exception as e:
        st.error(f"Order error: {e}")
        log_action("TRADE_OPEN_FAILED", str(e))

def close_trade(api, qty_gld, qty_gdx):
    try:
        api.submit_order(symbol=GLD_TICKER, qty=qty_gld, side="sell", type="market", time_in_force="gtc")
        api.submit_order(symbol=GDX_TICKER, qty=qty_gdx, side="buy", type="market", time_in_force="gtc")
        log_action("TRADE_CLOSE", f"SELL {qty_gld} GLD, BUY {qty_gdx} GDX")
        st.success(f"Closing trade: SELL {qty_gld} {GLD_TICKER}, BUY {qty_gdx} {GDX_TICKER}")
    except Exception as e:
        st.error(f"Close order error: {e}")
        log_action("TRADE_CLOSE_FAILED", str(e))

# --- Signal & sizing logic ---
def check_signal(row):
    return (
        (row['GLD_gap'] > GAP_THRESHOLD) and
        (row['GDX_ret'] < row['GLD_ret'] / 2) and
        (row['RVOL'] > VOLUME_MULTIPLIER) and
        (row['ZScore'] > 1)
    )

def compute_sizing(row):
    if USE_VOL_SIZING:
        scale = 1 / (row['GLD_volatility'] + row['GDX_volatility'])
        scale = min(scale, MAX_LEVERAGE)
    else:
        scale = 1
    notional = CAPITAL * scale
    qty_gld = int(notional / row['GLD'])
    qty_gdx = int(notional / row['GDX'])
    return qty_gld, qty_gdx, scale

# --- Dashboard UI ---
data = get_latest_data()
row = data.iloc[-1]
today = data.index[-1]

signal = check_signal(row)
qty_gld, qty_gdx, scale = compute_sizing(row)

st.write(f"Latest date: {today.date()} | GLD: ${row['GLD']:.2f} | GDX: ${row['GDX']:.2f}")
st.write(f"Signal: {'✅' if signal else '❌'}, Sizing scale: {scale:.2f}, Qty GLD: {qty_gld}, Qty GDX: {qty_gdx}")

api = get_alpaca_api() if (API_KEY and SECRET_KEY) else None
gld_pos, gdx_pos = get_open_position(api) if api else ([], [])

# --- Buttons ---
if signal and not (gld_pos and gdx_pos):
    if st.button(f"Open Trade (BUY {qty_gld} GLD, SELL {qty_gdx} GDX)"):
        if api:
            place_trade(api, qty_gld, qty_gdx)
            log_trade("open", qty_gld, qty_gdx, row['GLD'], row['GDX'])
        else:
            st.warning("No Alpaca API key/secret.")

if gld_pos and gdx_pos:
    # Ideally store persistent time of open; for now, just always allow closing
    if st.button(f"Close Trade (SELL {gld_pos[0].qty} GLD, BUY {gdx_pos[0].qty} GDX)"):
        if api:
            close_trade(api, int(float(gld_pos[0].qty)), int(float(gdx_pos[0].qty)))
            log_trade("close", int(float(gld_pos[0].qty)), int(float(gdx_pos[0].qty)), row['GLD'], row['GDX'])
        else:
            st.warning("No Alpaca API key/secret.")

# --- Trade Log Display ---
st.subheader("Trade Log")
try:
    trade_log = pd.read_csv("trade_log.csv", names=["Timestamp", "Event", "Qty_GLD", "Qty_GDX", "GLD_Price", "GDX_Price"])
    st.dataframe(trade_log.tail(20), use_container_width=True)
except Exception:
    st.info("No trades logged yet.")

# --- System Log Display ---
st.subheader("System Log")
try:
    sys_log = pd.read_csv("trade_system_log.csv", names=["Timestamp", "Action", "Details"])
    st.dataframe(sys_log.tail(20), use_container_width=True)
except Exception:
    st.info("No system log yet.")

# --- Visualization ---
st.subheader("GLD vs GDX Prices & Signal")
st.line_chart(data[[GLD_TICKER, GDX_TICKER]])
st.line_chart(data[["ZScore"]])

st.caption("Updated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
