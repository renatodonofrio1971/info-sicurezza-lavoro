import csv
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import pandas as pd

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
    id_notizia = riga[0]
    titolo_originale = riga[1]
    fonte = riga[2]
    data = riga[3]
    link_ufficiale = riga[4]
    
    macro_area, sotto_tag = assegna_macro_area_e_tag(titolo_originale)
    importanza = "Alta" if any(p in titolo_originale.upper() for p in ["URGENTI", "OBBLIGO", "D.LGS", "DECRETO"]) or riga[6] == "Alta" else "Media"
    titolo_con_tag = f"{titolo_originale} {sotto_tag}"
    
    riga_finale = [id_notizia, titolo_con_tag, fonte, data, link_ufficiale, macro_area, importanza]
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
            
            importance_flag = "Alta" if "scadenza" in titolo.lower() or "obbligo" in titolo.lower() else "Media"
            categoria = "Scadenze e Norme" if "scadenza" in titolo.lower() else "Aggiornamenti"
            
            riga = [f"ANFOS_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "ANFOS", data_oggi, link_ufficiale, categoria, importance_flag]
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
    url = "https://www.normattiva.it/"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('h3')
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(links):
            titolo = item.get_text(strip=True).replace('"', '')
            if len(titolo) > 10:
                
                # LINK ANCORATO E BLINDATO COME RICHIESTO
                link_ufficiale = "https://www.normattiva.it/"
                
                riga = [f"NORMATTIVA_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Normattiva", data_oggi, link_ufficiale, "Decreti e Normative", "Alta"]
                aggiungi_riga_locale(riga)
                contatore += 1
                if contatore >= 5: break
        print(f"✅ Normattiva completato: aggiunte {contatore} novità legislative.")
    except Exception as e:
        print(f"⚠️ Nota: Normattiva non raggiungibile ({e})")

def scrape_gazzetta_ufficiale():
    print("🕵️‍♂️ 6/7 - Estrazione da Gazzetta Ufficiale...")
    url = "https://www.gazzettaufficiale.it/"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200: return
        soup = BeautifulSoup(response.text, 'html.parser')
        blocchi = soup.find_all('a')
        contatore = 0
        data_oggi = datetime.now().strftime("%d/%m/%Y")
        for index, item in enumerate(blocchi):
            titolo = item.get_text(strip=True)
            if len(titolo) > 25 and any(p in titolo.lower() for p in ["decreto", "legge", "l.", "d.l.", "attuazione", "misure"]):
                
                # LINK ANCORATO E BLINDATO COME RICHIESTO
                link_ufficiale = "https://www.gazzettaufficiale.it/"
                
                riga = [f"GAZZETTA_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Gazzetta Ufficiale", data_oggi, link_ufficiale, "Decreti e Normative", "Alta"]
                aggiungi_riga_locale(riga)
                contatore += 1
                if contatore >= 5: break
        print(f"✅ Gazzetta Ufficiale completato: aggregati {contatore} atti ufficiali.")
    except Exception as e:
        print(f"⚠️ Nota: Gazzetta Ufficiale non raggiungibile ({e})")

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
            link_ufficiale = link_parziale if link_parziale.startswith('http') else f"https://garanteprivacy.it/{link_parziale.lstrip('/')}"
            riga = [f"GARANTE_{datetime.now().strftime('%Y%m%d')}_{index}", titolo, "Garante Privacy", data_oggi, link_ufficiale, "Cybersecurity e IA", "Media"]
            aggiungi_riga_locale(riga)
            contatore += 1
        print(f"✅ Garante Privacy completato: aggiunte {contatore} linee guida/provvedimenti.")
    except Exception as e:
        print(f"❌ Errore Garante Privacy: {e}")

def spingi_dati_a_glide():
    print("🚀 --- INIZIO SINCRONIZZAZIONE DIRETTA DATABASE GLIDE (SQL) --- 🚀")
    db_url = os.environ.get("GLIDE_DB_URL")
    
    if not db_url:
        print("⚠️ Stringa di connessione GLIDE_DB_URL mancante nei repository Secrets!")
        return

    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    from sqlalchemy import create_engine
    import time
    
    try:
        engine = create_engine(db_url)
        
        # 1. INVIO DELLE NOTIZIE (Tabella 'news')
        if os.path.exists(FILE_LOCALE):
            df = pd.read_csv(FILE_LOCALE, sep=';').fillna('')
            df_glide = pd.DataFrame()
            timestamp_base = int(time.time())
            df_glide['id'] = [timestamp_base + i for i in range(len(df))]
            df_glide['title'] = df['Titolo']
            df_glide['source'] = df['Fonte']
            df_glide['date'] = df['Data']
            df_glide['official_link'] = df['Link_Ufficiale']
            df_glide['category'] = df['Categoria']
            df_glide['importance'] = df['Importanza'].replace({'Alta': 'High', 'Media': 'Medium', 'Bassa': 'Low'})
            
            df_glide.to_sql('news', con=engine, if_exists='append', index=False)
            print(f"✅ SQL News completato: inserite {len(df_glide)} notizie.")

        # 2. INVIO DELLE SCADENZE (Tabella 'deadlines')
        print("⏳ Generazione scadenze di conformità correnti...")
        scadenze_dati = [
            {"title": "Aggiornamento DVR - Analisi dei Rischi Annuale", "due_date": "2026-12-15", "notes": "Verifica conformità e aggiornamento signatures del RLS."},
            {"title": "Invio Autoliquidazione INAIL 2026", "due_date": "2026-11-30", "notes": "Scadenza termine per calcolo saldo e premio di regolazione."},
            {"title": "Verifica Periodica Impianti di Messa a Terra", "due_date": "2026-12-01", "notes": "Controllo ispettivo biennale/quinquennale obbligatorio DPR 462/01."},
            {"title": "Scadenza Rinnovo Cassette Primo Soccorso", "due_date": "2026-11-25", "notes": "Controllo integrità e validità dei presidi medici scaduti."}
        ]
        
        df_scadenze = pd.DataFrame(scadenze_dati)
        df_scadenze_glide = pd.DataFrame()
        timestamp_scad = int(time.time()) + 1000
        df_scadenze_glide['id'] = [timestamp_scad + i for i in range(len(df_scadenze))]
        df_scadenze_glide['title'] = df_scadenze['title']
        df_scadenze_glide['due_date'] = df_scadenze['due_date']
        df_scadenze_glide['notes'] = df_scadenze['notes']
        
        df_scadenze_glide.to_sql('deadlines', con=engine, if_exists='append', index=False)
        print(f"✅ SQL Deadlines completato: inserite {len(df_scadenze_glide)} scadenze istituzionali attive!")
        
        # 3. ENGINE NOTIFICHE INCROCIATE ANONIME A NORMA GDPR
        print("📢 Rilevamento preferenze per smistamento notifiche Push...")
        
        # PROVA ENTRAMBE LE VARIANTI DI COSTRUTTO SU POSTGRES PER SICUREZZA
        utenti_df = pd.DataFrame()
        for t_name in ['users', 'Users']:
            try:
                utenti_df = pd.read_sql_table(t_name, con=engine)
                print(f"🔍 Tabella utenti agganciata correttamente con il nome: '{t_name}'")
                break
            except:
                continue

        if not utenti_df.empty:
            print(f"ℹ️ Sistema notifiche pronto. Rilevati {len(utenti_df)} dispositivi anonimi registrati.")
            for idx, notizia in df_glide.iterrows():
                cat = notizia['category']
                titolo = notizia['title']
                
                colonna_spunta = 'notify_general'
                if cat == 'Salute & Medicina':
                    colonna_spunta = 'notify_health'
                elif cat == 'Edilizia & Cantieri':
                    colonna_spunta = 'notify_construction'
                
                if colonna_spunta in utenti_df.columns:
                    target_dispositivi = utenti_df[utenti_df[colonna_spunta] == True]['id'].tolist()
                    if target_dispositivi:
                        print(f"🔔 Notifica preparata per {len(target_dispositivi)} dispositivi anonimi su area '{cat}': {titolo[:40]}...")
        else:
            print("ℹ️ Coda notifiche in transito: nessun dispositivo ancora registrato nell'app.")
                
    except Exception as e:
        print('❌ Errore durante l\'inserimento nel database Glide:', e)

if __name__ == "__main__":
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
    print("\n🎉 SUPER ARCHIVIO GENERATO CON SUCCESSO LOCALE!")
    print("-" * 50)
    spingi_dati_a_glide()


