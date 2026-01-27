import requests
from bs4 import BeautifulSoup
import re
import json
import os

# Web sitesi ayarları
BASE_URL = "https://www.hdfilmizle.life"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://www.hdfilmizle.life/",
    "Origin": "https://www.hdfilmizle.life"
}

def get_soup(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Hata ({url}): {e}")
        return None

def unpack_js(packed_js):
    """
    Basit bir Dean Edwards packer çözücü.
    eval(function(p,a,c,k,e,r)...) yapısını çözer.
    """
    try:
        # P, A, C, K, E, R değerlerini regex ile ayıkla
        pattern = r"}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)"
        match = re.search(pattern, packed_js)
        
        if not match:
            return packed_js
            
        payload, radix, count, keywords = match.groups()
        keywords = keywords.split('|')
        radix = int(radix)
        
        def baseN(num, b):
            return ((num == 0) and "0") or (baseN(num // b, b).lstrip("0") + "0123456789abcdefghijklmnopqrstuvwxyz"[num % b])

        # Kelime haritasını oluştur
        unpacked_source = payload
        for i, keyword in enumerate(keywords):
            if keyword:
                # Regex ile kelimeyi yer değiştir (bunu daha sağlam yapmak gerekebilir ama basitçe bu çalışır)
                key = baseN(i, radix)
                unpacked_source = re.sub(r'\b' + key + r'\b', keyword, unpacked_source)
        
        return unpacked_source
    except Exception as e:
        print(f"Unpack hatası: {e}")
        return packed_js

def extract_stream_data(iframe_url):
    """
    Vidrame/Pictureflix iframe içerisindeki m3u8 ve vtt linklerini arar.
    """
    try:
        # Iframe içeriğini çek (Referer önemli)
        iframe_headers = HEADERS.copy()
        iframe_headers["Referer"] = BASE_URL
        
        response = requests.get(iframe_url, headers=iframe_headers, timeout=10)
        content = response.text
        
        # 1. Adım: Eğer içerik "eval(function..." içeriyorsa çözmeyi dene
        if "eval(function" in content:
            content = unpack_js(content)
        
        # 2. Adım: M3U8 Linkini Bul
        # Genellikle file:"..." veya direk url içinde geçer
        m3u8_url = None
        
        # Yöntem A: Doğrudan URL arama
        m3u8_match = re.search(r'(https?://[^"\']+\.m3u8)', content)
        if m3u8_match:
            m3u8_url = m3u8_match.group(1)
        
        # Yöntem B: JS değişkeni içinde arama (file: "...")
        if not m3u8_url:
            file_match = re.search(r'file\s*:\s*"([^"]+\.m3u8)"', content)
            if file_match:
                m3u8_url = file_match.group(1)

        # 3. Adım: VTT Altyazılarını Bul
        vtt_files = []
        # tracks: [{file: "..."}] yapısını veya doğrudan .vtt linklerini ara
        vtt_matches = re.findall(r'(https?://[^"\']+\.vtt)', content)
        
        for vtt in vtt_matches:
            if vtt not in vtt_files:
                vtt_files.append(vtt)
        
        # Eğer m3u8 hala yoksa hata ayıklama için içeriğin başını yazdır (Loglarda görünür)
        if not m3u8_url:
            print(f"    DEBUG: Iframe içeriği (ilk 200 karakter): {content[:200]}")

        return m3u8_url, vtt_files
        
    except Exception as e:
        print(f"Stream detayları alınamadı: {e}")
        return None, []

def main():
    print("Film taraması başlıyor...")
    soup = get_soup(BASE_URL)
    
    if not soup:
        print("Ana sayfaya erişilemedi.")
        return

    movies_data = []
    
    movie_container = soup.find(id="moviesListResult")
    if not movie_container:
        print("Film listesi bulunamadı.")
        return

    movie_items = movie_container.find_all("a", class_="poster")
    
    print(f"Toplam {len(movie_items)} film bulundu.")

    for item in movie_items:
        try:
            title = item.get("title")
            movie_href = item.get("href")
            
            if not movie_href.startswith("http"):
                movie_link = BASE_URL + movie_href
            else:
                movie_link = movie_href

            img_tag = item.find("img")
            poster_url = ""
            if img_tag:
                poster_url = img_tag.get("data-src") or img_tag.get("src")
                if poster_url and not poster_url.startswith("http"):
                    poster_url = BASE_URL + poster_url

            print(f"İşleniyor: {title}")

            movie_soup = get_soup(movie_link)
            if not movie_soup:
                continue

            scripts = movie_soup.find_all("script")
            iframe_src = None
            
            for script in scripts:
                if script.string and "let parts=" in script.string:
                    json_match = re.search(r'let parts=(\[.*?\]);', script.string, re.DOTALL)
                    if json_match:
                        try:
                            # JSON temizliği
                            json_str = json_match.group(1)
                            # Bazen JS objesi olarak gelir, key'lerde tırnak olmayabilir.
                            # Basit regex ile src'yi alalım, json.loads hata verebilir.
                            src_match = re.search(r'src=\\"([^"]+)\\"', json_str)
                            if not src_match:
                                src_match = re.search(r'src="([^"]+)"', json_str)
                            
                            if src_match:
                                temp_src = src_match.group(1)
                                if temp_src.startswith("//"):
                                    iframe_src = "https:" + temp_src
                                else:
                                    iframe_src = temp_src
                                # Parametreleri temizle (?ap=1 vs)
                                # iframe_src = iframe_src.split('?')[0] 
                        except Exception as e:
                            print(f"  - Script parse hatası: {e}")
                    break
            
            if iframe_src:
                m3u8, vtts = extract_stream_data(iframe_src)
                
                if m3u8:
                    movies_data.append({
                        "title": title,
                        "poster": poster_url,
                        "url": m3u8,
                        "subtitles": vtts,
                        "page_url": movie_link
                    })
                    print(f"  + Başarılı: M3U8 ve {len(vtts)} altyazı alındı.")
                else:
                    print(f"  - M3U8 Bulunamadı (Iframe: {iframe_src})")
            else:
                print(f"  - Iframe kaynağı bulunamadı.")

        except Exception as e:
            print(f"  - Film işlenirken genel hata: {e}")
            continue

    # JSON Kaydet
    with open('movies.json', 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)
    print("movies.json oluşturuldu.")

    # M3U Kaydet
    with open('playlist.m3u', 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for movie in movies_data:
            f.write(f'#EXTINF:-1 tvg-logo="{movie["poster"]}" group-title="Filmler",{movie["title"]}\n')
            # Varsa altyazıları yorum satırı veya VLC option olarak ekle
            if movie["subtitles"]:
                # Birden fazla altyazı varsa, ilkini varsayılan yap
                f.write(f'#EXTVLCOPT:subtitles={movie["subtitles"][0]}\n')
            f.write(f'{movie["url"]}\n')
            
    print("playlist.m3u oluşturuldu.")

if __name__ == "__main__":
    main()
