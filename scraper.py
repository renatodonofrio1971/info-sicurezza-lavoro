import csv
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Configurazione file locale
FILE_LOCALE = "Database_Notizie.csv"
COLONNE = ["ID", "Titolo", "Fonte", "Data", "Link_Ufficiale", "Categoria", "Importanza"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def pulisci_testo(testo):
    """Sostituisce i caratteri speciali più comuni per evitare bug visivi in Excel"""
    if not testo:
        return ""
    sostituzioni = {
        "â€¦": "...", "â€œ": '"', "â€ ": '"', "â€“": "-", "â€™": "'", "\xa0": " ",
        "Ã\xa0": "à", "Ã²": "ò", "Ã¹": "ù", "Ã¨": "è", "Ã©": "é", "Ã¬": "ì",
        "unitÃ\xa0": "unità", "professionalitÃ\xa0": "professionalità"
    }
    for errato, corretto in sostituzioni.items():
        testo = testo.replace(errato, corretto)
    return testo.strip()

def inizializza_database_locale():
    if not os.path.exists(FILE_LOCALE):
        with open(FILE_LOCALE, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(COLONNE)
        print(f"📁 Creato nuovo database locale: {FILE_LOCALE}")

# =====================================================================
# MOTORE DI CATALOGAZIONE AUTOMATICA (Smart Tagging)
# =====================================================================
def assegna_macro_area_e_tag(titolo):
    """Analizza il titolo della notizia e assegna Macro-Area e Sotto-Area (Tag)"""
    titolo_up = titolo.upper()
    
    if any(p in titolo_up for p in ["ATTREZZATUR", "MACCHIN", "DPI", "SEGNALETICA", "LUOGHI DI LAVORO", "APPALT", "DUVRI"]):
        macro = "Sicurezza Generale"
        sub = "#Attrezzature" if "MACCHIN" in titolo_up or "ATTREZZATUR" in titolo_up else "#DPI" if "DPI" in titolo_up else "#Segnaletica" if "SEGNALETICA" in titolo_up else "#Generale"
    elif any(p in titolo_up for p in ["MEDICO", "SORVEGLIANZA SANITARIA", "VISIT", "RUMORE", "VIBRAZION", "ERGONOMIA", "VDT", "BIOLOGIC"]):
        macro = "Salute & Medicina"
        sub = "#Sorveglianza" if "MEDICO" in titolo_up or "VISIT" in titolo_up else "#RischiFisici" if "RUMORE" in titolo_up or "VIBRAZION" in titolo_up else "#Ergonomia"
    elif any(p in titolo_up for p in ["CANTIERE", "EDILIZIA", "POS", "PSC", "PONTEGGI", "QUOTA", "PATENTE A CREDITI"]):
        macro = "Edilizia & Cantieri"
        sub = "#PatenteACrediti" if "PATENTE" in titolo_up else "#LavoriInQuota" if "QUOTA" in titolo_up or "PONTEGGI" in titolo_up else "#Cantieristica"
    elif any(p in titolo_up for p in ["INCENDI", "ANTINCENDIO", "EVACUAZION", "EMERGENZ", "ESTINTORE", "SOCCORSO"]):
        macro = "Antincendio & Emergenze"
        sub = "#Presidi" if "ESTINTORE" in titolo_up or "MANUTENZ" in titolo_up else "#Antincendio"
    elif any(p in titolo_up for p in ["FORMAZION", "CORSO", "CORSI", "ADDESTRASMENTO", "AGGIORNAMENTO RSPP", "RLS", "PREPOSTO", "PATENTIN"]):
        macro = "Formazione & Ruoli"
        sub = "#Abilitazioni" if "PATENTIN" in titolo_up else "#Corsi"
    elif any(p in titolo_up for p in ["CHIMICO", "REACH", "CLP", "SDS", "ATEX", "RIFIUTI", "MUD", "AUA", "AMBIENT"]):
        macro = "Rischio Chimico & Ambiente"
        sub = "#Ambiente" if "RIFIUTI" in titolo_up or "MUD" in titolo_up else "#Chimico"
    else:
        macro = "Sicurezza Generale"
        sub = "#Generale"
        
    return macro, sub

def aggiungi_riga_locale(riga):
    """Intercetta la riga, applica la classificazione intelligente e scrive su CSV"""
    # Riconosciamo gli elementi inviati dagli scraper
    id_notizia = riga[0]
    titolo_originale = riga[1]
    fonte = riga[2]
    data = riga[3]
    link_ufficiale = riga[4]
    
    # Applichiamo l'AI locale di classificazione
    macro_area, sotto_tag = assegna_macro_area_e_tag(titolo_originale)
    
    # Assegniamo l'importanza: Alta se contiene parole chiave critiche o se impostata dallo scraper
    importanza = "Alta" if any(p in titolo_originale.upper() for p in ["URGENTI", "OBBLIGO", "D.LGS", "DECRETO"]) or riga[6] == "Alta" else "Media"
    
    # Modifichiamo il titolo per mostrare il tag visivo nell'applicazione
    titolo_con_tag = f"{titolo_originale} {sotto_tag}"
    
    # Ricostruiamo la riga finale ordinata secondo le colonne del CSV
    riga_finale = [id_notizia, titolo_con_tag, fonte, data, link_ufficiale, macro_area, importanza]
    
    # Pulizia del testo e scrittura finale
    riga_pulita = [pulisci_testo(str(item)) for item in riga_finale]
    with open(FILE_LOCALE, mode='a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(riga_pulita)

def scrape_inail():
    print("🕵️‍♂️ 1/7 - Estrazione da INAIL Nazionale...")
    url = "https://inail.it"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        notizie = soup.find_all('div', class_='news-item') or soup.find_all('div', class_='col-item') or [h3 for h3 in soup.find_all('h3') if h3.find('a')]

        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(notizie[:10]):
            link_tag = item if item.name == 'a' else item.find('a')
            if not link_tag: continue
            titolo = link_tag.get_text(strip=True)
            if len(titolo) < 15 or "vai a" in titolo.lower(): continue
            link_parziale = link_tag.get('href', '')
            link_ufficiale = f"https://inail.it{link_parziale}" if link_parziale.startswith('/') else link_parziale
            
            riga = [f"INAIL_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "INAIL Nazionale", data_oggi, link_ufficiale, "Istituzionale", "Media"]
            aggiungi_riga_locale(riga)
            contatore += 1
        print(f"✅ INAIL completato: aggiunte {contatore} notizie.")
    except Exception as e:
        print(f"❌ Errore INAIL: {e}")

def scrape_anfos():
    print("🕵️‍♂️ 2/7 - Estrazione da ANFOS (Scadenze & Formazione)...")
    url = "https://anfos.it"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        notizie = soup.find_all('h2', class_='entry-title')
        
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(notizie[:10]):
            link_tag = item.find('a')
            if not link_tag: continue
            titolo = link_tag.get_text(strip=True)
            link_ufficiale = link_tag.get('href', '')
            
            importanza = "Alta" if "scadenza" in titolo.lower() or "obbligo" in titolo.lower() else "Media"
            categoria = "Scadenze e Norme" if "scadenza" in titolo.lower() else "Aggiornamenti"
            
            riga = [f"ANFOS_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "ANFOS", data_oggi, link_ufficiale, categoria, importanza]
            aggiungi_riga_locale(riga)
            contatore += 1
        print(f"✅ ANFOS completato: aggiunte {contatore} notizie.")
    except Exception as e:
        print(f"❌ Errore ANFOS: {e}")

def scrape_inl():
    print("🕵️‍♂️ 3/7 - Estrazione da Ispettorato Nazionale del Lavoro (INL)...")
    url = "https://ispettorato.gov.it"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        notizie = soup.find_all('h3') or soup.find_all('h2')
        
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(notizie[:10]):
            link_tag = item if item.name == 'a' else item.find('a')
            if not link_tag: continue
            titolo = link_tag.get_text(strip=True)
            if len(titolo) < 15 or "menu" in titolo.lower(): continue
            link_parziale = link_tag.get('href', '')
            link_ufficiale = f"https://ispettorato.gov.it{link_parziale}" if link_parziale.startswith('/') else link_parziale
            
            riga = [f"INL_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Ispettorato Lavoro", data_oggi, link_ufficiale, "Vigilanza e Controlli", "Alta"]
            aggiungi_riga_locale(riga)
            contatore += 1
        print(f"✅ INL completato: aggiunte {contatore} notizie.")
    except Exception as e:
        print(f"❌ Errore INL: {e}")

def scrape_ministero_lavoro():
    print("🕵️‍♂️ 4/7 - Estrazione da Ministero del Lavoro...")
    url = "https://lavoro.gov.it"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        notizie = soup.find_all('h4') or soup.find_all('h3')
        
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(notizie[:10]):
            link_tag = item if item.name == 'a' else item.find('a')
            if not link_tag: continue
            titolo = link_tag.get_text(strip=True)
            if len(titolo) < 15: continue
            link_parziale = link_tag.get('href', '')
            link_ufficiale = f"https://lavoro.gov.it{link_parziale}" if link_parziale.startswith('/') else link_parziale
            
            riga = [f"MIN_LAVORO_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Ministero del Lavoro", data_oggi, link_ufficiale, "Decreti e Normative", "Alta"]
            aggiungi_riga_locale(riga)
            contatore += 1
        print(f"✅ Ministero del Lavoro completato: aggiunte {contatore} notizie.")
    except Exception as e:
        print(f"❌ Errore Ministero del Lavoro: {e}")
def scrape_normattiva():
    print("🕵️‍♂️ 5/7 - Estrazione da Normattiva (Leggi vigenti)...")
    # Aggiunto il prefisso www. richiesto dai server IPZS
    url = "https://www.normattiva.it/"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a')
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, link in enumerate(links):
            titolo = link.get_text(strip=True)
            if len(titolo) > 20 and ("d.lgs" in titolo.lower() or "legge" in titolo.lower() or "decreto" in titolo.lower()):
                link_parziale = link.get('href', '')
                if not link_parziale: continue
                link_ufficiale = f"https://normattiva.it{link_parziale}" if link_parziale.startswith('/') else link_parziale
                
                riga = [f"NORMATTIVA_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Normattiva", data_oggi, link_ufficiale, "Decreti e Normative", "Alta"]
                aggiungi_riga_locale(riga)
                contatore += 1
                if contatore >= 5: break
        print(f"✅ Normattiva completato: aggiunte {contatore} novità legislative.")
    except Exception as e:
        print(f"⚠️ Nota: Normattiva non raggiungibile sulla rete locale (omesso).")

def scrape_gazzetta_ufficiale():
    print("🕵️‍♂️ 6/7 - Estrazione da Gazzetta Ufficiale...")
    url = "https://www.gazzettaufficiale.it/"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        notizie = soup.find_all('span', class_='titolo-provvedimento') or [a for a in soup.find_all('a') if "serie" in a.get_text().lower()]
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(notizie[:5]):
            link_tag = item if item.name == 'a' else item.find('a')
            if not link_tag: continue
            titolo = link_tag.get_text(strip=True)
            if len(titolo) < 15: continue
            link_parziale = link_tag.get('href', '')
            link_ufficiale = f"https://gazzettaufficiale.it{link_parziale}" if link_parziale.startswith('/') else link_parziale
            
            riga = [f"GAZZETTA_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Gazzetta Ufficiale", data_oggi, link_ufficiale, "Decreti e Normative", "Alta"]
            aggiungi_riga_locale(riga)
            contatore += 1
        print(f"✅ Gazzetta Ufficiale completato: aggiunte {contatore} atti ufficiali.")
    except Exception as e:
        print(f"⚠️ Nota: Gazzetta Ufficiale non raggiungibile sulla rete locale (omesso).")

def scrape_garante_privacy():
    print("🕵️‍♂️ 7/7 - Estrazione da Garante Privacy (Cybersecurity e IA)...")
    url = "https://garanteprivacy.it"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        notizie = soup.find_all('h2', class_='titolo') or soup.find_all('p', class_='titolo') or soup.find_all('h3')
        
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(notizie[:5]):
            link_tag = item if item.name == 'a' else item.find('a')
            if not link_tag: continue
            titolo = link_tag.get_text(strip=True)
            if len(titolo) < 15 or "ricerca" in titolo.lower(): continue
            link_parziale = link_tag.get('href', '')
            link_ufficiale = f"https://garanteprivacy.it{link_parziale}" if link_parziale.startswith('/') else link_parziale
            
            riga = [f"GARANTE_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Garante Privacy", data_oggi, link_ufficiale, "Cybersecurity e IA", "Media"]
            aggiungi_riga_locale(riga)
            contatore += 1
        print(f"✅ Garante Privacy completato: aggiunte {contatore} linee guida/provvedimenti.")
    except Exception as e:
        print(f"❌ Errore Garante Privacy: {e}")

if __name__ == "__main__":
    if os.path.exists(FILE_LOCALE):
        try:
            os.remove(FILE_LOCALE)
            print("🧹 Vecchio file rimosso per pulizia codifica.")
        except Exception:
            print("⚠️ Chiudi Excel prima di avviare lo script!")
            
    inizializza_database_locale()
    
    print("🚀 --- AVVIO SUPER-MOTORE MULTI-FONTE ESTESO (7 FONTI) --- 🚀\n")
    scrape_inail()
    print("-" * 50)
    scrape_anfos()
    print("-" * 50)
    scrape_inl()
    print("-" * 50)
    scrape_ministero_lavoro()
    print("-" * 50)
    scrape_normattiva()
    print("-" * 50)
    scrape_gazzetta_ufficiale()
    print("-" * 50)
    scrape_garante_privacy()
    print("\n🎉 SUPER ARCHIVIO AGGIORNATO AL 100%! Carica il nuovo file .csv su Google Fogli.")
# =====================================================================
# BLOCCO DA AGGIUNGERE: MOTORE DI CATALOGAZIONE AUTOMATICA
# =====================================================================
def assegna_macro_area_e_tag(titolo):
    """Analizza il titolo della notizia e assegna Macro-Area e Sotto-Area (Tag)"""
    titolo_up = titolo.upper()
    
    if any(p in titolo_up for p in ["ATTREZZATUR", "MACCHIN", "DPI", "SEGNALETICA", "LUOGHI DI LAVORO", "APPALT", "DUVRI"]):
        macro = "Sicurezza Generale"
        sub = "#Attrezzature" if "MACCHIN" in titolo_up or "ATTREZZATUR" in titolo_up else "#DPI" if "DPI" in titolo_up else "#Segnaletica" if "SEGNALETICA" in titolo_up else "#Generale"
    elif any(p in titolo_up for p in ["MEDICO", "SORVEGLIANZA SANITARIA", "VISIT", "RUMORE", "VIBRAZION", "ERGONOMIA", "VDT", "BIOLOGIC"]):
        macro = "Salute & Medicina"
        sub = "#Sorveglianza" if "MEDICO" in titolo_up or "VISIT" in titolo_up else "#RischiFisici" if "RUMORE" in titolo_up or "VIBRAZION" in titolo_up else "#Ergonomia"
    elif any(p in titolo_up for p in ["CANTIERE", "EDILIZIA", "POS", "PSC", "PONTEGGI", "QUOTA", "PATENTE A CREDITI"]):
        macro = "Edilizia & Cantieri"
        sub = "#PatenteACrediti" if "PATENTE" in titolo_up else "#LavoriInQuota" if "QUOTA" in titolo_up or "PONTEGGI" in titolo_up else "#Cantieristica"
    elif any(p in titolo_up for p in ["INCENDI", "ANTINCENDIO", "EVACUAZION", "EMERGENZ", "ESTINTORE", "SOCCORSO"]):
        macro = "Antincendio & Emergenze"
        sub = "#Presidi" if "ESTINTORE" in titolo_up or "MANUTENZ" in titolo_up else "#Antincendio"
    elif any(p in titolo_up for p in ["FORMAZION", "CORSO", "CORSI", "ADDESTRASMENTO", "AGGIORNAMENTO RSPP", "RLS", "PREPOSTO", "PATENTIN"]):
        macro = "Formazione & Ruoli"
        sub = "#Abilitazioni" if "PATENTIN" in titolo_up else "#Corsi"
    elif any(p in titolo_up for p in ["CHIMICO", "REACH", "CLP", "SDS", "ATEX", "RIFIUTI", "MUD", "AUA", "AMBIENT"]):
        macro = "Rischio Chimico & Ambiente"
        sub = "#Ambiente" if "RIFIUTI" in titolo_up or "MUD" in titolo_up else "#Chimico"
    else:
        macro = "Sicurezza Generale"


# --- BLOCCO AGGIORNAMENTO DIRETTO GLIDE DEFINITIVO ---
import os
import requests
import json
import pandas as pd

def spingi_dati_a_glide():
    print("--- INIZIO SINCRONIZZAZIONE AUTOMATICA GLIDE ---")
    if os.path.exists('Database_Notizie.csv'):
        df = pd.read_csv('Database_Notizie.csv')
        df = df.fillna('')
        # Prende le ultime 10 notizie salvate
        rows = df.tail(10).to_dict(orient='records')
        payload = {'rows': rows}
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer GHSAT0AAAAAAEPLFULQT6XTJTB46EJSPZGM2XPMKCA'
        }
        # URL corretto e specifico per la tua applicazione
        url = 'https://glideapp.io'
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            print(f'Risposta API Glide - Stato: {response.status_code} - Dettagli: {response.text}')
        except Exception as e:
            print('Errore durante la connessione a Glide:', e)
    else:
        print('File Database_Notizie.csv non trovato per Glide!')

spingi_dati_a_glide()

