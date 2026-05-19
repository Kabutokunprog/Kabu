import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime

# --- 1. 画面設定 ---
st.set_page_config(page_title="株価加熱度他 V6.0", layout="wide")
st.markdown("<style>.block-container {padding-top: 1.5rem; padding-left: 1rem; padding-right: 1rem;}</style>", unsafe_allow_html=True)
st.write("") 

# --- 2. 固定資産リスト ---
FIXED_ASSETS = {
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

# --- 3. サイドバー ---
st.sidebar.header("🛠 銘柄操作")
custom_input = st.sidebar.text_input("追加Ticker", "")
user_tickers = [t.strip().upper() for t in custom_input.split(",") if t.strip()]

# --- 4. データ取得＆スコアリング ---
@st.cache_data(ttl=3600)
def fetch_v60(additional_tickers):
    res = []
    combined_assets = {**FIXED_ASSETS["保有"], **FIXED_ASSETS["監視"]}
    for t in additional_tickers:
        if t not in combined_assets: combined_assets[t] = f"追加({t})"

    for t, n in combined_assets.items():
        try:
            s = yf.Ticker(t)
            info = s.info
            hist_5y = s.history(period="5y")
            if hist_5y.empty: continue

            # 実績リターン(23-25)
            ret = {2025: np.nan, 2024: np.nan, 2023: np.nan}
            yearly = hist_5y['Close'].resample('YE').last().pct_change() * 100
            for y in ret.keys():
                target_date = f"{y}-12-31"
                matching_dates = yearly.index[yearly.index.strftime('%Y-%m-%d') == target_date]
                if not matching_dates.empty: ret[y] = yearly.loc[matching_dates[0]]

            current = info.get("regularMarketPrice") or info.get("currentPrice") or hist_5y['Close'].iloc[-1]
            ma50 = hist_5y['Close'].rolling(window=50).mean().iloc[-1]
            dev_ma50 = ((current - ma50) / ma50) * 100
            three_months_ago = hist_5y['Close'].iloc[-63] if len(hist_5y) > 63 else hist_5y['Close'].iloc[0]
            ret_3m = ((current - three_months_ago) / three_months_ago) * 100

            delta = hist_5y['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + (gain / loss).iloc[-1]))

            h52 = hist_5y['Close'].tail(252).max()
            l52 = hist_5y['Close'].tail(252).min()
            pos_52w = ((current - l52) / (h52 - l52)) * 100 if h52 != l52 else 0
            per = info.get("forwardPE") or info.get("trailingPE") or np.nan

            score = 50
            if rsi > 75: score -= 20
            elif 40 <= rsi <= 55: score += 15
            if dev_ma50 > 15: score -= 15
            elif -5 <= dev_ma50 <= 2: score += 10
            if 0 < per < 18: score += 15
            elif per > 35: score -= 10

            res.append({
                "区分": "追加" if t in additional_tickers else ("保有" if t in FIXED_ASSETS["保有"] else "監視"),
                "銘柄名": n, "Ticker": t, "魅力度": max(0, min(100, score)),
                "23年(%)": ret[2023], "24年(%)": ret[2024], "25年(%)": ret[2025],
                "加熱(RSI)": rsi, "50日乖離": dev_ma50, "3ヶ月騰落": ret_3m,
                "52週位置": pos_52w, "予想PER": per, "株価": current
            })
        except: continue
    return pd.DataFrame(res)

# --- 5. メイン表示 ---
st.write(f"### 🧠 戦略司令室 V6.0：究極俯瞰モデル（列固定＆スリム化）")

if st.button("🔄 最新データ更新"):
    st.session_state.v60_df = fetch_v60(user_tickers)

if 'v60_df' in st.session_state:
    df = st.session_state.v60_df
    
    def style_v60(row):
        styles = [''] * len(row)
        score_idx = row.index.get_loc('魅力度')
        if row['魅力度'] >= 70: styles[score_idx] = 'background-color: #ccffcc; font-weight: bold; color: black;'
        elif row['魅力度'] <= 40: styles[score_idx] = 'background-color: #ffcccc; color: black;'
        
        rsi_idx = row.index.get_loc('加熱(RSI)')
        if row['加熱(RSI)'] >= 75: styles[rsi_idx] = 'color: red; font-weight: bold;'
        return styles

    # データフレーム表示（列固定と幅の調整）
    st.dataframe(
        df.style.format({
            "魅力度": "{:.0f}点", "23年(%)": "{:.1f}%", "24年(%)": "{:.1f}%", "25年(%)": "{:.1f}%",
            "加熱(RSI)": "{:.1f}", "50日乖離": "{:.1f}%", "3ヶ月騰落": "{:.1f}%",
            "52週位置": "{:.1f}%", "予想PER": "{:.1f}", "株価": "{:.1f}"
        }, na_rep="-").apply(style_v60, axis=1),
        column_config={
            "区分": st.column_config.Column(width="small"),
            "銘柄名": st.column_config.Column(width="medium", pinned=True),
            "Ticker": st.column_config.Column(width="small", pinned=True),
            "魅力度": st.column_config.Column(width="small"),
            "23年(%)": st.column_config.Column(width="small"),
            "24年(%)": st.column_config.Column(width="small"),
            "25年(%)": st.column_config.Column(width="small"),
            "加熱(RSI)": st.column_config.Column(width="small"),
            "50日乖離": st.column_config.Column(width="small"),
            "3ヶ月騰落": st.column_config.Column(width="small"),
            "52週位置": st.column_config.Column(width="small"),
            "予想PER": st.column_config.Column(width="small"),
            "株価": st.column_config.Column(width="small"),
        },
        height=550,
        use_container_width=True,
        hide_index=True
    )

    # 用語解説ガイド
    st.markdown("---")
    st.info("**固定表示**: 銘柄名とTickerを左端にピン留めしています。横スクロールしても迷子になりません。")
    
    with st.expander("📖 指標の読み解きガイドを表示"):
        col1, col2 = st.columns(2)
        with col1:
            st.write("**【加熱感】**")
            st.write("- **加熱(RSI)**: 75超は天井警戒、30付近は底値圏。")
            st.write("- **50日乖離**: +15%超はバブル警戒、マイナス圏は押し目。")
        with col2:
            st.write("**【位置・割安度】**")
            st.write("- **52週位置**: 100%に近いほど最高値更新中。")
            st.write("- **予想PER**: 15倍以下は割安、35倍超は過熱気味。")

    st.subheader("🤖 Geminiへの相談用データ")
    st.text_area("コピー＆ペースト用：", value=df.to_string(index=False), height=100)