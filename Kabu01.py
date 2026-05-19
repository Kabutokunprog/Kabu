from flask import Flask, render_template_string, request
import pandas as pd
import yfinance as yf
import numpy as np

app = Flask(__name__)

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

def fetch_data(additional_tickers):
    res = []
    combined_assets = {**FIXED_ASSETS["保有"], **FIXED_ASSETS["監視"]}
    
    for t in additional_tickers:
        t = t.upper()
        if t not in combined_assets: 
            combined_assets[t] = f"追加({t})"

    for t, n in combined_assets.items():
        try:
            s = yf.Ticker(t)
            info = s.info
            hist_5y = s.history(period="5y")
            if len(hist_5y) < 200: continue # 200日線計算のため最低データ量を確認

            # 実績リターン
            ret = {2025: np.nan, 2024: np.nan, 2023: np.nan}
            yearly = hist_5y['Close'].resample('YE').last().pct_change() * 100
            for y in ret.keys():
                target_date = f"{y}-12-31"
                matching_dates = yearly.index[yearly.index.strftime('%Y-%m-%d') == target_date]
                if not matching_dates.empty: ret[y] = yearly.loc[matching_dates[0]]

            current = info.get("regularMarketPrice") or info.get("currentPrice") or hist_5y['Close'].iloc[-1]
            
            # 乖離率・騰落
            ma50 = hist_5y['Close'].rolling(window=50).mean().iloc[-1]
            dev_ma50 = ((current - ma50) / ma50) * 100
            ma200 = hist_5y['Close'].rolling(window=200).mean().iloc[-1]
            dev_ma200 = ((current - ma200) / ma200) * 100
            three_months_ago = hist_5y['Close'].iloc[-63] if len(hist_5y) > 63 else hist_5y['Close'].iloc[0]
            ret_3m = ((current - three_months_ago) / three_months_ago) * 100

            # RSI
            delta = hist_5y['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + (gain / loss).iloc[-1]))

            # 52週位置・PER
            h52 = hist_5y['Close'].tail(252).max()
            l52 = hist_5y['Close'].tail(252).min()
            pos_52w = ((current - l52) / (h52 - l52)) * 100 if h52 != l52 else 0
            per = info.get("forwardPE") or info.get("trailingPE") or np.nan

            # 出来高急増指標 (直近5日平均 ÷ 過去3ヶ月(63日)平均)
            vol_5d = hist_5y['Volume'].tail(5).mean()
            vol_60d = hist_5y['Volume'].tail(63).mean()
            vol_ratio = (vol_5d / vol_60d) if vol_60d > 0 else 1.0

            # 魅力度スコア計算ロジック
            score = 50
            if rsi > 75: score -= 20
            elif 40 <= rsi <= 55: score += 15
            if dev_ma50 > 15: score -= 15
            elif -5 <= dev_ma50 <= 2: score += 10
            if 0 < per < 18: score += 15
            elif per > 35: score -= 10
            
            # 200日線考慮 (中長期下落トレンドの減点)
            if dev_ma200 < 0: score -= 15 

            res.append({
                "区分": "追加" if t in additional_tickers else ("保有" if t in FIXED_ASSETS["保有"] else "監視"),
                "銘柄名": n, "Ticker": t, "魅力度": int(max(0, min(100, score))),
                "23年": f"{ret[2023]:.1f}%" if not np.isnan(ret[2023]) else "-",
                "24年": f"{ret[2024]:.1f}%" if not np.isnan(ret[2024]) else "-",
                "25年": f"{ret[2025]:.1f}%" if not np.isnan(ret[2025]) else "-",
                "RSI": f"{rsi:.0f}", "50日乖離": f"{dev_ma50:.1f}%", "200日乖離": f"{dev_ma200:.1f}%", 
                "3ヶ月": f"{ret_3m:.1f}%", "52週位置": f"{pos_52w:.0f}%", 
                "PER": f"{per:.1f}" if not np.isnan(per) else "-",
                "出来高比": f"{vol_ratio:.1f}倍", "株価": f"{current:.1f}"
            })
        except: continue
    return res

@app.route('/')
def index():
    custom_tickers_str = request.args.get('tickers', '')
    additional_tickers = [t.strip().upper() for t in custom_tickers_str.split(',') if t.strip()]
    data = fetch_data(additional_tickers)
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>戦略司令室 V6.7</title>
        <style>
            body { font-family: -apple-system, sans-serif; margin: 0; padding: 10px; background: #f9f9f9; color: #333; }
            h3 { margin: 10px 0; font-size: 16px; }
            .control-panel { background: #fff; padding: 10px; margin-bottom: 10px; border-radius: 5px; border: 1px solid #ccc; font-size: 14px;}
            input[type="text"] { padding: 5px; width: 150px; border: 1px solid #ccc; border-radius: 3px; }
            button { padding: 5px 10px; background: #007bff; color: white; border: none; border-radius: 3px; cursor: pointer; }
            .table-container { overflow-x: auto; max-width: 100%; border: 1px solid #ccc; background: #fff; margin-bottom: 20px; }
            table { border-collapse: collapse; width: 100%; font-size: 11px; white-space: nowrap; }
            th, td { padding: 6px 4px; text-align: center; border-right: 1px solid #eee; border-bottom: 1px solid #eee; }
            th { background: #f2f2f2; font-weight: bold; position: sticky; top: 0; z-index: 2; }
            .fixed-name { position: sticky; left: 0; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); text-align: left; font-weight: bold; }
            .fixed-ticker { position: sticky; left: 75px; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); }
            th.fixed-name, th.fixed-ticker { z-index: 3; background: #f2f2f2; }
            .high-score { background-color: #ccffcc !important; font-weight: bold; }
            .low-score { background-color: #ffcccc !important; }
            .high-rsi { color: red; font-weight: bold; }
            .high-vol { color: #d9534f; font-weight: bold; }
            .docs { background: #fff; padding: 15px; border-radius: 5px; border: 1px solid #ccc; font-size: 12px; line-height: 1.5; }
            .docs h4 { margin-top: 0; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        </style>
    </head>
    <body>
        <h3>🧠 戦略司令室 V6.7：200日線＆出来高強化</h3>
        
        <div class="control-panel">
            <form method="GET" action="/">
                <label>➕ 関心銘柄の追加 (カンマ区切り): </label>
                <input type="text" name="tickers" value="{{ custom_tickers_str }}" placeholder="例: MSFT, TSLA">
                <button type="submit">更新</button>
            </form>
        </div>

        <div class="table-container">
            <table>
                <tr>
                    <th>区分</th><th class="fixed-name">銘柄名</th><th class="fixed-ticker">Ticker</th>
                    <th>魅力度</th><th>23年</th><th>24年</th><th>25年</th>
                    <th>RSI</th><th>50日乖離</th><th>200日乖離</th><th>3ヶ月</th><th>52週</th><th>PER</th><th>出来高比</th><th>株価</th>
                </tr>
                {% for r in data %}
                <tr>
                    <td>{{ r['区分'] }}</td><td class="fixed-name">{{ r['銘柄名'] }}</td><td class="fixed-ticker">{{ r['Ticker'] }}</td>
                    <td class="{% if r['魅力度'] >= 70 %}high-score{% elif r['魅力度'] <= 40 %}low-score{% endif %}">{{ r['魅力度'] }}点</td>
                    <td>{{ r['23年'] }}</td><td>{{ r['24年'] }}</td><td>{{ r['25年'] }}</td>
                    <td class="{% if r['RSI']|float >= 75 %}high-rsi{% endif %}">{{ r['RSI'] }}</td>
                    <td>{{ r['50日乖離'] }}</td><td>{{ r['200日乖離'] }}</td><td>{{ r['3ヶ月'] }}</td><td>{{ r['52週位置'] }}</td>
                    <td>{{ r['PER'] }}</td>
                    <td class="{% if r['出来高比']|replace('倍','')|float >= 1.5 %}high-vol{% endif %}">{{ r['出来高比'] }}</td>
                    <td>{{ r['株価'] }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>

        <div class="docs">
            <h4>📖 指標の読み解きガイド</h4>
            <ul>
                <li><b>加熱(RSI):</b> 買われすぎ・売られすぎの指標。75超は天井警戒、30付近は底値圏の目安。</li>
                <li><b>50日乖離:</b> 短期的な過熱感。+15%超は短期バブル警戒、マイナス圏は押し目。</li>
                <li><b>200日乖離:</b> 中長期的なトレンド。マイナス圏は「長期下落トレンド（落ちるナイフ）」の警戒サイン。</li>
                <li><b>出来高比:</b> 直近5日間の出来高が、過去3ヶ月平均の何倍かを示す。1.5倍以上は機関投資家などの大きな資金流入（または流出）の初動の可能性大。</li>
                <li><b>52週位置:</b> 過去1年間の最安値0%、最高値100%とした現在地。</li>
            </ul>

            <h4>🧮 魅力度スコアの計算ロジック（満点100点）</h4>
            <p>基準点50点からスタートし、以下の条件で加減点。</p>
            <ul>
                <li><b>RSI:</b> 40〜55（適温）なら <b>+15点</b> / 75超（過熱）なら <b>-20点</b></li>
                <li><b>50日乖離:</b> -5%〜+2%（良い押し目）なら <b>+10点</b> / +15%超（急騰しすぎ）なら <b>-15点</b></li>
                <li><b>200日乖離:</b> 0%未満（中長期トレンド割れ）なら <b>-15点</b></li>
                <li><b>予想PER:</b> 18倍未満（割安）なら <b>+15点</b> / 35倍超（割高）なら <b>-10点</b></li>
            </ul>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, data=data, custom_tickers_str=custom_tickers_str)

if __name__ == '__main__':
    app.run(debug=True)
