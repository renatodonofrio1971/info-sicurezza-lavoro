import os
import csv
import json
import re
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

# Regole parole chiave per associare automaticamente gli hashtag alle notizie
REGOLE_HASHTAG = {
    "#PatenteACrediti": ["patente a crediti", "patente a punti"],
    "#CantieriTemporanei": ["cantiere", "cantieri", "ediliz"],
    "#Ponteggi": ["pontegg"],
    "#LavoriInQuota": ["quota", "caduta dall'alto"],
    "#PSC_POS": ["psc", "pos", "piano di sicurezza"],
    "#SorveglianzaSanitaria": ["sorveglianza sanitaria", "visita medica"],
    "#MedicoCompetente": ["medico competente"],
    "#Amianto": ["amianto"],
    "#StressLavoroCorrelato": ["stress lavoro", "salute mentale", "benessere psicologico"],
    "#MalattieProfessionali": ["malattia professionale", "malattie professionali", "patologie"],
    "#DirettivaMacchine": ["macchinar", "direttiva macchine"],
    "#ATEX": ["atex", "esplosiv"],
    "#RischioChimico": ["chimic", "sostanze pericolose"],
    "#ImpiantiElettrici": ["impiant", "elettric"],
    "#DPI": ["dpi", "dispositivi di protezione"],
    "#Videosorveglianza": ["videosorveglianza", "telecamer"],
    "#GDPRLavoro": ["privacy", "gdpr", "dati personali", "garante"],
    "#ControlloADistanza": ["controllo a distanza", "lavoro agile", "smart working"],
    "#DatiBiometrici": ["biometr"],
    "#DLgs81_08": ["81/08", "81/2008", "testo unico", "sicurezza sul lavoro", "prevenzione"],
    "#DVR": ["dvr", "valutazione dei rischi", "rischi"],
    "#FormazioneSicurezza": ["formazione", "addestramento", "corso", "scuole"],
    "#BandoISI": ["bando isi", "bric", "finanziament", "incentiv"],
    "#SanzioniINL": ["sanzion", "ispettorato", "vigilanza", "ispezion"]
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


def aggiungi_hashtag_al_testo(titolo, descrizione):
    """Appende gli hashtag pertinenti in fondo alla descrizione per attivare i chip su GlideOS."""
    testo_ricerca = f"{titolo} {descrizione}".lower()
    tag_trovati = []

    for hashtag, keywords in REGOLE_HASHTAG.items():
        if any(kw in testo_ricerca for kw in keywords):
            if hashtag not in descrizione:
                tag_trovati.append(hashtag)

    if not tag_trovati and "#DLgs81_08" not in descrizione:
        tag_trovati.append("#DLgs81_08")

    if tag_trovati:
        return f"{descrizione} | {' '.join(tag_trovati)}"
    return descrizione


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

PAROLE_SICUREZZA_STRETTE = [
    "sicurezza sul lavoro", "salute e sicurezza", "81/08", "81/2008", "testo unico sicurezza",
    "infortun", "malattia professionale", "malattie professionali", "prevenzione",
    "dvr", "valutazione dei rischi", "duvri", "psc", "pos",
    "cantiere", "cantieri", "patente a crediti", "pontegg", "lavori in quota", "caduta dall'alto",
    "sorveglianza sanitaria", "medico competente", "primo soccorso", "antincendio", "emergenza",
    "dpi", "dispositivi di protezione", "rspp", "aspp", "rls", "preposto", "preposti",
    "amianto", "rischio chimico", "rischio biologico", "rischio elettrico", "atex", "rumore", "vibrazioni",
    "direttiva macchine", "attrezzature di lavoro", "verifiche periodiche",
    "bando isi", "bandi isi", "bric", "incentivi alle imprese per la sicurezza",
    "formazione sicurezza", "addestramento", "accordo stato-regioni", "accordo stato regioni",
    "videosorveglianza", "controllo a distanza", "dati biometrici", "lavoratori"
]

PAROLE_ESCLUSE = [
    "cioccolato", "cinema", "mostra fotografica", "concerto", "teatro", "sport",
    "pensioni", "assegno di inclusione", "naspi", "disoccupazione", "tirocini extracurriculari",
    "flussi", "click day immigrati", "reddito di cittadinanza", "bonus mamme"
]


def e_pertinente(titolo, descrizione=""):
    """Accetta SOLO notizie strettamente inerenti a sicurezza, salute, cantieri e tutela sul lavoro."""
    testo = f"{titolo} {descrizione}".lower()
    if any(bad in testo for bad in PAROLE_ESCLUSE):
        return False
    return any(kw in testo for kw in PAROLE_SICUREZZA_STRETTE)

def aggiungi_riga_locale(titolo, fonte, data_str, link, categoria=None, importanza=None, tipo="News", descrizione=""):
    """Aggiunge una riga al CSV locale evitando duplicati interni e salvando la Descrizione con hashtag."""
    titolo_pulito = pulisci_testo(titolo)
    if not titolo_pulito or len(titolo_pulito) < 12:
        return False
    
    if not e_pertinente(titolo_pulito, descrizione):
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

    descrizione_pulita = aggiungi_hashtag_al_testo(titolo_pulito, descrizione_pulita)

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
    """1. INAIL - Scansiona le 4 sezioni tematiche scelte (Protocolli, Catalogo, Valutazione Rischio, News)."""
    fonte = "INAIL"
    url_base = "https://inail.it"
    urls_inail = [
        "https://inail.it/portale/it/atti-e-documenti/protocolli-accordi-e-convenzioni/protocolli-e-accordi.html",
        "https://inail.it/portale/it/inail-comunica/pubblicazioni/catalogo-generale.html",
        "https://inail.it/portale/prevenzione-e-sicurezza/it/prevenzione-e-sicurezza/prevenzione-per-la-salute-e-la-sicurezza-sul-lavoro/strumenti-per-la-valutazione-del-rischio.html",
        "https://inail.it/portale/it/inail-comunica/news.html"
    ]
    aggiunti = 0

    for url in urls_inail:
        try:
            resp = requests.get(url, headers=HEADERS_HTTP, timeout=25)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # A. Estrazione standard card (h2/h3 + p) per News, Catalogo e Protocolli
            articoli = estrai_articoli_generici(soup, url_base, limite=25)

            # B. Estrazione dedicata alla tabella "Strumenti per la valutazione del rischio"
            if "strumenti-per-la-valutazione-del-rischio" in url:
                for tr in soup.select("table tbody tr")[:25]:
                    celle = tr.find_all("td")
                    if len(celle) >= 3:
                        titolo_strum = pulisci_testo(celle[0].get_text(" ", strip=True))
                        a_tag = celle[0].find("a", href=True)
                        link_strum = urljoin(url_base, a_tag["href"]) if a_tag else url
                        rischio = pulisci_testo(celle[1].get_text(" ", strip=True))
                        ateco = pulisci_testo(celle[2].get_text(" ", strip=True))
                        tipo_strum = pulisci_testo(celle[3].get_text(" ", strip=True)) if len(celle) >= 4 else "Strumento INAIL"
                        desc_strum = f"{tipo_strum} INAIL per {rischio} (Settore: {ateco})."
                        articoli.append({
                            "titolo": titolo_strum,
                            "link": link_strum,
                            "descrizione": desc_strum
                        })

            for art in articoli:
                tipo = "Scadenza" if any(k in art["titolo"].lower() for k in ["bando", "scadenza", "isi"]) else "News"
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
            print(f"[ERRORE {fonte} su {url}] {e}")

    print(f"[{fonte}] Estratte {aggiunti} nuove voci dalle 4 sezioni.")

def scrape_anfos():
    """2. ANFOS - Scansiona sia anfos.it/notizie sia quotidianosicurezza.it."""
    sorgenti_anfos = [
        ("ANFOS", "https://www.anfos.it/notizie/", "https://www.anfos.it"),
        ("ANFOS - Quotidiano Sicurezza", "https://www.quotidianosicurezza.it/", "https://www.quotidianosicurezza.it")
    ]
    aggiunti = 0

    for nome_fonte, url_pagina, url_base in sorgenti_anfos:
        try:
            resp = requests.get(url_pagina, headers=HEADERS_HTTP, timeout=25)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            articoli = estrai_articoli_generici(soup, url_base, limite=25)
            for art in articoli:
                if aggiungi_riga_locale(
                    titolo=art["titolo"],
                    fonte=nome_fonte,
                    data_str=datetime.now().strftime("%Y-%m-%d"),
                    link=art["link"],
                    tipo="News",
                    descrizione=art["descrizione"]
                ):
                    aggiunti += 1
        except Exception as e:
            print(f"[ERRORE {nome_fonte}] {e}")

    print(f"[ANFOS & Quotidiano Sicurezza] Estratte {aggiunti} nuove voci.")

def scrape_inl():
    """3. INL - Scansiona le due sezioni ufficiali News INL e News dalle sedi."""
    fonte = "Ispettorato Nazionale del Lavoro"
    url_base = "https://www.ispettorato.gov.it"
    urls_inl = [
        "https://www.ispettorato.gov.it/comunicazione/comunicati/news-inl/",
        "https://www.ispettorato.gov.it/comunicazione/comunicati/news-dalle-sedi/"
    ]
    aggiunti = 0

    for url in urls_inl:
        try:
            resp = requests.get(url, headers=HEADERS_HTTP, timeout=25)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            articoli = estrai_articoli_generici(soup, url_base, limite=25)
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
            print(f"[ERRORE {fonte} su {url}] {e}")

    print(f"[{fonte}] Estratte {aggiunti} nuove voci dalle 2 sezioni.")

def scrape_ministero_lavoro():
    """4. Ministero del Lavoro - Scansiona le 3 tassonomie verticali su Sicurezza, Interpelli e Infortuni."""
    fonte = "Ministero del Lavoro"
    url_base = "https://www.lavoro.gov.it"
    urls_ministero = [
        "https://www.lavoro.gov.it/taxonomy/term/92",   # Sicurezza sul lavoro
        "https://www.lavoro.gov.it/taxonomy/term/26",   # Interpelli Salute e Sicurezza D.Lgs. 81/08
        "https://www.lavoro.gov.it/taxonomy/term/129"   # Infortuni sul lavoro
    ]
    aggiunti = 0

    for url in urls_ministero:
        try:
            resp = requests.get(url, headers=HEADERS_HTTP, timeout=25)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            articoli = estrai_articoli_generici(soup, url_base, limite=25)
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
            print(f"[ERRORE {fonte} su {url}] {e}")

    print(f"[{fonte}] Estratte {aggiunti} nuove voci dalle 3 sezioni tematiche.")

def scrape_normattiva():
    """5. Normattiva - Estrae il link diretto al singolo provvedimento (es. uri-res/N2Ls)."""
    fonte = "Normattiva"
    url_base = "https://www.normattiva.it"
    aggiunti = 0
    try:
        resp = requests.get(url_base, headers=HEADERS_HTTP, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articoli = estrai_articoli_generici(soup, url_base, limite=25)
        for art in articoli:
            link_diretto = art["link"] if art["link"].startswith("http") else url_base
            if aggiungi_riga_locale(
                titolo=art["titolo"],
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=link_diretto,
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
    """6. Gazzetta Ufficiale - Legge gli ultimi atti e decreti sulla sicurezza e normativa."""
    fonte = "Gazzetta Ufficiale"
    url_rss = "https://google.com"
    aggiunti = 0
    try:
        resp = requests.get(url_rss, headers=HEADERS_HTTP, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        items = soup.find_all("item")[:25]

        for item in items:
            title_tag = item.find("title")
            titolo = pulisci_testo(title_tag.get_text()) if title_tag else ""
            # Rimuove il suffisso " - Gazzetta Ufficiale" aggiunto da Google News
            titolo = re.sub(r"\s*-\s*Gazzetta Ufficiale.*$", "", titolo, flags=re.I).strip()

            link_tag = item.find("link")
            link_raw = ""
            if link_tag:
                link_raw = pulisci_testo(link_tag.get_text()) or (pulisci_testo(link_tag.next_sibling) if isinstance(link_tag.next_sibling, str) else "")
            link = link_raw if link_raw.startswith("http") else "https://www.gazzettaufficiale.it"

            desc_tag = item.find("description")
            desc_raw = desc_tag.get_text() if desc_tag else ""
            desc = pulisci_testo(BeautifulSoup(desc_raw, "html.parser").get_text())
            if not desc or len(desc) < 15:
                desc = f"Atto pubblicato in Gazzetta Ufficiale della Repubblica Italiana: {titolo}."

            if aggiungi_riga_locale(
                titolo=titolo,
                fonte=fonte,
                data_str=datetime.now().strftime("%Y-%m-%d"),
                link=link,
                categoria="Normativa Generale",
                importanza="High",
                tipo="News",
                descrizione=desc
            ):
                aggiunti += 1
    except Exception as e:
        print(f"[ERRORE {fonte}] {e}")

    print(f"[{fonte}] Estratte {aggiunti} nuove voci.")

def scrape_garante_privacy():
    """7. Garante Privacy - Scansiona le sezioni ufficiali /news e /comunicati-stampa con link diretti."""
    fonte = "Garante Privacy"
    url_base = "https://www.garanteprivacy.it"
    urls_garante = [
        "https://www.garanteprivacy.it/news",
        "https://www.garanteprivacy.it/comunicati-stampa"
    ]
    aggiunti = 0

    for url in urls_garante:
        try:
            resp = requests.get(url, headers=HEADERS_HTTP, timeout=25)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            articoli = estrai_articoli_generici(soup, url_base, limite=25)

            # Estrae anche i link diretti presenti nelle liste di News e Ultimi comunicati stampa
            for a_tag in soup.find_all("a", href=True):
                href = urljoin(url_base, a_tag["href"])
                titolo = pulisci_testo(a_tag.get_text(" ", strip=True))
                if len(titolo) >= 25 and ("/web/guest/" in href or "/home/docweb/" in href):
                    articoli.append({
                        "titolo": titolo,
                        "link": href,
                        "descrizione": f"Comunicazione ufficiale Garante Privacy: {titolo}."
                    })

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
            print(f"[ERRORE {fonte} su {url}] {e}")

    print(f"[{fonte}] Estratte {aggiunti} nuove voci dalle 2 sezioni.")

def e_pertinente_cassazione(titolo, descrizione=""):
    """Filtro ultra-stretto specifico per la giurisprudenza della Cassazione su sicurezza e infortuni sul lavoro."""
    testo = f"{titolo} {descrizione}".lower()
    
    # Blocca subito materie estranee tipiche della Cassazione Penale/Tributaria
    esclusioni_cassazione = [
        "superbonus", "credito di imposta", "credito d'imposta", "tributar",
        "arresto in flagranza", "misura cautelare", "rito abbreviato",
        "stupefacenti", "maltrattamenti", "furto", "rapina", "truffa",
        "diffamazione", "estorsione", "peculato", "abuso d'ufficio",
        "estradizione", "mandato di arresto", "codice della strada",
        "guida in stato di ebbrezza", "immigrazione", "falliment"
    ]
    if any(bad in testo for bad in esclusioni_cassazione):
        return False

    # Accetta SOLO se contiene almeno un riferimento esplicito a infortuni, D.Lgs. 81/08 o sicurezza sul lavoro
    parole_chiave_cassazione = [
        "infortunio sul lavoro", "infortuni sul lavoro", "infortunio lavorativo",
        "malattia professionale", "malattie professionali",
        "sicurezza sul lavoro", "sicurezza nei luoghi di lavoro", "igiene del lavoro",
        "81/2008", "81/08", "testo unico sicurezza",
        "datore di lavoro", "preposto", "rspp", "coordinatore per la sicurezza",
        "documento di valutazione dei rischi", "piano operativo di sicurezza",
        "cantiere edile", "caduta dall'alto", "dispositivi di protezione individuale",
        "omicidio colposo", "lesioni personali colpose", "violazione delle norme antinfortunistiche",
        "normativa antinfortunistica", "prevenzione infortuni"
    ]
    return any(kw in testo for kw in parole_chiave_cassazione)


def scrape_cassazione():
    """8. Corte di Cassazione & IV Sezione Penale - Solo sentenze su infortuni, D.Lgs. 81/08 e sicurezza sul lavoro."""
    fonte = "Corte di Cassazione"
    url_base = "https://cortedicassazione.it"
    urls_cassazione = [
        "https://cortedicassazione.it/it/ultime_dalla_corte.page",
        "https://cortedicassazione.it/it/quarta_sezione_penale.page",
        "https://cortedicassazione.it/it/giurisprudenza_penale.page"
    ]
    aggiunti = 0

    for url in urls_cassazione:
        try:
            resp = requests.get(url, headers=HEADERS_HTTP, timeout=25)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            articoli = estrai_articoli_generici(soup, url_base, limite=30)

            for item in soup.select("div.risultato, div.item, article, li"):
                testo_blocco = pulisci_testo(item.get_text(" ", strip=True))
                if len(testo_blocco) < 40:
                    continue

                a_tag = item.find("a", href=True)
                if not a_tag:
                    continue

                href = a_tag["href"]
                if href.startswith("#") or "javascript:" in href.lower():
                    continue

                link_sent = urljoin(url_base, href)
                titolo_raw = pulisci_testo(a_tag.get_text(" ", strip=True))
                if titolo_raw.lower() in {"vai al documento", "leggi di più", "dettaglio", "scarica"} or len(titolo_raw) < 15:
                    titolo_raw = testo_blocco[:140] + ("..." if len(testo_blocco) > 140 else "")

                sezione_tag = " [IV Sez. Penale]" if "quarta_sezione" in url or "quarta sezione" in testo_blocco.lower() else ""
                titolo_finale = f"Cassazione{sezione_tag}: {titolo_raw}" if not titolo_raw.lower().startswith("cassazione") else titolo_raw

                articoli.append({
                    "titolo": titolo_finale,
                    "link": link_sent,
                    "descrizione": testo_blocco[:450]
                })

            for art in articoli:
                # Controllo stretto specifico per Cassazione PRIMA di salvare
                if not e_pertinente_cassazione(art["titolo"], art["descrizione"]):
                    continue

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
            print(f"[ERRORE {fonte} su {url}] {e}")

    print(f"[{fonte} & IV Sez. Penale] Estratte {aggiunti} nuove voci pertinenti dalle 3 sezioni.")


# ==============================================================================
# 4. SINCRONIZZAZIONE DIRETTA SU POSTGRESQL GLIDEOS + BLOCCO MAIN
# ==============================================================================

def spingi_dati_a_glide():
    """
    Sincronizza su PostgreSQL di GlideOS calcolando ID interi progressivi (MAX(id) + 1)
    per subcategories, news e deadlines, e aggiorna le righe esistenti con hashtag e link diretti.
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

        # Pulizia automatica delle vecchie notizie fuori tema già presenti in PostgreSQL
        cur.execute("SELECT id, title, COALESCE(summary, '') FROM news;")
        ids_da_rimuovere = [
            r_id for r_id, r_title, r_summary in cur.fetchall()
            if not e_pertinente(r_title or "", r_summary or "")
        ]
        if ids_da_rimuovere:
            cur.execute("DELETE FROM news WHERE id = ANY(%s);", (ids_da_rimuovere,))
            print(f"[DB] Rimosse {len(ids_da_rimuovere)} notizie non strettamente inerenti alla sicurezza sul lavoro.")
        
        # Elimina automaticamente le scadenze passate da più di 15 giorni
        cur.execute("""
            DELETE FROM deadlines
            WHERE due_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
              AND TO_DATE(due_date, 'YYYY-MM-DD') < CURRENT_DATE - INTERVAL '15 days';
        """)
        if cur.rowcount > 0:
            print(f"[DB] Rimosse {cur.rowcount} scadenze passate da oltre 15 giorni.")

        # 0. Manutenzione automatica righe già esistenti (date ISO + hashtag nel summary + link Normattiva)
        cur.execute("""
            UPDATE news
            SET date = TO_CHAR(TO_DATE(date, 'DD/MM/YYYY'), 'YYYY-MM-DD')
            WHERE date ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$';
        """)

        cur.execute("SELECT id, title, COALESCE(summary, '') FROM news WHERE COALESCE(summary, '') NOT LIKE '%#%';")
        righe_senza_tag = cur.fetchall()
        for r_id, r_title, r_summary in righe_senza_tag:
            nuovo_summary = aggiungi_hashtag_al_testo(r_title or "", r_summary or r_title or "")
            cur.execute("UPDATE news SET summary = %s WHERE id = %s;", (nuovo_summary, r_id))
        if righe_senza_tag:
            print(f"[DB] Aggiornate {len(righe_senza_tag)} notizie esistenti con gli hashtag per i chip.")

        # Aggiorna eventuali link diretti di Normattiva per le notizie già presenti
        with open(FILE_CSV_LOCALE, mode="r", encoding="utf-8") as f_norm:
            for r_norm in csv.DictReader(f_norm):
                if r_norm.get("Fonte") == "Normattiva" and r_norm.get("Link", "").startswith("http"):
                    cur.execute(
                        "UPDATE news SET official_link = %s WHERE source = 'Normattiva' AND LOWER(TRIM(title)) = %s;",
                        (r_norm["Link"], pulisci_testo(r_norm["Titolo"]).lower())
                    )

        # 1. Sincronizzazione 'subcategories' con ID INTEGER progressivo
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM subcategories;")
        next_sub_id = cur.fetchone()[0] + 1

        cur.execute("SELECT macro_area, tag_name FROM subcategories;")
        sub_esistenti = {(r[0], r[1]) for r in cur.fetchall() if r[0] and r[1]}

        nuove_sub = []
        for macro_area, tags in mappa_categorie.items():
            for tag in tags:
                if (macro_area, tag) not in sub_esistenti:
                    nuove_sub.append((next_sub_id, macro_area, tag))
                    next_sub_id += 1

        if nuove_sub:
            execute_values(
                cur,
                "INSERT INTO subcategories (id, macro_area, tag_name) VALUES %s;",
                nuove_sub
            )
            print(f"[DB] Inserite {len(nuove_sub)} nuove sotto-categorie in 'subcategories'.")

        # 2. Calcolo prossimi ID INTEGER e recupero titoli esistenti per deduplicazione
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM news;")
        next_news_id = cur.fetchone()[0] + 1

        cur.execute("SELECT COALESCE(MAX(id), 0) FROM deadlines;")
        next_deadline_id = cur.fetchone()[0] + 1

        cur.execute("SELECT LOWER(TRIM(title)) FROM news WHERE title IS NOT NULL;")
        news_esistenti = {r[0] for r in cur.fetchall() if r[0]}

        cur.execute("SELECT LOWER(TRIM(title)) FROM deadlines WHERE title IS NOT NULL;")
        scadenze_esistenti = {r[0] for r in cur.fetchall() if r[0]}

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
                    # Filtro qualità: blocca titoli generici e verifica pertinenza sicurezza sul lavoro
                    titoli_generici = {"avvisi e scadenze", "bandi e concorsi", "news", "notizie"}
                    if chiave in titoli_generici or not e_pertinente(titolo, descrizione):
                        continue

                    if chiave not in scadenze_esistenti:
                        scadenze_esistenti.add(chiave)
                        nuove_scadenze.append((
                            next_deadline_id,
                            titolo,
                            data_val,
                            descrizione,
                            link
                        ))
                        next_deadline_id += 1
                else:
                    if chiave not in news_esistenti:
                        news_esistenti.add(chiave)
                        nuove_news.append((
                            next_news_id,
                            titolo,
                            fonte,
                            data_val,
                            link,
                            categoria,
                            importanza,
                            descrizione
                        ))
                        next_news_id += 1

        # Pulizia automatica da 'deadlines' di eventuali concorsi o voci generiche già presenti
        cur.execute("""
            DELETE FROM deadlines 
            WHERE LOWER(TRIM(title)) IN ('avvisi e scadenze', 'bandi e concorsi')
               OR title ILIKE '%bando di concorso%';
        """)

        # 3. Inserimento massivo su 'news'
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

        # 4. Inserimento massivo su 'deadlines'
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
        utenti_attivi = cur.fetchone()[0]
        print(f"[PUSH GDPR] Dispositivi anonimi con notifiche attive: {utenti_attivi}.")
        
        # 6. Esportazione archivio completo in 'dati_app.json' per la Web App / PWA gratuita
        cur.execute("""
            SELECT id, title, source, date, official_link, category, importance, summary
            FROM news
            ORDER BY date DESC, id DESC;
        """)
        tutte_news = [
            {
                "id": r[0],
                "title": r[1],
                "source": r[2],
                "date": r[3],
                "official_link": r[4],
                "category": r[5],
                "importance": r[6],
                "summary": r[7] or ""
            }
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT id, title, due_date, notes, official_link
            FROM deadlines
            ORDER BY due_date ASC, id DESC;
        """)
        tutte_scadenze = [
            {
                "id": r[0],
                "title": r[1],
                "due_date": r[2],
                "notes": r[3] or "",
                "official_link": r[4] or "https://inail.it"
            }
            for r in cur.fetchall()
        ]

        payload_app = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "subcategories": mappa_categorie,
            "news": tutte_news,
            "deadlines": tutte_scadenze
        }
        with open("dati_app.json", mode="w", encoding="utf-8") as f_json:
            json.dump(payload_app, f_json, ensure_ascii=False, indent=2)
        print(f"[PWA] Esportato 'dati_app.json' ({len(tutte_news)} news, {len(tutte_scadenze)} scadenze).")

        
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
    print("🚀 --- AVVIO SUPER-MOTORE MULTI-FONTE ESTESO (8 FONTI) --- 🚀\n")
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
    scrape_cassazione()
    print("-" * 50)
    print("\n🎉 SUPER ARCHIVIO GENERATO CON SUCCESSO LOCALE!")
    print("-" * 50)
    spingi_dati_a_glide()
