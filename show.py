import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os

# Web sitesi kök adresi
BASE_URL = "https://www.showtv.com.tr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Yeniden deneme ayarları
MAX_RETRIES = 5  # Her URL için maksimum deneme sayısı
RETRY_DELAY = 2  # Denemeler arası bekleme süresi (saniye)

def get_soup(url, retry_count=0):
    """
    URL'den BeautifulSoup nesnesi döndürür.
    Timeout hatalarında otomatik olarak yeniden dener.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")
    except requests.exceptions.Timeout:
        if retry_count < MAX_RETRIES:
            print(f"      ⚠ Timeout hatası! Yeniden deneniyor... ({retry_count + 1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
            return get_soup(url, retry_count + 1)
        else:
            print(f"      ✗ Maksimum deneme sayısına ulaşıldı. URL atlanıyor: {url}")
            return None
    except Exception as e:
        if retry_count < MAX_RETRIES:
            print(f"      ⚠ Hata: {e}. Yeniden deneniyor... ({retry_count + 1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
            return get_soup(url, retry_count + 1)
        else:
            print(f"      ✗ Maksimum deneme sayısına ulaşıldı. Hata: {e}")
            return None

def slugify(text):
    """Metni ID olarak kullanılabilecek formata çevirir"""
    text = text.lower()
    text = text.replace('ı', 'i').replace('ğ', 'g').replace('ü', 'u').replace('ş', 's').replace('ö', 'o').replace('ç', 'c')
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

def extract_episode_number(name):
    """
    Bölüm adından numarayı çeker (Sıralama için).
    Örn: '131. Bölüm' -> 131 döner.
    Bulamazsa 9999 döndürür ki en sona gitsin.
    """
    match = re.search(r'(\d+)\.\s*Bölüm', name)
    if match:
        return int(match.group(1))
    return 9999

def extract_episode_number_only(name):
    """
    Bölüm adından sadece sayıyı çıkarır ve formatlar.
    Örn: '131. Bölüm' -> '131. Bölüm'
          'Gülperi Sezon 1 Bölüm 23' -> '23. Bölüm'
    """
    match = re.search(r'(\d+)\.\s*Bölüm', name)
    if match:
        return f"{match.group(1)}. Bölüm"
    
    # Alternatif format: "Bölüm X" veya "X Bölüm"
    match = re.search(r'Bölüm\s*(\d+)', name, re.IGNORECASE)
    if match:
        return f"{match.group(1)}. Bölüm"
    
    match = re.search(r'(\d+)\s*Bölüm', name, re.IGNORECASE)
    if match:
        return f"{match.group(1)}. Bölüm"
    
    # Hiçbir format bulunamazsa orijinal adı döndür
    return name

def main():
    print("İçerikler taranıyor... (Diziler, Programlar, Haber)")
    
    # İstenilen 3 kategori buraya eklendi
    CATEGORIES = ["/diziler", "/programlar", "/show-haber"]
    
    # Tüm verileri tek bir sözlükte toplayacağız
    master_data = {}

    for category in CATEGORIES:
        full_cat_url = f"{BASE_URL}{category}"
        print(f"\n{'='*20}\nKategori Taranıyor: {category}\n{'='*20}")
        
        soup = get_soup(full_cat_url)
        if not soup:
            print(f"{category} sayfası yüklenemedi!")
            continue

        dizi_kutulari = soup.find_all("div", attrs={"data-name": "box-type6"})
        print(f"Bu kategoride {len(dizi_kutulari)} adet içerik bulundu.")

        for kutu in dizi_kutulari:
            try:
                link_tag = kutu.find("a", class_="group")
                if not link_tag:
                    continue
                    
                dizi_link = BASE_URL + link_tag.get("href")
                dizi_adi = link_tag.get("title")
                dizi_id = slugify(dizi_adi)
                
                # Afiş Linki
                img_tag = kutu.find("img")
                poster_url = img_tag.get("src") if img_tag else ""
                if img_tag and img_tag.get("data-src"):
                    poster_url = img_tag.get("data-src")
                if "?" in poster_url:
                    poster_url = poster_url.split("?")[0]

                print(f"\n--> İşleniyor: {dizi_adi}")

                # Ana sayfadaki "Son Bölüm" butonunu yakala
                son_bolum_url = None
                son_bolum_span = kutu.find("span", string="Son Bölüm")
                if son_bolum_span:
                    parent_a = son_bolum_span.find_parent("a")
                    if parent_a and parent_a.get("href"):
                        href = parent_a.get("href")
                        if "/tum_bolumler/" in href:
                            son_bolum_url = BASE_URL + href
                            print(f"    [✓] Ana sayfadan son bölüm linki tespit edildi.")

                # Detay Sayfasına Git
                detail_soup = get_soup(dizi_link)
                if not detail_soup:
                    print(f"    [✗] Detay sayfası yüklenemedi, atlanıyor.")
                    continue

                raw_links = []
                seen_urls = set()

                # Dropdown'dan linkleri topla
                options = detail_soup.find_all("option", attrs={"data-href": True})
                for opt in options:
                    rel_link = opt.get("data-href")
                    bolum_adi = opt.text.strip()
                    if "/tum_bolumler/" in rel_link:
                        full = BASE_URL + rel_link
                        if full not in seen_urls:
                            raw_links.append({"ad": bolum_adi, "page_url": full})
                            seen_urls.add(full)

                # Son bölümü ekle (eğer listede yoksa)
                if son_bolum_url and son_bolum_url not in seen_urls:
                    raw_links.append({"ad": "Yeni Bölüm (Otomatik)", "page_url": son_bolum_url})
                    seen_urls.add(son_bolum_url)
                    print("    [✓] Listede olmayan son bölüm manuel eklendi.")

                print(f"    [i] {len(raw_links)} adet sayfa linki bulundu. Videolar çekiliyor...")

                final_bolumler = []
                
                # Linkleri gez ve Video çek
                for idx, item in enumerate(raw_links, 1):
                    print(f"    [{idx}/{len(raw_links)}] İşleniyor: {item['ad'][:50]}...")
                    
                    video_soup = get_soup(item["page_url"])
                    if not video_soup:
                        print(f"      [✗] Sayfa yüklenemedi, atlanıyor.")
                        continue
                    
                    # Bölüm adını title'dan çekip düzeltelim
                    page_title = video_soup.title.string if video_soup.title else item["ad"]
                    clean_name = page_title.replace("İzle", "").replace("Show TV", "").strip()
                    
                    if "Bölüm" in clean_name:
                        display_name = clean_name
                    else:
                        display_name = item["ad"]
                    
                    # SADECE BÖLÜM NUMARASINI ÇIKAR (Haber vb için orijinal isim kalabilir)
                    episode_only = extract_episode_number_only(display_name)
                    # Eğer bölüm numarası çıkmıyorsa (örn: Program veya Haber), display_name'i kullan
                    if episode_only == display_name: 
                         final_name = display_name
                    else:
                         final_name = episode_only

                    # Video JSON verisi
                    video_div = video_soup.find("div", class_="hope-video")
                    if video_div and video_div.get("data-hope-video"):
                        try:
                            v_data = json.loads(video_div.get("data-hope-video"))
                            video_url = ""
                            format_type = ""

                            # Medya kaynaklarına bak
                            if "media" in v_data:
                                media = v_data["media"]
                                
                                # ÖNCE M3U8 ARA
                                if "m3u8" in media and len(media["m3u8"]) > 0:
                                    video_url = media["m3u8"][0]["src"]
                                    format_type = "M3U8"
                                
                                # EĞER M3U8 YOKSA MP4 ARA
                                elif "mp4" in media and len(media["mp4"]) > 0:
                                    video_url = media["mp4"][0]["src"]
                                    format_type = "MP4"
                            
                            if video_url:
                                # Link düzeltme
                                video_url = video_url.replace("//ht/", "/ht/").replace("com//", "com/")
                                
                                final_bolumler.append({
                                    "ad": final_name,
                                    "link": video_url,
                                    "episode_num": extract_episode_number(display_name)
                                })
                                print(f"      [✓] {final_name} [{format_type}] Eklendi")
                            else:
                                print(f"      [✗] Video Kaynağı (M3U8/MP4) Bulunamadı.")

                        except Exception as e:
                            print(f"      [!] Video JSON hatası: {e}")
                    
                    time.sleep(0.1)  # Rate limiting için bekleme

                # SIRALAMA: Küçükten Büyüğe
                if final_bolumler:
                    final_bolumler = sorted(final_bolumler, key=lambda x: x['episode_num'])
                    
                    # Veriyi temizle
                    cleaned_final = [{"ad": x["ad"], "link": x["link"]} for x in final_bolumler]

                    # Master Data'ya ekle
                    # Eğer aynı ID varsa (nadir durum) üstüne yazar, o yüzden kategori prefix eklenebilir ama
                    # şimdilik user isteği üzerine logic değiştirmeden ID bazlı saklıyoruz.
                    master_data[dizi_id] = {
                        "resim": poster_url,
                        "bolumler": cleaned_final
                    }
                    
                    print(f"    [✓] Toplam {len(cleaned_final)} bölüm eklendi.\n")
                else:
                    print(f"    [✗] Hiç bölüm bulunamadı.\n")

            except Exception as e:
                print(f"[HATA] İçerik işlenirken hata: {e}\n")

    print("\n" + "="*50)
    print(f"Tüm tarama bitti. Toplam {len(master_data)} içerik işlendi!")
    print("="*50)
    
    create_m3u_file(master_data)

def create_m3u_file(data):
    filename = "showtv.m3u"
    print(f"{filename} dosyası oluşturuluyor...")
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        
        for show_key, show_val in data.items():
            # ID'den okunabilir isim üret (show-haber -> SHOW HABER)
            group_title = show_key.replace("-", " ").upper()
            poster = show_val.get("resim", "")
            
            for bolum in show_val.get("bolumler", []):
                bolum_adi = bolum.get("ad", "Bilinmeyen Bölüm")
                link = bolum.get("link", "")
                
                # M3U Formatı
                # #EXTINF:-1 group-title="Dizi Adı" tvg-logo="LogoURL", Bölüm Adı
                line = f'#EXTINF:-1 group-title="{group_title}" tvg-logo="{poster}", {bolum_adi}\n{link}\n'
                f.write(line)
    
    print(f"DOSYA HAZIR: {filename}")

if __name__ == "__main__":
    main()
