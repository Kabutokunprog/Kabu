import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime

# --- 1. 画面設定 ---
st.set_page_config(page_title="株価加熱度他 V5.9", layout="wide")
st.markdown("<style>.block-container {padding-top: 2.5rem;}</style>", unsafe_allow_html=True)

# 一行下げるためのマージン
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

# --- 3. サイドバー：カスタム銘柄入力 ---
st.sidebar.header("🛠 銘柄操作")
custom_input = st.sidebar.text_input("追加Ticker (例: AAPL, TSLA)", "")
user_tickers = [t.strip().upper() for t in custom_input.split(",") if t.strip()]

# --- 4. データ取得＆スコアリングエンジン ---
@st.cache_data(ttl=3600)
def fetch_v59(additional_tickers):
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
                if not matching_dates.empty:
                    ret[y] = yearly.loc[matching_dates[0]]

            current = info.get("regularMarketPrice") or info.get("currentPrice") or hist_5y['Close'].iloc[-1]
            ma50 = hist_5y['Close'].rolling(window=50).mean().iloc[-1]
            dev_ma50 = ((current - ma50) / ma50) * 100
            three_months_ago = hist_5y['Close'].iloc[-63] if len(hist_5y) > 63 else hist_5y['Close'].iloc[0]
            ret_3m = ((current - three_months_ago) / three_months_ago) * 100

            # RSI
            delta = hist_5y['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + (gain / loss).iloc[-1]))

            # 52週位置
            h52 = hist_5y['Close'].tail(252).max()
            l52 = hist_5y['Close'].tail(252).min()
            pos_52w = ((current - l52) / (h52 - l52)) * 100 if h52 != l52 else 0
            
            per = info.get("forwardPE") or info.get("trailingPE") or np.nan

            # スコアロジック
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
st.write(f"### 🧠 戦略司令室 V5.9：完全版（実績・指標・解説ガイド付き）")

if st.button("🔄 データを最新に更新する"):
    st.session_state.v59_df = fetch_v59(user_tickers)

if 'v59_df' in st.session_state:
    df = st.session_state.v59_df
    
    def style_v59(row):
        styles = [''] * len(row)
        score_idx = row.index.get_loc('魅力度')
        if row['魅力度'] >= 70: styles[score_idx] = 'background-color: #ccffcc; font-weight: bold; color: black;'
        elif row['魅力度'] <= 40: styles[score_idx] = 'background-color: #ffcccc; color: black;'
        
        rsi_idx = row.index.get_loc('加熱(RSI)')
        if row['加熱(RSI)'] >= 75: styles[rsi_idx] = 'color: red; font-weight: bold;'
        
        for col in ['23年(%)', '24年(%)', '25年(%)']:
            idx = row.index.get_loc(col)
            if row[col] >= 15: styles[idx] = 'color: #008000;'
            elif row[col] < 0: styles[idx] = 'color: #ff0000;'
        return styles

    st.dataframe(df.style.format({
        "魅力度": "{:.0f}点", "23年(%)": "{:.1f}%", "24年(%)": "{:.1f}%", "25年(%)": "{:.1f}%",
        "加熱(RSI)": "{:.1f}", "50日乖離": "{:.1f}%", "3ヶ月騰落": "{:.1f}%",
        "52週位置": "{:.1f}%", "予想PER": "{:.1f}", "株価": "{:.2f}"
    }, na_rep="-").apply(style_v59, axis=1), height=550, use_container_width=True)

    # --- 6. 【復活】用語解説ガイド ---
    st.markdown("---")
    st.subheader("📖 各指標の読み解きガイド（買い時・守り時の判断基準）")
    
    col1, col2 = st.columns(2)
    with col1:
        st.write("**【加熱感・モメンタム】**")
        st.write("- **加熱(RSI)**: 14日間の買われすぎ指標。**75超は天井警戒、30付近は売られすぎ（底値圏）。**")
        st.write("- **50日乖離**: 中期平均とのズレ。**+15%超はバブルの可能性。マイナス圏なら絶好の押し目。**")
        st.write("- **3ヶ月騰落**: 直近の勢い。プラスなら上昇気流、大幅マイナスはトレンド崩壊。")
    with col2:
        st.write("**【位置・割安度】**")
        st.write("- **52週位置**: 1年間の安値を0、高値を100とした位置。**100に近いほど最強の状態。**")
        st.write("- **予想PER**: 利益から見た割安さ。**15倍以下なら割安、35倍超はかなり期待（または割高）。**")
        st.write("- **魅力度**: 上記を独自計算。**70点以上なら、冷静に買いを検討できる優良なタイミング。**")

    # --- 7. Gemini相談窓口 ---
    st.markdown("---")
    st.subheader("🤖 Geminiへの相談用データ")
    st.text_area("コピーしてGeminiに送信してください：", value=df.to_string(index=False), height=150)