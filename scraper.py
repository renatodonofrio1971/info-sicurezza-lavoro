import os
import csv
import re
import uuid
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values

FILE_CSV_LOCALE = "dati_opera_sicura.csv"
COLONNE_CSV = [
    "Titolo",
    "Fonte",
    "Data",
    "Link",
    "Categoria",
    "Importanza",
    "Tipo",         # "News" oppure "Scadenza"
    "Descrizione"   # 8a colonna -> popola 'summary' (news) e 'notes' (deadlines)
]

HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
}

# Set globale per evitare duplicati interni tra le 7 fonti senza passare parametri
TITOLI_VISTI = set()

# Dizionario dinamico per la tabella PostgreSQL 'subcategories'
mappa_categorie = {
    "Edilizia & Cantieri": [
        "#PatenteACrediti", "#CantieriTemporanei", "#Ponteggi", "#LavoriInQuota", "#PSC_POS"
    ],
    "Salute & Medicina": [
        "#SorveglianzaSanitaria", "#MedicoCompetente", "#Amianto", "#StressLavoroCorrelato", "#MalattieProfessionali"
    ],
    "Industria & Impianti": [
        "#DirettivaMacchine", "#ATEX", "#RischioChimico", "#ImpiantiElettrici", "#DPI"
    ],
    "Privacy & Lavoro": [
        "#Videosorveglianza", "#GDPRLavoro", "#ControlloADistanza", "#DatiBiometrici"
    ],
    "Normativa Generale": [
        "#DLgs81_08", "#DVR", "#FormazioneSicurezza", "#BandoISI", "#SanzioniINL"
    ]
}


def inizializza_database_locale():
    """Crea o azzera il file CSV locale a 8 colonne e resetta i titoli visti."""
    global TITOLI_VISTI
    TITOLI_VISTI = set()
    with open(FILE_CSV_LOCALE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLONNE_CSV)
    print(f"[CSV] Database locale '{FILE_CSV_LOCALE}' inizializzato (8 colonne).")


def pulisci_testo(testo):
    """Pulisce spazi multipli, tabulazioni e interruzioni di riga."""
    if not testo:
        return ""
    return re.sub(r"\s+", " ", testo).strip()


def classifica_notizia(titolo, descrizione=""):
    """Assegna categoria e importanza in base alle parole chiave."""
    testo = f"{titolo} {descrizione}".lower()

    parole_alte = [
        "scadenza", "obbligo", "sanzion", "decreto", "legge", "urgente",
        "infortun", "mort", "cantiere", "patente a crediti", "ispettorato",
        "dvr", "sorveglianza sanitaria", "bando isi", "sicurezza sul lavoro"
    ]
    importanza = "High" if any(p in testo for p in parole_alte) else "Medium"

    if any(k in testo for k in ["cantiere", "ediliz", "pontegg", "patente a crediti", "gru"]):
        categoria = "Edilizia & Cantieri"
    elif any(k in testo for k in ["sanit", "medico", "sorveglianza", "salute", "malattia professionale", "amianto"]):
        categoria = "Salute & Medicina"
    elif any(k in testo for k in ["industria", "macchinar", "chimic", "impiant", "atex", "fabbrica"]):
        categoria = "Industria & Impianti"
    elif any(k in testo for k in ["privacy", "gdpr", "videosorveglianza", "biometr", "garante"]):
        categoria = "Privacy & Lavoro"
    else:
        categoria = "Normativa Generale"

    return categoria, importanza


def aggiungi_riga_locale(titolo, fonte, data_str, link, categoria=None, importanza=None, tipo="News", descrizione=""):
    """Aggiunge una riga al CSV locale evitando duplicati interni e salvando la Descrizione."""
    titolo_pulito = pulisci_testo(titolo)
    if not titolo_pulito or len(titolo_pulito) < 12:
        return False

    chiave = titolo_pulito.lower()
    if chiave in TITOLI_VISTI:
        return False
    TITOLI_VISTI.add(chiave)

    descrizione_pulita = pulisci_testo(descrizione)
    if not descrizione_pulita:
        descrizione_pulita = f"Aggiornamento istituzionale da {fonte}: {titolo_pulito}."

    if not categoria or not importanza:
        cat_auto, imp_auto = classifica_notizia(titolo_pulito, descrizione_pulita)
        categoria = categoria or cat_auto
        importanza = importanza or imp_auto

    data_finale = pulisci_testo(data_str) or datetime.now().strftime("%Y-%m-%d")
    link_finale = pulisci_testo(link)

    with open(FILE_CSV_LOCALE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            titolo_pulito,
            fonte,
            data_finale,
            link_finale,
            categoria,
            importanza,
            tipo,
            descrizione_pulita
        ])
    return True


def estrai_articoli_generici(soup, base_url, limite=25):
    """Legge h2/h3 anche in basso, risale al padre per <a> ed estrae <p> per summary."""
    risultati = []
    titoli_locali = set()

    for heading in soup.find_all(["h2", "h3"]):
        if len(risultati) >= limite:
            break

        titolo = pulisci_testo(heading.get_text(" ", strip=True))
        if not titolo or len(titolo) < 15:
            continue

        if titolo.lower() in ["ricerca semplice", "collegamenti veloci", "in evidenza", "normattiva", "menu", "contatti"]:
            continue

        if titolo.lower() in titoli_locali:
            continue

        link_tag = heading.find("a", href=True)
        contenitore = heading.parent

        if not link_tag and contenitore:
            link_tag = contenitore.find("a", href=True)

        if not link_tag and contenitore and contenitore.parent:
            contenitore = contenitore.parent
            link_tag = contenitore.find("a", href=True)

        href = urljoin(base_url, link_tag["href"]) if link_tag else base_url

        riassunto = ""
        p_fratello = heading.find_next_sibling("p")
        if p_fratello:
            riassunto = pulisci_testo(p_fratello.get_text(" ", strip=True))

        if not riassunto and contenitore:
            for p in contenitore.find_all("p"):
                testo_p = pulisci_testo(p.get_text(" ", strip=True))
                if len(testo_p) > 35 and testo_p.lower() != titolo.lower():
                    riassunto = testo_p
                    break

        titoli_locali.add(titolo.lower())
        risultati.append({
            "titolo": titolo,
            "link": href,
            "descrizione": riassunto
        })

    return risultati
# ==============================================================================
# 3. LE 7 FUNZIONI DI SCRAPING ISTITUZIONALI (SENZA PARAMETRI)
# ==============================================================================

def scrape_inail():
    """1. INAIL - Homepage e News (usa www.inail.it e timeout 45s per server GitHub)."""
    fonte = "INAIL"
    url = "https://inail.it"
    aggiunti = 0
    try:
        resp = requests.get(url, headers=HEADERS_HTTP, timeout=45)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, "https://inail.it", limite=30)
        for art in articoli:
            tipo = "Scadenza" if any(k in art["titolo"].lower() for k in ["bando", "scadenza", "isi", "entro il"]) else "News"
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=art["link"],
                tipo=tipo,
                descrizione=art["descrizione"]
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")
    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")

def scrape_anfos():
    """2. ANFOS - Associazione Nazionale Formatori Sicurezza sul Lavoro."""
    fonte = "ANFOS"
    url = "https://anfos.it"
    aggiunti = 0
    try:
        resp = requests.get(url, headers=HEADERS_HTTP, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, "https://anfos.it", limite=25)
        for art in articoli:
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=art["link"],
                tipo="News",
                descrizione=art["descrizione"]
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")
    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")


def scrape_inl():
    """3. INL - Ispettorato Nazionale del Lavoro (card con h2/h3 e link nel padre)."""
    fonte = "Ispettorato Nazionale del Lavoro"
    url = "https://ispettorato.gov.it"
    aggiunti = 0
    try:
        resp = requests.get(url, headers=HEADERS_HTTP, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, "https://ispettorato.gov.it", limite=25)
        for art in articoli:
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=art["link"],
                tipo="News",
                descrizione=art["descrizione"]
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")
    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")


def scrape_ministero_lavoro():
    """4. Ministero del Lavoro e delle Politiche Sociali."""
    fonte = "Ministero del Lavoro"
    url = "https://lavoro.gov.it"
    aggiunti = 0
    try:
        resp = requests.get(url, headers=HEADERS_HTTP, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, "https://lavoro.gov.it", limite=25)
        for art in articoli:
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=art["link"],
                tipo="News",
                descrizione=art["descrizione"]
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")
    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")


def scrape_normattiva():
    """5. Normattiva - Usa sempre www.normattiva.it per evitare errori DNS."""
    fonte = "Normattiva"
    url_www = "https://normattiva.it"
    aggiunti = 0
    try:
        resp = requests.get(url_www, headers=HEADERS_HTTP, timeout=35)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, url_www, limite=25)
        for art in articoli:
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=url_www,
                categoria="Normativa Generale",
                importanza="High",
                tipo="News",
                descrizione=art["descrizione"]
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")
    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")


def scrape_gazzetta_ufficiale():
    """6. Gazzetta Ufficiale - Usa sempre www.gazzettaufficiale.it per il DNS."""
    fonte = "Gazzetta Ufficiale"
    url_scrape = "https://gazzettaufficiale.it"
    url_link = "https://gazzettaufficiale.it"
    aggiunti = 0
    try:
        resp = requests.get(url_scrape, headers=HEADERS_HTTP, timeout=35)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, url_link, limite=25)

        if not articoli:
            for item in soup.select(".risultato, .elenco_atti li, article")[:25]:
                testo = pulisci_testo(item.get_text(" ", strip=True))
                if len(testo) > 25:
                    articoli.append({
                        "titolo": testo[:180],
                        "link": url_link,
                        "descrizione": testo
                    })

        for art in articoli:
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=url_link,
                categoria="Normativa Generale",
                importanza="High",
                tipo="News",
                descrizione=art["descrizione"]
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")
    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")

def scrape_garante_privacy():
    """7. Garante per la Protezione dei Dati Personali - Provvedimenti e News lavoro."""
    fonte = "Garante Privacy"
    url = "https://garanteprivacy.it"
    aggiunti = 0
    try:
        resp = requests.get(url, headers=HEADERS_HTTP, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, "https://garanteprivacy.it", limite=25)
        for art in articoli:
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=art["link"],
                categoria="Privacy & Lavoro",
                tipo="News",
                descrizione=art["descrizione"]
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")
    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")
# ==============================================================================
# 4. SINCRONIZZAZIONE DIRETTA SU POSTGRESQL GLIDEOS + BLOCCO MAIN
# ==============================================================================

def spingi_dati_a_glide():
    """
    Sincronizza su PostgreSQL di GlideOS generando UUID espliciti per la colonna 'id'
    di subcategories, news e deadlines.
    """
    db_url = os.environ.get("GLIDE_DB_URL")
    if not db_url:
        print("[ERRORE DB] Variabile d'ambiente GLIDE_DB_URL non trovata.")
        return

    if not os.path.exists(FILE_CSV_LOCALE):
        print(f"[ERRORE CSV] File '{FILE_CSV_LOCALE}' non trovato.")
        return

    conn = None
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        print("[DB] Connessione a PostgreSQL GlideOS riuscita.")

        # 1. Sincronizzazione 'subcategories' con id UUID esplicito
        cur.execute("SELECT macro_area, tag_name FROM subcategories;")
        sub_esistenti = {(r, r) for r in cur.fetchall() if r and r}

        nuove_sub = []
        for macro_area, tags in mappa_categorie.items():
            for tag in tags:
                if (macro_area, tag) not in sub_esistenti:
                    nuove_sub.append((str(uuid.uuid4()), macro_area, tag))

        if nuove_sub:
            execute_values(
                cur,
                "INSERT INTO subcategories (id, macro_area, tag_name) VALUES %s;",
                nuove_sub
            )
            print(f"[DB] Inserite {len(nuove_sub)} nuove sotto-categorie in 'subcategories'.")

        # 2. Recupero titoli esistenti per deduplicazione
        cur.execute("SELECT LOWER(TRIM(title)) FROM news WHERE title IS NOT NULL;")
        news_esistenti = {r for r in cur.fetchall() if r}

        cur.execute("SELECT LOWER(TRIM(title)) FROM deadlines WHERE title IS NOT NULL;")
        scadenze_esistenti = {r for r in cur.fetchall() if r}

        nuove_news = []
        nuove_scadenze = []
        oggi_str = datetime.now().strftime("%Y-%m-%d")

        with open(FILE_CSV_LOCALE, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                titolo = pulisci_testo(row.get("Titolo", ""))
                if not titolo:
                    continue

                chiave = titolo.lower()
                fonte = pulisci_testo(row.get("Fonte", "")) or "Fonte Istituzionale"
                data_val = pulisci_testo(row.get("Data", "")) or oggi_str
                link = pulisci_testo(row.get("Link", "")) or "https://normattiva.it"
                categoria = pulisci_testo(row.get("Categoria", "")) or "Normativa Generale"
                importanza = pulisci_testo(row.get("Importanza", "")) or "Medium"
                tipo = pulisci_testo(row.get("Tipo", "")) or "News"
                descrizione = pulisci_testo(row.get("Descrizione", "")) or f"Aggiornamento da {fonte}: {titolo}."

                if tipo.lower() == "scadenza":
                    if chiave not in scadenze_esistenti:
                        scadenze_esistenti.add(chiave)
                        nuove_scadenze.append((
                            str(uuid.uuid4()),
                            titolo,
                            data_val,
                            descrizione,
                            link
                        ))
                else:
                    if chiave not in news_esistenti:
                        news_esistenti.add(chiave)
                        nuove_news.append((
                            str(uuid.uuid4()),
                            titolo,
                            fonte,
                            data_val,
                            link,
                            categoria,
                            importanza,
                            descrizione
                        ))

        # 3. Inserimento massivo su 'news' con id UUID
        if nuove_news:
            execute_values(
                cur,
                """
                INSERT INTO news (id, title, source, date, official_link, category, importance, summary)
                VALUES %s;
                """,
                nuove_news
            )
            print(f"[DB] Inserite {len(nuove_news)} nuove notizie in 'news' (con summary).")
        else:
            print("[DB] Nessuna nuova notizia da inserire in 'news'.")

        # 4. Inserimento massivo su 'deadlines' con id UUID
        if nuove_scadenze:
            execute_values(
                cur,
                """
                INSERT INTO deadlines (id, title, due_date, notes, official_link)
                VALUES %s;
                """,
                nuove_scadenze
            )
            print(f"[DB] Inserite {len(nuove_scadenze)} nuove scadenze in 'deadlines'.")
        else:
            print("[DB] Nessuna nuova scadenza da inserire in 'deadlines'.")

        # 5. Controllo utenti anonimi iscritti alle notifiche Push (GDPR)
        cur.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE COALESCE(notify_general, FALSE) = TRUE
               OR COALESCE(notify_health, FALSE) = TRUE
               OR COALESCE(notify_construction, FALSE) = TRUE
               OR COALESCE(notify_industry, FALSE) = TRUE;
        """)
        utenti_attivi = cur.fetchone()
        print(f"[PUSH GDPR] Dispositivi anonimi con notifiche attive: {utenti_attivi}.")

        conn.commit()
        cur.close()
        print("[DB] Sincronizzazione PostgreSQL completata con successo!")

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[ERRORE CRITICO DB] {e}")
    finally:
        if conn:
            conn.close()

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
