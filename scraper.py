import requests
from bs4 import BeautifulSoup
import re
import json
import os
import time

# Web sitesi ayarları
BASE_URL = "https://www.hdfilmizle.life"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://www.hdfilmizle.life/",
    "Origin": "https://www.hdfilmizle.life"
}

def get_soup(url):
    try:
        # Timeout süresini 30 saniyeye çıkardık (Timeout hataları için)
        response = requests.get(url, headers=HEADERS, timeout=30)
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
    except Exception as e:
        return packed_js

def extract_stream_data(iframe_url):
    try:
        # URL temizliği: Eğer URL içinde hala kaçış karakteri varsa temizle
        iframe_url = iframe_url.replace('\\/', '/')
        
        iframe_headers = HEADERS.copy()
        iframe_headers["Referer"] = BASE_URL
        
        response = requests.get(iframe_url, headers=iframe_headers, timeout=15)
        content = response.text
        
        if "eval(function" in content:
            content = unpack_js(content)
        
        m3u8_url = None
        # M3U8 Linkini Bul
        m3u8_match = re.search(r'(https?://[^"\']+\.m3u8)', content)
        if m3u8_match:
            m3u8_url = m3u8_match.group(1)
        
        if not m3u8_url:
            file_match = re.search(r'file\s*:\s*"([^"]+\.m3u8)"', content)
            if file_match:
                m3u8_url = file_match.group(1)

        # M3U8 linkini de temizle (bazen orada da kaçış karakteri olur)
        if m3u8_url:
            m3u8_url = m3u8_url.replace('\\/', '/')

        # VTT Altyazıları Bul
        vtt_files = []
        vtt_matches = re.findall(r'(https?://[^"\']+\.vtt)', content)
        
        for vtt in vtt_matches:
            clean_vtt = vtt.replace('\\/', '/')
            if clean_vtt not in vtt_files:
                vtt_files.append(clean_vtt)
        
        return m3u8_url, vtt_files
        
    except Exception as e:
        print(f"Stream detayları alınamadı: {e}")
        return None, []

def main():
    print("Film taraması başlıyor...")
    soup = get_soup(BASE_URL)
    
    if not soup:
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
                            json_str = json_match.group(1)
                            # Regex ile src kısmını yakala (escape karakterli olabilir)
                            # Hem çift tırnak hem tek tırnak kontrolü
                            src_match = re.search(r'src=\\?["\']([^"\']+)["\']', json_str)
                            
                            if src_match:
                                temp_src = src_match.group(1)
                                
                                # KRİTİK DÜZELTME: Kaçış karakterlerini temizle (https:\/\/ -> https://)
                                temp_src = temp_src.replace('\\/', '/')
                                
                                if temp_src.startswith("//"):
                                    iframe_src = "https:" + temp_src
                                else:
                                    iframe_src = temp_src
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
                    print(f"  + Başarılı: {title}")
                else:
                    print(f"  - M3U8 Bulunamadı (Iframe: {iframe_src})")
            else:
                print(f"  - Iframe kaynağı bulunamadı.")
            
            # Sunucuyu yormamak için kısa bir bekleme
            time.sleep(1)

        except Exception as e:
            print(f"  - Film işlenirken hata: {e}")
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
            if movie["subtitles"]:
                f.write(f'#EXTVLCOPT:subtitles={movie["subtitles"][0]}\n')
            f.write(f'{movie["url"]}\n')
            
    print("playlist.m3u oluşturuldu.")

if __name__ == "__main__":
    main()
