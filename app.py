# --- app.py ---
import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import base64
from PIL import Image
from io import BytesIO
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set page config FIRST
st.set_page_config(
    page_title="Josue's SPY Wheel Screener",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Display the logo centered at the top
logo = Image.open("wagon.png")
buffered = BytesIO()
logo.save(buffered, format="PNG")
logo_b64 = base64.b64encode(buffered.getvalue()).decode()
st.markdown(
    f"<div style='text-align: center;'><img src='data:image/png;base64,{logo_b64}' width='150'></div>",
    unsafe_allow_html=True
)

st.markdown("<h1 style='text-align: center;'>SPY Wheel Strategy Screener</h1>", unsafe_allow_html=True)
st.markdown("<h3 style='text-align: center;'>by Josue Ordonez</h3>", unsafe_allow_html=True)
st.markdown("Scans <b>S&P 500 stocks</b> for Wheel setups using price, market cap, IV, put premiums, and earnings filters.", unsafe_allow_html=True)

# FILTER VALUES
PRICE_MIN = 5
PRICE_MAX = 50
MARKET_CAP_MIN_B = 1
DAYS_OUT = 0  # Closest expiration
EARNINGS_MIN_DAYS = 0
EARNINGS_MAX_DAYS = 14

# GET TICKERS
@st.cache_data
def get_spy_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url)[0]
    return [t.replace(".", "-") for t in df["Symbol"].tolist()]

spy_tickers = get_spy_tickers()

# SCREENING FUNCTION
@st.cache_data
def screen_stocks(tickers):
    screened = []
    progress = st.progress(0)
    total = len(tickers)
    completed = 0

    def process_ticker(ticker):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            price = info.get("currentPrice", 0)
            market_cap = info.get("marketCap", 0)
            cap_b = market_cap / 1e9 if market_cap else 0
            iv = info.get("impliedVolatility", None)
            earnings_date = info.get("earningsDate")

            today = datetime.datetime.now().date()
            if not earnings_date:
                return None
            if isinstance(earnings_date, (list, tuple)):
                earnings_date = earnings_date[0]
            days_to_earnings = (pd.to_datetime(earnings_date).date() - today).days
            if days_to_earnings < EARNINGS_MIN_DAYS or days_to_earnings <= EARNINGS_MAX_DAYS:
                return None

            if not (PRICE_MIN <= price <= PRICE_MAX and cap_b >= MARKET_CAP_MIN_B):
                return None

            expiration_dates = stock.options
            if not expiration_dates or len(expiration_dates) <= DAYS_OUT:
                return None

            exp_date = expiration_dates[DAYS_OUT]
            opt_chain = stock.option_chain(exp_date)
            puts = opt_chain.puts
            if puts.empty:
                return None

            puts = puts.assign(delta_estimate=abs((puts["strike"] - price) / price))
            puts = puts[puts["strike"] < price]
            puts = puts.sort_values(by="delta_estimate")
            near_25_delta_puts = puts.head(3)

            result = []
            for _, put in near_25_delta_puts.iterrows():
                put_bid = put["bid"]
                put_oi = put["openInterest"]
                put_vol = put["volume"]
                put_strike = put["strike"]
                premium_yield = (put_bid / price) * 100 if price > 0 else 0

                # Optional filter: only include options with volume > 10 and OI > 100
                if put_vol < 10 or put_oi < 100:
                    continue

                result.append({
                    "Ticker": ticker,
                    "Price": round(price, 2),
                    "Market Cap ($B)": round(cap_b, 2),
                    "IV": f"{iv
