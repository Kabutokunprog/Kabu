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

# モメンタム（順張り）型として測定するアセットの定義
MOMENTUM_TICKERS = ["SMH", "QQQ", "VOO", "NDAQ", "9984.T"]

def fetch_data(additional_tickers):
    res = []
    combined_assets = {**FIXED_ASSETS["保有"], **FIXED_ASSETS["監視"]}
    
    for t in additional_tickers:
        t = t.upper()
        if t not in combined_assets: 
            combined_assets[t] = f"追加({t})"

    # 元の順番を保持するための通し番号（カウンター）
    serial_no = 1

    for t, n in combined_assets.items():
        try:
            s = yf.Ticker(t)
            info = s.info
            hist_5y = s.history(period="5y")
            if len(hist_5y) < 200: continue

            # 実績リターン
            ret = {2025: np.nan, 2024: np.nan, 2023: np.nan}
            yearly = hist_5y['Close'].resample('YE').last().pct_change() * 100
            for y in ret.keys():
                target_date = f"{y}-12-31"
                matching_dates = yearly.index[yearly.index.strftime('%Y-%m-%d') == target_date]
                if not matching_dates.empty: ret[y] = yearly.loc[matching_dates[0]]

            current = info.get("regularMarketPrice") or info.get("currentPrice") or hist_5y['Close'].iloc[-1]
            
            # 各種テクニカル指標
            ma50 = hist_5y['Close'].rolling(window=50).mean().iloc[-1]
            dev_ma50 = ((current - ma50) / ma50) * 100
            ma200 = hist_5y['Close'].rolling(window=200).mean().iloc[-1]
            dev_ma200 = ((current - ma200) / ma200) * 100
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

            vol_5d = hist_5y['Volume'].tail(5).mean()
            vol_60d = hist_5y['Volume'].tail(63).mean()
            vol_ratio = (vol_5d / vol_60d) if vol_60d > 0 else 1.0

            # --- 🧠 2系統マルチ定規アルゴリズム ---
            score = 50
            is_momentum = t in MOMENTUM_TICKERS
            
            if is_momentum:
                # 【1】モメンタム（順張り・成長株）型定規
                # RSI（強い上昇帯を評価、バブルは厳罰）
                if rsi > 85: score -= 30
                elif rsi > 80: score -= 20
                elif 45 <= rsi <= 65: score += 15
                
                # 50日乖離（長期上昇中の「熱さまし・黄金の押し目」を最高評価）
                if dev_ma200 > 0: # 長期トレンドが上向きが大前提
                    if -5 <= dev_ma50 <= 5: score += 25  # 黄金の押し目（大加点）
                    elif 5 < dev_ma50 <= 15: score += 10 # 健全な順張り
                
                # 危険域の線引き
                if dev_ma50 > 15: score -= 15  # 過熱
                if dev_ma50 > 20: score -= 30  # チキンレースバブル（絶対買わない）
                if dev_ma50 < -10: score -= 20 # トレンド崩壊
                
                # 200日線割れ（長期下落トレンド入りは即ペナルティ）
                if dev_ma200 < 0: score -= 20
                
                # 予想PER（低ければ低いほど高加点のグラデーション評価）
                if not np.isnan(per):
                    if per < 20: score += 20
                    elif 20 <= per < 30: score += 10
                    elif 30 <= per < 40: score += 0
                    elif 40 <= per <= 45: score -= 10
                    elif per > 45: score -= 30 # 45倍超はバブル足切り
            else:
                # 【2】バリュー・ディフェンシブ（逆張り）型定規
                if 40 <= rsi <= 55: score += 15
                if -5 <= dev_ma50 <= 2: score += 10
                if dev_ma200 < 0: score -= 15
                
                # 新興国株などの「底なし沼（落ちるナイフ）」判定
                if dev_ma200 < 0 and rsi < 40:
                    score -= 20  # ダラダラ下落はスコアを地の底へ落とす
                
                if 0 < per < 18: score += 15
                elif per > 35: score -= 10

            res.append({
                "No": serial_no,
                "区分": "追加" if t in additional_tickers else ("保有" if t in FIXED_ASSETS["保有"] else "監視"),
                "定規": "モーメンタム" if is_momentum else "バリュー",
                "銘柄名": n, "Ticker": t, "魅力度": int(max(0, min(100, score))),
                "23年": f"{ret[2023]:.1f}%" if not np.isnan(ret[2023]) else "-",
                "24年": f"{ret[2024]:.1f}%" if not np.isnan(ret[2024]) else "-",
                "25年": f"{ret[2025]:.1f}%" if not np.isnan(ret[2025]) else "-",
                "RSI": f"{rsi:.0f}", "50日乖離": f"{dev_ma50:.1f}%", "200日乖離": f"{dev_ma200:.1f}%", 
                "3ヶ月": f"{ret_3m:.1f}%", "52週位置": f"{pos_52w:.0f}%", 
                "PER": f"{per:.1f}" if not np.isnan(per) else "-",
                "出来高比": f"{vol_ratio:.1f}", "株価": f"{current:.1f}"
            })
            serial_no += 1
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
        <title>戦略司令室 V6.9</title>
        <style>
            body { font-family: -apple-system, sans-serif; margin: 0; padding: 10px; background: #f4f6f9; color: #333; }
            h3 { margin: 10px 0; font-size: 16px; color: #1e293b; }
            .control-panel { background: #fff; padding: 12px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 13px;}
            input[type="text"] { padding: 6px; width: 180px; border: 1px solid #cbd5e1; border-radius: 4px; }
            button { padding: 6px 12px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
            .btn-clear { background: #dc2626; margin-left: 4px; }
            .table-container { overflow-x: auto; max-width: 100%; border: 1px solid #cbd5e1; background: #fff; border-radius: 6px; margin-bottom: 20px; }
            table { border-collapse: collapse; width: 100%; font-size: 11px; white-space: nowrap; }
            th, td { padding: 7px 5px; text-align: center; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; }
            th { background: #f1f5f9; font-weight: bold; position: sticky; top: 0; z-index: 2; cursor: pointer; user-select: none; color: #475569; }
            th:hover { background: #cbd5e1; }
            
            /* 銘柄名とTickerを固定（通し番号Noの右側に配置） */
            .fixed-name { position: sticky; left: 0; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); text-align: left; font-weight: bold; }
            .fixed-ticker { position: sticky; left: 75px; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); }
            th.fixed-name, th.fixed-ticker { z-index: 3; background: #f1f5f9; }
            
            .high-score { background-color: #dcfce7 !important; color: #15803d !important; font-weight: bold; }
            .low-score { background-color: #fee2e2 !important; color: #b91c1c !important; }
            .high-rsi { color: #dc2626; font-weight: bold; }
            .high-vol { color: #d97706; font-weight: bold; border: 1px solid #fcd34d; background: #fffbeb; border-radius: 3px; padding: 1px 3px; }
            .badge-m { background: #eff6ff; color: #1e40af; padding: 2px 4px; border-radius: 3px; font-size: 9px; font-weight: bold;}
            .badge-v { background: #f5f5f5; color: #444; padding: 2px 4px; border-radius: 3px; font-size: 9px; }
            .docs { background: #fff; padding: 15px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 11px; line-height: 1.6; color: #334155; }
            .docs h4 { margin-top: 0; font-size: 13px; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; }
        </style>
    </head>
    <body>
        <h3>🧠 戦略司令室 V6.9：2系統マルチ定規 ＆ 複数端末同期モデル</h3>
        
        <div class="control-panel">
            <label>➕ 関心銘柄の追加 (カンマ区切り): </label>
            <input type="text" id="tickerInput" placeholder="例: MSFT, NVDA">
            <button onclick="addTickers()">追加・同期更新</button>
            <button class="btn-clear" onclick="clearTickers()">クリア</button>
        </div>

        <div class="table-container">
            <table id="kabuTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0, true)">No ↕</th>
                        <th>区分</th>
                        <th>定規</th>
                        <th class="fixed-name">銘柄名 ↕</th>
                        <th class="fixed-ticker">Ticker ↕</th>
                        <th onclick="sortTable(5, true)">魅力度 ↕</th>
                        <th onclick="sortTable(6, true)">23年 ↕</th>
                        <th onclick="sortTable(7, true)">24年 ↕</th>
                        <th onclick="sortTable(8, true)">25年 ↕</th>
                        <th onclick="sortTable(9, true)">RSI ↕</th>
                        <th onclick="sortTable(10, true)">50日乖離 ↕</th>
                        <th onclick="sortTable(11, true)">200日乖離 ↕</th>
                        <th onclick="sortTable(12, true)">3ヶ月 ↕</th>
                        <th onclick="sortTable(13, true)">52週 ↕</th>
                        <th onclick="sortTable(14, true)">PER ↕</th>
                        <th onclick="sortTable(15, true)">出来高比 ↕</th>
                        <th onclick="sortTable(16, true)">株価 ↕</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in data %}
                    <tr>
                        <td>{{ r['No'] }}</td>
                        <td>{{ r['区分'] }}</td>
                        <td>
                            {% if r['定規'] == 'モーメンタム' %}
                            <span class="badge-m">モメンタム</span>
                            {% else %}
                            <span class="badge-v">バリュー</span>
                            {% endif %}
                        </td>
                        <td class="fixed-name">{{ r['銘柄名'] }}</td>
                        <td class="fixed-ticker">{{ r['Ticker'] }}</td>
                        <td class="{% if r['魅力度'] >= 70 %}high-score{% elif r['魅力度'] <= 40 %}low-score{% endif %}">{{ r['魅力度'] }}点</td>
                        <td>{{ r['23年'] }}</td><td>{{ r['24年'] }}</td><td>{{ r['25年'] }}</td>
                        <td class="{% if r['RSI']|float >= 80 %}high-rsi{% endif %}">{{ r['RSI'] }}</td>
                        <td>{{ r['50日乖離'] }}</td><td>{{ r['200日乖離'] }}</td><td>{{ r['3ヶ月'] }}</td><td>{{ r['52週位置'] }}</td>
                        <td>{{ r['PER'] }}</td>
                        <td>
                            <span class="{% if r['出来高比']|float >= 1.5 %}high-vol{% endif %}">{{ r['出来高比'] }}倍</span>
                        </td>
                        <td>{{ r['株価'] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <script>
            // 端末間同期とローカルストレージの連携処理
            document.addEventListener("DOMContentLoaded", function() {
                const savedTickers = localStorage.getItem("kabu_v69_tickers");
                const urlParams = new URLSearchParams(window.location.search);
                const urlTickers = urlParams.get('tickers');
                
                // URLに銘柄が入っている場合は、それを正としてローカルストレージを上書き更新
                if (urlTickers) {
                    localStorage.setItem("kabu_v69_tickers", urlTickers);
                    document.getElementById("tickerInput").value = urlTickers;
                } 
                // URLが空で、過去の記憶がある場合は自動リダイレクトして同期
                else if (savedTickers) {
                    window.location.href = "/?tickers=" + encodeURIComponent(savedTickers);
                }
            });

            function addTickers() {
                const inputVal = document.getElementById("tickerInput").value.trim().upper();
                localStorage.setItem("kabu_v69_tickers", inputVal);
                window.location.href = "/?tickers=" + encodeURIComponent(inputVal);
            }

            function clearTickers() {
                localStorage.removeItem("kabu_v69_tickers");
                window.location.href = "/";
            }

            // 万能並び替えスクリプト（No列をクリックすれば元の順序に綺麗に戻る）
            function sortTable(n, isNum) {
                var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
                table = document.getElementById("kabuTable");
                switching = true;
                dir = "desc"; 
                while (switching) {
                    switching = false;
                    rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++) {
                        shouldSwitch = false;
                        x = rows[i].getElementsByTagName("TD")[n];
                        y = rows[i + 1].getElementsByTagName("TD")[n];
                        
                        var valX = x.innerHTML.replace(/[^0-9.-]+/g,"");
                        var valY = y.innerHTML.replace(/[^0-9.-]+/g,"");
                        
                        if (!isNum || valX === "" || valY === "") {
                            valX = x.innerHTML.toLowerCase();
                            valY = y.innerHTML.toLowerCase();
                        } else {
                            valX = parseFloat(valX);
                            valY = parseFloat(valY);
                        }

                        if (dir == "asc") {
                            if (valX > valY) { shouldSwitch = true; break; }
                        } else if (dir == "desc") {
                            if (valX < valY) { shouldSwitch = true; break; }
                        }
                    }
                    if (shouldSwitch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "desc") {
                            dir = "asc";
                            switching = true;
                        }
                    }
                }
            }
        </script>

        <div class="docs">
            <h4>🧮 司令室 V6.9 のアルゴリズム背景</h4>
            <p><b>1. モメンタム定規（SMH, QQQ, VOO等）:</b> 「長期トレンド（200日線）が上向き」であることを大前提とし、株価が急騰しすぎず、50日線の近く（-5%〜+5%）まで一時的に熱を冷ました「最高の押し目」を25点の大幅加点としてハイスコアを算出します。PERは45倍、50日乖離は15%〜20%を明確なバブルレッドゾーンとし、それを超えると点数が地に落ちる「階段式評価」を搭載しています。</p>
            <p><b>2. バリュー定規（新興国、高配当等）:</b> 割安度と短期的な売られすぎ（押し目）を評価します。ただし、長期トレンド（200日線）を下回っている状態でさらにRSIが40を割るような「ダラダラ下げ（底なし沼）」の状態を検知した場合は、「落ちるナイフ」ペナルティ（-20点）が発動し、スコアを強制排除します。</p>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, data=data, custom_tickers_str=custom_tickers_str)

if __name__ == '__main__':
    app.run(debug=True)