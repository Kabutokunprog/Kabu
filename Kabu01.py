from flask import Flask, render_template_string, request
import pandas as pd
import yfinance as yf
import numpy as np

app = Flask(__name__)

# 固定資産リスト（資産の高い順の並びを厳守 ＋ ヘッジなし本命2種を常駐 ＋ ロッキード削除 ＋ 宇宙ファンド・SPCX）
FIXED_ASSETS = {
    "保有": {
        "VPU": "AI電力(主力)", 
        "PAVE": "インフラ(主力)", 
        "VOO": "S&P500", 
        "SMH": "半導体", 
        "NVDA": "NVIDIA(本命)",
        "NDAQ": "NASDAQ", 
        "9984.T": "SBG", 
        "7201.T": "日産", 
        "4901.T": "富士フイルム", 
        "1489.T": "日経高配当50",
        "1545.T": "ニッセイNASDAQ100(投信クラス)", # 確実なデータ取得のため東証ヘッジなしコードを利用
        "2631.T": "eMAXIS Slim NASDAQ100"       # 確実なデータ取得のため東証ヘッジなしコードを利用
    },
    "監視": {
        "QQQ": "NASDAQ100(本家ドル建)", 
        "GLD": "金(有事の備え)", 
        "XLE": "エネルギー(保険)", 
        "EPI": "インド株(損切済)", 
        "VWO": "新興国株", 
        "VNM": "ベトナム", 
        "CIBR": "セキュリティ", 
        "XLV": "ヘルスケア",
        "ARKX": "ARK宇宙探査投信", 
        "UFO": "宇宙エコミETF", 
        "ITA": "米国航空宇宙防衛", 
        "SPCX": "SpaceX(6/12上場)"
    }
}

# モメンタム（順張り）型アセットの定義
MOMENTUM_TICKERS = ["SMH", "NVDA", "QQQ", "1545.T", "2631.T", "VOO", "NDAQ", "9984.T", "MSFT", "AAPL", "TSLA", "AMZN", "META", "GOOGL", "AVGO", "TSM", "ARKX", "UFO", "SPCX"]

def fetch_data(additional_tickers):
    res = []
    combined_assets = {**FIXED_ASSETS["保有"], **FIXED_ASSETS["監視"]}
    
    for t in additional_tickers:
        t = t.upper()
        if t not in combined_assets: 
            combined_assets[t] = f"追加({t})"

    serial_no = 1
    raw_text_lines = ["No\t区分\t定規\t銘柄名\tTicker\t魅力度\t23年\t24年\t25年\tRSI\t50日乖離\t200日乖離\t3ヶ月\t52週\t出来高比\t株価"]

    for t, n in combined_assets.items():
        try:
            s = yf.Ticker(t)
            
            # SPCX（SpaceX）未上場時のエラー回避処理
            if t == "SPCX":
                current, dev_ma50, dev_ma200, ret_3m, rsi, pos_52w, vol_ratio = 0.0, 0.0, 0.0, 0.0, 50, 0, 1.0
                ret = {2023: 0.0, 2024: 0.0, 2025: 0.0}
                score = 50
                is_momentum = True
            else:
                hist_5y = s.history(period="5y")
                if len(hist_5y) < 10:
                    hist_5y = s.history(period="max")
                if len(hist_5y) == 0: continue

                ret = {2025: np.nan, 2024: np.nan, 2023: np.nan}
                try:
                    yearly = hist_5y['Close'].resample('YE').last().pct_change() * 100
                    for y in ret.keys():
                        target_date = f"{y}-12-31"
                        matching_dates = yearly.index[yearly.index.strftime('%Y-%m-%d') == target_date]
                        if not matching_dates.empty: ret[y] = yearly.loc[matching_dates[0]]
                except:
                    pass

                current = s.info.get("regularMarketPrice") or s.info.get("currentPrice") or hist_5y['Close'].iloc[-1]
                
                # 移動平均と乖離の算出
                w50 = min(50, len(hist_5y))
                w200 = min(200, len(hist_5y))
                ma50 = hist_5y['Close'].rolling(window=w50).mean().iloc[-1] if w50 > 0 else current
                dev_ma50 = ((current - ma50) / ma50) * 100 if ma50 != 0 else 0
                ma200 = hist_5y['Close'].rolling(window=w200).mean().iloc[-1] if w200 > 0 else current
                dev_ma200 = ((current - ma200) / ma200) * 100 if ma200 != 0 else 0
                
                idx_3m = -min(63, len(hist_5y))
                three_months_ago = hist_5y['Close'].iloc[idx_3m] if len(hist_5y) > 0 else current
                ret_3m = ((current - three_months_ago) / three_months_ago) * 100 if three_months_ago != 0 else 0

                # RSI
                delta = hist_5y['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(min(14, len(hist_5y))).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(min(14, len(hist_5y))).mean()
                if len(loss) > 0 and loss.iloc[-1] != 0:
                    rsi = 100 - (100 / (1 + (gain.iloc[-1] / loss.iloc[-1])))
                else:
                    rsi = 50

                # 52週位置
                w252 = min(252, len(hist_5y))
                h52 = hist_5y['Close'].tail(w252).max()
                l52 = hist_5y['Close'].tail(w252).min()
                pos_52w = ((current - l52) / (h52 - l52)) * 100 if h52 != l52 else 0

                # 出来高比
                vol_5d = hist_5y['Volume'].tail(5).mean()
                vol_60d = hist_5y['Volume'].tail(min(63, len(hist_5y))).mean()
                vol_ratio = (vol_5d / vol_60d) if vol_60d > 0 else 1.0

                # --- 🧠 V7.5 確定客観ロジック ---
                score = 50
                is_momentum = t in MOMENTUM_TICKERS
                
                if is_momentum:
                    # ① モメンタム型：52週高値圏の滞空過熱リスク判定（PER二重処罰回避）
                    if rsi > 85: score -= 25
                    elif 45 <= rsi <= 65: score += 15
                    if pos_52w > 95: score -= 15

                    # トレンド評価
                    if dev_ma200 > 0:
                        if -5 <= dev_ma50 <= 5: score += 25  # 黄金の押し目
                        elif 5 < dev_ma50 <= 15: score += 10 # 健全な巡航
                    
                    # 過熱足切り
                    if dev_ma50 > 15: score -= 20
                    if dev_ma50 < -10: score -= 20
                    if dev_ma200 < 0: score -= 25
                else:
                    # ② バリュー型：死んだアセット（リターン5%未満）の完全排除
                    if ret_3m < 0 or dev_ma200 < -3:
                        score -= 30  
                    else:
                        if 40 <= rsi <= 55: score += 15
                        if -5 <= dev_ma50 <= 2: score += 10
                        if dev_ma200 < 0: score -= 15

                # ③ 共通：セリングクライマックス（大底）自動検知
                if dev_ma50 < -3 and vol_ratio >= 1.5:
                    score += 25

            final_score = int(max(0, min(100, score)))

            row_data = {
                "No": serial_no,
                "区分": "追加" if t in additional_tickers else ("保有" if t in FIXED_ASSETS["保有"] else "監視"),
                "定規": "モメンタム" if is_momentum else "バリュー",
                "銘柄名": n, "Ticker": t, "魅力度": final_score,
                "23年": f"{ret[2023]:.1f}%" if not np.isnan(ret[2023]) else "-",
                "24年": f"{ret[2024]:.1f}%" if not np.isnan(ret[2024]) else "-",
                "25年": f"{ret[2025]:.1f}%" if not np.isnan(ret[2025]) else "-",
                "RSI": f"{rsi:.0f}", "50日乖離": f"{dev_ma50:.1f}%", "200日乖離": f"{dev_ma200:.1f}%", 
                "3ヶ月": f"{ret_3m:.1f}%", "52週位置": f"{pos_52w:.0f}%", 
                "出来高比": f"{vol_ratio:.1f}", "株価": f"{current:.1f}" if t != "SPCX" else "未上場"
            }
            res.append(row_data)

            raw_line = f"{row_data['No']}\t{row_data['区分']}\t{row_data['定規']}\t{row_data['銘柄名']}\t{row_data['Ticker']}\t{row_data['魅力度']}\t{row_data['23年']}\t{row_data['24年']}\t{row_data['25年']}\t{row_data['RSI']}\t{row_data['50日乖離']}\t{row_data['200日乖離']}\t{row_data['3ヶ月']}\t{row_data['52週位置']}\t{row_data['出来高比']}\t{row_data['株価']}"
            raw_text_lines.append(raw_line)
            
            serial_no += 1
        except: continue
    
    return res, "\n".join(raw_text_lines)

@app.route('/')
def index():
    custom_tickers_str = request.args.get('tickers', '')
    additional_tickers = [t.strip().upper() for t in custom_tickers_str.split(',') if t.strip()]
    data, raw_text = fetch_data(additional_tickers)
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>戦略司令室 V7.5</title>
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
            .fixed-name { position: sticky; left: 0; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); text-align: left; font-weight: bold; }
            .fixed-ticker { position: sticky; left: 75px; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); }
            th.fixed-name, th.fixed-ticker { z-index: 3; background: #f1f5f9; }
            .high-score { background-color: #dcfce7 !important; color: #15803d !important; font-weight: bold; }
            .low-score { background-color: #fee2e2 !important; color: #b91c1c !important; }
            .high-rsi { color: #dc2626; font-weight: bold; }
            .high-vol { background: #fffbeb; color: #b45309; font-weight: bold; border: 1px solid #fde68a; border-radius: 3px; padding: 1px 3px; }
            .badge-m { background: #eff6ff; color: #1e40af; padding: 2px 4px; border-radius: 3px; font-size: 9px; font-weight: bold;}
            .badge-v { background: #f5f5f5; color: #444; padding: 2px 4px; border-radius: 3px; font-size: 9px; }
            
            .docs { background: #fff; padding: 15px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 12px; line-height: 1.6; color: #334155; margin-bottom: 15px;}
            .docs h4 { margin-top: 0; font-size: 14px; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; margin-bottom: 10px; }
            .docs ul { padding-left: 20px; margin: 8px 0; }
            .docs li { margin-bottom: 4px; }
            .copy-area { width: 100%; height: 120px; font-size: 10px; font-family: monospace; border: 1px solid #ccc; padding: 5px; white-space: pre; overflow: auto; }
        </style>
    </head>
    <body>
        <h3>🧠 戦略司令室 V7.5：完全配置・情報集約モデル</h3>
        
        <div class="control-panel">
            <form id="tickerForm" method="GET" action="/">
                <label>➕ 関心銘柄の追加: </label>
                <input type="text" id="tickerInput" name="tickers" placeholder="例: MSFT, AMD" value="{{ custom_tickers_str }}">
                <button type="submit" onclick="localStorage.setItem('kabu_v75_tickers', document.getElementById('tickerInput').value.trim().toUpperCase())">追加・同期更新</button>
                <button type="button" class="btn-clear" onclick="localStorage.removeItem('kabu_v75_tickers'); window.location.href='/';">クリア</button>
            </form>
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
                        <th onclick="sortTable(14, true)">出来高比 ↕</th>
                        <th onclick="sortTable(15, true)">株価 ↕</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in data %}
                    <tr>
                        <td>{{ r['No'] }}</td>
                        <td>{{ r['区分'] }}</td>
                        <td>
                            {% if r['定規'] == 'モメンタム' %}
                            <span class="badge-m">モメンタム</span>
                            {% else %}
                            <span class="badge-v">バリュー</span>
                            {% endif %}
                        </td>
                        <td class="fixed-name">{{ r['銘柄名'] }}</td>
                        <td class="fixed-ticker">{{ r['Ticker'] }}</td>
                        <td class="{% if r['魅力度'] >= 70 %}high-score{% elif r['魅力度'] <= 35 %}low-score{% endif %}">{{ r['魅力度'] }}点</td>
                        <td>{{ r['23年'] }}</td><td>{{ r['24年'] }}</td><td>{{ r['25年'] }}</td>
                        <td class="{% if r['RSI']|float >= 80 %}high-rsi{% endif %}">{{ r['RSI'] }}</td>
                        <td>{{ r['50日乖離'] }}</td><td>{{ r['200日乖離'] }}</td><td>{{ r['3ヶ月'] }}</td><td>{{ r['52週位置'] }}</td>
                        <td>
                            <span class="{% if r['出来高比']|float >= 1.5 %}high-vol{% endif %}">{{ r['出来高比'] }}倍</span>
                        </td>
                        <td>{{ r['株価'] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <div class="docs">
            <h4>📈 各表示項目の解説と計算式</h4>
            <ul>
                <li><strong>魅力度（点数）：</strong>基本点 50 点からスタートし、各定規のルールに応じて自動計算される客観的な買いシグナル（70点以上で緑、35点以下で赤表示）。</li>
                <li><strong>RSI（相対力指数）：</strong>過去14日間の「値上がり幅」と「値下がり幅」から、市場の心理的過熱度を 0〜100% で表したもの。80超は買われすぎ（天井圏）、30未満は売られすぎ（底値圏）を示す。</li>
                <li><strong>50日乖離 / 200日乖離：</strong>現在の株価が、過去 50 日間（中期トレンド）または 200 日間（長期トレンド）の移動平均線から何％離れているか。マイナスは割安、プラスは上昇トレンドまたは過熱。</li>
                <li><strong>3ヶ月（騰落率）：</strong>直近 3 ヶ月（約63営業日）の株価リターン。バリュー型でこれがマイナスのものは「死んだレンジ株」として弾かれる。</li>
                <li><strong>52週位置：</strong>過去1年間（52週間）の最高値を 100%、最安値を 0% とした時の現在の立ち位置。モメンタム株が 95% 超に長期間滞空している場合は過熱リスクを検知。</li>
                <li><strong>出来高比：</strong>直近 5 日間の平均取引量が、過去 3 ヶ月平均の何倍に増えているか。暴落時の「出来高急増（1.5倍以上）」は、プロの買い集め（大底）のシグナルとなる。</li>
            </ul>
        </div>

        <div class="docs">
            <h4>📊 客観スコアリング定規（加減点ルール詳細）</h4>
            <p><strong>【モメンタム型定規（順張り）】</strong>：トレンドの健全性と過熱滞空リスクを測定</p>
            <ul>
                <li><strong>加点：</strong>200日線の上にあることを前提とし、50日線付近の絶妙な押し目（乖離-5%〜+5%）なら <code>+25点</code>。健全な巡航速度（乖離+5%〜+15%）なら <code>+10点</code>。RSIが過熱していない健全レンジ（45〜65）なら <code>+15点</code>。</li>
                <li><strong>減点：</strong>RSIが異常過熱（85超）なら <code>-25点</code>。52週高値圏に張り付き（52週位置95%超）なら <code>-15点</code>。短期急騰（50日乖離15%超）なら <code>-20点</code>。200日線を下回るトレンド崩壊なら <code>-25点</code>。</li>
            </ul>
            
            <p><strong>【バリュー型定規（逆張り）】</strong>：死んだアセット（バリュートラップ）の排除と割安性の検知</p>
            <ul>
                <li><strong>足切り（最優先）：</strong>直近3ヶ月リターンがマイナス <code>(ret_3m < 0)</code>、または200日線から3%以上下方に沈んでいる <code>(dev_ma200 < -3%)</code> 場合は、リターン5%を期待できない「死んだレンジ株」とみなし <code>-30点</code>。</li>
                <li><strong>正常時の加減点：</strong>RSIが底値圏（40〜55）なら <code>+15点</code>。50日線付近での下げ止まり（乖離-5%〜+2%）なら <code>+10点</code>。200日線割れなら <code>-15点</code>。</li>
            </ul>

            <p><strong>【共通：セリングクライマックス（大底）自動検知】</strong></p>
            <ul>
                <li>短期的に売り込まれている局面（50日乖離が-3%未満）で、直近5日の出来高が過去3ヶ月平均の1.5倍以上に急増 <code>(vol_ratio >= 1.5)</code> している場合、恐怖に負けた個人の投げ売りをプロが底値で買い集めたと判定し、一律 <code>+25点</code> を強制加点。</li>
            </ul>
        </div>

        <div class="docs">
            <h4>🤖 Gemini 壁打ち用コピペエリア（全選択してコピー）</h4>
            <textarea class="copy-area" readonly onclick="this.select()">{{ raw_text }}</textarea>
        </div>

        <script>
            document.addEventListener("DOMContentLoaded", function() {
                const savedTickers = localStorage.getItem("kabu_v75_tickers");
                const urlParams = new URLSearchParams(window.location.search);
                const urlTickers = urlParams.get('tickers');
                
                if (!urlTickers && savedTickers) {
                    window.location.href = "/?tickers=" + encodeURIComponent(savedTickers);
                }
            });

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
    </body>
    </html>
    """
    return render_template_string(html, data=data, custom_tickers_str=custom_tickers_str, raw_text=raw_text)

if __name__ == '__main__':
    app.run(debug=True)