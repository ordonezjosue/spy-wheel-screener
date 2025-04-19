# --- app.py ---
import yfinance as yf
import pandas as pd
import streamlit as st
import datetime
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from streamlit_extras.switch_page_button import switch_page

# PAGE SETUP
st.set_page_config(
    page_title="Josue's SPY Wheel Screener",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("<h1 style='text-align: center;'>SPY Wheel Strategy Screener</h1>", unsafe_allow_html=True)
st.markdown("<h3 style='text-align: center;'>by Josue Ordonez</h3>", unsafe_allow_html=True)
st.markdown("Scans <b>S&P 500 stocks</b> for Wheel setups using price, market cap, IV, put premiums, and earnings filters.", unsafe_allow_html=True)

# FILTER VALUES
PRICE_MIN = 5
PRICE_MAX = 50
MARKET_CAP_MIN_B = 1
DAYS_OUT = 0
EARNINGS_MIN_DAYS = 7
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
    from concurrent.futures import ThreadPoolExecutor, as_completed

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

            if earnings_date:
                today = datetime.datetime.now().date()
                if isinstance(earnings_date, (list, tuple)):
                    earnings_date = earnings_date[0]
                days_to_earnings = (pd.to_datetime(earnings_date).date() - today).days
                if EARNINGS_MIN_DAYS <= days_to_earnings <= EARNINGS_MAX_DAYS:
                    return None

            if not (PRICE_MIN <= price <= PRICE_MAX and cap_b >= MARKET_CAP_MIN_B):
                return None

            expiration_dates = stock.options
            if not expiration_dates:
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

                result.append({
                    "Ticker": ticker,
                    "Price": round(price, 2),
                    "Market Cap ($B)": round(cap_b, 2),
                    "IV": f"{iv:.0%}" if iv else "N/A",
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

# RUN THE SCREEN
loading_block = st.empty()
loading_block.info("**Scanning S&P 500 tickers... Please wait while results are loading.**")

df = screen_stocks(spy_tickers)
loading_block.empty()

# HIDE SELECTED COLUMNS
hidden_cols = ["Market Cap ($B)", "IV", "Put Bid", "Earnings Date"]
display_df = df.drop(columns=hidden_cols)

# DISPLAY GRID
st.success(f"\u2705 Showing Top {len(df)} stocks matching Wheel Strategy filters (excluding earnings in 7\u201314 days).")
gb = GridOptionsBuilder.from_dataframe(display_df)
gb.configure_selection('single')
gb.configure_default_column(filter=False)  # Disable filter cone icons
grid_options = gb.build()

grid_return = AgGrid(
    display_df,
    gridOptions=grid_options,
    height=400,
    width='100%',
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    fit_columns_on_grid_load=True
)

if grid_return['selected_rows']:
    selected_row = grid_return['selected_rows'][0]
    st.session_state["selected_ticker"] = selected_row["Ticker"]
    switch_page("pages/2_Analysis")

# DOWNLOAD FULL CSV
st.download_button("Download CSV", df.to_csv(index=False), "spy_wheel_candidates.csv", "text/csv")

# STRATEGY GUIDE
st.markdown("""
---
### \ud83d\udcd8\ufe0f Wheel Strategy Guidelines
**When initiating the Wheel Strategy with a Cash-Secured Put (CSP):**

- \u2705 **Strike Selection:**
  - Choose a strike price **below the current stock price** (Out of the Money)
  - Target a delta between **0.16 and 0.30** (use 25 as a sweet spot)

- \u23f3 **DTE (Days to Expiration):**
  - Preferred: **30 to 45 DTE**
  - Manage or roll around 21 DTE

- \ud83d\udcb5 **Premium Consideration:**
  - Target a premium yield of at least **1% of the strike price**
  - Higher IV = better premiums (but may mean more volatility)

- \u2757 **Earnings Risk:**
  - Avoid selling CSPs with earnings reports due within **7\u201314 days**

- \ud83d\udcc8 **Post-assignment:**
  - If assigned, sell a Covered Call 1\u20132 strikes above your cost basis
  - Continue to generate premium until called away
---
""")
