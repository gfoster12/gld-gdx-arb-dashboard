"""
Streamlit Dashboard: GLD/GDX Arbitrage Paper Trading Tracker
------------------------------------------------------------
- Visualizes live signals, executed trades, and equity curve
- Plots historical equity line (paper simulated)
- Connects to Alpaca paper account
"""
import os
os.environ["YFINANCE_NO_CACHE"] = "1"
import yfinance as yf
import streamlit as st
import pandas as pd

st.title("GLD/GDX Arbitrage Strategy Dashboard")

try:
    gld = yf.download("GLD", period="90d", threads=False)["Close"]
    gdx = yf.download("GDX", period="90d", threads=False)["Close"]
    df = pd.DataFrame({"GLD": gld, "GDX": gdx})
except Exception as e:
    st.error(f"Failed to download price data: {e}")
    st.stop()

import pandas as pd
import numpy as np
import yfinance as yf
import alpaca_trade_api as tradeapi
import plotly.graph_objects as go
from datetime import datetime

# Alpaca credentials (use secrets manager or env vars in production)
API_KEY = "PKB79ABB89SMFI5C623U"
SECRET_KEY = "ezUgrAX3n33rxfhFHpOYk4kSR5RTIGBRILH36JCz"
BASE_URL = "https://paper-api.alpaca.markets"
api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

st.set_page_config(page_title="GLD/GDX Arb Tracker", layout="wide")
st.title("📊 GLD/GDX Arbitrage Strategy Dashboard")

# Parameters
LEAD = "GLD"
LAG = "GDX"
CAPITAL = 1_000_000

@st.cache_data
def load_price_data(lead, lag, capital):
    df = yf.download([lead, lag], period="90d")
    df = df['Close'].dropna()
    df.columns = ['GLD', 'GDX']
    df['Spread'] = df['GLD'] - df['GDX']
    df['ZScore'] = (df['Spread'] - df['Spread'].rolling(20).mean()) / df['Spread'].rolling(20).std()
    df['Equity'] = capital * (1 + df['ZScore'].fillna(0) * 0.01).cumprod()  # Simulated equity path
    return df

@st.cache_data
def load_trade_log():
    try:
        return pd.read_csv("trades_hold1.csv")
    except Exception as e:
        print("Failed to load trade log:", e)
        return pd.DataFrame(columns=["Entry Date", "Exit Date", "GLD Return", "GDX Return", "Net Return", "Scaled Return", "Leverage"])

def get_positions():
    try:
        positions = api.list_positions()
        return pd.DataFrame([{
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": p.side,
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl)
        } for p in positions])
    except Exception as e:
        print("Failed to fetch positions:", e)
        return pd.DataFrame()

def plot_signal_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['GLD'], mode='lines', name='GLD'))
    fig.add_trace(go.Scatter(x=df.index, y=df['GDX'], mode='lines', name='GDX'))
    signal_points = df[df['ZScore'] > 1]
    fig.add_trace(go.Scatter(
        x=signal_points.index,
        y=signal_points['GLD'],
        mode='markers',
        name='Signal (Z > 1)',
        marker=dict(color='red', size=8, symbol='x')
    ))
    try:
        trades = pd.read_csv("trades_hold1.csv")
        trades["Entry Date"] = pd.to_datetime(trades["Entry Date"])
        entries = trades.dropna(subset=["Entry Date"])
        yvals = df.reindex(entries["Entry Date"])['GLD']
        fig.add_trace(go.Scatter(
            x=entries["Entry Date"],
            y=yvals,
            mode='markers',
            name='Trade Entry',
            marker=dict(color='green', size=10, symbol='circle')
        ))
    except Exception as e:
        print("Trade overlay error:", e)
    fig.update_layout(
        title='GLD & GDX with Signal + Trade Overlay',
        height=450,
        xaxis=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=7, label="1w", step="day", stepmode="backward"),
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(step="all")
                ]
            ),
            rangeslider=dict(visible=True),
            type="date"
        )
    )
    return fig

# Load data
data = load_price_data(LEAD, LAG, CAPITAL)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Equity Curve (Simulated)")
    st.plotly_chart(plot_signal_chart(data), use_container_width=True)

with col2:
    st.subheader("Z-Score (GLD - GDX Spread)")
    st.line_chart(data['ZScore'])

st.divider()
st.subheader("📒 Recent Trades")
log = load_trade_log()
st.dataframe(log.sort_values("Entry Date", ascending=False), use_container_width=True)

st.divider()
st.subheader("📦 Open Positions (Alpaca)")
positions = get_positions()
st.dataframe(positions, use_container_width=True)

st.caption("Updated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
