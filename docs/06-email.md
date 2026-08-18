# 06 · Email transazionali

Tutte le email passano da **Resend** (API REST, nessun SDK: `POST
https://api.resend.com/emails` con `requests`).

Mittente: `FROM_EMAIL` (dominio verificato su Resend).
Notifiche interne: `geo@verticalai.it`, `info@verticalai.it`
(`_NOTIFY_TO`, [server.py:380](../server.py#L380)).

---

## Inventario

| Email | Funzione | File | Trigger | Stato |
|---|---|---|---|---|
| Report pronto (sblocco) | `_send_unlock_email()` | [server.py:560](../server.py#L560) | `POST /unlock/{job_id}` | ✅ attiva |
| Report pronto (async) | `_send_report_email()` | [api/cron.py:134](../api/cron.py#L134) | Cron, a completamento job | ⚠️ attiva ma irraggiungibile ¹ |
| I miei report | `_send_my_reports_email()` | [server.py:2206](../server.py#L2206) | `POST /miei-report` | ✅ attiva |
| Notifica contatto (interna) | `_send_contact_notif()` | [server.py:484](../server.py#L484) | `POST /contact/{job_id}` | ✅ attiva |
| Richiesta audit — team | `_send_report_request_admin()` | [server.py:2491](../server.py#L2491) | `POST /richiedi-audit` | ✅ attiva |
| Richiesta audit — utente | `_send_report_request_user()` | [server.py:2521](../server.py#L2521) | `POST /richiedi-audit` | ✅ attiva |
| Conferma audit ricevuto | `_send_conferma_audit()` | [api/cron.py:227](../api/cron.py#L227) | **nessuno** | 🔌 orfana |
| Analisi completa (follow-up) | `_send_analisi_completa()` | [server.py:2289](../server.py#L2289) | **nessuno** | 🔌 orfana |
| Report mensile / monitoraggio | `_send_report_mensile()` | [server.py:2346](../server.py#L2346) | **nessuno** | 🔌 orfana |

¹ Vive dentro `_process_next_job()`, che consuma la coda `audits status='pending'`
— coda in cui nessuno inserisce più nulla ([doc 10](10-stato-e-debito-tecnico.md#la-coda-pending-è-vestigiale)).

**Cinque email realmente in funzione, quattro no**: tre non hanno un trigger e una
(`_send_report_email`) ne ha uno che non scatta più. Sono tutte lavoro già fatto:
manca solo il wiring, che è più una decisione di prodotto che un problema tecnico.

---

## Le tre email orfane

### `_send_conferma_audit` — la più semplice da agganciare

Comunica "abbiamo preso in carico la tua richiesta". La funzione è in `cron.py`,
va chiamata **subito dopo il claim atomico del job**, prima di avviare l'audit.

Ha senso però solo se esiste un flusso asincrono in cui l'utente aspetta. Oggi
`/scan` è sincrono: l'utente vede il report dopo 30-60 secondi, quindi una mail di
conferma sarebbe rumore. **Diventa utile solo se si reintroduce la coda
asincrona** ([11 · Next steps](11-next-steps.md)).

### `_send_analisi_completa` — richiede una decisione di prodotto

Follow-up commerciale dopo il report gratuito. Va deciso il trigger:

| Opzione | Implicazione |
|---|---|
| N ore dopo l'invio del report | Serve uno scheduler o una colonna `followup_sent_at` |
| Su azione esplicita del team | Serve un'interfaccia interna (non esiste) |

### `_send_report_mensile` — richiede uno scheduler

Report periodico con storico e delta di punteggio. Serve:

1. un job schedulato mensile (il cron esiste già, andrebbe esteso)
2. una query che ricostruisca storico e delta per progetto — **i dati ci sono
   già** in `audits` e nel grafico storico dell'Overview

È la più vicina a essere realizzabile in termini di dati, la più lontana in
termini di infrastruttura di scheduling.

---

## Struttura dei template

Le email sono **HTML costruito in Python** con f-string, tabelle annidate e stili
inline — il pattern classico per la compatibilità con i client di posta.

Componenti condivisi, duplicati sia in `server.py` che in `api/cron.py`:

| Componente | Cosa fa |
|---|---|
| `_EMAIL_HEAD` | Meta, `color-scheme`, fix MSO, media query mobile e dark mode |
| `_EMAIL_FONTS` | Space Grotesk · Inter · JetBrains Mono da Google Fonts |
| `_email_logo_row()` | Header con logo Vertical AI + etichetta di sezione |
| `_email_footer()` | Footer con tagline e link preferenze/disiscrizione |
| `_score_band()` | `(label, background, colore)` per la banda di punteggio |

Accorgimenti presenti:

- `<!--[if mso]>` con `PixelsPerInch` per Outlook
- `@media (prefers-color-scheme: dark)` con classi `.bg-canvas` / `.t-ink` / `.brd`
  e `!important` (i client sovrascrivono aggressivamente)
- Breakpoint a 600px: `.stack` diventa full-width, i bottoni diventano block
- `role="presentation"` sulle tabelle di layout (accessibilità)

I template email di riferimento visivo sono in
[`design_system/ds_components/`](../design_system/ds_components/): `email-report-pronto.html`,
`email-conferma-audit.html`, `email-analisi-completa.html`,
`email-report-mensile.html`, `email-kit.html`.

> ⚠️ Quei file sono **la fonte di verità visiva, non il codice eseguito**. Il codice
> che invia davvero è nelle funzioni `_send_*`. Modificare un template in
> `design_system/` non cambia nulla in produzione finché non si riporta la modifica
> nella funzione corrispondente.

---

## Soglie di punteggio nelle email

`_score_band()` ([server.py:466](../server.py#L466), duplicata in
[api/cron.py:115](../api/cron.py#L115)):

| Punteggio | Label | Sfondo | Colore |
|---|---:|---|---|
| ≥ 75 | Ottimo | `#E7F8F0` | `#0E9F6E` |
| ≥ 50 | Buona, migliorabile | `#FCF3E3` | `#9a5b00` |
| < 50 | Critico | `#FCEBEC` | `#D92D34` |

Allineate al design system. I colori sono **hardcoded**: le email non possono
usare le variabili CSS, i client di posta non le supportano in modo affidabile.

> Conseguenza: **cambiare un token in `design-system.css` non aggiorna le email.**
> Vanno modificate a mano, in due file.

---

## Gestione degli errori

Tutte le chiamate di invio sono avvolte in `try/except: pass`:

```python
try:
    _send_unlock_email(email, job_id, domain, overall, grade)
except Exception:
    pass
```

**È deliberato**: un'email che non parte non deve far fallire la richiesta
dell'utente, che ha comunque ottenuto il suo report.

> ⚠️ Il rovescio della medaglia: **le email che falliscono spariscono senza
> traccia**. Nessun log, nessuna metrica, nessun retry. Non c'è modo di sapere
> quante notifiche di contatto si sono perse. Aggiungere almeno un `print()`
> nell'`except` è un intervento di 5 minuti con un ritorno alto
> ([11 · Next steps](11-next-steps.md)).

Se `RESEND_KEY` o `FROM_EMAIL` non sono configurate, `_resend_post()`
([server.py:475](../server.py#L475)) esce subito senza errore: in sviluppo locale
l'app funziona senza credenziali email.

---

## Duplicazione fra `server.py` e `api/cron.py`

Header, footer, logo, `_score_band`, `_EMAIL_HEAD` esistono **in entrambi i file**,
identici. La ragione è strutturale: sono due Vercel Function separate e `cron.py`
non importa `server.py` (importerebbe l'intera app FastAPI e tutte le sue
variabili d'ambiente obbligatorie).

**Ogni modifica al layout email va replicata in due posti.** Estrarre un
`email_kit.py` condiviso — importabile da entrambi senza tirarsi dietro FastAPI —
è un intervento pulito e a basso rischio ([11 · Next steps](11-next-steps.md)).
