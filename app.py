import yfinance as yf
import pandas as pd
import streamlit as st
import datetime
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

# -------------------- PAGE SETUP --------------------
st.set_page_config(
    page_title="Josue's SPY Wheel Screener",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("# 🛞 SPY Wheel Strategy Screener")
st.markdown("### by **Josue Ordonez**")
st.markdown("Scans **S&P 500 stocks** for Wheel setups using price, market cap, IV, put premiums, and earnings filters.")

# -------------------- FILTER VALUES --------------------
PRICE_MIN = 5
PRICE_MAX = 50
MARKET_CAP_MIN_B = 1
IV_THRESHOLD = 0.30
DAYS_OUT = 0  # Use nearest expiration
EARNINGS_MIN_DAYS = 7
EARNINGS_MAX_DAYS = 14

# -------------------- GET SPY TICKERS --------------------
@st.cache_data
def get_spy_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url)[0]
    return [t.replace(".", "-") for t in df["Symbol"].tolist()]

spy_tickers = get_spy_tickers()

# -------------------- SCREENING FUNCTION --------------------
@st.cache_data(show_spinner=True)
def screen_stocks(tickers):
    screened = []
    progress = st.progress(0)
    total = len(tickers)

    for i, ticker in enumerate(tickers):
        progress.progress(i / total)
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
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
                    continue

            if not (PRICE_MIN <= price <= PRICE_MAX and cap_b >= MARKET_CAP_MIN_B):
                continue

            expiration_dates = stock.options
            if not expiration_dates:
                continue

            exp_date = expiration_dates[DAYS_OUT]
            opt_chain = stock.option_chain(exp_date)
            puts = opt_chain.puts
            if puts.empty:
                continue

            # Estimate delta using strike distance as a proxy (for illustrative filtering only)
            puts = puts.assign(delta_estimate=abs((puts["strike"] - price) / price))
            puts = puts[puts["strike"] < price]  # OTM only
            puts = puts.sort_values(by="delta_estimate")
            near_25_delta_puts = puts.head(3)  # closest 3 strikes to 25-delta

            for _, put in near_25_delta_puts.iterrows():
                put_bid = put["bid"]
                put_oi = put["openInterest"]
                put_vol = put["volume"]
                put_strike = put["strike"]
                premium_yield = (put_bid / price) * 100 if price > 0 else 0

                screened.append({
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

        except Exception as e:
            st.write(f"❌ Error for {ticker}: {e}")
            continue

    progress.empty()
    df = pd.DataFrame(screened)
    df = df.sort_values(by="Market Cap ($B)", ascending=False)
    return df

# -------------------- RUN THE SCREEN --------------------
with st.spinner("🔍 Scanning S&P 500 tickers..."):
    df = screen_stocks(spy_tickers)

# -------------------- COLOR-CODE PREMIUM YIELD --------------------
def highlight_premium(val):
    if isinstance(val, (int, float)):
        if val >= 2:
            return 'background-color: #d4edda'
        elif val >= 1:
            return 'background-color: #fff3cd'
        else:
            return 'background-color: #f8d7da'
    return ''

# -------------------- DISPLAY AND SELECT FROM AGGRID --------------------
st.success(f"✅ Showing Top {len(df)} stocks matching Wheel Strategy filters (excluding earnings in 7–14 days).")
gb = GridOptionsBuilder.from_dataframe(df)
gb.configure_selection('single')
grid_options = gb.build()
AgGrid(
    df,
    gridOptions=grid_options,
    height=400,
    width='100%',
    update_mode=GridUpdateMode.SELECTION_CHANGED,
    fit_columns_on_grid_load=True
)

st.download_button("📥 Download CSV", df.to_csv(index=False), "spy_wheel_candidates.csv", "text/csv")

# -------------------- WHEEL STRATEGY RULES --------------------
st.markdown("""
---
### 📘 Wheel Strategy Guidelines
**When initiating the Wheel Strategy with a Cash-Secured Put (CSP):**

- ✅ **Strike Selection:**
  - Choose a strike price **below the current stock price** (Out of the Money)
  - Target a delta between **0.16 and 0.30** (use 25 as a sweet spot)

- ⏳ **DTE (Days to Expiration):**
  - Preferred: **30 to 45 DTE**
  - Manage or roll around 21 DTE

- 💵 **Premium Consideration:**
  - Target a premium yield of at least **1% of the strike price**
  - Higher IV = better premiums (but may mean more volatility)

- ❗ **Earnings Risk:**
  - Avoid selling CSPs with earnings reports due within **7–14 days**

- 📈 **Post-assignment:**
  - If assigned, sell a Covered Call 1–2 strikes above your cost basis
  - Continue to generate premium until called away
---
""")
