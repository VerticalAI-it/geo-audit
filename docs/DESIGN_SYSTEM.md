# GEO Audit · Design System

Documento di architettura del frontend e delle email.
Fonte di verità visiva: `docs/design-system/ds.html` e i quattro template email in `docs/design-system/`.

---

## Architettura del frontend

### Stack e rendering

| Layer | Tecnologia | Note |
|---|---|---|
| Backend | Python · FastAPI | `server.py` (app principale) + `api/cron.py` (worker cron) |
| Rendering HTML | Template statici + string injection | Non c'è un motore di template (no Jinja2). Le pagine sono file `.html` in `templates/` caricati a memoria, con sostituzioni via `.replace()` per i report. |
| CSS | Inline `<style>` + `/static/css/design-system.css` | Il file CSS condiviso è la fonte unica dei token. Le pagine di prodotto lo linkano via `<link>`. I report generati da `geo_audit.py` possono avere stili inline propri — non toccarli. |
| JavaScript | Vanilla JS inline | Nessun framework. Script minimi per form, gate e stato di scansione. |
| Deploy | Vercel (serverless) + Docker (container) | Vercel route tutto a `/api/index`; FastAPI serve `/static/*` direttamente. |

### Route e template

| Route | Metodo | Template / risposta | Note |
|---|---|---|---|
| `/` | GET | `templates/home.html` | Landing marketing |
| `/audit` | GET | `templates/form.html` | Form inserimento URL |
| `/scan` | POST | Redirect a `/r/{id}` | Esegue audit, salva su Supabase |
| `/r/{job_id}` | GET | HTML report da Supabase + overlay iniettato | Gate (blur) se non autenticato, barra azioni se sbloccato |
| `/unlock/{job_id}` | POST | HTTP 200 | Salva email, invia "report pronto" |
| `/miei-report` | GET | String inline (`_MIEI_REPORT_PAGE`) | Form recupero link |
| `/miei-report` | POST | String inline (`_MIEI_REPORT_SENT`) | Invia email con lista report |
| `/contact/{job_id}` | POST | HTTP 200 | Salva richiesta contatto, notifica interna |
| `/health` | GET | JSON | Health check |

### CSS: token e integrazione

Il file `static/css/design-system.css` contiene:
- Design token (`:root` light + `[data-theme="dark"]`)
- Reset / base
- Componenti: `.btn`, `.input`, `.field`, `.badge`, `.card`, `.alert`, `.tabs`, `.tbl`, `.gauge`, `.eyebrow`, `.spin`, `.hist-row`
- Responsive per tabelle e gauge

**Mappatura token vecchi → nuovi:**

| Vecchio (repo) | Nuovo (DS) | Valore dark |
|---|---|---|
| `--bg:#0B0B16` | `--canvas` | `#0B0A12` |
| `--card:#17152A` | `--surface` | `#131220` |
| `--line:#2A2640` | `--border` | `#272636` |
| `--violet:#6C5CE7` | `--brand` | `#7C6BEC` |
| `--vbright:#9B8CFF` | `--brand-text` / `--brand-hover` | `#B3A8F7` |
| `--text:#F2F1F8` | `--text` / `--ink` | `#F4F3F8` |
| `--muted:#9C99B5` | `--text-2` | `#BCBBCB` |

**Font stack:**

| Ruolo | Vecchio | Nuovo |
|---|---|---|
| Display / titoli | Archivo | Space Grotesk |
| Body / UI | Hanken Grotesk | Inter |
| Mono / dati | IBM Plex Mono | JetBrains Mono |

**Soglie score colore:**

| Range | Label | Colore |
|---|---|---|
| 75–100 | Ottimo | `--success` (#0E9F6E light / #3DDC97 dark) |
| 50–74 | Migliorabile | `--warning` (#C77700 light / #F5BE57 dark) |
| 0–49 | Critico | `--danger` (#D92D34 light / #FF6B70 dark) |

---

## Architettura email

Tutte le email sono inviate tramite **Resend** (API REST). Le funzioni di invio sono in `server.py` e `api/cron.py`.

### Inventario email

| Email | Funzione | Trigger | Stato |
|---|---|---|---|
| Report pronto (sblocco da gate) | `_send_unlock_email()` in `server.py` | POST `/unlock/{job_id}` | ✅ Aggiornata al nuovo template |
| Report pronto (cron async) | `_send_report_email()` in `api/cron.py` | Cron job al completamento audit | ✅ Aggiornata al nuovo template |
| Conferma audit ricevuto | `_send_conferma_audit()` in `api/cron.py` | Presa in carico job pending — TODO: aggancia al momento del claim (vedi sotto) | ✅ Funzione pronta |
| I miei report | `_send_my_reports_email()` in `server.py` | POST `/miei-report` | ✅ Aggiornata al nuovo template |
| Notifica contatto (interna) | `_send_contact_notif()` in `server.py` | POST `/contact/{job_id}` | ✅ Aggiornata al nuovo template |
| Analisi completa (follow-up) | `_send_analisi_completa()` in `server.py` | TODO: trigger di follow-up non implementato | ✅ Funzione pronta |
| Report mensile / monitoraggio | `_send_report_mensile()` in `server.py` | TODO: scheduler non implementato | ✅ Funzione pronta |

### TODO residui email

1. **`_send_conferma_audit`**: la funzione esiste in `api/cron.py`. Va chiamata subito dopo il claim atomico del job (riga ~120 di `cron.py`, dopo `claim.data`), prima di avviare l'audit. Questo garantisce che l'utente sappia che il lavoro è iniziato.

2. **`_send_analisi_completa`**: la funzione esiste in `server.py`. Decidere il trigger: subito dopo il report (es. X ore dopo `_send_unlock_email`), o su azione esplicita del team. Al momento è solo esposta come helper — il wiring va fatto nella logica di business.

3. **`_send_report_mensile`**: funzione pronta in `server.py`. Richiede uno scheduler (es. Vercel Cron, cron.py dedicato) che la invochi una volta al mese per ogni email con report attivi. I dati necessari (storico mensile, delta score) devono venire da una query a Supabase.

---

## PR aperte e ordine di merge consigliato

| # | Branch | Titolo | Dipendenze | Stato |
|---|---|---|---|---|
| 1 | `feat/ds-tokens-and-docs` | Design tokens CSS + docs | nessuna | Aperta |
| 2 | `feat/ds-frontend` | Refactor frontend templates | PR #1 (CSS file) | Aperta |
| 3 | `feat/ds-emails` | Redesign template email | nessuna | Aperta |

**Ordine di merge consigliato:** PR1 → PR2 → PR3 (PR3 è indipendente, può entrare in qualsiasi momento).

Nota: PR2 dipende da `/static/css/design-system.css` creato in PR1. Fare il merge di PR1 prima garantisce che le pagine linkino correttamente il CSS.
