import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import base64
import requests
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit_authenticator as stauth

# --- App Setup ---
st.set_page_config(
    page_title="Josue's SPY Wheel Screener",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Full-Screen Modal Password Protection ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("""
        <style>
            .main, footer, header {visibility: hidden;}
            div.block-container {padding-top: 8rem; text-align: center;}
            .password-box {
                padding: 2rem;
                background-color: #111;
                border-radius: 10px;
                width: 400px;
                margin: auto;
                color: white;
                box-shadow: 0 0 15px rgba(0,0,0,0.4);
            }
            input[type='password'] {
                text-align: center;
                font-size: 1.2rem;
                padding: 0.5rem;
                width: 300px;
                border: 2px solid #ccc;
                border-radius: 5px;
                background-color: #fff;
                color: #000;
            }
        </style>
        <div class='password-box'>
            <h1 style='font-size: 2rem;'>🔒 Welcome to the SPY Wheel Screener</h1>
            <p>Please enter the password below to access the strategy tool.</p>
            <p style='margin: 1rem 0; font-size: 0.95rem;'>
                You'll see a live screener of stocks in the S&P 500 with the best setups for the Wheel Strategy.
                This includes price, market cap, volume, open interest, and put strike suggestions.
            </p>
            <p style='font-size: 0.9rem; margin-top: 1.5rem;'>
                Want access? Send <strong>$25</strong> on Venmo to <strong>@ordonezjosue</strong>.
            </p>
        </div>
    """, unsafe_allow_html=True)

    password = st.text_input("Enter Password", type="password", label_visibility="collapsed", placeholder="Enter password here")
    if password == "wheeling":
        st.session_state.authenticated = True
        st.rerun()
    else:
        st.stop()


# --- Logo ---
logo = Image.open("wagon.png")
buffered = BytesIO()
logo.save(buffered, format="PNG")
logo_b64 = base64.b64encode(buffered.getvalue()).decode()
st.markdown(
    f"<div style='text-align: center;'><img src='data:image/png;base64,{logo_b64}' width='150' style='margin-top: 1rem;'></div>",
    unsafe_allow_html=True
)

st.markdown("""
    <h2 style='text-align: center; margin-top: 0.5rem;'>SPY Wheel Strategy Screener</h2>
    <h4 style='text-align: center; color: gray;'>by Josue Ordonez</h4>
""", unsafe_allow_html=True)

# --- Static Price Range ---
PRICE_MIN = 1
PRICE_MAX = 1000

# --- Timestamp ---
st.caption(f"🕒 Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

DAYS_OUT = 0
FILTER_EARNINGS = True

@st.cache_data
def get_spy_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url)[0]
    return [t.replace(".", "-") for t in df["Symbol"].tolist()]

spy_tickers = get_spy_tickers()

# --- Screener Logic ---
def screen_stocks(tickers, price_min, price_max):
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

            if not (price_min <= price <= price_max):
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
                })
            return result
        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")
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
    if not df.empty:
        df = df.sort_values(by="Market Cap ($B)", ascending=False)
    return df

# --- Run Screener ---
loading_block = st.empty()
loading_block.info("🔍 Scanning all S&P 500 tickers… This could take a minute.")
df = screen_stocks(spy_tickers, PRICE_MIN, PRICE_MAX)
loading_block.empty()

# --- Display Results ---
if df.empty:
    st.warning("⚠️ No tickers matched the filter criteria.")
else:
    st.success(f"✅ {len(df)} Wheel Strategy candidates found.")

    df_display = df.drop(columns=["IV", "Put Bid", "Premium Yield (%)"], errors='ignore')
    df_display = df_display.reset_index(drop=True)
    st.dataframe(df_display, use_container_width=True)

    st.download_button(
        "📥 Download CSV",
        df_display.to_csv(index=False),
        "spy_wheel_candidates.csv",
        "text/csv"
    )

# --- Strategy Notes ---
st.markdown("""
---
### 🛞 Wheel Strategy Guidelines
- **Strike:** 25 delta or lower
- **DTE:** 30–45 days preferred, manage at 21 DTE
- **Premium:** Aim for ≥1% of strike
- **Earnings:** Avoid if earnings in the next 14 days
- **Post-assignment:** Sell Covered Calls 1–2 strikes above cost basis

---
### 📊 Wheel Strategy: Account Size Guidelines

#### 💵 $1,000–$2,000 Account
- Stocks priced under $10–$20
- Example: **SOFI, F, PLTR**

#### 💵 $5,000–$10,000 Account
- Stocks priced up to $100
- Example: **KO, MRO, PBR**

#### 💵 $25,000+ Account
- Full use of larger stocks (AAPL, MSFT)

---
### ⚙️ Medium Risk Management Rules
- Never risk more than 5% of your account per trade.
- Close early at 50% profit.
- Avoid earnings within 14 days.
---
""")
