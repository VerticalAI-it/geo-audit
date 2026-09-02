# GEO Audit · CLAUDE.md

## Struttura del progetto

- `server.py` — app FastAPI: route, auth, email, cron
- `config.py` — variabili d'ambiente condivise
- `db.py` — accesso Supabase (tutti gli `_sb_*`); **importabile senza toccare `server.py`**
- `ai_sources.py` — chi sono le AI: crawler (dallo User-Agent) e referral (da
  `Referer`/`utm_source`). Modulo foglia, non importa nulla del progetto
- `views.py` — costruzione HTML di dashboard e tab di progetto
- `api/index.py` — entry point Vercel (importa `server.app`)
- `geo_audit.py` — logica di analisi GEO
- `templates/` — file HTML caricati a memoria da `server.py`
- `design_system/` — fonte di verità per font, token, componenti
- `docs/` — documentazione completa (architettura, check, dati, deploy, roadmap)

## Documentazione

Prima di un intervento non banale, leggi il documento pertinente in `docs/`:

| Ambito | Doc |
|---|---|
| Architettura, deploy, flussi | `docs/02-architettura.md` |
| Motore di audit e catalogo check | `docs/03-audit-engine.md` |
| Schema Supabase e ciclo issue | `docs/04-data-model.md` |
| Route, auth, dashboard, tracking | `docs/05-applicazione-web.md` |
| Email transazionali | `docs/06-email.md` |
| Limiti noti e debito tecnico | `docs/10-stato-e-debito-tecnico.md` |
| Backlog e priorità | `docs/11-next-steps.md` |

Se una modifica invalida quanto scritto lì, aggiorna il documento nello stesso
commit.

## Sezioni non ancora attive: dati dimostrativi, mai impliciti

**Regola cambiata il 1 settembre 2026.** Prima: «mai dati simulati, le sezioni
non disponibili dichiarano cosa manca». Ora: le sezioni non ancora attive
mostrano **dati dimostrativi realistici accompagnati da un banner esplicito**
(`_banner_campione` in `views.py`), perché una scatola vuota non fa capire cosa
si otterrà.

Il banner **non è opzionale**: senza, sarebbero numeri finti spacciati per veri.
Le sezioni interessate stanno in `_SEZIONI_CAMPIONE`; quando una diventa reale,
si toglie da quel dizionario e si scrive la funzione vera.

Resta invece pienamente in vigore il principio da cui la vecchia regola nasceva:
**un dato mostrato senza etichetta deve essere un dato misurato.** Dove manca
lo storico non si inventa una linea piatta — si scrive che lo storico non c'è
(vedi le sparkline della dashboard).

## Invarianti da non rompere

- **Direzione degli import**: `server.py` → `views.py` → `db.py` → `config.py`,
  con `ai_sources.py` foglia come `config.py`.
  Mai il contrario: `db.py` e `views.py` non devono importare `server.py`, o si
  crea un ciclo. Se una funzione di `views.py` ha bisogno di un dato, lo riceve
  come parametro o lo chiede a `db.py`.
- **Autorizzazione**: ogni route che accede a dati di progetto deve verificare
  `project["user_id"] == user["id"]` — la service role key bypassa le RLS.
- **Sessione**: ogni route protetta deve applicare `_apply_refresh(resp, refreshed)`,
  altrimenti la sessione scade dopo un'ora invece che dopo 30 giorni.
- **`check_id`**: rinominarli in `geo_audit.py` spezza il fingerprint delle issue e
  quindi la continuità dello storico. Serve una migrazione dedicata.
- **Cron**: `/api/cron` è una route FastAPI in `server.py`, non un file in
  `api/`. Vedi Deploy — un file `api/<altro>.py` non diventa mai una function.

## Route e template

| Route | Template |
|---|---|
| `/` | `templates/home.html` — landing marketing; `{{ULTIMI_RUN}}` iniettato da `server.py` solo se loggato |
| `/audit` | `templates/form.html` — form inserimento URL |
| `/r/{job_id}` | HTML report da Supabase + overlay iniettato via Python |
| `/miei-report` | String inline in `server.py` |

## Design System — regola fondamentale

> ⚠️ **Redesign in corso (settembre 2026).** Convivono due design system:
>
> | Foglio | Usato da | Token |
> |---|---|---|
> | `static/css/geo-ds.css` | schermate già ridisegnate | `--bg-canvas`, `--accent-primary`, `--state-good`… |
> | `static/css/design-system.css` | pagine non ancora migrate | `--canvas`, `--brand`, `--success`… |
> | `static/css/ponte-legacy.css` | ponte fra i due | rimappa i vecchi nomi sui nuovi |
>
> **Le schermate nuove si scrivono con i token di `geo-ds.css`.** Il ponte
> esiste solo per non dover riscrivere tutti i tab in un colpo solo, e va
> **eliminato** quando l'ultimo tab sarà migrato. Non aggiungerci nulla.
>
> Riferimenti del redesign, fuori dal repo:
> `Vertical AI/progetti/_specifiche-geo-audit/` — documento funzionale,
> design system e le 16 pagine HTML del prototipo (fonte di verità visiva).
>
> Il tema di default è **chiaro**; la preferenza sta in `localStorage` sulla
> chiave `geo-theme`, condivisa con il report generato.

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

**Corollario, costato un cron morto per due settimane:** l'unica function è quella FastAPI, quindi **nessun altro file in `api/` viene costruito**. `api/cron.py` esisteva e non è mai stato deployato — `GET /api/cron` finiva nel router di `server.py` e rispondeva `{"detail":"Not Found"}` a ogni invocazione di Vercel Cron. Il file è stato rimosso e il cron è ora la route `/api/cron` in `server.py`, referenziata in `vercel.json` sotto `crons`. Vale per qualsiasi endpoint futuro, cron o webhook che sia: **route FastAPI in `server.py`**.
