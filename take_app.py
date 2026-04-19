import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np

# --- 1. 画面設定 ---
st.set_page_config(page_title="Take Strategy Room V5.3", layout="wide")
st.markdown("<style>.block-container {padding: 1rem;}</style>", unsafe_allow_html=True)

# --- 2. 資産構成（QQQを監視に追加） ---
ASSETS = {
    "保有": {
        "VPU": "AI電力(主力)", "PAVE": "インフラ(主力)", "VOO": "S&P500", 
        "SMH": "半導体", "NDAQ": "NASDAQ", "9984.T": "SBG", 
        "7201.T": "日産", "4901.T": "富士フイルム", "1489.T": "日経高配当50"
    },
    "監視": {
        "QQQ": "NASDAQ100", "GLD": "金(有事の備え)", "XLE": "エネルギー(保険)", 
        "EPI": "インド株(損切済)", "VWO": "新興国株", "VNM": "ベトナム", 
        "CIBR": "セキュリティ", "XLV": "ヘルスケア"
    }
}

# --- 3. データ取得エンジン ---
@st.cache_data(ttl=3600)
def fetch_v53():
    res = []
    all_items = {**ASSETS["保有"], **ASSETS["監視"]}
    for t, n in all_items.items():
        try:
            s = yf.Ticker(t)
            info = s.info
            hist_5y = s.history(period="5y")
            
            ret_2025, ret_2024, ret_2023 = np.nan, np.nan, np.nan
            if not hist_5y.empty:
                yearly_data = hist_5y['Close'].resample('YE').last()
                annual_returns = yearly_data.pct_change() * 100
                for idx in annual_returns.index:
                    if idx.year == 2025: ret_2025 = annual_returns[idx]
                    elif idx.year == 2024: ret_2024 = annual_returns[idx]
                    elif idx.year == 2023: ret_2023 = annual_returns[idx]

            hist_3m = s.history(period="3mo")
            if not hist_3m.empty and len(hist_3m) > 14:
                delta = hist_3m['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs.iloc[-1]))
            else:
                rsi = np.nan
            
            current = info.get("regularMarketPrice") or info.get("currentPrice") or (hist_3m['Close'].iloc[-1] if not hist_3m.empty else 0)
            high_52 = info.get("fiftyTwoWeekHigh") or current or 1
            
            is_commodity = t in ["GLD", "IAU", "GSG"]
            pe = np.nan if is_commodity else (info.get("forwardPE") or info.get("trailingPE"))
            pb = np.nan if is_commodity else info.get("priceToBook")
            
            res.append({
                "区分": "保有" if t in ASSETS["保有"] else "監視",
                "銘柄名": n, "Ticker": t,
                "株価": current,
                "23年(%)": ret_2023, "24年(%)": ret_2024, "25年(%)": ret_2025,
                "予想PER": pe, "PBR": pb, "ボラ(Beta)": info.get("beta"),
                "配当(%)": (info.get("dividendYield") or 0) * 100,
                "加熱(RSI)": rsi,
                "52週高値比": (current / high_52 - 1) * 100 if current and high_52 else np.nan
            })
        except: continue
    return pd.DataFrame(res)

# --- 4. メイン表示 ---
st.write(f"### 🧠 戦略司令室 V5.3：QQQ追加・リスク管理モデル")

if st.button("🔄 最新データ更新（暴落・過熱＝赤信号）"):
    st.session_state.v53_df = fetch_v53()

if 'v53_df' in st.session_state:
    df = st.session_state.v53_df
    
    def style_v53(row):
        styles = [''] * len(row)
        for col in ['23年(%)', '24年(%)', '25年(%)']:
            idx = row.index.get_loc(col)
            if row[col] >= 10: styles[idx] = 'background-color: #ccffcc; color: black;'
            elif row[col] < 0: styles[idx] = 'background-color: #ffcccc; color: black;'
        rsi_idx = row.index.get_loc('加熱(RSI)')
        if row['加熱(RSI)'] >= 55: styles[rsi_idx] = 'background-color: #ffcccc; color: black;'
        elif row['加熱(RSI)'] <= 45: styles[rsi_idx] = 'background-color: #e6f3ff; color: black;'
        high_idx = row.index.get_loc('52週高値比')
        if row['52週高値比'] <= -10: styles[high_idx] = 'background-color: #ffcccc; color: black;'
        elif row['52週高値比'] >= -3: styles[high_idx] = 'background-color: #e6f3ff; color: black;'
        return styles

    styled_df = df.style.format({
        "株価": "{:.2f}", "23年(%)": "{:.1f}%", "24年(%)": "{:.1f}%", "25年(%)": "{:.1f}%",
        "予想PER": "{:.1f}", "PBR": "{:.2f}", "ボラ(Beta)": "{:.2f}", 
        "配当(%)": "{:.2f}%", "加熱(RSI)": "{:.1f}", "52週高値比": "{:.1f}%"
    }, na_rep="-").apply(style_v53, axis=1)

    st.dataframe(styled_df, height=600, use_container_width=True)

    # --- 5. AIへの報告用窓 ---
    st.markdown("---")
    st.subheader("📝 AIへの報告用データ（コピーして貼り付けてください）")
    report_text = df.to_string(index=False)
    st.text_area("以下の内容をコピーしてGeminiに送信してください:", value=report_text, height=200)

# --- 6. サイドバー ---
st.sidebar.write("💰 **1億円シミュレーター**")
current_total = st.sidebar.number_input("現在の総資産(万円)", value=2500)
yield_rate = st.sidebar.slider("想定年利(%)", 3.0, 15.0, 7.0)
if yield_rate > 0 and current_total > 0:
    years = np.log(10000 / current_total) / np.log(1 + yield_rate/100)
    st.sidebar.success(f"到達まであと **{years:.1f} 年**")

st.sidebar.markdown("---")
st.sidebar.write("🚀 **呪文（実行コマンド）**")
st.sidebar.code(f'python3 -m streamlit run "/Users/juntakeda/Documents/JT/02_Personal/★01プログラム/take_app.py"')