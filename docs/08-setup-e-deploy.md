# 08 · Setup e deploy

---

## Variabili d'ambiente

Riferimento: [.env.example](../.env.example).

| Variabile | Obbligatoria | Usata da | Note |
|---|---|---|---|
| `SUPABASE_URL` | ✅ | `server.py` | |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | `server.py` | **Bypassa RLS — mai lato client** |
| `SUPABASE_ANON_KEY` | ⚠️ di fatto sì | `server.py` | Iniettata nelle pagine di login: senza, l'auth non funziona |
| `RESEND_API_KEY` | ❌ | email | Senza, le email non partono (nessun errore) |
| `FROM_EMAIL` | ❌ | email | Dominio verificato su Resend |
| `SITE_URL` | ❌ | link, sitemap, snippet | Senza, i link nelle email e nello snippet sono rotti |
| `CRON_SECRET` | ❌ | `/api/cron`, token HMAC | Vedi avvertenza sotto |

### Comportamento all'avvio

Solo `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` sono lette con `os.environ[...]`
e fanno **crashare il processo** se mancanti. Le altre usano `os.environ.get()` con
default:

```python
SUPABASE_URL  = os.environ["SUPABASE_URL"]              # crash se manca
SUPABASE_SVC  = os.environ["SUPABASE_SERVICE_ROLE_KEY"] # crash se manca
SUPABASE_ANON = os.environ.get("SUPABASE_ANON_KEY", "") # degrada silenziosamente
RESEND_KEY    = os.environ.get("RESEND_API_KEY", "")
SITE_URL      = os.environ.get("SITE_URL", "").rstrip("/")
_SECRET       = os.environ.get("CRON_SECRET", "fallback-secret").encode()
```

> ⚠️ **`CRON_SECRET` ha un default `"fallback-secret"`.** Serve per due cose
> diverse:
> 1. proteggere `/api/cron` — qui il default è innocuo perché la route legge
>    `_CRON_SECRET` senza fallback, e con `CRON_SECRET` vuoto il controllo di
>    autorizzazione viene semplicemente saltato (endpoint pubblico);
> 2. **firmare i token HMAC di accesso ai report** in `server.py`.
>
> In produzione **deve essere valorizzata con una stringa casuale di almeno 32
> caratteri**. Con il default, i token di accesso ai report sono prevedibili da
> chiunque conosca il sorgente.

> ⚠️ **`SUPABASE_ANON_KEY` degrada in silenzio.** Se manca, `/login` renderizza una
> pagina in cui il client Supabase si inizializza con chiave vuota: il form appare
> ma il magic link non parte mai, senza errori evidenti. È la chiave pubblica
> progettata per essere esposta (protetta dalle RLS), non è un segreto — ma è
> necessaria.

---

## Sviluppo locale

### Minimo funzionante

```bash
git clone <repo> && cd geo-audit
python3 -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env      # compila almeno SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY
set -a && source .env && set +a

uvicorn server:app --reload
# → http://localhost:8000
```

`--reload` fa ripartire il processo ad ogni modifica: necessario perché i template
sono letti a memoria all'avvio.

### Con rendering JS e PDF

Servono le due dipendenze **fuori** da `requirements.txt`:

```bash
pip install playwright weasyprint
playwright install chromium

# macOS: WeasyPrint richiede le librerie Pango
brew install pango
```

La patch per macOS Apple Silicon è già nel codice
([geo_audit.py:934](../geo_audit.py#L934)): `ctypes.util.find_library()` non cerca
in `/opt/homebrew/lib`, quindi WeasyPrint verrebbe cercato con i nomi Linux. La
patch rimappa i nomi sui `.dylib` corretti prima dell'import.

### Solo il motore, senza web

```bash
python geo_audit.py www.esempio.it --max-pages 20 --out report.html --json report.json
```

Non richiede né Supabase né variabili d'ambiente. È il modo più rapido per
verificare una modifica all'engine.

### Con Docker (identico a un deploy a container)

```bash
docker build -t geo-audit .
docker run -p 8000:8000 --env-file .env geo-audit
```

L'immagine include Chromium e le librerie PDF: **è l'unico ambiente in cui
`render.parity` viene davvero calcolato**. La prima build richiede qualche minuto.

---

## Setup del database

### 1. Migrazione

Nel **SQL Editor** di Supabase, esegui l'intero
[supabase_setup.sql](../supabase_setup.sql). È idempotente: rieseguirlo per intero
è sempre sicuro.

L'ultima riga è essenziale:

```sql
NOTIFY pgrst, 'reload schema';
```

Senza, le nuove tabelle restano invisibili all'API REST con errore `PGRST205`.

### 2. Configurazione di Supabase Auth

Nel pannello **Authentication → URL Configuration**:

- **Site URL**: `https://tuo-dominio`
- **Redirect URLs**: deve includere `https://tuo-dominio/auth/callback`

> Il `redirect_to` inviato dall'app è **senza query string** — Supabase valida la
> URL contro questa whitelist e i parametri la facevano fallire. Non aggiungere
> query string al redirect.

### 3. Seed demo (opzionale)

[supabase_seed_demo.sql](../supabase_seed_demo.sql) popola un progetto
`demo-website` con 4 audit storici, issue e 12 sessioni di tracking.

⚠️ Prima di eseguirlo, **sostituisci l'`user_id` hardcoded**
(`05ba0f8c-7856-43d2-a86e-9036601e1cc0`) con l'UUID del tuo utente.

⚠️ La parte `audits` **non è idempotente**: rilanciarlo aggiunge 4 nuovi audit.
Vedi [04 · Modello dati](04-data-model.md#seed-demo).

---

## Deploy su Vercel

### Setup iniziale

1. Collega il repository al progetto Vercel.
2. **Non aggiungere configurazione di build.** Vercel rileva `fastapi` in
   `requirements.txt` e serve `api/index.py` come funzione ASGI nativa.
3. Imposta tutte le variabili d'ambiente in **Settings → Environment Variables**.
4. Il cron in [vercel.json](../vercel.json) si attiva da sé.

### Regola critica

> ⚠️ **Non aggiungere `rewrites` a `vercel.json`.**
>
> Un catch-all `"/(.*)" → "/api/index"` va in conflitto con il routing nativo e
> causa `{"detail":"Not Found"}` su **ogni** pagina. Il fallimento è silenzioso in
> build e totale in produzione — è già successo (commit `910ef87`).
>
> Le nuove route statiche vanno aggiunte come **endpoint FastAPI in `server.py`**,
> come è stato fatto per `/robots.txt`, `/sitemap.xml` e `/llms.txt`.

### Verifica post-deploy

```bash
curl https://tuo-dominio/health          # {"status":"ok"}
curl https://tuo-dominio/robots.txt      # contenuto, non 404
curl -I https://tuo-dominio/             # 200, non {"detail":"Not Found"}
curl https://tuo-dominio/static/css/design-system.css | head -3
```

Se `/health` risponde ma `/` dà `Not Found`, è quasi certamente un `rewrites` di
troppo.

### Il cron

```json
{ "crons": [ { "path": "/api/cron", "schedule": "0 * * * *" } ] }
```

Ogni ora, allo scoccare. Vercel invia `Authorization: Bearer $CRON_SECRET`;
senza il secret corretto la route risponde 401.

La cadenza oraria richiede il piano **Pro** — su Hobby i cron girano al massimo
una volta al giorno, che non basta oltre una manciata di progetti settimanali.

`/api/cron` è una **route FastAPI in `server.py`**, non un file in `api/`: con la
detection zero-config Vercel costruisce una sola function e nessun altro file in
`api/` diventa un endpoint. Il `api/cron.py` precedente non è mai stato deployato
e il cron ha ricevuto 404 per due settimane
([02 · Architettura](02-architettura.md#una-sola-function-apicron-incluso)).

Ogni invocazione processa fino a `max_projects` progetti scaduti (default **3**)
entro `_CRON_TIME_BUDGET` secondi per l'avvio di nuove iterazioni. In regime
normale ne trova 0 o 1: 24 invocazioni al giorno contro ~3 audit al giorno
necessari per 21 progetti settimanali.

#### Il vincolo fra budget e `maxDuration`

Il budget limita l'**avvio** di nuove iterazioni, non l'audit già partito. La
durata massima di un'invocazione è quindi:

```
_CRON_TIME_BUDGET + durata del singolo audit più lento
```

Un audit fa ~10 richieste HTTP con `geo_audit.TIMEOUT = 20s`: normalmente dura
10–20s, ma su un sito che non risponde può avvicinarsi a **200s**. Con
`_CRON_TIME_BUDGET = 60` serve quindi un `maxDuration` di almeno 260s.

> **`maxDuration` si imposta dal dashboard Vercel**, non da `vercel.json`:
> *Project Settings → Functions → Function Max Duration*. Il piano Pro arriva a
> 300s. Non aggiungere una chiave `functions` a `vercel.json` per ottenerlo — è
> esattamente il tipo di modifica che ha già rotto la produzione una volta
> (commit `910ef87`), e il dashboard fa la stessa cosa a rischio zero.
>
> Il valore vale per **tutta** l'app, non solo per il cron: alzarlo protegge
> anche `/scan` e `/project/{id}/rerun`, che eseguono lo stesso audit sincrono.

Test manuale:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" https://tuo-dominio/api/cron
# → {"processed": N, "elapsed": 12.4, "results": [...]}
# "processed": 0 con la lista vuota = nessun progetto scaduto, non un errore
```

Il parametro è sovrascrivibile per un recupero manuale del backlog:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" 'https://tuo-dominio/api/cron?max_projects=10'
```

Con la cadenza oraria il margine è ampio: 24 invocazioni al giorno × fino a 3
progetti = 72 audit/giorno di capacità contro i ~3 necessari. Il ritardo
accumulato si smaltisce da solo.

### Limiti da conoscere su Vercel

| Limite | Conseguenza |
|---|---|
| Niente Chromium | `render.parity` sempre `unknown` → `render=False` ovunque |
| Niente WeasyPrint | Nessun endpoint PDF |
| Timeout della function | `max_pages=6` sugli audit sincroni |
| Cron 1×/giorno su **Hobby** | Non sufficiente oltre ~7 progetti settimanali. Su **Pro** la cadenza è oraria |
| `maxDuration` default del piano | Va alzato dal dashboard: il default non copre un audit su un sito lento |

---

## Deploy alternativo (Railway / Render / Fly)

Il [Dockerfile](../Dockerfile) è mantenuto e funzionante. Su un host a container:

- **Playwright funziona** → `render.parity` viene calcolato davvero
- **WeasyPrint funziona** → si può esporre un endpoint PDF
- Nessun timeout serverless → si può alzare `max_pages`

Il cron Vercel però non esiste: servirebbe uno scheduler alternativo (cron di
sistema, o un chiamante esterno su `/api/cron`).

I tre provider leggono il `Dockerfile` automaticamente. La prima build installa
Chromium e richiede qualche minuto.

---

## Verifiche prima di un commit

Non ci sono test automatici ([doc 10](10-stato-e-debito-tecnico.md#nessun-test-automatico)).
Il minimo sindacale:

```bash
python3 -m py_compile server.py api/index.py geo_audit.py
python3 -c "import json; json.load(open('vercel.json'))"
python3 geo_audit.py example.com --no-pdf --max-pages 3   # smoke test dell'engine
```

I primi due sono già in allowlist in [.claude/settings.json](../.claude/settings.json).

Checklist manuale per una modifica alla UI:

- [ ] Tema chiaro **e** scuro
- [ ] Mobile (le tabelle usano `data-label`)
- [ ] Se hai toccato un template: il processo è ripartito?
- [ ] Se hai toccato l'engine: `check_id` invariati? (altrimenti si spezza lo
      storico delle issue — vedi [04](04-data-model.md#il-fingerprint-è-un-contratto))
