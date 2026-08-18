# 08 · Setup e deploy

---

## Variabili d'ambiente

Riferimento: [.env.example](../.env.example).

| Variabile | Obbligatoria | Usata da | Note |
|---|---|---|---|
| `SUPABASE_URL` | ✅ | `server.py`, `api/cron.py` | |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | `server.py`, `api/cron.py` | **Bypassa RLS — mai lato client** |
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
> 1. proteggere `/api/cron` — qui il default è innocuo perché in `cron.py` la
>    variabile non ha fallback, e con `CRON_SECRET` vuoto il controllo di
>    autorizzazione viene semplicemente saltato;
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
{ "crons": [ { "path": "/api/cron", "schedule": "0 3 * * *" } ] }
```

Una volta al giorno alle 03:00 UTC. Vercel invia `Authorization: Bearer
$CRON_SECRET`; senza il secret corretto la function risponde 401.

La cadenza è **deliberatamente conservativa** (commit `1ccb850`): era oraria, è
stata portata a giornaliera per essere compatibile con qualsiasi piano Vercel ed
escludere che la configurazione del cron potesse far fallire il deploy. Per
compensare la minore frequenza, ogni invocazione processa fino a **3 progetti**
scaduti con un budget di **20 secondi** per l'avvio di nuove iterazioni — così
anche uno scheduling raro recupera il ritardo accumulato.

Test manuale:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" https://tuo-dominio/api/cron
# → {"pending_queue": {...}, "project_scans": {"processed": N, "results": [...]}}
```

### Limiti da conoscere su Vercel

| Limite | Conseguenza |
|---|---|
| Niente Chromium | `render.parity` sempre `unknown` → `render=False` ovunque |
| Niente WeasyPrint | Nessun endpoint PDF |
| Timeout della function | `max_pages=6` sugli audit sincroni |
| Cron 1×/giorno (Hobby) | Cadenza giornaliera + recupero a 3 progetti per invocazione |

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
python3 -m py_compile server.py api/cron.py geo_audit.py
python3 -c "import json; json.load(open('vercel.json'))"
python3 geo_audit.py example.com --no-pdf --max-pages 3   # smoke test dell'engine
```

I primi due sono già in allowlist in [.claude/settings.json](../.claude/settings.json).

Checklist manuale per una modifica alla UI:

- [ ] Tema chiaro **e** scuro
- [ ] Mobile (le tabelle usano `data-label`)
- [ ] Se hai toccato un template: il processo è ripartito?
- [ ] Se hai toccato un'email: replicata in `server.py` **e** `api/cron.py`?
- [ ] Se hai toccato l'engine: `check_id` invariati? (altrimenti si spezza lo
      storico delle issue — vedi [04](04-data-model.md#il-fingerprint-è-un-contratto))
