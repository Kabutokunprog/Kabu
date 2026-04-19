import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
import pandas as pd
import time
import os
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 設定エリア
# ==========================================
GEMINI_API_KEY = "AIzaSyBMqlEgTM5Q4lqTnWtcusHRWFZFHI67ey8" 
# 2.0が枯渇している場合、1.5-flashに変えると動く可能性があります
MODEL_NAME = "gemini-1.5-flash" 

client = genai.Client(api_key=GEMINI_API_KEY)

NEGATIVE = "-経済新聞 -PRTIMES -プレスリリース -市場調査 -予測レポート -サプリ -食品"

SEARCH_QUERIES = {
    "👑最優先:素材サブスク": f"(旭化成 OR 信越化学 OR 三菱ケミカル OR 東レ) (サービス化 OR ソリューション OR 脱モノ売り) when:7d {NEGATIVE}",
    "データセンタ冷却": f"データセンター (液浸冷却 OR 冷却液 OR TIM OR 振動対策) when:7d {NEGATIVE}",
    "次世代電池・水素": f"(全固体電池 OR PEM OR 水電解 OR バッテリーリサイクル) when:7d {NEGATIVE}",
    "ロボ・自動運転": f"(タクタイルセンサ OR 触覚デバイス OR 4Dレーダー OR メモリスタ) when:7d {NEGATIVE}",
    "ディスプレイ・AR/VR": f"(マイクロLED OR 量子ドット OR ARグラス 材料) when:7d {NEGATIVE}",
    "温度センシング": f"(二次元温度 OR 感温材料 OR 温度分布センサ) when:7d {NEGATIVE}",
    "ライフ・宇宙": f"(病理診断 課題 OR 宇宙用樹脂 OR 宇宙材料 放射線) when:7d {NEGATIVE}"
}

def micro_batch_analyze_with_retry(article_subset, category, max_retries=3):
    """429エラーが出た際、指定秒数待機して再試行する（粘り強さ重視）"""
    if not article_subset: return []
    
    titles_text = "\n".join([f"・{a['title']}" for a in article_subset])
    prompt = f"""
    あなたは東工大卒の材料工学専門家で、大手化学メーカー部長の「たけさん」の技術秘書です。
    カテゴリ【{category}】のニュースを読み、具体的な社名・技術名を用いて3行以内で提言せよ。
    各提言の末尾に「||」をつけよ。
    
    【ニュース】
    {titles_text}
    """

    for attempt in range(max_retries):
        try:
            config = types.GenerateContentConfig(
                safety_settings=[types.SafetySetting(category=c, threshold="BLOCK_NONE") for c in 
                                ["HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
            )
            response = client.models.generate_content(model=MODEL_NAME, contents=prompt, config=config)
            return [s.strip() for s in response.text.strip().split('||') if len(s.strip()) > 3]
        
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = 15 * (attempt + 1)
                print(f"   ⚠️ 枠制限エラー。{wait_time}秒待機して再送します（試行 {attempt + 1}/{max_retries}）")
                time.sleep(wait_time)
            else:
                print(f"   ⚠️ 解析エラー: {e}")
                break
                
    return ["解析枠が終了しました。明日また実行してください。"] * len(article_subset)

def search_google_news(query):
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all('item')
        articles = []
        seen_titles = set()
        for item in items[:12]:
            title = item.title.text
            if title not in seen_titles:
                articles.append({'title': title, 'link': item.link.text, 'pubDate': item.pubDate.text})
                seen_titles.add(title)
        return articles
    except: return []

def main():
    today_str = datetime.now().strftime("%Y%m%d_%H%M")
    save_filename = f"Take_Intelligence_{today_str}.xlsx"
    save_path = os.path.expanduser(f"~/Desktop/{save_filename}")

    print(f"🚀 TIE Ver 2.8 起動。モデル『{MODEL_NAME}』で再挑戦します。\n")
    
    all_data = []

    for category, query in SEARCH_QUERIES.items():
        print(f"🔍 調査中: {category}...")
        articles = search_google_news(query)
        print(f"   >> {len(articles)}件 取得完了。")
        
        category_suggestions = []
        for i in range(0, len(articles), 3):
            subset = articles[i : i + 3]
            print(f"     ・{i+1}〜{i+len(subset)}件目を解析中...")
            batch_res = micro_batch_analyze_with_retry(subset, category)
            category_suggestions.extend(batch_res)
            time.sleep(5) 

        for i, article in enumerate(articles):
            all_data.append({
                '重要度': '★' if '👑' in category else '-',
                'ジャンル': category,
                'トピックス': article['title'],
                'AI秘書の提言': category_suggestions[i] if i < len(category_suggestions) else "-",
                '日付': article['pubDate'],
                'URL': article['link']
            })

    if all_data:
        df = pd.DataFrame(all_data)
        with pd.ExcelWriter(save_path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='LatestReport')
        print(f"\n✨ 完了！デスクトップの『{save_filename}』を確認してください。")

if __name__ == "__main__":
    main()