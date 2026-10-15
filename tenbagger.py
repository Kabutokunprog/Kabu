"""テンバガー候補ページ（/tenbagger）

半導体・AI関連の中小型株を中心に、Yahoo!ファイナンスの最新データ（約20分遅れ）から
「小さい・伸びている・稼いでいる・まだ安い」をスコア化して並べる。
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from flask import Blueprint, render_template_string, request

bp = Blueprint("tenbagger", __name__)

# (コード, 銘柄名, テーマ)
UNIVERSE = [
    # --- 前回の採点で取り上げた銘柄 ---
    ("6668.T", "アドテックプラズマ", "半導体装置部品"),
    ("3891.T", "ニッポン高度紙", "AIサーバー部材"),
    ("4187.T", "大阪有機化学", "半導体材料"),
    ("6627.T", "テラプローブ", "半導体検査"),
    ("4406.T", "新日本理化", "化学"),
    ("4055.T", "ティアンドエス", "半導体/AI"),
    ("6871.T", "日本マイクロニクス", "半導体検査"),
    # --- 半導体（装置・部品） ---
    ("6266.T", "タツモ", "半導体装置"),
    ("6235.T", "オプトラン", "半導体装置"),
    ("6315.T", "TOWA", "半導体装置"),
    ("6323.T", "ローツェ", "半導体装置"),
    ("6855.T", "日本電子材料", "半導体検査"),
    ("6264.T", "マルマエ", "半導体装置部品"),
    ("6337.T", "テセック", "半導体検査"),
    ("6387.T", "サムコ", "半導体装置"),
    ("6338.T", "タカトリ", "半導体装置"),
    ("6254.T", "野村マイクロ", "半導体装置"),
    ("6656.T", "インスペック", "半導体検査"),
    ("6227.T", "AIメカテック", "半導体装置"),
    ("6890.T", "フェローテック", "半導体装置部品"),
    ("3445.T", "RSテクノロジーズ", "半導体材料"),
    # --- 半導体（材料・基板） ---
    ("4369.T", "トリケミカル", "半導体材料"),
    ("4975.T", "JCU", "半導体材料"),
    ("6787.T", "メイコー", "AIサーバー基板"),
    ("3110.T", "日東紡", "AIサーバー部材"),
    ("6966.T", "三井ハイテック", "半導体部品"),
    ("6834.T", "精工技研", "光通信部品"),
    # --- 半導体商社 ---
    ("3321.T", "ミタチ産業", "半導体商社"),
    ("7537.T", "丸文", "半導体商社"),
    # --- AI・データセンター ---
    ("3778.T", "さくらインターネット", "データセンター"),
    ("3776.T", "ブロードバンドタワー", "データセンター"),
    ("5026.T", "トリプルアイズ", "AI"),
    ("3993.T", "PKSHA", "AI"),
    ("4180.T", "Appier", "AI"),
    ("5574.T", "ABEJA", "AI"),
    ("4011.T", "ヘッドウォータース", "AI"),
    ("4488.T", "AI inside", "AI"),
    ("5132.T", "pluszero", "AI"),
]

# 事業内容と注目点（2026年10月時点のWeb情報をもとに作成。業績の数字は決算短信で要確認）
# {コード: (何をしている会社か, 注目点・注意点)}
PROFILES = {
    "6668": ("半導体製造装置（エッチング・成膜）に組み込む高周波電源・整合器のメーカー。装置内でプラズマを安定させる心臓部の部品。",
             "26年8月期の営業利益は+42%。27年8月期は約2倍（53億円）の予想。7月の上方修正ではストップ高。"),
    "3891": ("アルミ電解コンデンサ用のセパレータ（電気を通さない特殊な紙）で世界トップ級のシェア。",
             "AIサーバー向けの需要が好調で、営業利益予想を44億→60億円に上方修正（8月）。"),
    "4187": ("アクリル酸エステルなどの化学品メーカー。半導体のレジスト（回路を描く感光材）向け材料、ディスプレイ材料、化粧品原料を手がける。",
             "上期の営業利益+51%。通期の営業利益予想を75億円に上方修正し、増配も発表。"),
    "6627": ("半導体のウエハテスト（完成前の半導体チップの検査）の受託会社。台湾の半導体後工程大手・力成科技（PTI）のグループ。",
             "経常利益+84%の予想。10月1日に1株→5株の株式分割を実施。表示のPER・PEGは分割前の利益で計算されている可能性があり、実際より割安に見えている恐れ。"),
    "4406": ("油脂化学（オレオケミカル）、可塑剤、樹脂添加剤、水素化の受託などを手がける化学メーカー。",
             "第1四半期の利益が約4倍、通期の経常利益予想を8億→17億円に上方修正。PBR0.4倍と超割安。ただしAI・半導体との直接の関係は確認できず。"),
    "4055": ("半導体工場（キオクシアなど）向けのシステム開発・運用と、AI（画像認識など）の開発を行うIT企業。",
             "半導体関連の売上が+24.5%。メモリ（SSD）需要の回復の恩恵を受ける立場。"),
    "6871": ("半導体の検査に使うプローブカード（チップに針を当てて電気検査する部品）の大手。特にメモリ向けに強い。",
             "AI向けメモリ（HBM）の需要で、26年12月期の営業利益は+87%（314億円）の予想。会社は優秀だが時価総額が大きく、10倍は難しい。"),
    "6266": ("半導体・ディスプレイの製造装置（塗布装置、貼り合わせ装置など）とウエハ搬送ロボットのメーカー。",
             "直近は減収。受注の回復待ちの段階。"),
    "6235": ("スマホのカメラやセンサーのレンズに光学薄膜をつける成膜装置のメーカー。",
             "中国向けの売上が大きく、景気や規制の影響を受けやすい。直近は減益。"),
    "6315": ("半導体の樹脂封止（チップを樹脂で包んで保護する工程）装置で世界トップ。",
             "AI向けメモリ（HBM）用の封止装置が成長の柱。増収+100%と好調。"),
    "6323": ("半導体ウエハの搬送ロボット・搬送装置で世界大手。",
             "営業利益率30%と高収益。時価総額が約7,800億円と大きめ。"),
    "6855": ("半導体の検査に使うプローブカードのメーカー。",
             "第1四半期の経常利益+127%。通期の経常利益予想を73億→93億円に上方修正（8月）。"),
    "6264": ("半導体・ディスプレイ製造装置向けの真空部品や電極の精密加工。子会社KMACで半導体材料用の超高純度アルミも手がける。",
             "半導体装置向けの受注が急拡大し、26年8月期は2度の上方修正。"),
    "6337": ("半導体の検査工程で使うハンドラ（チップを運んで良品・不良品に仕分ける装置）とテスタ（検査装置）のメーカー。",
             "AI需要でハンドラの受注が増加。27年3月期の経常利益予想を5.9億→13億円に上方修正（7月）。時価総額200億円前後と小さい。"),
    "6387": ("化合物半導体・パワー半導体向けのエッチング装置・成膜装置のメーカー（京都）。",
             "営業利益率34%と高収益だが、売上の伸びは鈍い。"),
    "6338": ("SiC（次世代パワー半導体材料）を切断するワイヤーソーや、ウエハの貼り付け装置のメーカー。",
             "SiC市場の不振で大幅な減収減益。PBR1倍割れだが回復待ち。"),
    "6254": ("半導体工場で使う超純水の製造装置のメーカー。",
             "工場建設のタイミングで売上が大きく変動。直近は減収減益。"),
    "6656": ("プリント基板や半導体パッケージの外観検査装置のメーカー。",
             "赤字が続いており、注意が必要。"),
    "6227": ("半導体パッケージにはんだボールを載せる装置や、インクジェット装置のメーカー。",
             "2年で約7倍に上昇済み。直近は減収減益。"),
    "6890": ("半導体製造装置向けの真空シール、石英・セラミックス部品、シリコンウエハなどを幅広く手がける。",
             "増収+165%と急伸。中国での事業が大きい点はリスク。"),
    "3445": ("使用済みのテスト用ウエハを再生する事業で世界トップ。中国子会社で新品のウエハも製造。",
             "売上の伸びは鈍化。中国事業の比率が高い。"),
    "4369": ("半導体の成膜に使う高純度の化学材料（High-k材料など）のメーカー。",
             "営業利益率25%と高収益。直近は減益。"),
    "4975": ("プリント基板・半導体パッケージ向けのめっき薬品のメーカー。",
             "営業利益率36%と非常に高収益だが、成長はゆるやか。"),
    "6787": ("プリント基板のメーカー。自動車向けが中心で、AIサーバー・通信向けを拡大中。",
             "増収+38%だが利益の伸びは小さい。高値から−50%超。"),
    "3110": ("ガラス繊維のメーカー。AIサーバーの基板に使う特殊なガラスクロスで高いシェア。",
             "AIサーバー向けで成長。高値から−54%と大きく下落。時価総額は5,000億円超と大きめ。"),
    "6966": ("EV（電気自動車）用モーターコアと、半導体部品のリードフレームのメーカー。精密金型に強み。",
             "売上の約7割がEV向けのモーターコアで、半導体・AIの比率は小さい。"),
    "6834": ("光ファイバーの接続部品（光コネクタ関連）と光ディスク用金型のメーカー。",
             "データセンターの光通信向けで急成長。2年で約9倍に上昇済み。"),
    "3321": ("電子部品・半導体の商社（名古屋）。自動車向けが中心。",
             "PBR1倍割れだが、商社のため営業利益率は2%台と低い。"),
    "7537": ("半導体・電子部品の独立系商社。",
             "PBR1倍割れだが、営業利益率は3%台と低い。"),
    "3778": ("データセンター・クラウドの運営。政府認定のGPUクラウド（AI計算用）を提供。",
             "増収+49%。GPU投資の負担で利益は不安定。"),
    "3776": ("都市型データセンターの運営。",
             "直近は減収。利益率が低い。"),
    "5026": ("画像認識AIやAIを使ったシステム開発を行う会社。",
             "時価総額約50億円と非常に小さいが、直近は減収。"),
    "3993": ("東大・松尾研究室系のAI企業。コールセンター向けAIやチャットボットなどのAIソフトを提供。",
             "増収+81%と好調。"),
    "4180": ("台湾発のAIマーケティング（広告・顧客分析）のソフト会社。",
             "増収+25%、増益が続く。2年で−23%と株価は出遅れ。"),
    "5574": ("企業のAI導入支援と、AI基盤「ABEJA Platform」の開発・運用。現場で使うAI（Physical AI）に注力。",
             "第3四半期までの営業利益+42%。通期予想を上方修正。PERが55倍と割高。"),
    "4011": ("マイクロソフト系の生成AIを使った企業向けAIシステムの開発。",
             "増収+133%と急伸だが、利益率は6%台と低い。"),
    "4488": ("AI-OCR（手書き書類の読み取りAI）「DX Suite」が主力。生成AIの基盤開発にも注力。",
             "27年3月期の営業利益は+69%の予想。2年で−41%と株価は低迷。"),
    "5132": ("「第4世代AI」と呼ぶ独自AI（AEI）を使ったAI開発・コンサルティング。",
             "通期の売上+30%・経常利益+43%の予想。業績は伸びているが、株価は上場後長く低迷（高値から−60%）。PER46倍と割高。"),
}

CACHE_SECONDS = 600
_cache = {"time": 0.0, "key": None, "data": None}


def _num(v):
    """数値でなければ NaN にする"""
    try:
        f = float(v)
        return f if np.isfinite(f) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _fetch_info(ticker):
    try:
        return ticker, yf.Ticker(ticker).info or {}
    except Exception:
        return ticker, {}


def _price_history(tickers):
    """全銘柄の2年分の株価を一括取得して {コード: 終値Series} にする"""
    out = {}
    try:
        df = yf.download(tickers, period="2y", group_by="ticker", auto_adjust=False,
                         threads=True, progress=False)
    except Exception:
        return out
    for t in tickers:
        try:
            close = df[t]["Close"] if len(tickers) > 1 else df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close) > 0:
                out[t] = close
        except Exception:
            continue
    return out


PEG_GROWTH_CAP = 100   # PEG 計算に使う増益率の上限（%）。前年が小さすぎる反動の異常値対策
PEG_MAX_PER = 40       # これより PER が高い株は PEG の加点なし
SPIKE_GROWTH = 200     # 増益率がこれを超えたら「一時的な急増?」の目印を出す
DIP_MIN_RET_2Y = 50    # 押し目の加点は、2年でこれ以上（%）上がっている上昇トレンドの株だけ

# 採点ルール: (項目名, 指標キー, [(条件, 点数, 説明), ...]) を上から順に判定し、最初に当てはまったものを採用
RULES = [
    ("小型", "cap_oku", [
        (lambda v: v <= 300, 20, "時価総額300億円以下"),
        (lambda v: v <= 1000, 15, "時価総額1,000億円以下"),
        (lambda v: v <= 3000, 5, "時価総額3,000億円以下"),
    ]),
    ("増収", "rev_growth", [
        (lambda v: v >= 30, 15, "増収率30%以上"),
        (lambda v: v >= 20, 10, "増収率20%以上"),
        (lambda v: v >= 10, 5, "増収率10%以上"),
        (lambda v: v < 0, -5, "減収"),
    ]),
    ("増益", "earn_growth", [
        (lambda v: v >= 50, 10, "増益率50%以上"),
        (lambda v: v >= 20, 5, "増益率20%以上"),
        (lambda v: v < 0, -5, "減益"),
    ]),
    ("利益率", "op_margin", [
        (lambda v: v >= 20, 15, "営業利益率20%以上"),
        (lambda v: v >= 10, 10, "営業利益率10%以上"),
        (lambda v: v < 0, -10, "営業赤字"),
    ]),
    ("PEG", "peg", [
        (lambda v: v <= 0.5, 15, "PEG 0.5以下（PER40倍以下のときだけ）"),
        (lambda v: v <= 1.0, 10, "PEG 1以下（PER40倍以下のときだけ）"),
    ]),
    ("PBR", "pbr", [
        (lambda v: v <= 1.0, 10, "PBR 1倍以下"),
        (lambda v: v <= 2.0, 5, "PBR 2倍以下"),
    ]),
    ("出遅れ", "ret_2y", [
        (lambda v: v <= 50, 10, "2年上昇率+50%以下"),
        (lambda v: v >= 300, -10, "2年で4倍超"),
    ]),
    ("押し目", "from_high", [
        (lambda v: v <= -20, 10, "高値から20%以上下落（2年で+50%以上の上昇株のみ）"),
    ]),
    ("オーナー", "insider", [
        (lambda v: v >= 20, 5, "経営陣保有20%以上"),
    ]),
]


def score_stock(m):
    """指標の dict から スコア（0〜100）・点数の内訳・シグナル を返す"""
    breakdown = []
    for label, key, conds in RULES:
        v = m[key]
        if np.isnan(v):
            continue
        # PEG は PER が 40倍を超える割高株には加点しない
        if key == "peg" and not (m["per"] <= PEG_MAX_PER):
            continue
        # 押し目は「売上が伸びている（または不明）」ときだけ加点（業績悪化による下落を除く）
        if key == "from_high" and not (np.isnan(m["rev_growth"]) or m["rev_growth"] > 0):
            continue
        # 押し目は上昇トレンドの株の一時的な下げだけ（ずっと低迷している株は除く）
        if key == "from_high" and not (m["ret_2y"] >= DIP_MIN_RET_2Y):
            continue
        for cond, pts, desc in conds:
            if cond(v):
                breakdown.append((label, pts, desc))
                break

    score = int(max(0, min(100, sum(p for _, p, _ in breakdown))))

    signals = []
    if not np.isnan(m["pbr"]) and m["pbr"] <= 1.0:
        signals.append(("🔴PBR1倍割れ", "sig-red"))
    if any(l == "押し目" for l, _, _ in breakdown):
        signals.append(("🟡高値から急落", "sig-yellow"))
    if not np.isnan(m["earn_growth"]) and m["earn_growth"] > SPIKE_GROWTH:
        signals.append(("⚠️増益率が異常に大きい", "sig-gray"))
    if not np.isnan(m["ret_2y"]):
        if m["ret_2y"] <= 50:
            signals.append(("🟢まだ上がっていない", "sig-green"))
        elif m["ret_2y"] >= 300:
            signals.append(("⚠️2年で4倍超", "sig-gray"))
    return score, breakdown, signals


def collect(extra_tickers):
    universe = list(UNIVERSE)
    known = {u[0] for u in universe}
    for t in extra_tickers:
        if t not in known:
            universe.append((t, f"追加({t})", "追加"))
            known.add(t)
    tickers = [u[0] for u in universe]

    key = tuple(tickers)
    if _cache["key"] == key and time.time() - _cache["time"] < CACHE_SECONDS:
        return _cache["data"]

    with ThreadPoolExecutor(max_workers=8) as ex:
        infos = dict(ex.map(_fetch_info, tickers))
    hist = _price_history(tickers)

    rows = []
    for t, name, theme in universe:
        info = infos.get(t, {})
        close = hist.get(t)
        if not info and close is None:
            continue

        price = _num(info.get("regularMarketPrice") or info.get("currentPrice"))
        if np.isnan(price) and close is not None:
            price = float(close.iloc[-1])
        prev = _num(info.get("regularMarketPreviousClose") or info.get("previousClose"))
        if np.isnan(prev) and close is not None and len(close) >= 2:
            prev = float(close.iloc[-2])

        day_chg = (price / prev - 1) * 100 if prev and not np.isnan(prev) else np.nan
        from_high = ret_2y = np.nan
        if close is not None and len(close) > 0:
            high52 = max(float(close.tail(252).max()), price if not np.isnan(price) else 0)
            from_high = (price / high52 - 1) * 100 if high52 else np.nan
            ret_2y = (price / float(close.iloc[0]) - 1) * 100

        per = _num(info.get("forwardPE"))
        if np.isnan(per) or per <= 0:
            per = _num(info.get("trailingPE"))
        earn_growth = _num(info.get("earningsGrowth")) * 100
        peg = per / min(earn_growth, PEG_GROWTH_CAP) if per > 0 and earn_growth > 0 else np.nan

        m = {
            "price": price,
            "day_chg": day_chg,
            "from_high": from_high,
            "ret_2y": ret_2y,
            "cap_oku": _num(info.get("marketCap")) / 1e8,
            "per": per,
            "pbr": _num(info.get("priceToBook")),
            "peg": peg,
            "op_margin": _num(info.get("operatingMargins")) * 100,
            "rev_growth": _num(info.get("revenueGrowth")) * 100,
            "earn_growth": earn_growth,
            "insider": _num(info.get("heldPercentInsiders")) * 100,
        }
        score, breakdown, signals = score_stock(m)
        rows.append({"code": t.replace(".T", ""), "name": name, "theme": theme,
                     "score": score, "breakdown": breakdown, "signals": signals, **m})

    rows.sort(key=lambda r: r["score"], reverse=True)
    _cache.update(time=time.time(), key=key, data=rows)
    return rows


def _fmt(v, digits=1, suffix="", sign=False):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    s = f"{v:+,.{digits}f}" if sign else f"{v:,.{digits}f}"
    return s + suffix


COPY_COLUMNS = [
    ("本日", "day_chg", 1, "%", True), ("高値から", "from_high", 1, "%", False),
    ("2年上昇", "ret_2y", 0, "%", True), ("時価総額(億)", "cap_oku", 0, "", False),
    ("PER", "per", 1, "", False), ("PBR", "pbr", 2, "", False), ("PEG", "peg", 2, "", False),
    ("営業利益率", "op_margin", 1, "%", False), ("増収率", "rev_growth", 1, "%", True),
    ("増益率", "earn_growth", 1, "%", True), ("経営陣保有", "insider", 1, "%", False),
]


def to_copy_text(rows, updated):
    """Claude などに貼り付けて共有するためのタブ区切りテキスト"""
    head = ["順位", "銘柄", "コード", "スコア", "点数の内訳", "シグナル", "テーマ", "株価"] + [c[0] for c in COPY_COLUMNS]
    lines = [f"テンバガー候補ランキング（データ取得: {updated} JST）", "\t".join(head)]
    for i, r in enumerate(rows, 1):
        cells = [str(i), r["name"], r["code"], str(r["score"]),
                 " ".join(f"{l}{p:+d}" for l, p, _ in r["breakdown"]) or "-",
                 " ".join(sig for sig, _ in r["signals"]) or "-",
                 r["theme"], _fmt(r["price"], 0)]
        cells += [_fmt(r[k], d, suf, sign) for _, k, d, suf, sign in COPY_COLUMNS]
        lines.append("\t".join(cells))
    return "\n".join(lines)


@bp.route("/tenbagger")
def tenbagger():
    extra_str = request.args.get("tickers", "")
    extra = []
    for t in extra_str.split(","):
        t = t.strip().upper()
        if not t:
            continue
        if t.isdigit() or (len(t) == 4 and t[:3].isdigit()):
            t += ".T"
        extra.append(t)
    rows = collect(extra)
    jst = timezone(timedelta(hours=9))
    updated = datetime.fromtimestamp(_cache["time"], jst).strftime("%Y/%m/%d %H:%M")
    return render_template_string(HTML, rows=rows, rules=RULES, fmt=_fmt, profiles=PROFILES,
                                  peg_max_per=PEG_MAX_PER, dip_min=DIP_MIN_RET_2Y, peg_cap=PEG_GROWTH_CAP, spike=SPIKE_GROWTH, extra_str=extra_str, updated=updated,
                                  copy_text=to_copy_text(rows, updated))


HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>テンバガー候補</title>
<link rel="apple-touch-icon" href="/static/icons/tenbagger-180.png">
<link rel="icon" type="image/png" sizes="512x512" href="/static/icons/tenbagger-512.png">
<meta name="apple-mobile-web-app-title" content="10x候補">
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; padding: 10px; background: #f4f6f9; color: #333; }
  .nav { display: flex; gap: 6px; margin-bottom: 8px; }
  .nav a { padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 13px; font-weight: bold; background: #e2e8f0; color: #334155; }
  .nav a.active { background: #2563eb; color: #fff; }
  h3 { margin: 10px 0; font-size: 16px; color: #1e293b; }
  .meta { font-size: 11px; color: #64748b; margin-bottom: 8px; }
  .control-panel { background: #fff; padding: 12px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 13px; }
  input[type="text"] { padding: 6px; width: 180px; border: 1px solid #cbd5e1; border-radius: 4px; }
  button { padding: 6px 12px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
  .btn-clear { background: #dc2626; margin-left: 4px; }
  .filters { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 10px; }
  .table-container { overflow-x: auto; max-width: 100%; border: 1px solid #cbd5e1; background: #fff; border-radius: 6px; margin-bottom: 20px; }
  table { border-collapse: collapse; width: 100%; font-size: 11px; white-space: nowrap; }
  th, td { padding: 7px 5px; text-align: center; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; }
  th { background: #f1f5f9; font-weight: bold; position: sticky; top: 0; z-index: 2; cursor: pointer; user-select: none; color: #475569; }
  th:hover { background: #cbd5e1; }
  .fixed-name { position: sticky; left: 0; background: #fff; z-index: 1; box-shadow: 2px 0 5px rgba(0,0,0,0.05); text-align: left; font-weight: bold; }
  th.fixed-name { z-index: 3; background: #f1f5f9; }
  .code { color: #64748b; font-weight: normal; font-size: 10px; }
  .high-score { background-color: #dcfce7 !important; color: #15803d !important; font-weight: bold; }
  .low-score { background-color: #fee2e2 !important; color: #b91c1c !important; }
  .up { color: #dc2626; } .down { color: #2563eb; }
  .good { color: #15803d; font-weight: bold; }
  .sig { display: inline-block; padding: 1px 4px; border-radius: 3px; font-size: 9px; font-weight: bold; margin: 1px; }
  .sig-red { background: #fee2e2; color: #b91c1c; }
  .sig-yellow { background: #fef9c3; color: #a16207; }
  .sig-green { background: #dcfce7; color: #15803d; }
  .sig-gray { background: #f1f5f9; color: #475569; }
  .pt { display: inline-block; padding: 1px 4px; border-radius: 3px; font-size: 9px; margin: 1px; }
  .pt-plus { background: #eff6ff; color: #1e40af; }
  .pt-minus { background: #fef2f2; color: #b91c1c; }
  .formula { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 8px; font-family: monospace; font-size: 11px; white-space: pre-wrap; }
  .copy-area { width: 100%; box-sizing: border-box; height: 120px; font-size: 10px; font-family: monospace; border: 1px solid #ccc; padding: 5px; white-space: pre; overflow: auto; }
  .profile { border-bottom: 1px solid #e2e8f0; padding: 8px 0; }
  .profile-head { font-weight: bold; margin-bottom: 4px; color: #0f172a; }
  .profile-head a { font-weight: normal; font-size: 11px; margin-left: 6px; }
  .docs table { white-space: normal; font-size: 11px; }
  .docs { background: #fff; padding: 15px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 12px; line-height: 1.6; color: #334155; margin-bottom: 15px; }
  .docs h4 { margin-top: 0; font-size: 14px; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; margin-bottom: 10px; }
  .docs ul { padding-left: 20px; margin: 8px 0; }
  .docs li { margin-bottom: 4px; }
</style>
</head>
<body>
  <div class="nav">
    <a href="/">📊 戦略司令室</a>
    <a href="/tenbagger" class="active">🚀 テンバガー候補</a>
  </div>
  <h3>🚀 テンバガー候補ランキング（半導体・AI 中小型株）</h3>
  <div class="meta">データ取得: {{ updated }}（Yahoo!ファイナンス・株価は約20分遅れ／10分間は同じ結果を表示）</div>

  <div class="control-panel">
    <form method="GET" action="/tenbagger">
      <label>➕ 銘柄の追加（4桁コード）: </label>
      <input type="text" id="tickerInput" name="tickers" placeholder="例: 6920, 7735" value="{{ extra_str }}">
      <button type="submit" onclick="try{localStorage.setItem('kabu_tb_tickers', document.getElementById('tickerInput').value.trim())}catch(e){}">追加・更新</button>
      <button type="button" class="btn-clear" onclick="try{localStorage.removeItem('kabu_tb_tickers')}catch(e){}; window.location.href='/tenbagger';">クリア</button>
    </form>
    <div style="margin-top:8px;">
      <button type="button" onclick="copyTable()">📋 表を丸ごとコピー（Claude共有用）</button>
      <span id="copyMsg" style="font-size:12px; color:#15803d; margin-left:6px;"></span>
    </div>
    <div class="filters">
      <label><input type="checkbox" id="fCap" onchange="applyFilter()"> 時価総額1,000億円以下だけ</label>
      <label><input type="checkbox" id="fSig" onchange="applyFilter()"> シグナルありだけ</label>
    </div>
  </div>

  <div class="table-container">
    <table id="tbTable">
      <thead>
        <tr>
          <th onclick="sortTable(0)">順位 ↕</th>
          <th class="fixed-name" onclick="sortTable(1, false)">銘柄 ↕</th>
          <th onclick="sortTable(2)">スコア ↕</th>
          <th>点数の内訳</th>
          <th>シグナル</th>
          <th onclick="sortTable(5, false)">テーマ ↕</th>
          <th onclick="sortTable(6)">株価 ↕</th>
          <th onclick="sortTable(7)">本日 ↕</th>
          <th onclick="sortTable(8)">高値から ↕</th>
          <th onclick="sortTable(9)">2年上昇 ↕</th>
          <th onclick="sortTable(10)">時価総額(億) ↕</th>
          <th onclick="sortTable(11)">PER ↕</th>
          <th onclick="sortTable(12)">PBR ↕</th>
          <th onclick="sortTable(13)">PEG ↕</th>
          <th onclick="sortTable(14)">営業利益率 ↕</th>
          <th onclick="sortTable(15)">増収率 ↕</th>
          <th onclick="sortTable(16)">増益率 ↕</th>
          <th onclick="sortTable(17)">経営陣保有 ↕</th>
        </tr>
      </thead>
      <tbody>
      {% for r in rows %}
        <tr data-cap="{{ r['cap_oku'] if r['cap_oku'] == r['cap_oku'] else '' }}" data-sig="{{ r['signals']|length }}">
          <td>{{ loop.index }}</td>
          <td class="fixed-name">{{ r['name'] }} <span class="code">{{ r['code'] }}</span></td>
          <td class="{% if r['score'] >= 60 %}high-score{% elif r['score'] <= 25 %}low-score{% endif %}">{{ r['score'] }}点</td>
          <td style="text-align:left">{% for l, p, d in r['breakdown'] %}<span class="pt {{ 'pt-plus' if p > 0 else 'pt-minus' }}" title="{{ d }}">{{ l }}{{ '%+d' % p }}</span>{% else %}-{% endfor %}</td>
          <td style="text-align:left">{% for s, c in r['signals'] %}<span class="sig {{ c }}">{{ s }}</span>{% endfor %}</td>
          <td>{{ r['theme'] }}</td>
          <td>{{ fmt(r['price'], 0) }}</td>
          <td class="{% if r['day_chg'] > 0 %}up{% elif r['day_chg'] < 0 %}down{% endif %}">{{ fmt(r['day_chg'], 1, '%', True) }}</td>
          <td>{{ fmt(r['from_high'], 1, '%') }}</td>
          <td>{{ fmt(r['ret_2y'], 0, '%', True) }}</td>
          <td class="{% if r['cap_oku'] <= 1000 %}good{% endif %}">{{ fmt(r['cap_oku'], 0) }}</td>
          <td>{{ fmt(r['per'], 1) }}</td>
          <td class="{% if r['pbr'] <= 1 %}good{% endif %}">{{ fmt(r['pbr'], 2) }}</td>
          <td class="{% if r['peg'] <= 1 %}good{% endif %}">{{ fmt(r['peg'], 2) }}</td>
          <td class="{% if r['op_margin'] >= 10 %}good{% endif %}">{{ fmt(r['op_margin'], 1, '%') }}</td>
          <td>{{ fmt(r['rev_growth'], 1, '%', True) }}</td>
          <td>{{ fmt(r['earn_growth'], 1, '%', True) }}</td>
          <td>{{ fmt(r['insider'], 1, '%') }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <div class="docs">
    <h4>🏢 上位10社の事業内容と注目点</h4>
    {% for r in rows[:10] %}
    <div class="profile">
      <div class="profile-head">{{ loop.index }}位　{{ r['name'] }} <span class="code">{{ r['code'] }}</span>　<strong>{{ r['score'] }}点</strong>
        <a href="https://kabutan.jp/stock/?code={{ r['code'] }}" target="_blank" rel="noopener">株探で見る ↗</a></div>
      {% set p = profiles.get(r['code']) %}
      {% if p %}
      <div><strong>何をしている会社か：</strong>{{ p[0] }}</div>
      <div><strong>注目点・注意点：</strong>{{ p[1] }}</div>
      {% else %}
      <div>（追加した銘柄のため解説なし。「株探で見る」から確認してください）</div>
      {% endif %}
    </div>
    {% endfor %}
    <p style="font-size:11px; color:#64748b;">※解説は2026年10月時点のWeb情報をもとに作成しています。最新の業績は決算短信でご確認ください。</p>
  </div>

  <div class="docs">
    <h4>📋 共有用テキスト（ボタンが使えないときは、ここを全選択してコピー）</h4>
    <textarea id="copyArea" class="copy-area" readonly onclick="this.select()">{{ copy_text }}</textarea>
  </div>

  <div class="docs">
    <h4>🧮 スコアの計算式</h4>
    <div class="formula">スコア ＝ 下の表の各項目で「当てはまった点数」を合計（0〜100点に収める）
・各項目は上の行から順に判定し、最初に当てはまった1つだけを採用
・データがない項目（表で「-」）は0点扱い（加点も減点もしない）
・「押し目」は、売上が伸びている（またはデータなし）ときだけ加点 ＝ 業績悪化で下がった株は除外
・「押し目」は、2年で+{{ dip_min }}%以上上がっている株だけ加点 ＝ ずっと低迷している株は除外（上昇中の株が一時的に下がった場面だけを拾う）
・「PEG」は、PERが{{ peg_max_per }}倍以下のときだけ加点 ＝ そもそも割高な株は除外
・PEGの計算に使う増益率は最大{{ peg_cap }}%まで ＝ 前年の利益が小さすぎた反動の異常値で満点にならないように
・増益率が{{ spike }}%を超えたら「⚠️増益率が異常に大きい」の目印（前年が小さかった反動の可能性）</div>
    <table>
      <thead><tr><th>項目</th><th>条件</th><th>点数</th></tr></thead>
      <tbody>
      {% for label, key, conds in rules %}{% for cond, pts, desc in conds %}
        <tr>{% if loop.first %}<td rowspan="{{ conds|length }}"><strong>{{ label }}</strong></td>{% endif %}<td style="text-align:left">{{ desc }}</td><td>{{ '%+d' % pts }}</td></tr>
      {% endfor %}{% endfor %}
      </tbody>
    </table>
    <p>満点の目安：小型20＋増収15＋増益10＋利益率15＋PEG15＋PBR10＋（出遅れ10 または 押し目10）＋オーナー5 ＝ 100点。出遅れ（2年+50%以下）と押し目（2年+50%以上）は同時には付かない。60点以上を緑、25点以下を赤で表示。</p>

    <h4>📐 各指標の計算式</h4>
    <div class="formula">本日        ＝ (現在の株価 ÷ 前日の終値 − 1) × 100
高値から    ＝ (現在の株価 ÷ 直近1年の最高値 − 1) × 100
2年上昇     ＝ (現在の株価 ÷ 2年前の株価 − 1) × 100
時価総額    ＝ 株価 × 発行済株式数（億円）
PER         ＝ 株価 ÷ 予想1株利益（予想がなければ実績）
PBR         ＝ 株価 ÷ 1株あたり純資産
PEG         ＝ PER ÷ 増益率（%、最大100%）   … 1以下なら「成長のわりに安い」
営業利益率  ＝ 営業利益 ÷ 売上高 × 100（直近1年）
増収率      ＝ 直近四半期の売上 ÷ 前年同期の売上 − 1
増益率      ＝ 直近四半期の利益 ÷ 前年同期の利益 − 1
経営陣保有  ＝ 経営陣・関係者が持つ株の割合</div>
    <p>各銘柄の「点数の内訳」にカーソルを合わせる（スマホは長押し）と、当てはまった条件が表示されます。</p>
    <p>データ元：Yahoo!ファイナンス（株価は約20分遅れ、財務は最新の決算を反映）。</p>
    <p>※銘柄選びの補助ツールです。数値は必ず決算短信などでご確認のうえ、投資判断はご自身で行ってください。</p>
  </div>

<script>
  document.addEventListener("DOMContentLoaded", function() {
    var saved = null;
    try { saved = localStorage.getItem("kabu_tb_tickers"); } catch (e) {}
    var params = new URLSearchParams(window.location.search);
    if (!params.get("tickers") && saved) {
      window.location.href = "/tenbagger?tickers=" + encodeURIComponent(saved);
    }
  });

  function copyTable() {
    var area = document.getElementById("copyArea");
    var msg = document.getElementById("copyMsg");
    function done() { msg.textContent = "✅ コピーしました。Claudeのチャットに貼り付けてください"; }
    function fallback() {
      area.select();
      try { document.execCommand("copy"); done(); }
      catch (e) { msg.textContent = "コピーできませんでした。ページ下の共有用テキストを全選択してコピーしてください"; }
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(area.value).then(done, fallback);
    } else {
      fallback();
    }
  }

  function applyFilter() {
    var cap = document.getElementById("fCap").checked;
    var sig = document.getElementById("fSig").checked;
    document.querySelectorAll("#tbTable tbody tr").forEach(function(tr) {
      var c = parseFloat(tr.dataset.cap);
      var show = true;
      if (cap && !(c <= 1000)) show = false;
      if (sig && tr.dataset.sig === "0") show = false;
      tr.style.display = show ? "" : "none";
    });
  }

  var sortDir = {};
  function sortTable(n, isNum) {
    if (isNum === undefined) isNum = true;
    var tbody = document.querySelector("#tbTable tbody");
    var rows = Array.prototype.slice.call(tbody.rows);
    var dir = sortDir[n] = sortDir[n] === "desc" ? "asc" : "desc";
    rows.sort(function(a, b) {
      var x = a.cells[n].textContent.trim(), y = b.cells[n].textContent.trim();
      if (isNum) {
        var nx = parseFloat(x.replace(/[^0-9.-]+/g, "")), ny = parseFloat(y.replace(/[^0-9.-]+/g, ""));
        if (isNaN(nx)) return 1;
        if (isNaN(ny)) return -1;
        return dir === "desc" ? ny - nx : nx - ny;
      }
      return dir === "desc" ? y.localeCompare(x, "ja") : x.localeCompare(y, "ja");
    });
    rows.forEach(function(r) { tbody.appendChild(r); });
  }
</script>
</body>
</html>
"""
