import requests
from bs4 import BeautifulSoup
import re
import json
import time

# --- AYARLAR ---
BASE_URL = "https://www.hdfilmizle.life"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.hdfilmizle.life/",
    "Origin": "https://www.hdfilmizle.life",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

def get_soup(url):
    """Verilen URL'ye istek atıp BeautifulSoup objesi döndürür."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Hata ({url}): {e}")
        return None

def unpack_js(packed_js):
    """
    Vidrame gibi playerların kullandığı 'eval(function(p,a,c,k,e,r)...)' 
    şifrelemesini çözer (Dean Edwards Unpacker).
    """
    try:
        pattern = r"}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)"
        match = re.search(pattern, packed_js)
        
        if not match:
            return packed_js
            
        payload, radix, count, keywords = match.groups()
        keywords = keywords.split('|')
        radix = int(radix)
        
        def baseN(num, b):
            return ((num == 0) and "0") or (baseN(num // b, b).lstrip("0") + "0123456789abcdefghijklmnopqrstuvwxyz"[num % b])

        unpacked_source = payload
        for i, keyword in enumerate(keywords):
            if keyword:
                key = baseN(i, radix)
                unpacked_source = re.sub(r'\b' + key + r'\b', keyword, unpacked_source)
        
        return unpacked_source
    except:
        return packed_js

def clean_url(url):
    """
    JSON içinden gelen 'https:\/\/...' formatını 'https://...' formatına çevirir.
    ATV kodundaki fix_fake_url mantığına benzer.
    """
    if not url: return None
    # Ters eğik çizgileri temizle
    url = url.replace('\\/', '/')
    # HTML entity temizliği (gerekirse)
    url = url.encode('utf-8').decode('unicode_escape') if '\\u' in url else url
    return url

def extract_stream_data(iframe_url):
    """
    Iframe içindeki M3U8 ve VTT dosyalarını bulur.
    """
    try:
        # Iframe URL'sini temizle
        iframe_url = clean_url(iframe_url)
        
        # Player istekleri için Referer çok önemlidir
        player_headers = HEADERS.copy()
        
        response = requests.get(iframe_url, headers=player_headers, timeout=20)
        content = response.text
        
        # JS Şifreliyse çöz
        if "eval(function" in content:
            content = unpack_js(content)
        
        m3u8_url = None
        vtt_files = []

        # 1. M3U8 Ara (Regex ile)
        # Genellikle: file:"https://..." veya src:"https://..."
        m3u8_matches = re.findall(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', content)
        if m3u8_matches:
            # En uzun olanı genelde master playlisttir
            m3u8_url = clean_url(m3u8_matches[0])

        # 2. VTT Ara (Regex ile)
        # Genellikle: file:"https://...vtt"
        vtt_matches = re.findall(r'(https?://[^"\'\s]+\.vtt[^"\'\s]*)', content)
        for vtt in vtt_matches:
            clean_vtt = clean_url(vtt)
            if clean_vtt not in vtt_files:
                vtt_files.append(clean_vtt)
                
        return m3u8_url, vtt_files

    except Exception as e:
        print(f"    - Stream alma hatası: {e}")
        return None, []

def main():
    print("🚀 HD Film Scraper Başlatılıyor...")
    
    soup = get_soup(BASE_URL)
    if not soup: return

    movies_data = []
    
    # Filmleri bul
    movie_items = soup.select("#moviesListResult a.poster")
    print(f"Toplam {len(movie_items)} film bulundu.")

    for item in movie_items:
        try:
            title = item.get("title")
            page_href = item.get("href")
            
            # Linki tamamlama
            movie_link = BASE_URL + page_href if not page_href.startswith("http") else page_href
            
            # Görseli alma
            img_tag = item.find("img")
            poster_url = ""
            if img_tag:
                raw_src = img_tag.get("data-src") or img_tag.get("src")
                poster_url = BASE_URL + raw_src if raw_src and not raw_src.startswith("http") else raw_src

            print(f"\nİşleniyor: {title}")
            
            # Film detay sayfasına git
            movie_soup = get_soup(movie_link)
            if not movie_soup: continue

            # "let parts = [...]" verisini bul (Iframe linki burada gizli)
            scripts = movie_soup.find_all("script")
            iframe_src = None
            
            for script in scripts:
                if script.string and "let parts=" in script.string:
                    match = re.search(r'let parts=(\[.*?\]);', script.string, re.DOTALL)
                    if match:
                        json_str = match.group(1)
                        # src="..." kısmını regex ile al (JSON parse bazen hata veriyor)
                        src_match = re.search(r'src=\\?["\']([^"\']+)["\']', json_str)
                        if src_match:
                            iframe_src = clean_url(src_match.group(1))
                            if iframe_src.startswith("//"): iframe_src = "https:" + iframe_src
                    break
            
            if iframe_src:
                m3u8, vtts = extract_stream_data(iframe_src)
                
                if m3u8:
                    print(f"  ✅ Bulundu: {m3u8}")
                    if vtts:
                        print(f"  📝 {len(vtts)} altyazı bulundu.")
                    
                    movies_data.append({
                        "title": title,
                        "poster": poster_url,
                        "url": m3u8,
                        "subtitles": vtts,
                        "page_url": movie_link
                    })
                else:
                    print(f"  ❌ M3U8 bulunamadı (Iframe erişildi ama link yok)")
            else:
                print(f"  ❌ Video kaynağı bulunamadı")
                
            # Serverı boğmamak için kısa bekleme
            time.sleep(1)

        except Exception as e:
            print(f"  ⚠️ İşlem hatası: {e}")
            continue

    # --- DOSYALARI KAYDETME ---
    
    # 1. JSON Kaydet
    with open('movies.json', 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)
    print("\n💾 movies.json oluşturuldu.")

    # 2. M3U Kaydet
    with open('playlist.m3u', 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for movie in movies_data:
            # Metadata satırı
            f.write(f'#EXTINF:-1 tvg-logo="{movie["poster"]}" group-title="Filmler",{movie["title"]}\n')
            
            # Altyazı ekleme (Standart dışı ama VLC gibi playerlar destekler)
            # Eğer altyazı varsa, linkin altına '#EXTVLCOPT' veya benzeri eklenebilir.
            # Ancak en temiz yöntem, M3U8 linkini direkt vermektir. 
            # (M3U8 içinde zaten altyazı varsa player otomatik görür).
            # Biz yine de harici VTT varsa ekleyelim:
            if movie["subtitles"]:
                # İlk Türkçe altyazıyı bulmaya çalışalım (basit mantık)
                tr_sub = next((s for s in movie["subtitles"] if "tr" in s or "tur" in s), None)
                if tr_sub:
                    f.write(f'#EXTVLCOPT:subtitles={tr_sub}\n')
            
            f.write(f'{movie["url"]}\n')
            
    print("💾 playlist.m3u oluşturuldu.")

if __name__ == "__main__":
    main()
