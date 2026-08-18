# 03 · Audit engine (`geo_audit.py`)

Il motore di analisi. **1004 righe, zero dipendenze dall'app web**: si usa sia da
`server.py` che da riga di comando. Nessun LLM è coinvolto — tutti i check sono
deterministici e riproducibili.

Versione motore corrente: **`ENGINE_VERSION = "1.1.0"`**
([geo_audit.py:37](../geo_audit.py#L37)), salvata su ogni riga di `audits`.

---

## Contratto pubblico

```python
run_audit(url, max_pages=20, render=True, respect_robots=False, log=lambda *a: None) -> dict
```

Ritorna ([geo_audit.py:923-931](../geo_audit.py#L923-L931)):

```python
{
  "html": str,              # report completo, autoconsistente (CSS inline)
  "overall": int,           # 0-100
  "grade": str,             # A|B|C|D|E|F
  "band": str,              # Eccellente|Buono|Discreto|Da rafforzare|Critico
  "domain": str,
  "render": bool,           # rendering headless effettivamente usato
  "respect_robots": bool,
  "engine_version": str,
  "pages": [                # dettaglio per pagina
    {"url", "type", "title", "score", "checks": [Check...]}
  ],
  "site_checks": [Check...],       # check a livello di sito
  "areas": [{"key", "score"}],     # punteggio per macro-area, asc
  "actions": [                     # interventi aggregati, machine-readable
    {"check_id", "title", "category", "recommendation", "severity", "count", "urls"}
  ],
  "issues_count": int,      # check warn + fail
  "critical_count": int,    # check fail
}
```

`run_audit` **non scrive file**: è pensata per essere chiamata da un servizio web.
La CLI si occupa di persistere.

Solleva `RuntimeError` se la home non risponde 200 o non è HTML.

### Il tipo `Check`

```python
@dataclass
class Check:
    id: str; category: str; title: str; status: str
    weight: int = 1; severity: str = "medium"; detail: str = ""; recommendation: str = ""
```

- `status` ∈ `ok` | `warn` | `fail` | `unknown`
- `severity` ∈ `critical` | `high` | `medium` | `low` | `info`
- `id` è la **chiave stabile** su cui si costruisce il fingerprint delle issue.
  Cambiarlo spezza la continuità storica di quella issue ([04 · Modello
  dati](04-data-model.md#il-fingerprint-è-un-contratto)).

---

## Pipeline di esecuzione

```
run_audit(url)
 │
 ├─ 1. normalizza URL (aggiunge https:// se manca)
 ├─ 2. playwright_available()? → se no, render=False (degrada, non fallisce)
 ├─ 3. get_page(base) → fetch della home
 │     └─ se status != 200 o non HTML → RuntimeError
 ├─ 4. build_site(base)          → robots.txt, sitemap.xml, llms.txt, HTTPS
 ├─ 5. build_site_checks(site)   → 5 check a livello di sito
 ├─ 6. discover(...)             → lista URL da analizzare (max_pages)
 ├─ 7. per ogni URL: analyze_page() → 26 check di pagina, con CRAWL_DELAY 0.4s
 ├─ 8. render_report(...)        → HTML del report + punteggio complessivo
 └─ 9. aggrega: areas, actions, issues_count, critical_count
```

### Fetch

Due modalità ([geo_audit.py:95-144](../geo_audit.py#L95-L144)):

| Funzione | Come | Quando |
|---|---|---|
| `fetch_static()` | `requests.Session` con UA browser, timeout 20s, segue redirect | sempre |
| `fetch_rendered()` | Playwright Chromium headless, `networkidle` | solo se `render=True` **e** Playwright è installato |

`get_page(url, render)` ritorna la tupla `(fetched, static_for_parity)`: quando il
rendering è attivo servono entrambe le versioni per calcolare `render.parity`.

`playwright_available()` fa un probe una sola volta e memoizza il risultato in
`_PW_OK` — se Playwright manca, l'audit **degrada** invece di fallire.

### Discovery delle URL

`discover()` ([geo_audit.py:436](../geo_audit.py#L436)) unisce due sorgenti, in
quest'ordine di priorità:

1. i link `<a href>` della **home**
2. le URL della **sitemap.xml** (fino a 300, `fetch_sitemap_urls`)

Filtrate da `is_page_url()`, che scarta:

| Filtro | Esempi |
|---|---|
| `SKIP_EXT` | `.jpg .png .svg .pdf .zip` … — asset, non pagine |
| `SKIP_PATH` | `/wp-content/ /wp-admin/ /wp-json/ /feed` … — infrastruttura CMS |
| `SKIP_QUERY` | `add-to-cart` `replytocom` `?share=` `?attachment_id` — URL parametriche |

Più `same_domain()` (ignora il `www.`) e `norm()` (rimuove fragment, normalizza
trailing slash).

Questi filtri esistono per **affidabilità del punteggio**: analizzare 6 URL di cui
3 sono immagini o feed RSS produce un punteggio senza senso.

`UTILITY_RE` riconosce le pagine di servizio (privacy, cookie, termini, legal):
su queste un `noindex` è **atteso e corretto**, non un errore — vedi
`page.noindex` nel catalogo.

---

## Catalogo completo dei check

**31 check distinti**: 5 a livello di sito, 26 a livello di pagina. Alcuni sono
condizionali (indicato in nota) e quindi non compaiono su tutte le pagine.

### Livello sito — eseguiti una volta per audit

Da `build_site_checks()` ([geo_audit.py:866-884](../geo_audit.py#L866-L884)).

| ID | Titolo | Area | Peso | Severità | Condizione OK |
|---|---|---|---:|---|---|
| `crawl.ai` | Accesso crawler AI (robots.txt) | Rendering & accesso | **12** | `critical` | Nessun bot AI bloccato |
| `crawl.https` | HTTPS | Rendering & accesso | 3 | `high` | Schema `https` |
| `crawl.sitemap` | sitemap.xml | Rendering & accesso | 3 | `medium` | `/sitemap.xml` → 200 |
| `crawl.robots` | robots.txt | Rendering & accesso | 2 | `low` | `/robots.txt` → 200 |
| `crawl.llms` | llms.txt | Rendering & accesso | 1 | `info` | `/llms.txt` → 200 (opzionale) |

`crawl.ai` è **il check più pesante e l'unico `critical`** del catalogo, e a
ragione: se `robots.txt` blocca GPTBot, tutto il resto è irrilevante. I bot
monitorati ([geo_audit.py:47](../geo_audit.py#L47)):

```
GPTBot · OAI-SearchBot · ChatGPT-User · Google-Extended · PerplexityBot
ClaudeBot · Claude-Web · anthropic-ai · CCBot · Applebot-Extended · Bytespider
```

`parse_robots_ai()` rileva sia il blocco esplicito per user-agent sia il
`Disallow: /` su `User-agent: *`.

### Livello pagina — Rendering & accesso

Da `checks_indexing()` e `check_js_parity()`.

| ID | Titolo | Peso | Severità | Note |
|---|---|---:|---|---|
| `render.parity` | Parità contenuto senza JS | **8** | `high` | ⚠️ `unknown` in produzione — vedi sotto |
| `page.noindex` | Indicizzabilità | 6 | `medium`/`info`/`high` | `info` se noindex su pagina di servizio (atteso) |
| `page.status` | Stato HTTP | 4 | `high` | OK solo se 200 |

**`render.parity`** confronta il numero di parole dell'HTML statico con quello
renderizzato ([geo_audit.py:393-410](../geo_audit.py#L393-L410)):

| Rapporto statico/renderizzato | Esito |
|---|---|
| ≥ 80 % | `ok` |
| 50-80 % | `warn` — "parte del contenuto dipende dal JS" |
| < 50 % | `fail` — "il resto è iniettato via JS" |
| rendering non eseguito | `unknown` |

> ⚠️ **In produzione questo check è sempre `unknown`**: Vercel non ha Chromium e
> tutte le chiamate passano `render=False`. I check `unknown` sono esclusi dallo
> scoring, quindi non penalizzano — ma il segnale, che è uno dei più importanti
> per la GEO, oggi manca. Vedi [11 · Next steps](11-next-steps.md).

### Livello pagina — Dati strutturati

Da `checks_structured()` ([geo_audit.py:230-262](../geo_audit.py#L230-L262)).

| ID | Titolo | Peso | Severità | Condizione OK |
|---|---|---:|---|---|
| `sd.present` | Dati strutturati (JSON-LD) | **18** | `high` | Almeno un blocco JSON-LD |
| `sd.highvalue` | Tipi schema ad alto valore | 6 | `medium` | Almeno un tipo in `SCHEMA_HIGH_VALUE` ¹ |
| `sd.valid` | JSON-LD ben formato | 4 | `high` | Sintassi JSON valida ¹ |
| `sd.completeness` | Completezza proprietà schema | 4 | `low` | ¹ ² |
| `sd.sameas` | Collegamento entità (sameAs) | 3 | `low` | Almeno un `sameAs` ¹ |

¹ eseguito solo se esiste almeno un blocco JSON-LD · ² emesso solo se mancano
proprietà richieste

**`sd.present` con peso 18 è il check singolo più pesante del catalogo.** Riflette
la tesi centrale del prodotto: i dati strutturati sono il segnale più forte per un
assistente AI.

Il parser `jsonld()` gestisce array, `@graph` annidati e `@type` multipli.

`SCHEMA_HIGH_VALUE`: `Organization`, `LocalBusiness`, `Corporation`, `Product`,
`Offer`, `Article`, `BlogPosting`, `NewsArticle`, `FAQPage`, `HowTo`, `Person`,
`Service`, `Event`, `Recipe`, `Course`, `JobPosting`, `Review`, `BreadcrumbList`.

`SCHEMA_REQUIRED` verifica le proprietà obbligatorie per tipo, es.
`Organization: name, url, logo, sameAs`.

### Livello pagina — Contenuti & answerability

Da `checks_content()` ([geo_audit.py:310-347](../geo_audit.py#L310-L347)).

| ID | Titolo | Peso | Severità | Condizione OK |
|---|---|---:|---|---|
| `content.h1` | H1 unico | 6 | `medium` | Esattamente 1 `<h1>` |
| `content.len` | Profondità del contenuto | 5 | `medium` | ≥ 300 parole |
| `content.q` | Contenuti in forma di domanda | 4 | `low` | ≥ 1 H2/H3/H4 che finisce con `?` |
| `content.struct` | Formati estraibili | 4 | `medium` | ≥ 1 `<ul>`/`<ol>`/`<table>` |
| `content.hier` | Gerarchia dei titoli | 3 | `low` | ≥ 1 `<h2>` |
| `content.tldr` | Riassunto iniziale (TL;DR) | 3 | `low` | Regex su primi 600 caratteri ³ |
| `content.fresh` | Segnali di freschezza | 2 | `low` | `<time>`, `article:modified_time` o regex ⁴ |

³ `in breve|in sintesi|tl;dr|riassunto|punti chiave` · ⁴ `aggiornat|ultimo aggiornamento|updated`

`content.q` e `content.tldr` codificano due pattern specifici della GEO: gli
assistenti AI estraggono più volentieri da contenuti già strutturati come
domanda→risposta e da un riassunto in apertura.

### Livello pagina — HTML semantico

| ID | Titolo | Peso | Severità | Condizione OK | Definito in |
|---|---|---:|---|---|---|
| `sem.html` | HTML semantico | 3 | `low` | ≥ 3 fra `main`/`article`/`section`/`nav`/`header`/`footer` | `checks_eeat()` |
| `content.alt` | Alt text immagini | 2 | `low` | ≥ 80 % delle `<img>` con `alt` ⁵ | `checks_content()` |

⁵ emesso solo se la pagina contiene immagini

> Nota: entrambi appartengono all'area **HTML semantico** ma sono definiti in
> funzioni con un altro nome. È un dettaglio da conoscere quando si cerca il
> codice partendo dall'area mostrata nel report.

### Livello pagina — Meta & social

Da `checks_meta()` ([geo_audit.py:273-308](../geo_audit.py#L273-L308)).

| ID | Titolo | Peso | Severità | Condizione OK |
|---|---|---:|---|---|
| `meta.description` | Meta description | 5 | `high` se assente, altrimenti `medium` | ≥ 50 caratteri |
| `meta.title` | Title | 4 | `medium` | 10-70 caratteri |
| `meta.og` | Open Graph | 3 | `medium` | ≥ 3 tag `og:*` |
| `meta.canonical` | Canonical | 2 | `low` | `<link rel="canonical">` presente |
| `meta.lang` | Attributo lang | 2 | `low` | `<html lang>` presente |
| `meta.twitter` | Twitter card | 1 | `low` | ≥ 1 tag `twitter:*` |

`best_description()` prende la **più lunga** fra `meta[name=description]` e
`og:description` — alcuni CMS ne emettono più di una.

### Livello pagina — Autorità & trust

Da `checks_eeat()` ([geo_audit.py:349-371](../geo_audit.py#L349-L371)).

| ID | Titolo | Peso | Severità | Condizione OK |
|---|---|---:|---|---|
| `trust.contact` | Contatti presenti | 4 | `medium` | Link `mailto:`/`tel:` o email nel testo |
| `trust.social` | Profili social | 3 | `low` | ≥ 2 link a social noti |
| `trust.author` | Indicazione autore | 2 | `low` | `rel=author`, `article:author` o regex ⁶ |

⁶ `scritto da|autore|by`

---

## Scoring

### Formula

[geo_audit.py:413-418](../geo_audit.py#L413-L418):

```python
frac = {OK: 1.0, WARN: 0.5, FAIL: 0.0}
score = round(100 * Σ(weight × frac[status]) / Σ(weight))
```

Media pesata. **I check `unknown` sono esclusi da numeratore e denominatore**: non
penalizzano e non premiano.

Il punteggio complessivo si calcola su `site_checks + tutti i check di tutte le
pagine` concatenati ([geo_audit.py:918](../geo_audit.py#L918)).

> **Conseguenza da conoscere:** più pagine si analizzano, più i 5 check di sito si
> diluiscono. Con 6 pagine, `crawl.ai` (peso 12) pesa ~12 su un denominatore di
> ~500. Un sito che blocca GPTBot può quindi comunque ottenere un punteggio alto.
> Il report lo evidenzia nella sezione criticità, ma il **numero** non lo riflette
> in proporzione alla gravità. Da valutare in un futuro rework dello scoring
> ([doc 10](10-stato-e-debito-tecnico.md#lo-scoring-diluisce-i-check-di-sito)).

### Bande di punteggio

Attenzione: nel prodotto **convivono due scale diverse**.

| Scala | Dove | Soglie |
|---|---|---|
| **Grade / Band** | Report generato da `geo_audit.py` | A ≥ 90 · B ≥ 75 · C ≥ 60 · D ≥ 45 · E ≥ 30 · F |
| | | Eccellente ≥ 90 · Buono ≥ 75 · Discreto ≥ 60 · Da rafforzare ≥ 45 · Critico |
| **Colore** | Dashboard, UI, email | Verde ≥ 75 · Giallo ≥ 50 · Rosso < 50 |

La scala colore è quella normativa del design system. **`geo_audit.barcol()`
([geo_audit.py:473](../geo_audit.py#L473)) usa però 55 invece di 50** come soglia
intermedia: un punteggio di 52 è giallo nella dashboard e rosso nel report. È un
bug di coerenza noto ([doc 10](10-stato-e-debito-tecnico.md#soglie-colore-incoerenti)).

### Aree e azioni

`compute_area_scores()` raggruppa i check per `category` e applica la stessa
formula per area. Il risultato alimenta il radar del report e il breakdown per
area nella dashboard.

`derive_actions_full()` ([geo_audit.py:664](../geo_audit.py#L664)) aggrega i check
`warn`/`fail` **per `check_id`**, conta le occorrenze e raccoglie le URL
interessate, ordinando per severità e poi per frequenza. È la versione
machine-readable salvata nella colonna `actions`.

`derive_actions()` è la versione a tuple usata dall'HTML del report. **Sono
deliberatamente separate**: modificare l'una non deve alterare l'output dell'altra.

> Nota: `SEV_PRIO` ([geo_audit.py:465](../geo_audit.py#L465)) mappa `medium`,
> `low` e `info` tutti sull'etichetta "media". Nel report la distinzione fra
> severità basse non è visibile.

---

## Report HTML

`render_report()` produce un documento **autoconsistente**: CSS inline (`CSS`,
[geo_audit.py:553](../geo_audit.py#L553)), grafici in SVG generato a mano, nessuna
dipendenza esterna a parte i Google Fonts.

Grafici, tutti costruiti in Python:

| Funzione | Output |
|---|---|
| `gauge(score)` | Anello di progresso con il punteggio al centro |
| `radar(cats)` | Radar dei punteggi per area |
| `donut(ok, warn, fail)` | Distribuzione degli esiti |
| `scale_bar(score)` | Barra di posizionamento sulla scala |
| `dist_chart(pages)` | Distribuzione dei punteggi per pagina |

Sezioni: header · sommario · salute controlli · profilo per area · distribuzione ·
check di sito · quick win · interventi prioritari · elenco pagine · note · CTA ·
footer.

Il report supporta il **tema chiaro/scuro** con preferenza in `localStorage`
(chiave `geo-theme`), allineato al resto del prodotto pur mantenendo intatta la
resa in stampa/PDF.

> ⚠️ **Il report ha stili inline propri: non applicargli i token di
> `design-system.css`.** È una regola esplicita di [CLAUDE.md](../CLAUDE.md).
> L'HTML viene salvato integralmente nella colonna `audits.html` e servito così
> com'è mesi dopo: deve restare autoconsistente.

---

## Uso da CLI

```bash
pip install -r requirements.txt
pip install playwright weasyprint     # non in requirements.txt
playwright install chromium

python geo_audit.py www.esempio.it \
  --max-pages 20 \
  --out report.html \
  --json report.json
```

| Flag | Default | Effetto |
|---|---|---|
| `--max-pages N` | 20 | Numero massimo di pagine (produzione usa 6) |
| `--out FILE` | `geo_report.html` | Report HTML |
| `--json FILE` | — | Dump completo del dict di `run_audit` |
| `--no-render` | off | Disattiva Playwright |
| `--no-pdf` | off | Salta la generazione PDF |
| `--respect-robots` | off | Rispetta il `robots.txt` durante il crawl |

La CLI è **l'unico modo per ottenere il PDF** e **l'unico modo per avere
`render.parity` valorizzato**. È lo strumento giusto per un audit approfondito
manuale, mentre la produzione fa audit rapidi a 6 pagine senza rendering.
