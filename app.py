from flask import Flask, render_template_string
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

def fetch_data():
    res = []
    combined_assets = {**FIXED_ASSETS["保有"], **FIXED_ASSETS["監視"]}
    for t, n in combined_assets.items():
        try:
            s = yf.Ticker(t)
            info = s.info
            hist_5y = s.history(period="5y")
            if hist_5y.empty: continue

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
                "区分": "保有" if t in FIXED_ASSETS["保有"] else "監視",
                "銘柄名": n, "Ticker": t, "魅力度": int(max(0, min(100, score))),
                "23年": f"{ret[2023]:.1f}%" if not np.isnan(ret[2023]) else "-",
                "24年": f"{ret[2024]:.1f}%" if not np.isnan(ret[2024]) else "-",
                "25年": f"{ret[2025]:.1f}%" if not np.isnan(ret[2025]) else "-",
                "RSI": f"{rsi:.1f}", "50日乖離": f"{dev_ma50:.1f}%", "3ヶ月騰落": f"{ret_3m:.1f}%",
                "52週位置": f"{pos_52w:.1f}%", "PER": f"{per:.1f}" if not np.isnan(per) else "-",
                "株価": f"{current:.1f}"
            })
        except: continue
    return res

@app.route('/')
def index():
    data = fetch_data()
    
    # 銘柄名とTickerを固定し、列幅を極限まで絞るHTML/CSS
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>戦略司令室 V6.5</title>
        <style>
            body { font-family: -apple-system, sans-serif; margin: 0; padding: 10px; background: #f9f9f9; color: #333; }
            h3 { margin: 10px 0; font-size: 16px; }
            .table-container { overflow-x: auto; max-width: 100%; border: 1px solid #ccc; background: #fff; }
            table { border-collapse: collapse; width: 100%; font-size: 11px; white-space: nowrap; }
            th, td { padding: 6px 4px; text-align: center; border-right: 1px solid #eee; border-bottom: 1px solid #eee; }
            th { background: #f2f2f2; font-weight: bold; position: sticky; top: 0; z-index: 2; }
            
            /* 銘柄名とTickerを左側にピン留め固定(スマホ対応) */
            .fixed-name { position: sticky; left: 0; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); text-align: left; font-weight: bold; }
            .fixed-ticker { position: sticky; left: 75px; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); }
            th.fixed-name, th.fixed-ticker { z-index: 3; background: #f2f2f2; }
            
            /* 魅力度の色付け */
            .high-score { background-color: #ccffcc !important; font-weight: bold; }
            .low-score { background-color: #ffcccc !important; }
            .high-rsi { color: red; font-weight: bold; }
        </style>
    </head>
    <body>
        <h3>🧠 戦略司令室 V6.5：不眠サーバーモデル</h3>
        <div class="table-container">
            <table>
                <tr>
                    <th>区分</th>
                    <th class="fixed-name">銘柄名</th>
                    <th class="fixed-ticker">Ticker</th>
                    <th>魅力度</th>
                    <th>23年</th>
                    <th>24年</th>
                    <th>25年</th>
                    <th>RSI</th>
                    <th>50日乖離</th>
                    <th>3ヶ月</th>
                    <th>52週</th>
                    <th>PER</th>
                    <th>株価</th>
                </tr>
                {% for r in data %}
                <tr>
                    <td>{{ r['区分'] }}</td>
                    <td class="fixed-name">{{ r['銘柄名'] }}</td>
                    <td class="fixed-ticker">{{ r['Ticker'] }}</td>
                    <td class="{% if r['魅力度'] >= 70 %}high-score{% elif r['魅力度'] <= 40 %}low-score{% endif %}">{{ r['魅力度'] }}点</td>
                    <td>{{ r['23年'] }}</td>
                    <td>{{ r['24年'] }}</td>
                    <td>{{ r['25年'] }}</td>
                    <td class="{% if r['RSI']|float >= 75 %}high-rsi{% endif %}">{{ r['RSI'] }}</td>
                    <td>{{ r['50日乖離'] }}</td>
                    <td>{{ r['3ヶ月'] }}</td>
                    <td>{{ r['52週'] }}</td>
                    <td>{{ r['PER'] }}</td>
                    <td>{{ r['株価'] }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, data=data)

if __name__ == '__main__':
    app.run(debug=True)
    