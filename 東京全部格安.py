import requests
from bs4 import BeautifulSoup
import time
import re
import pandas as pd
import os

# --- 設定エリア ---
# たけさん指定の新しいURL（ページ番号 b= を除いたもの）
BASE_URL = "https://fujoho.jp/index.php?p=shop_list&t=13&k=38"
# 保存先のパス（デスクトップ）
SAVE_PATH = os.path.expanduser("~/Desktop/shop_list.xlsx")

def extract_plans(text):
    """テキストからプランを抽出（60分以上 且つ 12,000円以下）"""
    results = []
    # 「60分 10000円」などの数字パターンを検索
    patterns = re.findall(r'(\d+)分.*?(\d{1,3}(?:,\d{3})?)円', text)
    
    for p_time, p_price in patterns:
        time_val = int(p_time)
        price_val = int(p_price.replace(',', ''))
        
        # 条件：60分以上 且つ 3000円〜12000円
        if time_val >= 60 and 3000 <= price_val <= 12000:
            results.append(f"{time_val}分 {price_val}円")
            
    # 重複を消して、時間の短い順に並び替え
    return ", ".join(sorted(list(set(results)), key=lambda x: int(x.split('分')[0])))

def main():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://fujoho.jp/'
    }
    
    page_num = 0
    all_seen_ids = set() # 重複チェック用
    all_data = []        # エクセル用

    print(f"🚀 新エリア（t=13, k=38）のスキャンを開始します（60分1.2万円以下）\n")

    while True:
        # ページURLを生成 (b=0, 1, 2...)
        current_url = f"{BASE_URL}&b={page_num}"
        print(f"--- {page_num + 1}ページ目を調査中... ---")
        
        try:
            res = requests.get(current_url, headers=headers, timeout=10)
            res.encoding = res.apparent_encoding
            soup = BeautifulSoup(res.content, 'html.parser')
        except Exception as e:
            print(f"❌ 接続エラー: {e}")
            break

        # ページ内のお店のリンクをすべて取得
        all_links = soup.find_all('a', href=True)
        temp_shops = {}
        
        for link in all_links:
            url = link['href']
            if 'p=shop' in url and 'id=' in url:
                shop_id = url.split('id=')[-1].split('&')[0]
                
                if shop_id not in temp_shops:
                    # リンクの親要素を辿って周辺テキストを確保
                    container = link.parent.parent.parent
                    text = container.get_text(separator=" ", strip=True)
                    
                    name = link.text.strip()
                    # ゴミデータを排除
                    if len(name) < 2 or any(x in name for x in ["すぐヒメ", "割引", "出勤", "口コミ", "日記"]):
                        continue
                        
                    temp_shops[shop_id] = {
                        '店名': name,
                        'URL': "https://fujoho.jp/" + url if not url.startswith('http') else url,
                        'text': text
                    }

        # 【終了判定】このページの全IDが「既に見たもの」なら終了
        current_page_ids = set(temp_shops.keys())
        if not current_page_ids or current_page_ids.issubset(all_seen_ids):
            print("\n🏁 最終ページ、または重複ページに到達しました。")
            break
            
        all_seen_ids.update(current_page_ids)

        # プラン精査
        for shop_id, info in temp_shops.items():
            plans = extract_plans(info['text'])
            if plans:
                print(f" ✅ 発見: {info['店名']}")
                # エクセルのHYPERLINK関数を作成
                excel_link = f'=HYPERLINK("{info["URL"]}", "ショップを開く")'
                all_data.append({
                    '店名': info['店名'],
                    '該当プラン': plans,
                    'リンク': excel_link
                })

        page_num += 1
        # 安全策：50ページを超えたら停止
        if page_num > 50: break
        time.sleep(1.5)

    # --- エクセル出力処理 ---
    if all_data:
        print(f"\n📊 データをエクセルに書き込んでいます...")
        df = pd.DataFrame(all_data)
        
        with pd.ExcelWriter(SAVE_PATH, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='お宝リスト')
            
            # 列の幅を調整して見やすくする
            worksheet = writer.sheets['お宝リスト']
            worksheet.column_dimensions['A'].width = 30 # 店名
            worksheet.column_dimensions['B'].width = 45 # 該当プラン
            worksheet.column_dimensions['C'].width = 18 # リンク
            
        print(f"✨ 完了！デスクトップの '{os.path.basename(SAVE_PATH)}' を確認してください。")
    else:
        print("\n該当する店舗は見つかりませんでした。")

if __name__ == "__main__":
    main()