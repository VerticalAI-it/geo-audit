#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEO Audit — Vertical AI SRL  ·  scanner GEO completo (standalone CLI)
====================================================================
Analizza quanto un sito è "GEO-friendly" (visibile/citabile dalle AI) e produce
un report in HTML e PDF, con infografiche.

Dati più completi possibili:
  • user-agent da browser reale + header completi;
  • rendering headless con Playwright (vede contenuti/JSON-LD via JS);
  • robots.txt analizzato (segnala i bot AI bloccati) ma NON usato come barriera;
  • scoperta pagine da link + sitemap.xml, con filtro degli URL non-pagina.

USO ETICO: esegui solo su siti tuoi o autorizzati dal cliente.

INSTALLAZIONE
    pip install requests beautifulsoup4 lxml weasyprint
    pip install playwright && playwright install chromium     # consigliato
    # macOS, per il PDF:  brew install pango

USO
    python geo_audit.py https://www.esempio.it
    python geo_audit.py esempio.it --max-pages 30 --out report.html
    python geo_audit.py esempio.it --no-render | --respect-robots | --no-pdf | --json dati.json
"""
from __future__ import annotations
import sys, re, json, time, math, argparse, html as H
from dataclasses import dataclass, field
from urllib.parse import urljoin, urldefrag, urlparse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ============================================================ CONFIG
ENGINE_VERSION = "1.1.0"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 VerticalAI-GEOAudit/1.1")
HEADERS = {"User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8", "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"}
TIMEOUT = 20
CRAWL_DELAY = 0.4

AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "Google-Extended", "PerplexityBot",
    "Perplexity-User", "ClaudeBot", "anthropic-ai", "Claude-Web", "Bytespider",
    "Amazonbot", "Applebot-Extended", "CCBot", "Meta-ExternalAgent"]

SCHEMA_HIGH_VALUE = {"Organization", "LocalBusiness", "Corporation", "Product", "Offer",
    "Service", "FAQPage", "QAPage", "Article", "BlogPosting", "NewsArticle",
    "BreadcrumbList", "WebSite", "Person", "Review", "AggregateRating", "HowTo",
    "Event", "VideoObject"}
SCHEMA_REQUIRED = {"Organization": ["name", "url", "logo", "sameAs"],
    "LocalBusiness": ["name", "address", "telephone", "openingHours"],
    "Product": ["name", "description", "offers"],
    "Article": ["headline", "author", "datePublished"],
    "FAQPage": ["mainEntity"], "BreadcrumbList": ["itemListElement"]}

# --- affidabilità: URL da NON trattare come pagine ---
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tif",
    ".pdf", ".zip", ".rar", ".gz", ".mp4", ".mov", ".avi", ".mp3", ".wav", ".doc",
    ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".css", ".js", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".eot", ".webmanifest", ".dmg", ".exe", ".csv")
SKIP_PATH = ("/wp-content/", "/wp-admin/", "/wp-json/", "/wp-includes/", "/feed",
    "/cdn-cgi/", "/xmlrpc.php", "/comments/feed")
SKIP_QUERY = ("add-to-cart", "replytocom", "?share=", "?attachment_id")
UTILITY_RE = re.compile(r"(privacy|cookie|termini|terms|condizioni|legal|informativa|"
    r"disclaimer|login|accedi|registr|carrello|cart|checkout|wishlist|account|"
    r"thank|grazie|404|cerca|/search)", re.I)

OK, WARN, FAIL, UNK = "ok", "warn", "fail", "unknown"
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

session = requests.Session(); session.headers.update(HEADERS)

# ============================================================ MODELLO
@dataclass
class Check:
    id: str; category: str; title: str; status: str
    weight: int = 1; severity: str = "medium"; detail: str = ""; recommendation: str = ""

@dataclass
class Page:
    url: str; page_type: str = "generic"; title: str = ""; score: int = 0
    checks: list = field(default_factory=list)

@dataclass
class Fetched:
    url: str; status: int | None; final_url: str; html: str
    is_html: bool; redirects: int = 0; rendered: bool = False

# ============================================================ FETCH
def fetch_static(url: str) -> Fetched:
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        return Fetched(url, r.status_code, str(r.url), r.text, ("html" in ct or ct == ""), len(r.history))
    except Exception as e:
        return Fetched(url, None, url, f"<!--fetch error: {e}-->", False)

_PW_OK = None
def playwright_available() -> bool:
    global _PW_OK
    if _PW_OK is None:
        try:
            import playwright  # noqa
            _PW_OK = True
        except Exception:
            _PW_OK = False
    return _PW_OK

def fetch_rendered(url: str):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = b.new_context(user_agent=BROWSER_UA, locale="it-IT",
                                viewport={"width": 1366, "height": 900})
            page = ctx.new_page(); status = None
            try:
                resp = page.goto(url, wait_until="load", timeout=30000)
                status = resp.status if resp else None
                page.wait_for_timeout(1200)
            except Exception:
                pass
            html = page.content(); final = page.url; b.close()
            return status, html, final
    except Exception:
        return None

def get_page(url: str, render: bool):
    static = fetch_static(url)
    if render and playwright_available():
        rr = fetch_rendered(url)
        if rr is not None:
            rstatus, rhtml, rfinal = rr
            if rhtml:
                return Fetched(url, rstatus or static.status, rfinal or static.final_url,
                               rhtml, True, static.redirects, rendered=True), static
    return static, static

# ============================================================ ROBOTS / SITE
@dataclass
class Site:
    base_url: str; https: bool; robots_found: bool = False; sitemap_found: bool = False
    llms_found: bool = False; ai_bots_blocked: list = field(default_factory=list)
    sitemap_urls: list = field(default_factory=list); site_checks: list = field(default_factory=list)

def parse_robots_ai(body: str) -> list:
    agents, cur, blocked = {}, None, []
    for line in body.splitlines():
        low = line.strip().lower()
        if low.startswith("user-agent:"):
            cur = line.split(":", 1)[1].strip().lower(); agents.setdefault(cur, [])
        elif low.startswith("disallow:") and cur is not None:
            agents[cur].append(line.split(":", 1)[1].strip())
    for bot in AI_BOTS:
        rules = agents.get(bot.lower())
        if rules is not None and any(d == "/" for d in rules):
            blocked.append(bot)
    return blocked

def fetch_sitemap_urls(root: str, cap: int = 300) -> list:
    out = []
    sm = fetch_static(root + "/sitemap.xml")
    if sm.status == 200:
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm.html, re.I)
        if locs and all(u.endswith(".xml") for u in locs[:3]):
            for child in locs[:8]:
                c = fetch_static(child)
                if c.status == 200:
                    out += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", c.html, re.I)
        else:
            out = locs
    return out[:cap]

def build_site(base_url: str) -> Site:
    p = urlparse(base_url); root = f"{p.scheme}://{p.netloc}"
    s = Site(base_url=base_url, https=(p.scheme == "https"))
    robots = fetch_static(root + "/robots.txt")
    s.robots_found = robots.status == 200
    if s.robots_found:
        s.ai_bots_blocked = parse_robots_ai(robots.html)
    s.sitemap_found = fetch_static(root + "/sitemap.xml").status == 200
    s.llms_found = fetch_static(root + "/llms.txt").status == 200
    s.sitemap_urls = fetch_sitemap_urls(root)
    return s

# ============================================================ URL FILTERING
def is_page_url(u: str) -> bool:
    pl = u.lower()
    path = urlparse(pl).path
    if any(path.endswith(e) for e in SKIP_EXT): return False
    if any(sp in pl for sp in SKIP_PATH): return False
    if any(sq in pl for sq in SKIP_QUERY): return False
    return True

def norm(u: str) -> str:
    u = urldefrag(u)[0]
    p = urlparse(u)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc}{path}" + (f"?{p.query}" if p.query else "")

# ============================================================ CHECKS
def jsonld(soup):
    blocks, types, valid = [], set(), True
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            valid = False; continue
        items = data if isinstance(data, list) else [data]
        exp = []
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("@graph"), list):
                exp += it["@graph"]
            else:
                exp.append(it)
        for it in exp:
            if isinstance(it, dict):
                blocks.append(it); t = it.get("@type")
                types.update(t if isinstance(t, list) else [t] if t else [])
    return blocks, types, valid

def ck(checks, **kw): checks.append(Check(**kw))

def checks_structured(soup, checks):
    blocks, types, valid = jsonld(soup)
    ck(checks, id="sd.present", category="Dati strutturati", title="Dati strutturati (JSON-LD)",
       status=OK if blocks else FAIL, weight=18, severity="high",
       detail=(f"{len(blocks)} blocchi: {', '.join(sorted(str(x) for x in types)) or 'n/d'}" if blocks
               else "Nessun JSON-LD schema.org."),
       recommendation="" if blocks else "Aggiungi JSON-LD: è il segnale più forte per le AI.")
    if not blocks: return
    ck(checks, id="sd.valid", category="Dati strutturati", title="JSON-LD ben formato",
       status=OK if valid else FAIL, weight=4, severity="high",
       detail="Sintassi valida." if valid else "Errori di sintassi nel JSON-LD.",
       recommendation="" if valid else "Correggi il JSON non valido.")
    hv = types & SCHEMA_HIGH_VALUE
    ck(checks, id="sd.highvalue", category="Dati strutturati", title="Tipi schema ad alto valore",
       status=OK if hv else WARN, weight=6,
       detail=f"Tipi: {', '.join(sorted(hv))}" if hv else "Nessun tipo ad alto valore.",
       recommendation="" if hv else "Aggiungi i tipi pertinenti (Organization, Product, Article, FAQPage...).")
    miss = []
    for b in blocks:
        t = b.get("@type"); t = t[0] if isinstance(t, list) and t else t
        req = SCHEMA_REQUIRED.get(t)
        if req:
            m = [pr for pr in req if pr not in b]
            if m: miss.append(f"{t}: mancano {', '.join(m)}")
    if miss:
        ck(checks, id="sd.completeness", category="Dati strutturati", title="Completezza proprietà schema",
           status=WARN, weight=4, detail="; ".join(miss), severity="low",
           recommendation="Compila le proprietà mancanti dello schema.")
    has_sa = any(b.get("sameAs") for b in blocks)
    ck(checks, id="sd.sameas", category="Dati strutturati", title="Collegamento entità (sameAs)",
       status=OK if has_sa else WARN, weight=3, severity="low",
       detail="sameAs presente." if has_sa else "Nessun sameAs.",
       recommendation="" if has_sa else "Aggiungi sameAs (LinkedIn, Wikipedia, social).")

def best_description(soup):
    cands = []
    for m in soup.find_all("meta", attrs={"name": "description"}):
        cands.append(m.get("content", "") or "")
    og = soup.find("meta", attrs={"property": "og:description"})
    if og: cands.append(og.get("content", "") or "")
    cands = [c.strip() for c in cands if c and c.strip()]
    return max(cands, key=len) if cands else ""

def checks_meta(soup, checks):
    title = soup.title.get_text(strip=True) if soup.title else ""
    if not title:
        ogt = soup.find("meta", attrs={"property": "og:title"})
        title = ogt.get("content", "").strip() if ogt else ""
    ck(checks, id="meta.title", category="Meta & social", title="Title",
       status=OK if 10 <= len(title) <= 70 else (WARN if title else FAIL), weight=4,
       detail=f"{len(title)} caratteri." if title else "Title assente.",
       recommendation="" if 10 <= len(title) <= 70 else "Title descrittivo di 50-60 caratteri.")
    desc = best_description(soup)
    st = OK if len(desc) >= 50 else (WARN if desc else FAIL)
    ck(checks, id="meta.description", category="Meta & social", title="Meta description",
       status=st, weight=5, severity="high" if st == FAIL else "medium",
       detail=(f"{len(desc)} caratteri." if desc else "Meta description assente.")
              + (" (troppo corta)" if 0 < len(desc) < 50 else ""),
       recommendation="" if st == OK else "Aggiungi/estendi la description (spesso ripresa come sintesi dalle AI).")
    canon = soup.find("link", attrs={"rel": "canonical"})
    ck(checks, id="meta.canonical", category="Meta & social", title="Canonical",
       status=OK if canon else WARN, weight=2, severity="low",
       detail="Presente." if canon else "Assente.",
       recommendation="" if canon else "Imposta il canonical.")
    og = soup.find_all("meta", attrs={"property": re.compile("^og:")})
    ck(checks, id="meta.og", category="Meta & social", title="Open Graph",
       status=OK if len(og) >= 3 else WARN, weight=3,
       detail=f"{len(og)} tag og:*" if og else "Assente.",
       recommendation="" if len(og) >= 3 else "Aggiungi og:title/description/image/url.")
    tw = soup.find_all("meta", attrs={"name": re.compile("^twitter:")})
    ck(checks, id="meta.twitter", category="Meta & social", title="Twitter card",
       status=OK if tw else WARN, weight=1, severity="low",
       detail=f"{len(tw)} tag." if tw else "Assente.",
       recommendation="" if tw else "Aggiungi i meta twitter:*.")
    htmltag = soup.find("html"); lang = htmltag.get("lang") if htmltag else None
    ck(checks, id="meta.lang", category="Meta & social", title="Attributo lang",
       status=OK if lang else WARN, weight=2, severity="low",
       detail=f"lang='{lang}'" if lang else "Mancante.",
       recommendation="" if lang else "Imposta lang su <html>.")

def checks_content(soup, checks):
    h1 = soup.find_all("h1")
    ck(checks, id="content.h1", category="Contenuti & answerability", title="H1 unico",
       status=OK if len(h1) == 1 else (WARN if len(h1) > 1 else FAIL), weight=6, severity="medium",
       detail=f"{len(h1)} H1.", recommendation="" if len(h1) == 1 else "Usa un solo H1 chiaro.")
    h2 = len(soup.find_all("h2"))
    ck(checks, id="content.hier", category="Contenuti & answerability", title="Gerarchia dei titoli",
       status=OK if h2 >= 1 else WARN, weight=3, severity="low", detail=f"{h2} H2.",
       recommendation="" if h2 >= 1 else "Struttura il contenuto con H2/H3.")
    text = soup.get_text(" ", strip=True); words = len(text.split())
    ck(checks, id="content.len", category="Contenuti & answerability", title="Profondità del contenuto",
       status=OK if words >= 300 else WARN, weight=5, detail=f"{words} parole.",
       recommendation="" if words >= 300 else "Contenuto scarno: amplia con dettagli utili.")
    q = [h for h in soup.find_all(["h2", "h3", "h4"]) if h.get_text(strip=True).endswith("?")]
    ck(checks, id="content.q", category="Contenuti & answerability", title="Contenuti in forma di domanda",
       status=OK if q else WARN, weight=4, severity="low", detail=f"{len(q)} titoli-domanda." if q else "Nessuno.",
       recommendation="" if q else "Aggiungi sezioni Q&A (riflettono come si interrogano le AI).")
    lists = len(soup.find_all(["ul", "ol"])); tables = len(soup.find_all("table"))
    ck(checks, id="content.struct", category="Contenuti & answerability", title="Formati estraibili",
       status=OK if (lists + tables) else WARN, weight=4, detail=f"Liste {lists}, tabelle {tables}.",
       recommendation="" if (lists + tables) else "Usa liste e tabelle (formati ripresi dalle AI).")
    tldr = bool(re.search(r"(in breve|in sintesi|tl;dr|riassunto|punti chiave)", text[:600].lower()))
    ck(checks, id="content.tldr", category="Contenuti & answerability", title="Riassunto iniziale (TL;DR)",
       status=OK if tldr else WARN, weight=3, severity="low", detail="Presente." if tldr else "Assente.",
       recommendation="" if tldr else "Apri con un 'In breve' di 2-3 frasi.")
    fresh = bool(soup.find("time")) or bool(soup.find("meta", attrs={"property": "article:modified_time"})) \
            or bool(re.search(r"(aggiornat|ultimo aggiornamento|updated)", text.lower()))
    ck(checks, id="content.fresh", category="Contenuti & answerability", title="Segnali di freschezza",
       status=OK if fresh else WARN, weight=2, severity="low",
       detail="Data/aggiornamento presente." if fresh else "Assente.",
       recommendation="" if fresh else "Mostra data di pubblicazione/aggiornamento.")
    imgs = soup.find_all("img")
    if imgs:
        ratio = len([i for i in imgs if i.get("alt", "").strip()]) / len(imgs)
        ck(checks, id="content.alt", category="HTML semantico", title="Alt text immagini",
           status=OK if ratio >= 0.8 else WARN, weight=2, severity="low",
           detail=f"{int(ratio*100)}% con alt.",
           recommendation="" if ratio >= 0.8 else "Aggiungi alt descrittivi.")

def checks_eeat(soup, checks):
    text = soup.get_text(" ", strip=True)
    contact = bool(soup.find("a", href=re.compile(r"^(mailto:|tel:)", re.I))) or \
              bool(re.search(r"[\w.\-]+@[\w.\-]+\.\w+", text))
    ck(checks, id="trust.contact", category="Autorità & trust", title="Contatti presenti",
       status=OK if contact else WARN, weight=4, detail="Email/telefono rilevati." if contact else "Assenti.",
       recommendation="" if contact else "Esponi contatti chiari.")
    social = soup.find_all("a", href=re.compile(r"(facebook|instagram|linkedin|twitter|x\.com|youtube|tiktok)\.com", re.I))
    ck(checks, id="trust.social", category="Autorità & trust", title="Profili social",
       status=OK if len(social) >= 2 else WARN, weight=3, severity="low",
       detail=f"{len(social)} link social." if social else "Assenti.",
       recommendation="" if len(social) >= 2 else "Collega i profili ufficiali (rafforza l'entità).")
    author = bool(soup.find(attrs={"rel": "author"})) or \
             bool(soup.find("meta", attrs={"property": "article:author"})) or \
             bool(re.search(r"\b(scritto da|autore|by)\b", text.lower()))
    ck(checks, id="trust.author", category="Autorità & trust", title="Indicazione autore",
       status=OK if author else WARN, weight=2, severity="low",
       detail="Presente." if author else "Assente.",
       recommendation="" if author else "Mostra autore con bio (idealmente schema Person).")
    sem = sum(bool(soup.find(t)) for t in ["main", "article", "section", "nav", "header", "footer"])
    ck(checks, id="sem.html", category="HTML semantico", title="HTML semantico",
       status=OK if sem >= 3 else WARN, weight=3, severity="low", detail=f"{sem}/6 elementi.",
       recommendation="" if sem >= 3 else "Usa main/article/section.")

def checks_indexing(soup, checks, status_code, redirects, url):
    ck(checks, id="page.status", category="Rendering & accesso", title="Stato HTTP",
       status=OK if status_code == 200 else FAIL, weight=4, severity="high",
       detail=f"HTTP {status_code}, {redirects} redirect.",
       recommendation="" if status_code == 200 else "La pagina non risponde 200.")
    mr = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    noindex = mr is not None and "noindex" in mr.get("content", "").lower()
    if not noindex:
        ck(checks, id="page.noindex", category="Rendering & accesso", title="Indicizzabilità",
           status=OK, weight=6, severity="medium", detail="Indicizzabile.")
    elif UTILITY_RE.search(url):  # noindex atteso su pagine di servizio
        ck(checks, id="page.noindex", category="Rendering & accesso", title="Indicizzabilità",
           status=OK, weight=6, severity="info",
           detail="noindex presente — atteso per pagina di servizio (corretto).")
    else:
        ck(checks, id="page.noindex", category="Rendering & accesso", title="Indicizzabilità",
           status=UNK, weight=6, severity="high",
           detail="meta robots NOINDEX: verifica se intenzionale.",
           recommendation="Se la pagina deve essere trovata, rimuovi il noindex.")

def check_js_parity(checks, static_html, rendered_used, rendered_soup):
    if not rendered_used:
        ck(checks, id="render.parity", category="Rendering & accesso", title="Parità contenuto senza JS",
           status=UNK, weight=8, severity="high",
           detail="Rendering headless non eseguito: confronto non disponibile.",
           recommendation="Esegui con Playwright per verificare il contenuto visibile ai crawler AI.")
        return
    sw = len(BeautifulSoup(static_html, "lxml").get_text(" ", strip=True).split())
    rw = len(rendered_soup.get_text(" ", strip=True).split())
    ratio = (sw / rw) if rw else 1.0
    if ratio < 0.5:
        st, det, rec = FAIL, f"Solo {int(ratio*100)}% del contenuto nell'HTML statico ({sw}/{rw} parole): il resto è iniettato via JS.", "Abilita SSR/prerendering: molti crawler AI non eseguono il JS."
    elif ratio < 0.8:
        st, det, rec = WARN, f"Parte del contenuto dipende dal JS ({int(ratio*100)}% nello statico).", "Valuta SSR per le sezioni chiave."
    else:
        st, det, rec = OK, f"Contenuto presente nell'HTML statico ({int(ratio*100)}%).", ""
    ck(checks, id="render.parity", category="Rendering & accesso", title="Parità contenuto senza JS",
       status=st, weight=8, severity="high", detail=det, recommendation=rec)

# ============================================================ SCORING
def score_checks(checks):
    frac = {OK: 1.0, WARN: 0.5, FAIL: 0.0}; num = den = 0.0
    for c in checks:
        if c.status in frac:
            den += c.weight; num += c.weight * frac[c.status]
    return round(100 * num / den) if den else 0

def grade(s): return "A" if s>=90 else "B" if s>=75 else "C" if s>=60 else "D" if s>=45 else "E" if s>=30 else "F"
def band(s): return "Eccellente" if s>=90 else "Buono" if s>=75 else "Discreto" if s>=60 else "Da rafforzare" if s>=45 else "Critico"

def classify(url, types):
    path = urlparse(url).path.rstrip("/"); t = {str(x).lower() for x in types}
    if path in ("", "/"): return "home"
    if "faqpage" in t or re.search(r"(faq|domande)", path, re.I): return "faq"
    if {"article","blogposting","newsarticle"} & t or re.search(r"(blog|guida|news|articol|post)", path, re.I): return "article"
    if {"product","offer","localbusiness"} & t or re.search(r"(product|prodotto|venue|servizi|shop|store)", path, re.I): return "product"
    if re.search(r"(category|categoria|settori|listing)", path, re.I): return "categoria"
    return "generic"

# ============================================================ CRAWL
def same_domain(a, b):
    return urlparse(a).netloc.replace("www.", "") == urlparse(b).netloc.replace("www.", "")

def discover(home_soup, base, sitemap_urls, max_pages):
    seen = {norm(base)}; urls = [base]
    if home_soup:
        for a in home_soup.find_all("a", href=True):
            u = norm(urljoin(base, a["href"]))
            if u.startswith("http") and same_domain(base, u) and is_page_url(u) and u not in seen:
                seen.add(u); urls.append(u)
            if len(urls) >= max_pages: break
    for u in sitemap_urls:
        if len(urls) >= max_pages: break
        u = norm(u)
        if u.startswith("http") and same_domain(base, u) and is_page_url(u) and u not in seen:
            seen.add(u); urls.append(u)
    return urls[:max_pages]

def analyze_page(url, fetched, static_for_parity, render_used):
    soup = BeautifulSoup(fetched.html, "lxml"); checks = []
    checks_indexing(soup, checks, fetched.status, fetched.redirects, url)
    checks_meta(soup, checks); checks_structured(soup, checks)
    checks_content(soup, checks); checks_eeat(soup, checks)
    check_js_parity(checks, static_for_parity.html, render_used and fetched.rendered, soup)
    _, types, _ = jsonld(soup)
    title = soup.title.get_text(strip=True) if soup.title else url
    return Page(url=url, page_type=classify(url, types), title=title,
                score=score_checks(checks), checks=checks)

# ============================================================ REPORT
SC = {OK:"#0E9F6E", WARN:"#C77700", FAIL:"#D92D34", UNK:"#76768A"}
SLAB = {OK:"OK", WARN:"DA MIGLIORARE", FAIL:"CRITICITÀ", UNK:"DA VERIFICARE"}
SEV_PRIO = {"critical":("critica","#D92D34"), "high":("alta","#C77700"),
            "medium":("media","#5A45D8"), "low":("media","#5A45D8"), "info":("media","#5A45D8")}
SHORT = {"Dati strutturati":"Dati", "Contenuti & answerability":"Contenuti",
    "Meta & social":"Meta", "Autorità & trust":"Autorità", "HTML semantico":"HTML",
    "Rendering & accesso":"Accesso"}
MONTHS = ["","gennaio","febbraio","marzo","aprile","maggio","giugno","luglio",
          "agosto","settembre","ottobre","novembre","dicembre"]
def esc(s): return H.escape(str(s))
def barcol(s): return "#0E9F6E" if s>=75 else ("#C77700" if s>=55 else "#D92D34")
def fmt_date(): d = datetime.now(); return f"{d.day} {MONTHS[d.month]} {d.year}"

def gauge(score):
    r=52; c=2*math.pi*r; off=c*(1-score/100); col=barcol(score)
    return (f'<svg width="146" height="146" viewBox="0 0 150 150">'
      f'<circle cx="75" cy="75" r="{r}" fill="none" stroke="#E6E6EF" stroke-width="14"/>'
      f'<circle cx="75" cy="75" r="{r}" fill="none" stroke="{col}" stroke-width="14" stroke-linecap="round" '
      f'stroke-dasharray="{c:.1f}" stroke-dashoffset="{off:.1f}" transform="rotate(-90 75 75)"/>'
      f'<text x="75" y="68" text-anchor="middle" font-family="Space Grotesk" font-weight="800" font-size="40" fill="#16151E">{score}</text>'
      f'<text x="75" y="90" text-anchor="middle" font-family="JetBrains Mono" font-size="11" fill="#76768A">/ 100</text></svg>')

def radar(cats):
    n = len(cats)
    if n < 3: return ""
    cx = 160; cy = 140; R = 90
    rings = "".join(f'<circle cx="{cx}" cy="{cy}" r="{R*k/100:.0f}" fill="none" stroke="#E6E6EF" stroke-width="1"/>' for k in (25,50,75,100))
    axes = ""; labels = ""; pts = []
    for i,(name,sc) in enumerate(cats):
        ang = -math.pi/2 + 2*math.pi*i/n
        ax = cx + R*math.cos(ang); ay = cy + R*math.sin(ang)
        axes += f'<line x1="{cx}" y1="{cy}" x2="{ax:.0f}" y2="{ay:.0f}" stroke="#E6E6EF"/>'
        rr = R*sc/100; pts.append(f"{cx+rr*math.cos(ang):.0f},{cy+rr*math.sin(ang):.0f}")
        lx = cx + (R+16)*math.cos(ang); ly = cy + (R+16)*math.sin(ang)
        anc = "middle" if abs(math.cos(ang))<0.3 else ("start" if math.cos(ang)>0 else "end")
        labels += (f'<text x="{lx:.0f}" y="{ly+3:.0f}" text-anchor="{anc}" font-family="JetBrains Mono" '
                   f'font-size="9.5" fill="#76768A">{esc(SHORT.get(name,name))}</text>')
    poly = f'<polygon points="{" ".join(pts)}" fill="rgba(90,69,216,.18)" stroke="#5A45D8" stroke-width="2"/>'
    dots = "".join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="3" fill="#5A45D8"/>' for p in pts)
    return f'<svg width="300" height="285" viewBox="0 0 320 285">{rings}{axes}{poly}{dots}{labels}</svg>'

def donut(ok, warn, fail):
    total = ok + warn + fail or 1
    r = 54; C = 2*math.pi*r; cx = cy = 70
    out = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#E6E6EF" stroke-width="16"/>']
    acc = 0.0
    for val, col in [(ok,"#0E9F6E"),(warn,"#C77700"),(fail,"#D92D34")]:
        if val <= 0: continue
        frac = val/total
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{col}" stroke-width="16" '
                   f'stroke-dasharray="{frac*C:.2f} {C:.2f}" stroke-dashoffset="{-acc*C:.2f}" '
                   f'transform="rotate(-90 {cx} {cy})" stroke-linecap="butt"/>')
        acc += frac
    out.append(f'<text x="{cx}" y="{cy-2}" text-anchor="middle" font-family="Space Grotesk" font-weight="800" font-size="24" fill="#16151E">{total}</text>')
    out.append(f'<text x="{cx}" y="{cy+15}" text-anchor="middle" font-family="JetBrains Mono" font-size="8.5" fill="#76768A">CONTROLLI</text>')
    return f'<svg width="140" height="140" viewBox="0 0 140 140">{"".join(out)}</svg>'

def scale_bar(score):
    segs = [("F","#D92D34"),("E","#E0612A"),("D","#C77700"),("C","#C9A227"),("B","#5FA52E"),("A","#0E9F6E")]
    cells = "".join(f'<div style="flex:1;height:14px;background:{c};display:flex;align-items:center;'
                    f'justify-content:center;font-family:JetBrains Mono;font-size:8px;color:#fff;font-weight:600">{l}</div>'
                    for l,c in segs)
    return (f'<div style="position:relative;margin:6px 0 2px">'
            f'<div style="display:flex;border-radius:6px;overflow:hidden">{cells}</div>'
            f'<div style="position:absolute;top:-7px;left:{score}%;transform:translateX(-50%);width:0;height:0;'
            f'border-left:6px solid transparent;border-right:6px solid transparent;border-top:8px solid #16151E"></div>'
            f'<div style="position:absolute;top:18px;left:{score}%;transform:translateX(-50%);font-family:JetBrains Mono;'
            f'font-size:9px;color:#16151E;font-weight:600;white-space:nowrap">{score}/100</div></div>')

def dist_chart(pages):
    bands = [("Ottimo",90,100,"#0E9F6E"),("Buono",75,89,"#5FA52E"),("Discreto",60,74,"#C77700"),
             ("Debole",45,59,"#E0612A"),("Critico",0,44,"#D92D34")]
    counts = []
    for name,lo,hi,col in bands:
        counts.append((name, len([p for p in pages if lo <= p.score <= hi]), col))
    mx = max((c for _,c,_ in counts), default=1) or 1
    cols = ""
    for name,c,col in counts:
        h = 8 + int(78*c/mx)
        cols += (f'<div style="flex:1;text-align:center">'
                 f'<div style="font-family:Space Grotesk;font-weight:800;font-size:14px;color:#16151E">{c}</div>'
                 f'<div style="height:{h}px;background:{col};border-radius:5px 5px 0 0;margin:3px 6px 0"></div>'
                 f'<div style="font-family:JetBrains Mono;font-size:8.5px;color:#76768A;margin-top:5px">{name}</div></div>')
    return f'<div style="display:flex;align-items:flex-end;gap:4px;height:130px">{cols}</div>'

LOGO = ('<span class="logo"><svg width="22" height="22" viewBox="0 0 22 22" fill="none">'
  '<rect x="2" y="9" width="4" height="11" rx="1.5" fill="#5A45D8"/>'
  '<rect x="9" y="4" width="4" height="16" rx="1.5" fill="#B3A8F7"/>'
  '<rect x="16" y="11" width="4" height="9" rx="1.5" fill="#5A45D8"/></svg>'
  '<b>vertical</b><span style="color:#B3A8F7">ai</span></span>')

CSS = """
:root{--ink:#16151E;--muted:#76768A;--line:#E6E6EF;--soft:#F3F1FB;--violet:#5A45D8;--violet-deep:#3D2CB8}
*{box-sizing:border-box;margin:0;padding:0}html{font-size:15px}
body{font-family:"Inter",sans-serif;color:var(--ink);background:linear-gradient(135deg,#EAE6FB 0%,#F0EDF8 60%,#E8EEFB 100%);background-attachment:fixed;line-height:1.55}
.mono{font-family:"JetBrains Mono",monospace}
.sheet{background:#fff;max-width:880px;margin:28px auto;box-shadow:0 4px 6px rgba(90,69,216,.06),0 16px 48px rgba(20,16,60,.14);border-radius:20px;overflow:hidden}
h1,h2,h3{font-family:"Space Grotesk",sans-serif}
.logo b{font-family:"Space Grotesk",sans-serif}
.top{background:var(--ink);color:#fff;padding:30px 56px 26px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}
.logo{display:inline-flex;align-items:center;gap:8px;font-size:17px;color:#fff;font-family:"Space Grotesk",sans-serif;font-weight:700}.logo b{font-weight:800}
.kicker{font-family:"JetBrains Mono";font-size:11px;letter-spacing:3px;color:#B3A8F7;text-transform:uppercase}
.top h1{font-size:32px;font-weight:800;margin:6px 0 12px;word-break:break-word;letter-spacing:-.02em}
.meta{font-family:"JetBrains Mono";font-size:12px;color:#BCBBCB;display:flex;gap:22px;flex-wrap:wrap}.meta b{color:#fff;font-weight:500}
.scaninfo{margin-top:14px;font-family:"JetBrains Mono";font-size:10.5px;color:#8E8BA8;display:flex;gap:14px;flex-wrap:wrap}
.scaninfo .on{color:#3DDC97}.scaninfo .off{color:#F5BE57}
.summary{display:flex;gap:30px;align-items:center;padding:32px 56px 4px}
.gaugewrap{text-align:center;flex:none}.band{font-family:"Space Grotesk";font-weight:800;font-size:13px;color:var(--violet-deep);margin-top:4px;letter-spacing:.04em}
.sumright{flex:1;min-width:0}.tiles{display:flex;gap:12px;margin-bottom:14px}
.tile{flex:1;border:1px solid var(--line);border-radius:14px;padding:12px 14px;background:var(--soft)}
.tile .n{font-family:"Space Grotesk";font-weight:800;font-size:24px}.tile .l{font-size:10px;color:var(--muted);text-transform:uppercase;font-family:"JetBrains Mono";margin-top:2px;letter-spacing:.06em}
.verdict{font-size:14px;border-left:3px solid var(--violet);padding-left:13px;color:#2C2A3A;line-height:1.6}
.sec{padding:28px 56px 4px}
h2{font-size:11px;letter-spacing:3px;text-transform:uppercase;color:var(--violet-deep);font-weight:700;margin-bottom:16px;font-family:"JetBrains Mono"}
.two{display:flex;gap:30px;align-items:center;flex-wrap:wrap}
.two .half{flex:1;min-width:240px}
.legend{font-size:12.5px;color:var(--muted);margin-top:8px}.legend span{display:inline-flex;align-items:center;gap:6px;margin-right:14px}
.dotL{width:9px;height:9px;border-radius:50%;display:inline-block}
.catrow{display:flex;align-items:center;gap:14px;margin-bottom:9px}
.catname{width:200px;font-size:13px}.cattrack{flex:1;height:8px;background:var(--line);border-radius:6px;overflow:hidden}
.catfill{height:100%;border-radius:6px}.catscore{width:30px;text-align:right;font-size:12.5px;font-weight:600;font-family:"Space Grotesk"}
.callouts{display:flex;gap:12px;flex-wrap:wrap}
.callout{flex:1;min-width:150px;background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.callout .big{font-family:"Space Grotesk";font-weight:800;font-size:28px;color:var(--violet-deep)}
.callout .lbl{font-size:12px;color:var(--muted);margin-top:2px}
table{width:100%;border-collapse:collapse}td{padding:9px 6px;border-top:1px solid var(--line);font-size:13px;vertical-align:top}
tr:first-child td{border-top:none}.cdot{width:18px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%}
.cchk{font-weight:600;width:30%}.cdet{color:var(--muted)}.cst{width:118px;text-align:right;font-size:10px;font-weight:500;font-family:"JetBrains Mono"}
.wins{display:flex;gap:12px;flex-wrap:wrap}
.win{flex:1;min-width:200px;border:1px solid var(--line);border-radius:16px;padding:18px 20px;break-inside:avoid;background:var(--soft)}
.win .wn{font-family:"JetBrains Mono";font-size:10px;color:var(--violet);font-weight:600;letter-spacing:.1em;text-transform:uppercase}
.win h3{font-family:"Space Grotesk";font-size:15px;font-weight:700;margin:6px 0 4px}.win p{font-size:12.5px;color:var(--muted);line-height:1.5}
.win .badge{display:inline-block;margin-top:8px;font-family:"JetBrains Mono";font-size:9.5px;color:var(--violet-deep);background:#EDE9FB;border-radius:20px;padding:3px 10px;border:1px solid #D4CFFA}
.pcard{border:1px solid var(--line);border-radius:16px;margin-bottom:12px;overflow:hidden;break-inside:avoid}
.phead{display:flex;justify-content:space-between;align-items:center;background:var(--soft);padding:12px 18px;border-bottom:1px solid var(--line)}
.ptag{display:inline-block;background:var(--violet);color:#fff;font-size:10px;font-weight:600;padding:3px 9px;border-radius:20px;font-family:"JetBrains Mono";text-transform:uppercase;margin-right:10px;letter-spacing:.06em}
.purl{font-size:12px;color:var(--muted);word-break:break-all}.pscore{font-family:"Space Grotesk";font-weight:800;font-size:23px}.pscore i{font-size:12px;color:var(--muted);font-style:normal}
.pbody{padding:11px 18px}.finding{display:flex;gap:11px;padding:6px 0;align-items:flex-start}.finding .dot{margin-top:6px;flex:none}
.ftitle{display:block;font-weight:600;font-size:13px}.fdetail{display:block;font-size:12.5px;color:var(--muted)}.allok{color:#0E9F6E;font-size:13px;padding:6px 0;font-weight:600}
.action{display:flex;gap:16px;padding:14px 0;border-top:1px solid var(--line);break-inside:avoid}.action:first-child{border-top:none}
.anum{font-family:"Space Grotesk";font-weight:800;font-size:19px;color:var(--violet);width:32px;flex:none}
.ahead{display:flex;align-items:center;gap:10px;margin-bottom:3px;flex-wrap:wrap}.ptitle{font-weight:700;font-size:14px;font-family:"Space Grotesk"}
.pill{font-family:"JetBrains Mono";font-size:9.5px;font-weight:600;border:1px solid;border-radius:20px;padding:2px 8px}
.adesc{font-size:12.5px;color:var(--muted);line-height:1.5}
.notes{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:16px 20px;font-size:12.5px;color:#46435A;line-height:1.6}.notes b{color:var(--ink)}
.cta{background:var(--ink);color:#fff;padding:40px 56px;margin-top:32px;display:flex;justify-content:space-between;align-items:flex-start;gap:40px;flex-wrap:wrap}
.cta-l{flex:1;min-width:220px}
.cta-badge{display:inline-block;background:rgba(90,69,216,.3);color:#B3A8F7;font-family:"JetBrains Mono";font-size:10px;letter-spacing:2.5px;text-transform:uppercase;padding:4px 11px;border-radius:20px;margin-bottom:14px}
.cta h3{font-family:"Space Grotesk";font-size:23px;font-weight:800;margin:0 0 12px;line-height:1.25;color:#fff;letter-spacing:-.01em}
.cta-desc{font-size:13.5px;color:#BCBBCB;margin:0 0 14px;line-height:1.6}
.cta ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:5px}
.cta li{font-size:13px;color:#BCBBCB;padding-left:18px;position:relative}
.cta li::before{content:"✓";position:absolute;left:0;color:#B3A8F7;font-weight:700}
.cta-r{flex:0 0 290px;min-width:260px}
.cta-r p{font-size:13px;color:#BCBBCB;margin:0 0 12px;line-height:1.5}
.cta-r input{width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);border-radius:10px;color:#fff;font-size:14px;padding:11px 13px;font-family:inherit;outline:none;margin-bottom:8px;box-sizing:border-box;transition:border-color .15s}
.cta-r input::placeholder{color:rgba(255,255,255,.32)}
.cta-r input:focus{border-color:#B3A8F7}
.cta-pref{display:flex;align-items:center;gap:12px;font-size:13px;color:#BCBBCB;margin-bottom:12px;flex-wrap:wrap}
.cta-pref label{display:flex;align-items:center;gap:5px;cursor:pointer}
.cta-btn{width:100%;background:#5A45D8;color:#fff;border:none;border-radius:10px;font-family:"Space Grotesk";font-weight:700;font-size:15px;padding:13px;cursor:pointer;transition:background .15s;letter-spacing:.01em}
.cta-btn:hover{background:#4A37BE}
.cta-ok{display:none;color:#3DDC97;font-size:14px;margin-top:12px;font-weight:600;text-align:center}
.foot{padding:16px 56px;font-size:11px;color:var(--muted);font-family:"JetBrains Mono";display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;border-top:1px solid var(--line)}
@page{size:A4;margin:13mm 0}
@media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:none;border-radius:0}.sec,.summary,.top,.cta,.foot{padding-left:15mm;padding-right:15mm}}
@media (max-width:760px){.sheet{margin:8px;border-radius:14px}.top,.sec,.cta,.foot{padding-left:22px;padding-right:22px}.top h1{font-size:25px}
.summary{flex-direction:column;align-items:stretch;padding:26px 22px 4px;gap:18px}.gaugewrap{align-self:center}.catname{width:120px}.cst{width:90px}
.phead{flex-wrap:wrap;gap:8px}.cta{flex-direction:column;align-items:flex-start}.cta-r{width:100%}.foot{flex-direction:column}}
"""

def derive_actions(site_checks, pages, limit=8):
    agg = {}; allc = list(site_checks) + [c for p in pages for c in p.checks]
    for c in allc:
        if c.status in (WARN, FAIL) and c.recommendation:
            a = agg.setdefault(c.id, {"t": c.title, "r": c.recommendation, "s": c.severity, "n": 0})
            a["n"] += 1
            if SEV_ORDER[c.severity] < SEV_ORDER[a["s"]]: a["s"] = c.severity
    rows = sorted(agg.values(), key=lambda a: (SEV_ORDER[a["s"]], -a["n"]))
    out = []
    for a in rows[:limit]:
        prio, col = SEV_PRIO[a["s"]]; desc = a["r"] + (f" (su {a['n']} pagine)" if a["n"] > 1 else "")
        out.append((prio, col, a["t"], desc, a["n"]))
    return out

def render_report(domain, site, pages, render_used, respect_robots):
    allc = list(site.site_checks) + [c for p in pages for c in p.checks]
    overall = score_checks(allc); g = grade(overall); bnd = band(overall)
    nok = len([c for c in allc if c.status == OK]); nwarn = len([c for c in allc if c.status == WARN])
    nfail = len([c for c in allc if c.status == FAIL])
    catmap = {}
    for c in allc:
        if c.status in (OK, WARN, FAIL): catmap.setdefault(c.category, []).append(c)
    cats = sorted([(k, score_checks(v)) for k, v in catmap.items()], key=lambda x: x[1])
    cats_radar = [(k, score_checks(v)) for k, v in catmap.items()]
    issues = [c for c in allc if c.status in (WARN, FAIL)]
    crit = nfail  # "critici" = controlli rossi (FAIL), coerente col donut e con problemi = warn + crit
    acts = derive_actions(site.site_checks, pages)
    best = max(cats, key=lambda x: x[1]) if cats else ("—", 0)
    worst = min(cats, key=lambda x: x[1]) if cats else ("—", 0)
    repeated = [a for a in acts if a[4] > 1]

    head = ('<!doctype html><html lang="it"><head><meta charset="utf-8">'
      '<meta name="viewport" content="width=device-width,initial-scale=1"><title>GEO Audit — '+esc(domain)+'</title>'
      '<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700;800'
      '&family=Inter:ital,wght@0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
      '<style>'+CSS+'</style></head><body><div class="sheet">')

    rmode = '<span class="on">rendering JS attivo</span>' if render_used else '<span class="off">rendering JS non attivo</span>'
    robmode = '<span class="off">robots rispettato</span>' if respect_robots else '<span class="on">robots superato (audit)</span>'
    top = (f'<div class="top"><div class="topbar">{LOGO}<span class="kicker">GEO Audit Report</span></div>'
      f'<h1>{esc(domain)}</h1><div class="meta"><span>Data <b>{fmt_date()}</b></span>'
      f'<span>Pagine analizzate <b>{len(pages)}</b></span><span>Preparato da <b>verticalai.it</b></span></div>'
      f'<div class="scaninfo">{rmode} · {robmode} · <span>engine v{ENGINE_VERSION}</span></div></div>')

    verdict = (f"Il sito è <b>{bnd.lower()}</b> per la visibilità sulle AI. "
               f"Punto di forza: «{best[0]}» ({best[1]}/100). "
               f"Area su cui intervenire subito: «{worst[0]}» ({worst[1]}/100).")
    summ = (f'<div class="summary"><div class="gaugewrap">{gauge(overall)}<div class="band">{bnd.upper()} · {g}</div></div>'
      f'<div class="sumright"><div class="tiles">'
      f'<div class="tile"><div class="n">{len(pages)}</div><div class="l">Pagine</div></div>'
      f'<div class="tile"><div class="n" style="color:#C77700">{len(issues)}</div><div class="l">Problemi</div></div>'
      f'<div class="tile"><div class="n" style="color:#D92D34">{crit}</div><div class="l">Critici</div></div></div>'
      f'{scale_bar(overall)}<div class="verdict" style="margin-top:14px">{verdict}</div></div></div>')

    # salute controlli (donut) + callouts
    pct_ok = round(100*nok/(nok+nwarn+nfail or 1))
    health = (f'<div class="sec"><h2>La salute dei controlli</h2><div class="two">'
      f'<div style="flex:none;text-align:center">{donut(nok,nwarn,nfail)}'
      f'<div class="legend"><span><i class="dotL" style="background:#0E9F6E"></i>{nok} ok</span>'
      f'<span><i class="dotL" style="background:#C77700"></i>{nwarn} da migliorare</span>'
      f'<span><i class="dotL" style="background:#D92D34"></i>{nfail} critici</span></div></div>'
      f'<div class="half"><div class="callouts">'
      f'<div class="callout"><div class="big">{pct_ok}%</div><div class="lbl">controlli superati</div></div>'
      f'<div class="callout"><div class="big">{len(repeated)}</div><div class="lbl">problemi ricorrenti su più pagine</div></div>'
      f'<div class="callout"><div class="big">{best[1]}</div><div class="lbl">miglior area: {esc(best[0])}</div></div>'
      f'</div></div></div></div>')

    # radar + barre
    catrows = "".join(f'<div class="catrow"><div class="catname">{esc(n)}</div>'
      f'<div class="cattrack"><div class="catfill" style="width:{s}%;background:{barcol(s)}"></div></div>'
      f'<div class="catscore mono">{s}</div></div>' for n, s in cats)
    profile = (f'<div class="sec"><h2>Profilo GEO per area</h2><div class="two">'
      f'<div style="flex:none">{radar(cats_radar)}</div>'
      f'<div class="half">{catrows}</div></div></div>') if cats else ""

    # distribuzione punteggi pagine
    dist = (f'<div class="sec"><h2>Distribuzione dei punteggi per pagina</h2>{dist_chart(pages)}</div>' if len(pages) > 1 else "")

    # controlli sito
    siterows = "".join(f'<tr><td class="cdot"><span class="dot" style="background:{SC[c.status]}"></span></td>'
      f'<td class="cchk">{esc(c.title)}</td><td class="cdet">{esc(c.detail)}</td>'
      f'<td class="cst mono" style="color:{SC[c.status]}">{SLAB[c.status]}</td></tr>' for c in site.site_checks)
    site_sec = f'<div class="sec"><h2>Controlli a livello di sito</h2><table>{siterows}</table></div>' if siterows else ""

    # vittorie rapide
    wins = ""
    for prio, col, t, d, n in [a for a in acts if a[4] > 1][:3] or acts[:3]:
        badge = f"1 modifica → {n} pagine" if n > 1 else "intervento mirato"
        wins += (f'<div class="win"><div class="wn">VITTORIA RAPIDA</div><h3>{esc(t)}</h3>'
                 f'<p>{esc(d.split(" (su")[0])}</p><span class="badge">{badge}</span></div>')
    wins_sec = f'<div class="sec"><h2>Vittorie rapide ad alto impatto</h2><div class="wins">{wins}</div></div>' if wins else ""

    # interventi prioritari
    actrows = "".join(f'<div class="action"><div class="anum mono">{i:02d}</div><div><div class="ahead">'
      f'<span class="ptitle">{esc(t)}</span><span class="pill" style="color:{col};border-color:{col}33;background:{col}0f">{prio.upper()}</span></div>'
      f'<div class="adesc">{esc(d)}</div></div></div>' for i, (prio, col, t, d, n) in enumerate(acts, 1))
    act_sec = f'<div class="sec"><h2>Interventi prioritari</h2>{actrows}</div>' if actrows else ""

    # pagine (cap a 14)
    shown = sorted(pages, key=lambda x: x.score)[:14]; extra = len(pages) - len(shown)
    cards = ""
    for p in shown:
        iss = [c for c in p.checks if c.status in (WARN, FAIL)][:5]
        if iss:
            body = "".join(f'<div class="finding"><span class="dot" style="background:{SC[c.status]}"></span>'
              f'<div><span class="ftitle">{esc(c.title)}</span>'
              f'<span class="fdetail">{esc(c.detail)}{(" — "+esc(c.recommendation)) if c.recommendation else ""}</span></div></div>' for c in iss)
        else:
            body = '<div class="allok">✓ Nessuna criticità rilevata.</div>'
        cards += (f'<div class="pcard"><div class="phead"><div><span class="ptag">{esc(p.page_type)}</span>'
          f'<span class="purl mono">{esc(p.url)}</span></div>'
          f'<div class="pscore mono" style="color:{barcol(p.score)}">{p.score}<i>/100</i></div></div>'
          f'<div class="pbody">{body}</div></div>')
    if extra > 0:
        cards += f'<div style="text-align:center;color:#76768A;font-size:12.5px;font-family:JetBrains Mono;padding:6px">+ altre {extra} pagine analizzate</div>'
    pages_sec = f'<div class="sec"><h2>Analisi per pagina</h2>{cards}</div>' if cards else ""

    notes = ('<div class="sec"><h2>Metodo &amp; note</h2><div class="notes">'
      'Punteggio basato su check deterministici (rendering &amp; accesso, dati strutturati, meta, contenuti &amp; '
      'answerability, autorità). Sono esclusi dalla scansione gli URL non-pagina (immagini, file, feed). Le voci '
      '<b>“da verificare”</b> non incidono sul punteggio. <b>Fase 2:</b> analisi semantica dei contenuti via LLM e '
      'presenza off-site (Wikipedia/Wikidata, citazioni di terzi, visibilità reale nelle risposte AI).</div></div>')
    cta = (
      '<div class="cta">'
        '<div class="cta-l">'
          '<div class="cta-badge">Ottimizzazione professionale</div>'
          '<h3>Il tuo sito può fare molto di più.<br>Ci occupiamo noi di tutto.</h3>'
          '<p class="cta-desc">Schema.org, dati strutturati, contenuti riscritti per ChatGPT, Gemini e Perplexity: '
          'ti riportiamo al massimo della visibilità AI e monitoriamo i progressi nel tempo. '
          'Tu non devi fare nulla.</p>'
          '<ul>'
            '<li>Schema.org, FAQ e dati strutturati</li>'
            '<li>Contenuti ottimizzati per le risposte AI</li>'
            '<li>Re-scan e monitoraggio progressi</li>'
          '</ul>'
        '</div>'
        '<div class="cta-r">'
          '<p>Lasciaci i tuoi contatti: ti scriviamo o ti chiamiamo noi.</p>'
          '<form id="cta-contact-form">'
            '<input type="email" id="cta-email" name="email" placeholder="La tua email" required>'
            '<input type="tel" id="cta-phone" name="phone" placeholder="Telefono (opzionale)">'
            '<div class="cta-pref">'
              '<span>Contattami via</span>'
              '<label><input type="radio" name="preference" value="email" checked> Email</label>'
              '<label><input type="radio" name="preference" value="phone"> Telefono</label>'
            '</div>'
            '<button type="submit" class="cta-btn">Voglio essere contattato →</button>'
          '</form>'
          '<p class="cta-ok" id="cta-ok">✓ Ricevuto! Ti contatteremo presto.</p>'
        '</div>'
      '</div>'
      '<script>'
      'document.getElementById("cta-contact-form").addEventListener("submit",async function(e){'
        'e.preventDefault();'
        'var btn=this.querySelector("button");'
        'btn.disabled=true;btn.textContent="Invio…";'
        'var fd=new FormData(this);'
        'try{'
          'var r=await fetch("/contact/__JOB_ID__",{method:"POST",body:fd});'
          'if(r.ok){'
            'document.getElementById("cta-ok").style.display="block";'
            'this.style.display="none";'
          '}else{btn.disabled=false;btn.textContent="Voglio essere contattato →";}'
        '}catch(err){btn.disabled=false;btn.textContent="Voglio essere contattato →";}'
      '});'
      '</script>'
    )
    foot = f'<div class="foot"><span>verticalai.it · GEO Audit</span><span>Generato il {fmt_date()}</span></div>'

    return (head + top + summ + health + profile + dist + site_sec + wins_sec
            + act_sec + pages_sec + notes + cta + foot + "</div></body></html>"), overall

# ============================================================ MAIN
def build_site_checks(site):
    site.site_checks = []
    ck(site.site_checks, id="crawl.ai", category="Rendering & accesso", title="Accesso crawler AI (robots.txt)",
       status=FAIL if site.ai_bots_blocked else OK, weight=12, severity="critical",
       detail=("Bloccati: " + ", ".join(site.ai_bots_blocked)) if site.ai_bots_blocked else "Nessun blocco esplicito ai crawler AI.",
       recommendation="Sblocca i crawler AI in robots.txt." if site.ai_bots_blocked else "")
    ck(site.site_checks, id="crawl.robots", category="Rendering & accesso", title="robots.txt",
       status=OK if site.robots_found else WARN, weight=2, severity="low", detail="Presente." if site.robots_found else "Assente.",
       recommendation="" if site.robots_found else "Aggiungi un robots.txt.")
    ck(site.site_checks, id="crawl.sitemap", category="Rendering & accesso", title="sitemap.xml",
       status=OK if site.sitemap_found else WARN, weight=3, detail="Presente." if site.sitemap_found else "Assente.",
       recommendation="" if site.sitemap_found else "Pubblica una sitemap.xml.")
    ck(site.site_checks, id="crawl.llms", category="Rendering & accesso", title="llms.txt",
       status=OK if site.llms_found else WARN, weight=1, severity="info",
       detail="Presente." if site.llms_found else "Assente (opzionale).",
       recommendation="" if site.llms_found else "Valuta un llms.txt.")
    ck(site.site_checks, id="crawl.https", category="Rendering & accesso", title="HTTPS",
       status=OK if site.https else FAIL, weight=3, severity="high",
       detail="Attivo." if site.https else "Assente.", recommendation="" if site.https else "Abilita HTTPS.")


def run_audit(url, max_pages=20, render=True, respect_robots=False, log=lambda *a: None):
    """Esegue un audit completo e ritorna un dict con l'HTML del report e i metadati.
    Non scrive file: pensato per essere chiamato dal servizio web o dalla CLI."""
    base = url if url.startswith("http") else "https://" + url
    if render and not playwright_available():
        log("Playwright non disponibile: rendering headless disattivato.")
        render = False
    home, home_static = get_page(base, render)
    if home.status != 200 or not home.is_html:
        raise RuntimeError(f"Impossibile aprire la home (HTTP {home.status}).")
    base = home.final_url
    home_soup = BeautifulSoup(home.html, "lxml")
    site = build_site(base)
    build_site_checks(site)
    urls = discover(home_soup, base, site.sitemap_urls, max_pages)
    log(f"Analizzo {len(urls)} pagine...")
    pages = []
    for u in urls:
        if norm(u) == norm(base):
            f, st = home, home_static
        else:
            f, st = get_page(u, render)
        if f.status != 200 or not f.is_html:
            log(f"[skip {f.status}] {u}"); continue
        pg = analyze_page(u, f, st, render)
        pages.append(pg)
        log(f"[{pg.score:3d}/100] {'JS' if f.rendered else '  '} {u}")
        if norm(u) != norm(base):
            time.sleep(CRAWL_DELAY)
    html, overall = render_report(urlparse(base).netloc, site, pages, render, respect_robots)
    return {"html": html, "overall": overall, "grade": grade(overall), "band": band(overall),
            "domain": urlparse(base).netloc, "render": render, "respect_robots": respect_robots,
            "pages": [{"url": p.url, "type": p.page_type, "score": p.score} for p in pages],
            "site_checks": [c.__dict__ for c in site.site_checks]}


def _patch_macos_weasyprint():
    # On macOS with Homebrew (Apple Silicon), ctypes.util.find_library() doesn't
    # search /opt/homebrew/lib, so WeasyPrint falls back to the Linux name
    # "libpango-1.0-0" which doesn't exist. We patch find_library to return the
    # correct .dylib path before WeasyPrint is imported.
    import sys
    if sys.platform != "darwin":
        return
    import ctypes.util, os
    brew = "/opt/homebrew/lib"
    _libs = {
        "pango-1.0":      "libpango-1.0.0.dylib",
        "pangocairo-1.0": "libpangocairo-1.0.0.dylib",
        "pangoft2-1.0":   "libpangoft2-1.0.0.dylib",
        "cairo":          "libcairo.2.dylib",
        "gdk_pixbuf-2.0": "libgdk_pixbuf-2.0.0.dylib",
        "gobject-2.0":    "libgobject-2.0.0.dylib",
        "glib-2.0":       "libglib-2.0.0.dylib",
        "fontconfig":     "libfontconfig.1.dylib",
        "freetype":       "libfreetype.6.dylib",
    }
    _orig = ctypes.util.find_library
    def _patched(name):
        dylib = _libs.get(name)
        if dylib:
            path = os.path.join(brew, dylib)
            if os.path.exists(path):
                return path
        return _orig(name)
    ctypes.util.find_library = _patched


def render_pdf(html):
    """Ritorna i byte del PDF a partire dall'HTML del report (richiede WeasyPrint)."""
    _patch_macos_weasyprint()
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


def main():
    ap = argparse.ArgumentParser(description="GEO Audit - scanner GEO completo")
    ap.add_argument("url"); ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--out", default="geo_report.html")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--respect-robots", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    print(f"=== GEO AUDIT - {a.url} ===")
    res = run_audit(a.url if a.url.startswith("http") else "https://" + a.url,
                    max_pages=a.max_pages, render=not a.no_render,
                    respect_robots=a.respect_robots, log=lambda m: print("  " + str(m)))
    out_html = a.out if a.out.endswith(".html") else a.out + ".html"
    open(out_html, "w", encoding="utf-8").write(res["html"])
    print(f"\n  GEO Readiness: {res['overall']}/100 ({res['grade']} - {res['band']})")
    print(f"  Report HTML: {out_html}")
    if not a.no_pdf:
        try:
            out_pdf = out_html[:-5] + ".pdf"
            open(out_pdf, "wb").write(render_pdf(res["html"]))
            print(f"  Report PDF:  {out_pdf}")
        except Exception as e:
            print(f"  (PDF non generato: {type(e).__name__}. Su macOS: brew install pango)")
    if a.json:
        import json as _json
        _json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  JSON:        {a.json}")


if __name__ == "__main__":
    main()
