#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pelota.py – Generador de eventos.m3u desde múltiples fuentes
"""
import re
import time
import os
from pathlib import Path
from git import Repo, exc as git_exc
import requests
from bs4 import BeautifulSoup
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# ───────────── Configuración ─────────────
ROJA_URL       = "https://www.rojadirectaenvivo.pl/"
FUTLIB_URL     = "https://futbollibre.mx/"
LIBPEL_URL     = "https://librepelota.com/"
PELOTA1_URL    = "https://www.pelotalibre1.pe/"

# Directorio del repo local
REPO_DIR       = Path(__file__).parent
EVENT_FILE     = "eventos.m3u"
CDN_URL        = f"https://raw.githubusercontent.com/KPRDROP/kprhub/main/{EVENT_FILE}"
SLOW_WAIT      = 4

# Ligas a incluir/excluir
INCLUDE_LEAGUES = []
EXCLUDED_LEAGUES = [
    "Super Lig", "Liga Endesa", "Super League", "Bundesliga",
    "Liga de Peru", "Liga de Ecuador", "Ligue 1", "Liga de Colombia",
    "Liga de Chile", "MLS", "Liga de Portugal", "NBA",
    "Liga Expansion MX", "Liga de Paraguay", "Liga MX"
]

# ───────────── Drivers ─────────────
def init_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-web-security")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_argument("--window-size=1920,1080")
    
    # Try multiple paths for chromedriver
    paths = [
        '/home/felipe/.wdm/drivers/chromedriver/linux64/143.0.7499.192/chromedriver-linux64/chromedriver',
        '/home/felipe/.wdm/drivers/chromedriver/linux64/139.0.7258.138/chromedriver-linux64/chromedriver',
        '/usr/bin/chromedriver'
    ]
    
    service = None
    for p in paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            try:
                service = Service(p)
                break
            except:
                pass
                
    if not service:
        # Fallback to webdriver-manager
        try:
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            print(f"Warning: WebDriver Manager failed: {e}")
            pass

    return webdriver.Chrome(service=service, options=opts) if service else webdriver.Chrome(options=opts)

# ───────────── Scrapers de Eventos ─────────────

def normalize(url: str) -> str:
    if not url or url.startswith('#'): return ''
    if url.startswith("//"): return "https:" + url
    if not url.startswith("http"): return "https://" + url.lstrip("/")
    return url

def get_roja_events() -> list:
    """Scraper original de RojaDirecta (basado en HTML estatico si es posible)"""
    events = []
    try:
        print(f"Scraping RojaDirecta: {ROJA_URL}")
        resp = requests.get(ROJA_URL, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        for li in soup.select("ul.menu > li"):
            t = li.find("span", class_="t")
            if not t: continue
            hora = t.text.strip()
            link = li.find("a", recursive=False)
            if not link or not link.contents: continue
            raw = link.contents[0].strip()
            if ":" not in raw: continue
            liga, partido = map(str.strip, raw.split(":", 1))
            
            for chan_link in li.select("ul > li > a"):
                href = normalize(chan_link.get("href", "").strip())
                if not href: continue
                chan_name = chan_link.text.strip()
                events.append((liga, hora, partido, chan_name, href))
    except Exception as e:
        print(f"Error scraping RojaDirecta: {e}")
    return events

def get_futbollibre_style_events(url: str, source_name: str) -> list:
    """Scraper para sitios tipo FutbolLibre/LibrePelota usando Selenium"""
    events = []
    driver = init_driver()
    try:
        print(f"Scraping {source_name}: {url}")
        driver.get(url)
        time.sleep(5) # Esperar carga de JS
        
        # Buscar enlaces que contengan un tiempo
        # Estrategia: Buscar todos los 'a', chequear si tienen hijo 'time' o texto tipo XX:XX
        links = driver.find_elements(By.TAG_NAME, "a")
        
        for a in links:
            try:
                href = a.get_attribute("href")
                if not href or "#" in href or "whatsapp" in href: continue
                
                # Check for time element or text
                text = a.text
                match = re.search(r'(\d{2}:\d{2})', text)
                
                # Si no encuentra hora en el enlace, buscar en padres (traversal)
                if not match:
                    el = a
                    for _ in range(3): # Subir hasta 3 niveles
                        try:
                            el = el.find_element(By.XPATH, "..")
                            p_txt = el.text
                            match = re.search(r'(\d{2}:\d{2})', p_txt)
                            if match:
                                text = p_txt # Usar texto del contenedor padre
                                break
                        except:
                            break
                
                if match:
                    hora = match.group(1)
                    # Limpiar texto para obtener titulo
                    full_text = text.replace(hora, "").replace("\n", " ").strip()
                    
                    if ":" in full_text:
                        parts = full_text.split(":", 1)
                        liga = parts[0].strip()
                        partido = parts[1].strip()
                    else:
                        liga = "Varios"
                        partido = full_text
                    
                    chan_name = f"{source_name} Stream"
                    events.append((liga, hora, partido, chan_name, href))
            except:
                continue
                
    except Exception as e:
        print(f"Error scraping {source_name}: {e}")
    finally:
        driver.quit()
    return events

def get_fixed_channels(url: str) -> list:
    """Obtiene canales fijos de LibrePelota (barra navegación)"""
    channels = []
    driver = init_driver()
    try:
        print(f"Scraping Fixed Channels from: {url}")
        driver.get(url)
        time.sleep(3)
        
        links = driver.find_elements(By.TAG_NAME, "a")
        seen = set()
        
        for a in links:
            try:
                href = a.get_attribute("href")
                txt = a.text.strip()
                if not href: continue
                
                # Criterio: URL contiene 'en-vivo' y el texto es corto (nombre de canal)
                if "/en-vivo/" in href and len(txt) > 2 and len(txt) < 30 and "partido" not in txt.lower() and "ver" not in txt.lower():
                    if txt not in seen:
                        # Crear entrada M3U provisional (sin stream URL aun)
                        channels.append((txt, href))
                        seen.add(txt)
            except:
                continue
    except Exception as e:
        print(f"Error scraping fixed channels: {e}")
    finally:
        driver.quit()
    return channels

# ───────────── Extracción de Stream (M3U8) ─────────────

def click_play_buttons(drv):
    """Intenta hacer clic en botones de play"""
    try:
        selectors = [
            "button[aria-label*='play']", ".play-button", ".vjs-play-control", 
            ".jw-display-icon-container", ".plyr__control--overlaid", 
            "button.vjs-big-play-button", "div[class*='play']", "svg[class*='play']"
        ]
        elements = drv.find_elements(By.CSS_SELECTOR, ", ".join(selectors))
        count = 0
        for el in elements:
            if count >= 2: break
            try:
                if el.is_displayed():
                    drv.execute_script("arguments[0].click();", el)
                    time.sleep(0.5)
                    count += 1
            except: pass
    except: pass

def extract_m3u8(url: str) -> dict:
    """Extrae el m3u8 de una URL usando Selenium Wire y clics inteligentes. Retorna dict con url y headers."""
    driver = init_driver()
    stream_data = None
    
    try:
        driver.set_page_load_timeout(20)
        try:
            driver.get(url)
        except: pass
        
        time.sleep(3)
        click_play_buttons(driver)
        
        # Buscar iframes
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i in range(min(len(iframes), 3)):
            try:
                driver.switch_to.default_content()
                iframes = driver.find_elements(By.TAG_NAME, "iframe") # refresh
                if i < len(iframes):
                    driver.switch_to.frame(iframes[i])
                    click_play_buttons(driver)
                    # Nested
                    nested = driver.find_elements(By.TAG_NAME, "iframe")
                    if nested:
                        driver.switch_to.frame(nested[0])
                        click_play_buttons(driver)
            except: pass
            
        driver.switch_to.default_content()
        time.sleep(4)
        
        # Capturar requests - Priorizar requests exitosos (status 200)
        candidates = []
        for req in driver.requests:
            if req.response and ('.m3u8' in req.url or '.mpd' in req.url):
                # Filter out master playlists if we can find a specific chunklist, 
                # but many times master is what we want. 
                # Just avoid duplicates and 404s.
                if req.response.status_code in [200, 206]:
                   candidates.append(req)
        
        # Prefer the last successful request (most likely the playing one)
        found_req = candidates[-1] if candidates else None
        
        if found_req:
            # Capture relevant headers for VLC
            headers = found_req.headers
            stream_data = {
                "url": found_req.url,
                "referer": headers.get("Referer", ""),
                "origin": headers.get("Origin", ""),
                "user_agent": headers.get("User-Agent", ""),
                "cookie": headers.get("Cookie", "")
            }
                    
    except Exception as e:
        print(f"Error extracting stream from {url}: {e}")
    finally:
        driver.quit()
    return stream_data

# ───────────── Main ─────────────

def main():
    all_events = []
    
    # 1. Obtener eventos de todas las fuentes
    all_events.extend(get_roja_events())
    all_events.extend(get_futbollibre_style_events(FUTLIB_URL, "FutbolLibre"))
    all_events.extend(get_futbollibre_style_events(LIBPEL_URL, "LibrePelota"))
    all_events.extend(get_futbollibre_style_events(PELOTA1_URL, "PelotaLibre1"))
    
    # 2. Filtrar y ordenar
    unique_events = {} # Key: (hora, partido) -> data
    
    for liga, hora, partido, chan, url in all_events:
        # Filtros Ligas
        if any(exc.lower() in liga.lower() for exc in EXCLUDED_LEAGUES): continue
        if INCLUDE_LEAGUES and not any(inc.lower() in liga.lower() for inc in INCLUDE_LEAGUES): continue
        pass

    # 3. Generar archivo eventos
    entries = ["#EXTM3U"]
    print(f"Total raw events found: {len(all_events)}")
    
    # Ordenar
    all_events.sort(key=lambda x: (x[1], x[0])) # Hora, Liga
    
    # Procesar streams (ESTO LLEVA TIEMPO)
    processed_count = 0
    for liga, hora, partido, chan, url in all_events:
        # Re-aplicar filtro por seguridad
        if any(exc.lower() in liga.lower() for exc in EXCLUDED_LEAGUES): continue
        if INCLUDE_LEAGUES and not any(inc.lower() in liga.lower() for inc in INCLUDE_LEAGUES): continue
        
        print(f"Procesando: {hora} {liga} - {partido}")
        result = extract_m3u8(url)
        if result:
            title = f"{hora} {liga} – {partido}"
            entries.append(f'#EXTINF:-1 tvg-name="{chan}" group-title="{liga}", {title} – {chan}')
            
            # Use keys from the extract_m3u8 (user_agent, referer, origin, cookie)
            ref = result.get("referer")
            origin = result.get("origin")
            ua = result.get("user_agent")
            cookie = result.get("cookie")
            
            if ref: 
                entries.append(f'#EXTVLCOPT:http-referrer={ref}')
            if origin: 
                entries.append(f'#EXTVLCOPT:http-origin={origin}')
            if ua: 
                entries.append(f'#EXTVLCOPT:http-user-agent={ua}')
            if cookie: 
                entries.append(f'#EXTVLCOPT:http-cookie={cookie}')
            
            entries.append(result["url"])
            processed_count += 1
        else:
            print("  -> No stream found")

    out_file = REPO_DIR / EVENT_FILE
    out_file.write_text("\n".join(entries), encoding="utf-8")
    print(f"Guardado {out_file} con {processed_count} eventos.")
    
    # 4. Canales Fijos (LibrePelota)
    fixed_channels = get_fixed_channels(LIBPEL_URL)
    fixed_entries = []
    print(f"Procesando {len(fixed_channels)} canales fijos...")
    
    names_count = {}
    for name, url in fixed_channels:
        print(f"  Fixed: {name}")
        result = extract_m3u8(url)
        if result:
            # Handle duplicate names if any
            display_name = name
            if name in names_count:
                names_count[name] += 1
                display_name = f"{name} {names_count[name]}"
            else:
                names_count[name] = 1
                
            fixed_entries.append(f'#EXTINF:-1 group-title="Fijos", {display_name}')
            
            ref = result.get("referer")
            origin = result.get("origin")
            ua = result.get("user_agent")
            cookie = result.get("cookie")
            
            if ref: 
                fixed_entries.append(f'#EXTVLCOPT:http-referrer={ref}')
            if origin: 
                fixed_entries.append(f'#EXTVLCOPT:http-origin={origin}')
            if ua: 
                fixed_entries.append(f'#EXTVLCOPT:http-user-agent={ua}')
            if cookie: 
                fixed_entries.append(f'#EXTVLCOPT:http-cookie={cookie}')
            
            fixed_entries.append(result["url"])
            
    # 5. Combinar Playlist
    combo_entries = ["#EXTM3U"]
    combo_entries.extend(fixed_entries) # Primero fijos
    if len(entries) > 1:
        combo_entries.extend(entries[1:]) # Luego eventos
        
    combo_file = REPO_DIR / "playlist.m3u"
    combo_file.write_text("\n".join(combo_entries), encoding="utf-8")
    print("Playlist combinada generada.")
    
    # 6. Git Push
    try:
        repo = Repo(REPO_DIR)
        repo.index.add([str(out_file), str(combo_file)])
        repo.index.commit(f'Update playlist: {processed_count} events + {len(fixed_entries)//2} fixed')
        repo.remote('origin').push()
        print("Pushed to GitHub.")
    except Exception as e:
        print(f"Git Error: {e}")

if __name__ == '__main__':
    main()
