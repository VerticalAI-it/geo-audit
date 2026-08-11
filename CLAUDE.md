# GEO Audit · CLAUDE.md

## Struttura del progetto

- `server.py` — app FastAPI principale (route, email, Supabase helpers)
- `api/index.py` — entry point Vercel (importa `server.app`)
- `api/cron.py` — worker cron per audit asincroni
- `geo_audit.py` — logica di analisi GEO
- `templates/` — file HTML caricati a memoria da `server.py`
- `design_system/` — fonte di verità per font, token, componenti

## Route e template

| Route | Template |
|---|---|
| `/` | `templates/home.html` — landing marketing |
| `/audit` | `templates/form.html` — form inserimento URL |
| `/r/{job_id}` | HTML report da Supabase + overlay iniettato via Python |
| `/miei-report` | String inline in `server.py` |

## Design System — regola fondamentale

**Ogni modifica a UX/UI deve rispettare `design_system/DESIGN_SYSTEM.md`.**

Leggi sempre quel file prima di toccare HTML, CSS o email. I punti chiave:

### Token CSS (`static/css/design-system.css`)

Usa i nuovi token, non i valori legacy:

| Legacy (vecchio) | Token DS (nuovo) |
|---|---|
| `--bg:#0B0B16` | `--canvas` |
| `--card:#17152A` | `--surface` |
| `--line:#2A2640` | `--border` |
| `--violet:#6C5CE7` | `--brand` |
| `--vbright:#9B8CFF` | `--brand-text` |
| `--text:#F2F1F8` | `--text` / `--ink` |
| `--muted:#9C99B5` | `--text-2` |

### Font stack

| Ruolo | Font |
|---|---|
| Display / titoli | Space Grotesk |
| Body / UI | Inter |
| Mono / dati | JetBrains Mono |

### Soglie colore punteggio

| Range | Colore token |
|---|---|
| 75–100 | `--success` |
| 50–74 | `--warning` |
| 0–49 | `--danger` |

### Pagine di prodotto vs report

- Le pagine in `templates/` linkano `static/css/design-system.css` — usa i token DS.
- I report generati da `geo_audit.py` hanno stili inline propri: **non toccarli**.

### Email

Tutte le email usano Resend. I template seguono il design system (sfondo `--canvas`, card `--surface`, CTA `--brand`). Vedi inventario completo in `design_system/DESIGN_SYSTEM.md`.

## Deploy

Vercel rileva `server.py`/`api/index.py` come app FastAPI nativa (zero-config, via `fastapi` in `requirements.txt`) e la serve come singola Vercel Function che gestisce internamente tutto il routing — **niente `rewrites` in `vercel.json`**: un catch-all manuale (`"/(.*)" → "/api/index"`) va in conflitto con questo routing nativo e causa `{"detail":"Not Found"}` su ogni pagina (successo silenzioso in build, rotto in produzione). Aggiungere nuove route statiche (es. `/robots.txt`) come endpoint FastAPI in `server.py`.

`api/cron.py` non definisce un'app FastAPI (usa `BaseHTTPRequestHandler`), quindi resta una Vercel Function indipendente su `/api/cron`, invariata da quanto sopra; è referenziata in `vercel.json` sotto `crons`.
