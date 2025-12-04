"""
movie_scraper.py
爬取 https://ssr1.scrape.center/ 的前 10 頁（page/1 ~ page/10），
解析每頁中的電影資訊並存成 movie.csv

注意：此腳本盡量使用健壯的選取器與備援機制來處理不同的 HTML 結構。
如果網站之後改版或使用 heavy JS，可能需要改為 Selenium 或 Playwright。

使用方式：
    python movie_scraper.py

輸出：
    movie.csv (欄位：title,image_url,rating,types,page,detail_url)

"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import random
from urllib.parse import urljoin

BASE = "https://ssr1.scrape.center"
OUT_CSV = "movie.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/114.0 Safari/537.36"
}


def fetch(url, timeout=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[WARN] fetch failed for {url}: {e}")
        return None


def parse_movie_card(card, page_url):
    """嘗試從一個 movie card element 擷取所需欄位。
    使用多個 CSS 選擇器的備援策略來提高成功率。
    回傳 dict。
    """
    data = {
        "title": "",
        "image_url": "",
        "rating": "",
        "types": "",
        "detail_url": "",
    }

    # 1) title: 常見在 <h2>, .name, a[title]
    title_selectors = [
        'h2',
        '.name',
        'a[title]',
        'a.movie-name',
        '.el-card__header h2',
    ]
    for sel in title_selectors:
        node = card.select_one(sel)
        if node:
            # 取 text 或 title 屬性
            if node.has_attr('title') and node['title'].strip():
                data['title'] = node['title'].strip()
            else:
                data['title'] = node.get_text(strip=True)
            if data['title']:
                break

    # 2) detail_url: a[href]
    a = None
    if card.select_one('a[href]'):
        a = card.select_one('a[href]')
    elif card.find('a'):
        a = card.find('a')
    if a and a.has_attr('href'):
        data['detail_url'] = urljoin(BASE, a['href'])

    # 3) image url: <img src=...> 或 data-src
    img = card.find('img')
    if img:
        src = img.get('src') or img.get('data-src') or img.get('data-original')
        if src:
            data['image_url'] = urljoin(BASE, src)

    # 4) rating: class 名稱可能是 score、rating、score-number
    rating_selectors = ['.score', '.rating', '.en .score', '.info .score', '.score-number']
    for sel in rating_selectors:
        node = card.select_one(sel)
        if node:
            data['rating'] = node.get_text(strip=True)
            break
    # 有些站會把 rating 放在 attribute
    if not data['rating']:
        if card.has_attr('data-score'):
            data['rating'] = card['data-score']

    # 5) types / categories: 常見在 .types, .genres, .category
    type_selectors = ['.types', '.genre', '.genres', '.categories', '.meta', '.info .tags']
    types_found = []
    for sel in type_selectors:
        nodes = card.select(sel)
        if nodes:
            for n in nodes:
                txt = n.get_text(strip=True)
                if txt:
                    types_found.append(txt)
            if types_found:
                break
    # 另外嘗試在整個 card 中查找小的 <span> 或 <p> 標籤，可能包含類型資料
    if not types_found:
        spans = card.find_all(['span', 'p'], limit=6)
        for s in spans:
            txt = s.get_text(strip=True)
            # 假如包含中文或英文字樣且較短，視為可能的類型（heuristic）
            if txt and 1 <= len(txt) <= 40 and any(c.isalpha() for c in txt) or any('\u4e00' <= c <= '\u9fff' for c in txt):
                types_found.append(txt)
    # 合併並過濾
    if types_found:
        clean = []
        for t in types_found:
            t = t.replace('\n', ' ').strip()
            if t and t.lower() not in ['new', '2020', '2021']:
                clean.append(t)
        data['types'] = ';'.join(dict.fromkeys(clean))  # 去重並以 ; 分隔

    return data


def scrape_pages(start=1, end=10):
    rows = []
    for i in range(start, end + 1):
        page_url = f"{BASE}/page/{i}"
        print(f"[INFO] Fetching page {i}: {page_url}")
        html = fetch(page_url)
        if not html:
            print(f"[WARN] No HTML for page {i}, skipping")
            continue
        soup = BeautifulSoup(html, 'html.parser')

        # 嘗試找到每個電影卡片（多個選擇器的備援）
        card_selectors = [
            '.movie-item',
            '.el-card.movie-item',
            '.el-card',
            '.card',
            '.item',
            '.movie'  # 容錯
        ]
        cards = []
        for sel in card_selectors:
            found = soup.select(sel)
            if found and len(found) >= 1:
                cards = found
                break

        # 如果仍找不到，嘗試搜尋所有 article、li 標籤並在其中解析
        if not cards:
            possible = soup.find_all(['article', 'li', 'div'])
            # 盡量挑取包含 img 與 a 的節點
            for p in possible:
                if p.find('img') and p.find('a'):
                    cards.append(p)
            # 若還是空代表這頁結構與我們預期不同

        print(f"[INFO] Found {len(cards)} candidate cards on page {i}")

        for c in cards:
            data = parse_movie_card(c, page_url)
            # 附加頁碼跟原始頁面 URL
            data['page'] = i
            # 若完全沒有 title 就跳過
            if not data['title']:
                # 嘗試從 card 的 alt/title attribute 後補
                if c.find('img') and c.find('img').has_attr('alt'):
                    data['title'] = c.find('img')['alt'].strip()
            if not data['title']:
                # skip
                continue
            rows.append(data)

        # 禮貌等待
        time.sleep(0.6 + random.random() * 1.2)

    return rows


def save_csv(rows, path=OUT_CSV):
    if not rows:
        print("[WARN] No rows to save")
        return
    fieldnames = ['title', 'image_url', 'rating', 'types', 'page', 'detail_url']
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, '') for k in fieldnames})
    print(f"[INFO] Saved {len(rows)} rows to {path}")


if __name__ == '__main__':
    scraped = scrape_pages(1, 10)
    save_csv(scraped)

    # 小範例列印前 5 筆
    for i, r in enumerate(scraped[:5], 1):
        print(f"{i}. {r['title']} | {r.get('rating','')} | {r.get('types','')}")

    print("Done.")
