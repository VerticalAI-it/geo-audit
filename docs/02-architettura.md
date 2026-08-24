# 02 · Architettura

## Stack

| Layer | Tecnologia | File |
|---|---|---|
| Backend | Python 3.12 · FastAPI | [server.py](../server.py) |
| Motore di audit | Python (requests + BeautifulSoup + lxml) | [geo_audit.py](../geo_audit.py) |
| Worker cron | Route FastAPI `/api/cron` | [server.py](../server.py) |
| Entry point serverless | Import ASGI | [api/index.py](../api/index.py) |
| Database + Auth | Supabase (Postgres + Auth magic link) | [supabase_setup.sql](../supabase_setup.sql) |
| Email | Resend (API REST) | funzioni `_send_*` in [server.py](../server.py) |
| Frontend | HTML statici + string injection, vanilla JS | [templates/](../templates/) |
| CSS | Token condivisi | [static/css/design-system.css](../static/css/design-system.css) |
| Hosting | Vercel (serverless) | [vercel.json](../vercel.json) |

**Nessun framework frontend, nessun template engine, nessun ORM, nessun bundler.**
È una scelta esplicita: il prodotto è un'app server-rendered con poche pagine e
un motore di analisi. Aggiungere React/Jinja2/SQLAlchemy aggiungerebbe superficie
senza risolvere un problema che oggi esiste.

## Dipendenze

Da [requirements.txt](../requirements.txt):

```
fastapi>=0.110          uvicorn[standard]>=0.29   python-multipart>=0.0.9
requests>=2.31          beautifulsoup4>=4.12      lxml>=5.0
supabase>=2.3,<3        resend>=0.7
```

Due dipendenze sono **fuori** da `requirements.txt`, installate solo nel
[Dockerfile](../Dockerfile):

- **Playwright** (Chromium headless) — per il rendering JS
- **WeasyPrint** — per l'export PDF

Non girano su Vercel. Vedi [Il rendering headless è disattivato in
produzione](#il-rendering-headless-è-disattivato-in-produzione).

---

## Rendering delle pagine

Non c'è un template engine. I file `.html` in `templates/` vengono **letti a
memoria all'avvio del processo** ([server.py:32-40](../server.py#L32-L40)) e i
placeholder `{{CHIAVE}}` sostituiti da `_render()`
([server.py:43](../server.py#L43)):

```python
FORM_HTML = open(os.path.join(_HERE, "templates", "form.html"), encoding="utf-8").read()

def _render(tpl: str, **kv) -> str:
    for k, v in kv.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    return tpl
```

**Implicazione operativa:** modificare un file in `templates/` richiede il
riavvio del processo. In dev `uvicorn --reload` lo fa da sé; in produzione ogni
deploy è un processo nuovo, quindi il punto non si presenta.

**Implicazione di sicurezza:** `_render()` non fa escaping. Ogni valore
interpolato deve essere già sicuro — nel codice si usa `geo_audit.esc()`
(che è `html.escape`) o `json.dumps()` per i valori destinati a contesto JS.

Le parti dinamiche più complesse (dashboard, tab di progetto, report) sono
**HTML costruito in Python** con f-string, non template. Vedi le funzioni
`_tab_*` in [server.py:1566-1938](../server.py#L1566-L1938).

---

## Deploy su Vercel

### La configurazione minima è deliberata

[vercel.json](../vercel.json) contiene **solo** la definizione del cron:

```json
{ "crons": [ { "path": "/api/cron", "schedule": "0 * * * *" } ] }
```

Nessun `builds`, nessun `routes`, nessun `rewrites`. È il risultato di un bug di
produzione risolto nel commit `910ef87`, ed è documentato anche in
[CLAUDE.md](../CLAUDE.md):

> Vercel rileva `server.py`/`api/index.py` come app FastAPI nativa (zero-config,
> via `fastapi` in `requirements.txt`) e la serve come **singola Vercel Function**
> che gestisce internamente tutto il routing. Un catch-all manuale
> (`"/(.*)" → "/api/index"`) va in conflitto con questo routing nativo e causa
> `{"detail":"Not Found"}` su ogni pagina.

Il bug era particolarmente insidioso: **build verde, produzione completamente
rotta**. Non aggiungere `rewrites`. Le nuove route statiche (es. `/robots.txt`)
vanno aggiunte come endpoint FastAPI in `server.py`, non come rewrite.

### Una sola function, `/api/cron` incluso

```
┌──────────────────────────────────────────────────────┐
│ api/index.py  →  from server import app              │
│   Vercel Function ASGI: TUTTE le route dell'app      │
│   /, /audit, /scan, /r/{id}, /dashboard, /project/…  │
│   /robots.txt, /sitemap.xml, /llms.txt, /api/cron    │
│   + /static/* servito da FastAPI StaticFiles         │
└──────────────────────────────────────────────────────┘
```

`api/index.py` fa `sys.path.insert(0, <repo root>)` per poter importare
`geo_audit` e `server` dalla radice.

**Non esistono function separate.** Fino ad agosto 2026 il repo conteneva un
`api/cron.py` basato su `BaseHTTPRequestHandler`, nell'assunto che non essendo
FastAPI sopravvivesse come function autonoma. **L'assunto era falso**: con la
detection zero-config Vercel serve l'intero deployment come singola function
FastAPI, quindi quel file non veniva mai costruito e ogni `GET /api/cron`
finiva nel router di `server.py`, che non aveva quella route:

```
$ curl -s https://geo.verticalai.it/api/cron
{"detail":"Not Found"}          ← FastAPI, non Vercel
```

Vercel Cron ha quindi ricevuto un 404 a ogni invocazione dall'11 agosto 2026
(commit `1ccb850`) fino al fix. È la stessa trappola di `/robots.txt`, con la
differenza che qui nessuno se ne accorgeva: il fallimento era di un job
automatico, non di una pagina visitata.

**Regola:** qualsiasi endpoint, cron incluso, va aggiunto come route FastAPI in
`server.py`. Un file in `api/` che non sia `index.py` non diventa una function.

### Il Dockerfile è un percorso alternativo, non morto

Il [Dockerfile](../Dockerfile) installa Chromium via Playwright e le librerie
Pango/Cairo per WeasyPrint. Serve per il deploy su un host a container
(Railway/Render/Fly) dove il rendering JS e il PDF funzionerebbero. **Non è il
deploy attuale** ma resta valido e va tenuto allineato se cambiano le dipendenze.

---

## Flussi runtime

### Audit on-demand (`POST /scan`)

```
utente autenticato → POST /scan {url}
  │
  ├─ non loggato? → 303 /login?next=/audit
  │
  ├─ normalizza URL (aggiunge https:// se manca lo schema)
  │
  ├─ run_in_threadpool(geo_audit.run_audit, url, max_pages=6, render=False)
  │     └─ CPU/IO bound sincrono, isolato dall'event loop
  │
  ├─ upsert project (user_id + domain, unique)
  ├─ insert audits (status='done', html + tutte le colonne strutturate)
  ├─ _sb_issue_sync()  → apre/aggiorna/risolve le issue del progetto
  ├─ _sb_project_bump_scan() → sposta next_scan_at in avanti
  │
  └─ 303 → /r/{job_id}
```

Riferimento: [server.py:969-1036](../server.py#L969-L1036).

Il salvataggio su Supabase è **non bloccante**: se fallisce, l'errore viene
loggato con il body della risposta HTTP e l'utente vede comunque il report
(fallback sul gate inline). Il log esplicito è stato aggiunto apposta nel commit
`0d9179c` — prima un salvataggio rotto era invisibile e l'utente ricadeva
silenziosamente sul flusso legacy.

### Audit periodico (`GET /api/cron`)

```
Vercel Cron → GET /api/cron   (route FastAPI in server.py)
  │  Authorization: Bearer $CRON_SECRET  → 401 se non combacia
  │  (nessun controllo se CRON_SECRET non è impostata)
  │
  └─ finché processed < max_projects e elapsed < _CRON_TIME_BUDGET:
        │
        ├─ _sb_project_claim_due()
        │    SELECT il primo progetto con next_scan_at <= now
        │    UPDATE next_scan_at = now + _SCAN_LEASE (20 min)
        │      WHERE id = ? AND next_scan_at <= now
        │    → se 0 righe aggiornate, un'altra invocazione l'ha già preso
        │
        └─ _run_project_scan()
             ├─ run_audit(url, max_pages=6, render=False)
             ├─ insert audits + _sb_issue_sync()
             └─ _sb_project_bump_scan() → next_scan_at = now + intervallo pieno
```

Riferimento: `_sb_project_claim_due`, `_run_project_scan` e la route `/api/cron`
in [server.py](../server.py).

**Il claim scrive una lease breve, non l'intervallo pieno.** È la differenza che
rende il sistema resistente ai timeout: se la function viene uccisa a metà audit,
`next_scan_at` resta a `now + 20 min` e il progetto viene ritentato al giro
successivo. Con il claim a intervallo pieno un timeout faceva sparire il progetto
per una settimana intera, senza errore e senza traccia.

Un errore **esplicito** (sito irraggiungibile, Supabase KO) sposta invece
`next_scan_at` all'intervallo pieno: niente retry aggressivi su un sito rotto.
Solo il caso "processo ucciso" resta sulla lease breve.

### Tracking first-party (`POST /t`)

```
sito del CLIENTE (dominio terzo)
  │  <script src=".../static/js/geo-track.js" data-project="{uuid}" async>
  │
  ├─ genera/recupera session_id in sessionStorage
  └─ navigator.sendBeacon(POST /t, {pid, event, sid, url, ref, props})
        │  (fallback: fetch keepalive)
        │
        └─ server: nessuna auth, validazione minima, troncamento campi
             ├─ _detect_ai_source(referrer) → mappa host → provider
             ├─ insert tracking_event (service role, bypassa RLS)
             └─ SEMPRE 204, anche in caso di errore
```

Riferimento: [static/js/geo-track.js](../static/js/geo-track.js) e
[server.py:933-966](../server.py#L933-L966).

Il **fallimento silenzioso è il requisito principale**: lo snippet gira sul sito
di un cliente, non deve mai romperlo né rallentarlo. Per questo: `sendBeacon`
(non blocca l'unload), timeout Supabase a 5s, `try/except: pass`, 204 in ogni caso.

---

## Decisioni architetturali e loro perché

### Supabase via REST diretta, non `supabase-py`

`server.py` parla con Supabase costruendo a mano le chiamate PostgREST con
`requests` ([server.py:59-291](../server.py#L59-L291)), con header service role:

```python
_SB_H = {"apikey": SUPABASE_SVC, "Authorization": f"Bearer {SUPABASE_SVC}",
         "Content-Type": "application/json", "Prefer": "return=representation"}
```

Il motivo è storico ed è documentato nella cronologia dei commit: il client
sincrono di `supabase-py` bloccava l'event loop, e la sua dipendenza `httpx`
risultò incompatibile con il runtime Vercel dell'epoca (commit `1877536`,
`cfb7f41`, `4dd13e7`). La REST diretta ha risolto entrambi i problemi.

Fino ad agosto 2026 `api/cron.py` usava invece `supabase-py`, nell'assunto che
girasse in una function separata dove il vincolo non si applicava, e questo
duplicava la sincronizzazione delle issue in due implementazioni equivalenti da
tenere allineate a mano. Con il cron diventato una route FastAPI il file è stato
rimosso: `_sb_issue_sync` in `server.py` è ora l'unica implementazione, e vale
la regola sopra anche per il codice del cron — **REST diretta, non `supabase-py`**.

### La service role key bypassa RLS — l'autorizzazione è nel codice

Tutte le query dell'app usano la service role key, che **ignora le Row Level
Security policy**. Le policy definite in `supabase_setup.sql` sono un backstop per
l'accesso diretto via anon key, non il meccanismo di autorizzazione effettivo.

L'autorizzazione reale è nel codice applicativo, con lo stesso pattern ovunque:

```python
project = _sb_project_get(project_id)
if not project or project.get("user_id") != user["id"]:
    return 404
```

**Ogni nuova route che accede a dati di progetto deve ripetere questo controllo.**
Non c'è un middleware che lo faccia.

### Il rendering headless è disattivato in produzione

`run_audit` accetta `render=True` e userebbe Playwright per confrontare l'HTML
statico con quello renderizzato — il check `render.parity`, peso 8, uno dei più
importanti del catalogo. **Su Vercel non c'è Chromium**, quindi tutte le chiamate
in produzione passano `render=False`:

| Chiamante | Parametri |
|---|---|
| `POST /scan` | `run_audit(url, 6, False, False)` |
| `POST /project/{id}/rerun` | `run_audit(url, 6, False, False)` |
| `GET /api/cron` (audit periodico) | `run_audit(url, 6, False, False)` |
| CLI (`python geo_audit.py`) | `render=True` di default |

Quando `render=False`, il check `render.parity` restituisce stato `unknown` con
il messaggio *"Rendering headless non eseguito: confronto non disponibile"*
([geo_audit.py:393-399](../geo_audit.py#L393-L399)). I check `unknown` sono
esclusi dal calcolo del punteggio, quindi **non penalizzano** — ma il segnale
manca del tutto.

È il limite più significativo dell'audit in produzione. Vedi
[11 · Next steps](11-next-steps.md).

### `max_pages=6` in produzione

L'audit sincrono deve stare dentro il timeout della function Vercel. 6 pagine con
`CRAWL_DELAY = 0.4s` sono un compromesso fra copertura e latenza. La CLI usa 20
di default.

### Il PDF non esiste come route

`geo_audit.render_pdf()` esiste e funziona (WeasyPrint, con una patch per macOS
Homebrew in [geo_audit.py:934](../geo_audit.py#L934)), ma **nessuna route la
espone**: WeasyPrint non è in `requirements.txt` e non gira su Vercel. Il PDF si
ottiene solo da CLI. Il README alla radice afferma il contrario ed è obsoleto.

---

## Mappa dei file

```
geo-audit/
├── server.py                    2588 righe — TUTTA l'app web
│                                route, helper Supabase, auth, email,
│                                costruzione HTML di dashboard e tab
├── geo_audit.py                 1004 righe — motore di audit + report HTML/PDF
│                                usabile anche standalone da CLI
├── api/
│   └── index.py                 4 righe — import ASGI per Vercel
├── templates/                   HTML letti a memoria all'avvio
│   ├── home.html                1535 righe — landing marketing
│   ├── form.html                inserimento URL
│   ├── login.html               magic link
│   ├── auth_callback.html       scambio token → cookie
│   ├── dashboard.html           portfolio progetti (rendering JS da JSON)
│   ├── project.html             shell del dettaglio progetto
│   ├── roadmap.html             roadmap pubblica
│   ├── privacy.html             privacy policy
│   ├── cookie.html              cookie policy
│   ├── gate.html                ⚠️ ORFANO — non caricato da server.py
│   └── waiting.html             ⚠️ ORFANO — non caricato da server.py
├── static/
│   ├── css/design-system.css    581 righe — token e componenti
│   └── js/geo-track.js          snippet di tracking per i siti dei clienti
├── design_system/               fonte di verità visiva
│   ├── DESIGN_SYSTEM.md
│   └── ds_components/           ds.html + 5 template email di riferimento
├── docs/                        questa documentazione
├── supabase_setup.sql           migrazione completa, idempotente
├── supabase_seed_demo.sql       dati demo per il progetto "demo-website"
├── vercel.json                  solo la definizione del cron
├── Dockerfile                   deploy alternativo con Chromium + WeasyPrint
├── requirements.txt
├── CLAUDE.md                    regole operative per chi modifica il repo
└── README.md                    ⚠️ obsoleto (descrive la Fase A)
```

**`server.py` a 2588 righe è il punto di concentrazione del rischio.** Contiene
route, accesso ai dati, auth, generazione email e costruzione HTML. Non è un
problema oggi (l'app è piccola e coesa) ma è la prima cosa da spezzare se il team
cresce. Un taglio naturale sarebbe `db.py` / `auth.py` / `emails.py` / `views.py`.
