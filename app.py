# --- 2_Analysis.py ---
import streamlit as st
import yfinance as yf
import pandas as pd
import streamlit.components.v1 as components

st.set_page_config(layout="wide")

# Read ticker from query parameters instead of session_state
params = st.query_params
ticker = params.get("ticker", [None])[0]

if not ticker:
    st.warning("No ticker found in URL. Please return to the screener and select one.")
    st.stop()

stock = yf.Ticker(ticker)
hist = stock.history(period="6mo")
info = stock.info

st.markdown(f"# Detailed Analysis for **{ticker}**")
st.markdown("---")

# --- FUNDAMENTALS ---
st.subheader("Fundamental Data")
st.write({
    "Current Price": info.get("currentPrice"),
    "Market Cap": info.get("marketCap"),
    "P/E Ratio": info.get("trailingPE"),
    "EPS": info.get("trailingEps"),
    "ROE": info.get("returnOnEquity"),
    "52w High": info.get("fiftyTwoWeekHigh"),
    "52w Low": info.get("fiftyTwoWeekLow")
})

# --- TECHNICAL ANALYSIS ---
st.subheader("Technical Indicators")

hist["SMA50"] = hist["Close"].rolling(window=50).mean()
hist["SMA200"] = hist["Close"].rolling(window=200).mean()
hist["RSI"] = 100 - (100 / (1 + hist["Close"].pct_change().add(1).rolling(14).apply(lambda x: x.prod()) - 1))

st.line_chart(hist[["Close", "SMA50", "SMA200"]].dropna())

# --- SUPPORT / RESISTANCE ---
st.subheader("Support & Resistance")
recent_close = hist["Close"].iloc[-1]
support = hist["Close"].rolling(window=20).min().iloc[-1]
resistance = hist["Close"].rolling(window=20).max().iloc[-1]

st.write({
    "Current Price": round(recent_close, 2),
    "20-day Support": round(support, 2),
    "20-day Resistance": round(resistance, 2)
})

# --- EMBEDDED TRADINGVIEW CHART ---
st.subheader("Interactive Chart (TradingView)")
components.html(f"""
<iframe src=\"https://s.tradingview.com/widgetembed/?frameElementId=tradingview_{ticker}&symbol={ticker}&interval=D&hidesidetoolbar=1&symboledit=1&saveimage=1&toolbarbg=F1F3F6&studies=[]&theme=light&style=1&timezone=Etc/UTC&withdateranges=1&hideideas=1\" 
width=\"100%\" height=\"500\" frameborder=\"0\" allowtransparency=\"true\" scrolling=\"no\"></iframe>
""", height=500)

st.markdown("[Back to Screener](../app.py)")
