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

# Set page config
st.set_page_config(
    page_title="Josue's SPY Wheel Screener",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Display logo centered at the top
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

# Filter constants
PRICE_MIN = 5
PRICE_MAX = 50
MARKET_CAP_MIN_B = 1
DAYS_OUT = 0
EARNINGS_MIN_DAYS = 0
EARNINGS_MAX_DAYS = 14

# Get S&P 500 tickers
@st.cache_data
def get_spy_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url)[0]
    return [t.replace(".", "-") for t in df["Symbol"].tolist()]

spy_tickers = get_spy_tickers()

# Screening function
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

                if put_vol < 10 or put_oi < 100:
                    continue

                result.append({
                    "Ticker": ticker,
                    "Price": round(price, 2),
                    "Market Cap ($B)": round(cap_b, 2),
                    "IV": f"{iv:.0%}" if iv is not None else "N/A",
                    "Put Strike": put_strike,
                    "Put Bid": round(put_bid, 2),
                    "Premium Yield (%)": round(premium_yield, 2),
                    "Volume": int(put_vol if pd.notna(put_vol) else 0),
                    "Open Interest": int(put_oi if pd.notna(put_oi) else 0),
                    "Earnings Date": pd.to_datetime(earnings_date).date() if earnings_date else "N/A"
                })
            return result
        except Exception as e:
            print(f"[ERROR] Ticker {ticker}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_ticker, t): t for t in tickers}
        for future in as_completed(futures):
            result = future.result()
            if result:
                screened.extend(result)
            completed += 1
            progress.progress(completed / total)

    progress.empty()
    df = pd.DataFrame(screened)
    df = df.sort_values(by="Market Cap ($B)", ascending=False)
    return df

# Load and screen tickers
loading_block = st.empty()
loading_block.info("Scanning S&P 500 tickers... Please wait while results are loading.")
df = screen_stocks(spy_tickers)
loading_block.empty()

# Show results
st.success(f"Showing {len(df)} stocks matching Wheel Strategy filters (excluding earnings in next 14 days).")
gb = GridOptionsBuilder.from_dataframe(df)
gb.configure_default_column(filter=True)
grid_options = gb.build()

AgGrid(
    df,
    gridOptions=grid_options,
    height=400,
    width='100%',
    update_mode=GridUpdateMode.NO_UPDATE,
    fit_columns_on_grid_load=True
)

# Download CSV
st.download_button("Download CSV", df.to_csv(index=False), "spy_wheel_candidates.csv", "text/csv")

# Wheel strategy guidelines
st.markdown("""
---
### 🛞 Wheel Strategy Guidelines

**When initiating the Wheel Strategy with a Cash-Secured Put (CSP):**

- **Strike Selection:**
  - Choose a strike price *below the current stock price* (Out of the Money)
  - Target a delta between 0.16 and 0.30 (25 is a sweet spot)

- **DTE (Days to Expiration):**
  - Preferred: 30 to 45 DTE
  - Manage or roll around 21 DTE

- **Premium Consideration:**
  - Aim for premium ≥ 1% of strike price
  - Higher IV = better premiums (but more volatility)

- **Earnings Risk:**
  - Avoid selling CSPs if earnings are due within 14 days

- **Post-assignment:**
  - Sell Covered Call 1–2 strikes above cost basis
  - Repeat until assigned away
---
""")
