# GEO Audit — Vertical AI

Piattaforma di **Generative Engine Optimization**: analizza quanto un sito è
leggibile, citabile e consigliabile dagli assistenti AI (ChatGPT, Gemini, Claude,
Perplexity), produce un report con punteggio e interventi prioritari, e monitora
nel tempo l'andamento del progetto.

---

## 📚 Documentazione

**La documentazione completa è in [`docs/`](docs/README.md)** — architettura,
catalogo dei check, modello dati, deploy, debito tecnico e roadmap.

| Se devi… | Leggi |
|---|---|
| Capire cos'è il prodotto | [docs/01-prodotto.md](docs/01-prodotto.md) |
| Mettere le mani nel codice | [docs/02-architettura.md](docs/02-architettura.md) |
| Far girare tutto in locale | [docs/08-setup-e-deploy.md](docs/08-setup-e-deploy.md) |
| Sapere dove sono le mine | [docs/10-stato-e-debito-tecnico.md](docs/10-stato-e-debito-tecnico.md) |
| Pianificare il prossimo lavoro | [docs/11-next-steps.md](docs/11-next-steps.md) |
| Toccare HTML, CSS o email | [design_system/DESIGN_SYSTEM.md](design_system/DESIGN_SYSTEM.md) |

Regole operative vincolanti per chi modifica il repo: [CLAUDE.md](CLAUDE.md).

---

## Avvio rapido

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # compila almeno SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY
set -a && source .env && set +a

uvicorn server:app --reload
# → http://localhost:8000
```

Setup completo (database, auth, rendering JS, PDF, Docker):
[docs/08-setup-e-deploy.md](docs/08-setup-e-deploy.md).

### Solo il motore, da riga di comando

Non richiede Supabase né variabili d'ambiente:

```bash
python geo_audit.py www.esempio.it --max-pages 20 --out report.html --json report.json
```

È anche l'unico modo per ottenere il PDF e per avere il check `render.parity`
calcolato davvero — vedi [docs/03-audit-engine.md](docs/03-audit-engine.md#uso-da-cli).

---

## Struttura

| Percorso | Contenuto |
|---|---|
| [`server.py`](server.py) | App FastAPI: route, auth, dashboard, email, helper Supabase |
| [`geo_audit.py`](geo_audit.py) | Motore di audit: crawl, 31 check, scoring, report HTML/PDF |
| [`api/index.py`](api/index.py) | Entry point Vercel (importa `server.app`) |
| [`templates/`](templates/) | Pagine HTML, caricate a memoria da `server.py` |
| [`static/`](static/) | CSS del design system, snippet di tracking |
| [`design_system/`](design_system/) | Fonte di verità visiva: token, componenti, email |
| [`docs/`](docs/) | Documentazione completa |
| [`supabase_setup.sql`](supabase_setup.sql) | Migrazione dello schema (idempotente) |

---

## Deploy

Produzione su **Vercel**, zero-config: `api/index.py` è servita come funzione ASGI
nativa, ed è **l'unica funzione del deployment**.

> ⚠️ **Non aggiungere `rewrites` a [`vercel.json`](vercel.json).** Un catch-all va
> in conflitto con il routing FastAPI nativo e restituisce `{"detail":"Not Found"}`
> su ogni pagina — build verde, produzione rotta.

> ⚠️ **Non aggiungere file in `api/`.** Solo `index.py` diventa una funzione: ogni
> altro file lì dentro non viene costruito e le sue richieste finiscono nel router
> FastAPI. È così che il cron è rimasto morto per due settimane. Qualsiasi nuovo
> endpoint — pagina statica, cron, webhook — va aggiunto come route FastAPI in
> `server.py`.

Il [`Dockerfile`](Dockerfile) resta valido per un deploy a container
(Railway/Render/Fly), dove funzionano anche il rendering headless e il PDF.

---

## Stato

Disponibile oggi: motore di audit, account con magic link, progetti con storico,
dashboard portfolio, dettaglio progetto, ciclo di vita delle issue, tracking
first-party con tab AI Traffic, audit periodici automatici.

In arrivo: monitoraggio delle citazioni reali sui provider AI, competitor e share
of voice, presenza off-site. Vedi [docs/11-next-steps.md](docs/11-next-steps.md)
e la [roadmap pubblica](https://geo-audit.vercel.app/roadmap).

---

© [verticalai.it](https://verticalai.it)
