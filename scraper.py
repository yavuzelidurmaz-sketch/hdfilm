import requests
from bs4 import BeautifulSoup
import re
import json
import os

# Web sitesi ayarları
BASE_URL = "https://www.hdfilmizle.life"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://www.hdfilmizle.life/"
}

def get_soup(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Hata ({url}): {e}")
        return None

def extract_stream_data(iframe_url):
    """
    Vidrame/Pictureflix iframe içerisindeki m3u8 ve vtt linklerini arar.
    """
    try:
        # Iframe içeriğini çek (Referer önemli olabilir)
        iframe_headers = HEADERS.copy()
        iframe_headers["Referer"] = BASE_URL
        
        response = requests.get(iframe_url, headers=iframe_headers, timeout=10)
        content = response.text
        
        # M3U8 Linkini Bul (Regex ile)
        # Örnek: https://vs3.pictureflix.org/.../master.m3u8
        m3u8_match = re.search(r'https?://[^"\']+\.m3u8', content)
        m3u8_url = m3u8_match.group(0) if m3u8_match else None
        
        # VTT Altyazılarını Bul (Regex ile - birden fazla olabilir)
        # Sadece sonu .vtt ile bitenleri al
        vtt_files = []
        vtt_matches = re.findall(r'https?://[^"\']+\.vtt', content)
        
        for vtt in vtt_matches:
            if vtt not in vtt_files: # Tekrar edenleri engelle
                vtt_files.append(vtt)
                
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
    
    # Ana sayfadaki filmleri bul (#moviesListResult altındaki poster class'lı linkler)
    # Verdiğin kodda id="moviesListResult" var.
    movie_container = soup.find(id="moviesListResult")
    if not movie_container:
        print("Film listesi bulunamadı.")
        return

    movie_items = movie_container.find_all("a", class_="poster")
    
    print(f"Toplam {len(movie_items)} film bulundu.")

    for item in movie_items:
        try:
            # 1. Temel Bilgileri Al
            title = item.get("title")
            movie_href = item.get("href")
            
            # Link göreceli ise tamamla
            if not movie_href.startswith("http"):
                movie_link = BASE_URL + movie_href
            else:
                movie_link = movie_href

            # Poster URL'sini al (data-src veya src)
            img_tag = item.find("img")
            poster_url = ""
            if img_tag:
                poster_url = img_tag.get("data-src") or img_tag.get("src")
                if poster_url and not poster_url.startswith("http"):
                    poster_url = BASE_URL + poster_url

            print(f"İşleniyor: {title}")

            # 2. Film Sayfasına Git
            movie_soup = get_soup(movie_link)
            if not movie_soup:
                continue

            # 3. 'parts' değişkenini (Javascript) bul ve iframe linkini al
            # Verdiğin kodda: let parts=[{"id":52397,...,"data":"<iframe src=\"...\" ...>"}]
            scripts = movie_soup.find_all("script")
            iframe_src = None
            
            for script in scripts:
                if script.string and "let parts=" in script.string:
                    # Regex ile parts dizisini json benzeri yapıyı yakala
                    json_match = re.search(r'let parts=(\[.*?\]);', script.string, re.DOTALL)
                    if json_match:
                        try:
                            # Javascript objesini Python listesine çevirmeye çalışıyoruz
                            # Basit bir replace ile HTML içindeki kaçış karakterlerini temizle
                            parts_data = json.loads(json_match.group(1))
                            if len(parts_data) > 0:
                                # Data içindeki iframe src'yi bul
                                iframe_html = parts_data[0].get("data", "")
                                iframe_match = re.search(r'src="([^"]+)"', iframe_html)
                                if iframe_match:
                                    iframe_src = iframe_match.group(1)
                                    # Eğer // ile başlıyorsa https ekle
                                    if iframe_src.startswith("//"):
                                        iframe_src = "https:" + iframe_src
                        except:
                            print(f"  - JSON parse hatası: {title}")
                    break
            
            if iframe_src:
                # 4. İframe'e gidip m3u8 ve vtt al
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
                    print(f"  - M3U8 Bulunamadı: {title}")
            else:
                print(f"  - Iframe kaynağı bulunamadı: {title}")

        except Exception as e:
            print(f"  - Film işlenirken hata: {e}")
            continue

    # 5. JSON Dosyası Oluştur
    with open('movies.json', 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)
    print("movies.json oluşturuldu.")

    # 6. M3U Dosyası Oluştur
    with open('playlist.m3u', 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for movie in movies_data:
            # M3U formatında poster ve başlık
            f.write(f'#EXTINF:-1 tvg-logo="{movie["poster"]}" group-title="Filmler",{movie["title"]}\n')
            
            # Altyazıları VLC formatında ekle (Opsiyonel, oynatıcı desteğine bağlı)
            # Not: Standart M3U'da altyazı desteği sınırlıdır, genellikle oynatıcı otomatik bulur
            # veya #EXTVLCOPT etiketi kullanılır.
            if movie["subtitles"]:
                # İlk altyazıyı varsayılan yapalım
                f.write(f'#EXTVLCOPT:subtitles={movie["subtitles"][0]}\n')
            
            f.write(f'{movie["url"]}\n')
            
    print("playlist.m3u oluşturuldu.")

if __name__ == "__main__":
    main()
