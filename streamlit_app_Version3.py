"""
Streamlit Dashboard: GLD/GDX Arbitrage Paper Trading Tracker
------------------------------------------------------------
- Visualizes live signals, executed trades, and equity curve
- Plots historical equity line (paper simulated)
- Connects to Alpaca paper account (if API keys are provided in Streamlit secrets)
- Robust against yfinance and Alpaca errors on Streamlit Cloud
- Handles empty data, trade logs, and API failures gracefully
"""

import os
os.environ["YFINANCE_NO_CACHE"] = "1"

import streamlit as st

st.set_page_config(page_title="GLD/GDX Arb Tracker", layout="wide")

import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

st.title("GLD/GDX Arbitrage Strategy Dashboard")

# --- PARAMETERS ---
LEAD = "GLD"
LAG = "GDX"
CAPITAL = 1_000_000

# --- ALPACA CREDENTIALS ---
# Use Streamlit secrets for security on Streamlit Cloud!
API_KEY = st.secrets.get("API_KEY", "")
SECRET_KEY = st.secrets.get("SECRET_KEY", "")
BASE_URL = st.secrets.get("BASE_URL", "https://paper-api.alpaca.markets")

# --- LOAD PRICE DATA ---
@st.cache_data
def load_price_data(lead, lag, capital):
    lead_series = yf.Ticker(lead).history(period="90d")["Close"]
    lag_series = yf.Ticker(lag).history(period="90d")["Close"]
    if lead_series.empty or lag_series.empty:
        return pd.DataFrame()
    df = pd.DataFrame({lead: lead_series, lag: lag_series})
    df['Spread'] = df[lead] - df[lag]
    df['ZScore'] = (df['Spread'] - df['Spread'].rolling(20).mean()) / df['Spread'].rolling(20).std()
    df['Equity'] = capital * (1 + df['ZScore'].fillna(0) * 0.01).cumprod()  # Simulated equity path
    return df

# --- LOAD TRADE LOG ---
@st.cache_data
def load_trade_log():
    try:
        return pd.read_csv("trades_hold1.csv")
    except Exception as e:
        print("Failed to load trade log:", e)
        return pd.DataFrame(columns=["Entry Date", "Exit Date", "GLD Return", "GDX Return", "Net Return", "Scaled Return", "Leverage"])

# --- PLOT SIGNAL CHART ---
def plot_signal_chart(df):
    if df.empty:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df[LEAD], mode='lines', name=LEAD))
    fig.add_trace(go.Scatter(x=df.index, y=df[LAG], mode='lines', name=LAG))
    # Signal overlay (ZScore > 1)
    signal_points = df[df['ZScore'] > 1]
    fig.add_trace(go.Scatter(
        x=signal_points.index,
        y=signal_points[LEAD],
        mode='markers',
        name='Signal (Z > 1)',
        marker=dict(color='red', size=8, symbol='x')
    ))
    # Trade log overlay (if available)
    try:
        trades = pd.read_csv("trades_hold1.csv")
        trades["Entry Date"] = pd.to_datetime(trades["Entry Date"])
        entries = trades.dropna(subset=["Entry Date"])
        yvals = df.reindex(entries["Entry Date"])[LEAD]
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
        title=f'{LEAD} & {LAG} with Signal + Trade Overlay',
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

# --- SHOW PRICE DATA ---
data = load_price_data(LEAD, LAG, CAPITAL)
if data.empty:
    st.error("Failed to download price data for GLD or GDX. Please try again later.")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Equity Curve (Simulated)")
    st.plotly_chart(plot_signal_chart(data), use_container_width=True)

with col2:
    st.subheader("Z-Score (GLD - GDX Spread)")
    st.line_chart(data['ZScore'])

# --- SHOW RECENT TRADE LOG ---
st.divider()
st.subheader("📒 Recent Trades")
log = load_trade_log()
if not log.empty:
    st.dataframe(log.sort_values("Entry Date", ascending=False), use_container_width=True)
else:
    st.info("No trade log available yet.")

# --- SHOW OPEN POSITIONS (ALPACA) ---
st.divider()
st.subheader("📦 Open Positions (Alpaca)")

positions_df = pd.DataFrame()
alpaca_connected = False
if API_KEY and SECRET_KEY:
    try:
        import alpaca_trade_api as tradeapi
        api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')
        positions = api.list_positions()
        positions_df = pd.DataFrame([{
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": p.side,
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl)
        } for p in positions])
        alpaca_connected = True
    except Exception as e:
        st.info(f"Could not fetch Alpaca positions (check API keys and internet connection): {e}")
else:
    st.info("Alpaca API keys not configured. Add them as Streamlit secrets to enable live positions.")

if alpaca_connected and not positions_df.empty:
    st.dataframe(positions_df, use_container_width=True)
elif alpaca_connected:
    st.info("No open positions in Alpaca account.")

# --- SHOW RECENT PRICES ---
st.divider()
st.subheader("Recent Prices")
st.line_chart(data[[LEAD, LAG]])

# --- STRATEGY DESCRIPTION ---
st.divider()
with st.expander("ℹ️ About this dashboard"):
    st.markdown(
        f"""
        **GLD/GDX Arbitrage Strategy Dashboard**

        - **Equity Curve:** Simulated performance using a rolling Z-Score (spread between {LEAD} and {LAG}).
        - **Z-Score Chart:** Highlights when the spread is statistically significant (Z>1).
        - **Trade Log:** Shows simulated or real trades (add `trades_hold1.csv` to your repo for real logs).
        - **Open Positions:** If you add your Alpaca Paper API keys as Streamlit secrets, you'll see your live paper trading positions.
        - **Data:** Price data is from Yahoo Finance, robust for cloud deployment.

        **Troubleshooting:**
        - If data is missing or errors show, it's usually a cloud download or API issue. Try refreshing, or check your API keys.

        ---
        """
    )

st.caption("Updated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
