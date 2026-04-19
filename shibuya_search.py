import requests
from bs4 import BeautifulSoup
from google import genai
import time
import re # 数字判定用のライブラリ

# --- 設定エリア ---
GEMINI_API_KEY = "AIzaSyBMqlEgTM5Q4lqTnWtcusHRWFZFHI67ey8" 
LIST_URL = "https://fujoho.jp/index.php?p=shop_list&a=16&k=38"

client = genai.Client(api_key=GEMINI_API_KEY)

def ask_ai_if_free(shop_name, text):
    prompt = f"""
    あなたは優秀な秘書です。以下の店舗情報を読み、
    「東京都渋谷区」への出張費・交通費・派遣料が【完全に無料】か判定してください。

    【店舗名】: {shop_name}
    【テキスト】: {text[:2000]}

    判定ルール：
    - 渋谷区への派遣が「無料」「0円」「タダ」であれば 'FREE'
    - 有料（1000円〜など）、または不明なら 'PAID'
    - 回答は 'FREE' または 'PAID' の一言のみで出力。
    """
    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
        return response.text.strip()
    except:
        return "ERROR"

def main():
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    print("1. 店舗IDを特定して、個別ページのみを抽出しています...")
    
    try:
        res = requests.get(LIST_URL, headers=headers, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.content, 'html.parser')
    except Exception as e:
        print(f"接続エラー: {e}")
        return

    shops = []
    # 【たけさんのアイデアを採用！】
    # URLに 'id=' が含まれるものだけを抽出する
    for a in soup.find_all('a', href=True):
        url = a['href']
        if 'id=' in url and 'p=shop' in url:
            # 「p=shop_list」などの「list」が含まれるものは除外（念のため）
            if 'list' in url:
                continue
                
            full_url = "https://fujoho.jp/" + url if not url.startswith('http') else url
            if full_url not in [s['url'] for s in shops]:
                shops.append({'url': full_url})

    if not shops:
        print("個別店舗（ID付きURL）が見つかりませんでした。")
        return

    print(f"2. 本物の店舗が {len(shops)} 件見つかりました。精査を開始します...\n")

    for i, shop in enumerate(shops):
        print(f"[{i+1}/{len(shops)}] 解析中: {shop['url']}")
        time.sleep(2) # 相手サーバーへのマナー
        
        try:
            detail_res = requests.get(shop['url'], headers=headers, timeout=5)
            detail_res.encoding = detail_res.apparent_encoding
            detail_soup = BeautifulSoup(detail_res.content, 'html.parser')
            
            # 店名取得
            shop_name = "不明な店舗"
            if detail_soup.find('h1'):
                shop_name = detail_soup.find('h1').text.strip()
            elif detail_soup.title:
                shop_name = detail_soup.title.text.strip().split('|')[0] # タイトルの前半だけ取る

            print(f"   >> AI判定中: {shop_name}...")
            page_text = detail_soup.get_text()
            result = ask_ai_if_free(shop_name, page_text)

            if "FREE" in result:
                print(f"   ✅【渋谷区無料！】確定：{shop_name}")
                print("-" * 40)
            else:
                print(f"   ❌ 非該当（有料または不明）")
        except:
            print("   ⚠️ 通信エラーによりスキップ")

    print("\nすべての解析が完了しました！")

if __name__ == "__main__":
    main()