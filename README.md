# GEO Audit — verticalai

Strumento che analizza quanto un sito è **leggibile e citabile dalle AI**
(ChatGPT, Gemini, Perplexity e principali LLM) e produce un report con punteggio,
infografiche e interventi prioritari, in HTML e PDF.

Questo repository è la **Fase A**: un servizio web con una pagina in cui inserisci
un URL e ottieni il report. Il motore usa un browser headless (Chromium) per leggere
anche i contenuti caricati via JavaScript.

## Cosa c'è dentro

| File | Cosa fa |
|------|---------|
| `geo_audit.py` | Il motore: crawl, controlli GEO, scoring, report HTML/PDF. Usabile anche da terminale. |
| `server.py` | Il servizio web (FastAPI): form → audit → report. |
| `templates/form.html` | La pagina d'ingresso con il campo URL. |
| `Dockerfile` | Immagine pronta al deploy (include Chromium e le librerie per il PDF). |

## ⚠️ Dove gira

Il browser headless **non funziona su hosting serverless** (es. Vercel/Netlify
functions). Serve un **host a container sempre attivo**: Railway, Render o Fly.io.
Tutti e tre leggono il `Dockerfile` automaticamente.

---

## Uso da terminale (il motore, senza web)

```bash
pip install -r requirements.txt
playwright install chromium
python geo_audit.py www.esempio.it --out report.html
```

## Avvio locale del servizio web

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn server:app --reload
# apri http://localhost:8000
```

## Con Docker (identico alla produzione)

```bash
docker build -t geo-audit .
docker run -p 8000:8000 geo-audit
# apri http://localhost:8000
```

---

## Deploy in produzione

### Railway (consigliato, più semplice)
1. Vai su railway.app → **New Project → Deploy from GitHub repo**.
2. Seleziona questo repository. Railway rileva il `Dockerfile` e fa la build.
3. In **Settings → Networking** genera un dominio pubblico. Fatto.

### Render
1. render.com → **New → Web Service** → collega il repo.
2. Environment: **Docker**. Render usa il `Dockerfile`.
3. Deploy → ottieni l'URL pubblico.

> La prima build installa Chromium: richiede qualche minuto. Le richieste di scan
> sono sincrone (Fase A): per siti grandi tieni le pagine sotto ~20 per evitare
> timeout. In **Fase B** passeremo a una coda + worker asincrono.

---

## Endpoints

- `GET /` — pagina con il form
- `POST /scan` — esegue l'audit (campi: `url`, `max_pages`)
- `GET /r/{id}` — report HTML
- `GET /r/{id}.pdf` — report PDF
- `GET /health` — stato del servizio

---

## Roadmap

- **Fase A (questo repo):** servizio web on-demand. ✅
- **Fase B:** coda + worker asincrono, salvataggio persistente su **Supabase**,
  imbuto email (cattura lead, double opt-in, follow-up), analytics.
- **Fase 2 (contenuti):** analisi semantica via LLM e presenza off-site
  (Wikipedia/Wikidata, citazioni di terzi, visibilità reale nelle risposte AI).

---

© verticalai.it
