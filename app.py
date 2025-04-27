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

# --- LOGIN SYSTEM ---
names = ['Josh Ordonez']
usernames = ['josh']
passwords = ['1234']

authenticator = stauth.Authenticate(
    names, usernames, passwords,
    'cookie_name', 'secret_key', cookie_expiry_days=30
)

name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
    st.success(f'Welcome {name}!')
elif authentication_status is False:
    st.error('Username/password is incorrect')
    st.stop()
elif authentication_status is None:
    st.warning('Please enter your username and password')
    st.stop()

# --- Twelve Data API Key ---
TWELVE_API_KEY = "your_api_key_here"  # ← Replace with your Twelve Data key

# --- Get Earnings Date from Twelve Data ---
def get_earnings_date(symbol):
    try:
        url = f"https://api.twelvedata.com/earnings_calendar?symbol={symbol}&apikey={TWELVE_API_KEY}"
        response = requests.get(url)
        data = response.json()
        if "earnings" in data and len(data["earnings"]) > 0:
            return data["earnings"][0]["date"]
    except Exception as e:
        print(f"[EARNINGS ERROR] {symbol}: {e}")
    return None

# --- App Setup ---
st.set_page_config(
    page_title="Josue's SPY Wheel Screener",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Logo ---
logo = Image.open("wagon.png")
buffered = BytesIO()
logo.save(buffered, format="PNG")
logo_b64 = base64.b64encode(buffered.getvalue()).decode()
st.markdown(
    f"<div style='text-align: center;'><img src='data:image/png;base64,{logo_b64}' width='150'></div>",
    unsafe_allow_html=True
)

st.markdown("<h2 style='text-align: center;'>SPY Wheel Strategy Screener</h2>", unsafe_allow_html=True)
st.markdown("<h4 style='text-align: center;'>by Josue Ordonez</h4>", unsafe_allow_html=True)

# --- Filters ---
PRICE_MIN = 5
PRICE_MAX = 50
MARKET_CAP_MIN_B = 1
DAYS_OUT = 0
FILTER_EARNINGS = True
MIN_VOL = 10
MIN_OI = 100

# --- Load S&P 500 Tickers ---
@st.cache_data
def get_spy_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url)[0]
    return [t.replace(".", "-") for t in df["Symbol"].tolist()]

spy_tickers = get_spy_tickers()

# --- Screener Logic ---
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

            earnings_date = get_earnings_date(ticker)
            if FILTER_EARNINGS and earnings_date:
                today = datetime.date.today()
                days_to_earnings = (pd.to_datetime(earnings_date).date() - today).days
                if 0 <= days_to_earnings <= 14:
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

                if put_vol < MIN_VOL or put_oi < MIN_OI:
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
loading_block.info("🔍 Scanning S&P 500 tickers… Please wait.")
df = screen_stocks(spy_tickers)
loading_block.empty()

# --- Display Results ---
if df.empty:
    st.warning("⚠️ No tickers matched the filter criteria.")
else:
    st.success(f"✅ {len(df)} Wheel Strategy candidates found.")

    df_display = df.drop(columns=["IV", "Put Bid", "Premium Yield (%)", "Earnings Date"], errors='ignore')  # optional
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

### 📊 WHEEL STRATEGY: ACCOUNT SIZE GUIDELINES

#### 💵 $100 Account (Micro Starter Account)
- Play: Use fractional shares or penny stocks (under $5).
- Premium Goal: $1–$2 per trade.
- Profit Target: 50%–70%.
- Stop Loss: 2x–3x premium collected.
- Example Stocks: **SNDL, GPRO, NU**

#### 💵 $1,000 Account (Small but Serious)
- Play: Stocks $5–$15.
- Premium Goal: $10–$20.
- Profit Target: 50%–70%.
- Stop Loss: 2x premium collected.
- Example Stocks: **SOFI, Ford, CHPT, PLTR**

#### 💵 $5,000 Account (Starter Wheel Account)
- Play: Stocks $10–$50.
- Premium Goal: $50+.
- Profit Target: 50%–60%.
- Stop Loss: 2x premium collected.
- Example Stocks: **KO, PBR, MRO, CROX, WBD**

#### 💵 $10,000 Account (Scaling Up)
- Play: Stocks $20–$100.
- Premium Goal: $75–$150.
- Profit Target: 50%–60%.
- Stop Loss: 2x–2.5x premium collected.
- Example Stocks: **AAPL, CSCO, PFE, KO, XLF**

---

### ⚙️ Medium Risk Management Rules
- Never risk more than 5% of your account on any one trade.
- Close trades early at 50%–60% profit.
- Always avoid stocks with earnings in the next 14 days.
- Focus on stacking **consistent small wins**.

---
""")
