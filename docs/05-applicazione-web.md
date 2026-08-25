# 05 · Applicazione web (`server.py`)

2588 righe che contengono l'intera app: route, accesso ai dati, autenticazione,
generazione email e costruzione HTML di dashboard e tab.

---

## Tutte le route

### Pubbliche

| Route | Metodo | Risposta | Auth |
|---|---|---|---|
| `/` | GET | `templates/home.html` — landing marketing, + riquadro «Ultimi run» se loggato | — ¹ |
| `/privacy` | GET | `templates/privacy.html` | — |
| `/cookie-policy` | GET | `templates/cookie.html` | — |
| `/roadmap` | GET | `templates/roadmap.html` — roadmap pubblica | — |
| `/robots.txt` | GET | `text/plain` generato | — |
| `/sitemap.xml` | GET | `application/xml` generato | — |
| `/llms.txt` | GET | `text/plain` generato | — |

¹ `/` è pubblica, ma legge la sessione se c'è: a utente loggato inietta in fondo
il riquadro **Ultimi run** al posto del placeholder `{{ULTIMI_RUN}}`, a visitatore
anonimo lo sostituisce con stringa vuota e la landing resta identica a prima.
Essendo una route che legge la sessione applica `_apply_refresh`.

**Il riquadro non può far fallire la home.** `_ultimi_run_section()` cattura
qualunque eccezione e ritorna stringa vuota: la landing è la pagina più esposta
del sito e non deve dipendere dalla disponibilità di Supabase per rendersi.

Mostra gli ultimi 10 run dell'utente — data e ora in fuso italiano, origine
(manuale o automatico), sito, punteggio — filtrati per `user_id`, che è
l'autorizzazione: la service role key bypassa le RLS. Sotto la tabella una riga
dice quando è avvenuto l'ultimo audit automatico, che è l'informazione per cui il
riquadro esiste.
| `/health` | GET | `{"status": "ok"}` | — |
| `/t` | POST | 204 sempre | — (endpoint pubblico di ingestion) |
| `/richiedi-audit` | POST | Richiesta audit dalla landing | — |
| `/miei-report` | GET/POST | Recupero link report via email (legacy) | — |
| `/unlock/{job_id}` | POST | Sblocco gate email (legacy) | — |
| `/contact/{job_id}` | POST | Richiesta di contatto dal report | — |

### Autenticazione

| Route | Metodo | Cosa fa |
|---|---|---|
| `/login` | GET | Form magic link; se già loggato redirige a `next` |
| `/auth/callback` | GET | Pagina che estrae i token dal fragment dell'URL |
| `/auth/set-session` | POST | Scambia i token con i cookie HttpOnly server-side |
| `/auth/logout` | GET | Cancella i cookie, redirige a `/` |

### Protette (richiedono login)

| Route | Metodo | Cosa fa |
|---|---|---|
| `/audit` | GET | Form di inserimento URL |
| `/scan` | POST | Esegue l'audit, salva, redirige al report |
| `/r/{job_id}` | GET | Report HTML (regime doppio, vedi sotto) |
| `/dashboard` | GET | Portfolio progetti |
| `/project/{project_id}` | GET | Dettaglio progetto — `?tab=` seleziona la sezione |
| `/project/{project_id}/settings` | POST | Nome, settore, cadenza di scansione |
| `/project/{project_id}/rerun` | POST | Rifà l'audit manualmente |

Le route protette redirigono a `/login?next=<destinazione>` quando manca la
sessione.

---

## Autenticazione: magic link con sessione server-side

Nessuna password. Supabase Auth manda un magic link via email; il flusso poi
sposta la sessione **dal client ai cookie HttpOnly**:

```
1. /login                → il JS chiama supabase.auth.signInWithOtp()
                           redirect_to = {SITE_URL}/auth/callback   (senza query string)

2. l'utente clicca il link nell'email
                           → atterra su /auth/callback#access_token=…&refresh_token=…

3. /auth/callback        → il JS legge il fragment e fa
                           POST /auth/set-session {access_token, refresh_token, next}

4. /auth/set-session     → valida il token contro Supabase (GET /auth/v1/user)
                           → set-cookie sb-access-token  (HttpOnly, Secure, SameSite=Lax, 30gg)
                           → set-cookie sb-refresh-token (idem)
                           → risponde {"redirect": next}

5. il JS naviga a next
```

**Perché passare per il server invece di tenere la sessione in `localStorage`:**
i cookie `HttpOnly` non sono leggibili da JavaScript, quindi un XSS non può
esfiltrare la sessione. In cambio serve il passaggio 3-4, che è il prezzo da
pagare.

Il `redirect_to` è deliberatamente **senza query string** (commit `4b3e0e1`):
Supabase valida la URL di redirect contro una whitelist e i parametri la facevano
fallire. La destinazione post-login viaggia quindi in un altro canale.

### Refresh trasparente

`_current_user()` ([server.py:345](../server.py#L345)) ritorna una **tupla**
`(user, refreshed_tokens)`:

```python
def _current_user(request) -> tuple[dict | None, dict | None]:
    access = request.cookies.get("sb-access-token", "")
    if access:
        user = _sb_auth_user(access)
        if user:
            return user, None            # token ancora valido

    refresh = request.cookies.get("sb-refresh-token", "")
    ...                                   # rinnova e ritorna i nuovi token
```

Il secondo elemento va **applicato esplicitamente** alla risposta:

```python
user, refreshed = _current_user(request)
...
return _apply_refresh(resp, refreshed)
```

> ⚠️ **Questo è il tranello più facile in cui cadere su questo codice.** I cookie
> impostati su un oggetto `Response` iniettato via dependency injection non
> sopravvivono se la route ritorna un `Response` diverso. Perciò il refresh non
> può essere automatico e va applicato a mano. **Se dimentichi `_apply_refresh`,
> la sessione scade dopo un'ora invece che dopo 30 giorni** — un bug che si
> manifesta solo dopo un'ora, quindi difficile da vedere in sviluppo.
>
> Ogni nuova route protetta deve seguire il pattern.

---

## Il doppio regime dei report

`GET /r/{job_id}` ([server.py:1039](../server.py#L1039)) si comporta in due modi a
seconda che l'audit sia legato a un account:

```
GET /r/{job_id}[?token=…]
 │
 ├─ token valido in query string?
 │     └─ set-cookie geo-access-{job_id} (90gg) → 303 verso /r/{job_id} pulito
 │
 ├─ audit non trovato / senza html → 404
 │
 ├─ job.user_id VALORIZZATO  ← regime attuale
 │     ├─ non loggato o utente ≠ proprietario → 303 /login?next=/r/{job_id}
 │     └─ report + barra azioni + link alla dashboard
 │
 └─ job.user_id NULL         ← regime legacy anonimo
       ├─ cookie geo-access valido → report + barra azioni
       └─ altrimenti            → report OSCURATO + gate email
```

**Il regime legacy non è più raggiungibile per i nuovi audit**: `/scan` richiede
il login e valorizza sempre `user_id`. Resta attivo solo per i report generati
prima dell'introduzione degli account.

### Il token HMAC

```python
def _make_token(job_id: str) -> str:
    return hmac.new(_SECRET, job_id.encode(), hashlib.sha256).hexdigest()
```

Deterministico: **non serve salvarlo nel database**, si ricalcola da `job_id` +
`CRON_SECRET`. Verificato con `hmac.compare_digest` (confronto a tempo costante).

> **Nota di sicurezza.** `POST /unlock/{job_id}` non verifica la proprietà del
> report: chiunque conosca un `job_id` può farsi mandare l'email di sblocco con
> il token. Nella pratica il `job_id` è un UUID v4 non enumerabile, e soprattutto
> **il token non bypassa il controllo di proprietà**: su un report con `user_id`
> valorizzato il cookie di accesso non basta, serve comunque il login come
> proprietario. L'esposizione è quindi limitata ai report legacy anonimi.

### Overlay iniettati

Il report è HTML già generato e salvato: l'app ci **inietta** sopra gli overlay
invece di rigenerarlo.

| Funzione | Cosa inietta |
|---|---|
| `_inject_bar()` [server.py:673](../server.py#L673) | Barra azioni: email, link dashboard, nuova analisi |
| `_inject_gate()` [server.py:708](../server.py#L708) | Blur + modale di richiesta email (legacy) |
| `_with_topbar()` [server.py:788](../server.py#L788) | Topbar con email utente e logout sulle pagine di prodotto |

---

## Dashboard (`/dashboard`)

Per ogni progetto dell'utente costruisce una card
([server.py:1107](../server.py#L1107)):

```python
{"id", "name", "domain", "overall", "grade", "delta", "critical_count",
 "pages_count", "last_scan", "status", "tracking", "tracking_active"}
```

Le card vengono serializzate in JSON e passate a `templates/dashboard.html`, che
fa il **rendering lato client** — così ricerca e filtri non richiedono round-trip.

### Stato del progetto

`_project_status()` ([server.py:1071](../server.py#L1071)) — calcolato, mai
persistito, valutato in quest'ordine:

| Condizione | Stato |
|---|---|
| Nessun audit o `overall` NULL | `Audit required` |
| Ultimo audit più vecchio di **30 giorni** | `Audit required` |
| `critical_count > 0` | `Critical` |
| `overall < 50` | `Critical` |
| `overall < 75` | `Needs attention` |
| altrimenti | `Healthy` |

Nessuno stato scritto a mano significa nessuna possibilità di disallineamento fra
stato mostrato e dati reali.

### Backfill dei progetti

`_backfill_projects()` ([server.py:1093](../server.py#L1093)) gira ad **ogni**
caricamento della dashboard: aggancia a un progetto le righe `audits` create prima
che il modello project esistesse, raggruppandole per dominio. È idempotente — una
volta agganciate tutte, la query di orfani ritorna vuota e la funzione esce
subito.

È una migrazione dati eseguita a runtime invece che con uno script una tantum:
funziona anche se un utente dormiente torna fra sei mesi.

---

## I 12 tab di progetto

`GET /project/{id}?tab=…`. Definizione in `_TAB_CATEGORIES`
([server.py:1156](../server.py#L1156)): 5 categorie di primo livello, i tab veri
come sotto-livello.

| Categoria | Tab | Stato | Fonte dati |
|---|---|---|---|
| **Overview** | *(nessun figlio)* | ✅ | Ultimi 2 audit + storico + issue |
| **Audit** | Riepilogo | ✅ | `audits` |
| | Pages | ✅ | `audits.pages_detail` |
| | Technical GEO | ✅ | `audits.site_checks` + aggregazione per pagina |
| | Opportunities | ✅ | `issue` |
| **AI Intelligence** | AI Visibility | 🔒 soon | — |
| | Prompts & Queries | 🔒 soon | — |
| | Competitors | 🔒 soon | — |
| | Citations | 🔒 soon | — |
| **Traffic & Reports** | AI Traffic | ✅ *(se lo snippet è installato)* | `tracking_event` |
| | Reports | 🔒 soon | — |
| **Settings** | *(nessun figlio)* | ✅ | `project` |

Una categoria in cui **tutti** i figli sono "coming soon" viene marcata `soon` già
nel menu di primo livello (`AI Intelligence`), così l'utente non ci clicca dentro
per scoprirlo dopo.

I tab "coming soon" rendono `_coming_soon_tab()` con una **spiegazione esplicita
di cosa manca** — non un placeholder generico:

> *"Richiede un panel di monitoraggio prompt sui provider AI (ChatGPT, Gemini,
> Perplexity). Non ancora configurato per questo progetto."*

**Nessun tab mostra mai dati simulati.** È una regola di prodotto esplicita.

### Overview

`_tab_overview()` ([server.py:1566](../server.py#L1566)) contiene:

- Punteggio corrente con **pill di delta** rispetto all'audit precedente
- Grafico storico interattivo (vedi sotto)
- Mini-stat colorati: issue aperte, risolte di recente, pagine, critici
- Griglia di riepilogo con una card per sezione — numero in evidenza + link al
  dettaglio, o blocco "coming soon" esplicito per quelle non disponibili

### Grafico storico del punteggio

`_score_history_chart()` ([server.py:1511](../server.py#L1511)) — l'ultima feature
aggiunta (commit `b29a35d`).

Il server serializza i punti `[{t, s}]` in JSON e li passa a un blocco JS inline:
**il rendering SVG e i filtri (3 mesi / 6 mesi / tutto) sono lato client**, così
cambiare intervallo non richiede una richiesta al server.

Tre stati distinti:

| Punti | Resa |
|---|---|
| 0 | Card "Ancora nessun punteggio registrato" |
| 1 | Punteggio grande + "servono almeno due audit per costruire uno storico" |
| ≥ 2 | Grafico con tooltip, filtri di intervallo, punteggio corrente colorato |

### Technical GEO

`_tab_technical()` ([server.py:1725](../server.py#L1725)) mette insieme due
prospettive:

- **Accesso e infrastruttura**: i check `crawl.*` a livello di sito, più
  `meta.canonical` e `render.parity` **aggregati** su tutte le pagine
  (`_aggregate_page_check`, con conteggio "N/M pagine OK")
- **Dati strutturati ed entity signals**: `sd.*`, `trust.*`, `sem.html`
  aggregati per pagina

L'aggregazione è ciò che rende leggibile un check che esiste su 6 pagine: invece
di 6 righe, una riga con "4/6 pagine OK".

### Opportunities

`_tab_opportunities()` legge dalla tabella `issue`, non dall'ultimo audit. È
quello che permette di mostrare **"prima vista"** e **"ultima vista"** per ogni
criticità, e una sezione separata delle risolte di recente.

### AI Traffic

`_tab_traffic()` ([server.py:1805](../server.py#L1805)) legge fino a 5000 eventi
degli ultimi 30 giorni e **aggrega in Python**, non in SQL.

La sessione è l'unità di misura: gli eventi vengono raggruppati per `session_id` e
una sessione è "da AI" se **almeno uno** dei suoi eventi ha `ai_source`
valorizzato. La landing page è quella dell'evento più vecchio della sessione.

Metriche mostrate:

| Metrica | Definizione |
|---|---|
| Sessioni (30gg) | Numero di `session_id` distinti |
| Sessioni da AI | Sessioni con almeno un evento con `ai_source` |
| Quota AI | Rapporto fra le due |
| Per provider | Sessioni AI raggruppate per `ai_source` |
| Landing page da AI | Top 10 pagine di ingresso delle sessioni AI |
| Andamento | **Eventi** AI per giorno, ultimi 14 giorni |

> Nota: l'andamento conta **eventi**, non sessioni, a differenza delle metriche
> sopra. La colonna è etichettata "Eventi AI" e quindi non è ingannevole, ma è una
> discontinuità da tenere presente quando si confrontano i numeri.

Quando non c'è nessun evento, il tab mostra lo snippet da installare invece di una
tabella vuota.

> **Limite noto:** l'aggregazione a 5000 eventi in Python non scala. Su un sito
> con traffico significativo la tab diventerà lenta e il tetto troncherà i dati
> senza avvisare. Va spostata in SQL (viste materializzate o aggregazione
> giornaliera) prima di venderla a un cliente con volumi reali.

### Settings

Nome, settore, cadenza di scansione (giornaliera/settimanale/mensile), stato di
installazione del tracking e snippet pronto da copiare.

Cambiare la cadenza ricalcola `next_scan_at` **solo se la frequenza è
effettivamente cambiata** ([server.py:2018](../server.py#L2018)): salvare le
impostazioni senza toccare la frequenza non rimanda l'audit già schedulato.

Lo stato di installazione è rilevato da `_sb_has_tracking()`, che verifica
l'esistenza di **almeno un evento**. Non c'è un ping di verifica dedicato: finché
non arriva la prima visita, lo stato resta "not installed" anche se lo snippet è
già stato incollato correttamente.

---

## Tracking first-party

### Lo snippet

[static/js/geo-track.js](../static/js/geo-track.js) — ~1.5 KB, IIFE, nessuna
dipendenza.

```html
<script src="https://tuo-dominio/static/js/geo-track.js"
        data-project="{project_id}" async></script>
```

Eventi custom: `window.geoTrack("nome_evento", {chiave: "valore"})`.

Scelte progettuali, tutte orientate a **non rompere il sito del cliente**:

| Scelta | Perché |
|---|---|
| `navigator.sendBeacon` | Non blocca l'unload della pagina; fallback su `fetch` con `keepalive` |
| `sessionStorage` per il session id | Nessun cookie → nessun consenso cookie richiesto per il funzionamento base |
| Endpoint derivato da `script.src` | Lo snippet funziona su qualsiasi dominio senza configurazione |
| `try/catch` su tutto | `sessionStorage` può lanciare in modalità privata |
| Esce subito se manca `data-project` | Nessun rumore, nessun errore in console |

### L'endpoint

`POST /t` ([server.py:933](../server.py#L933)):

- **Nessuna autenticazione** — gira su domini di terzi
- Validazione minima: senza `pid` esce, e basta
- Troncamento difensivo: `event` 64 char, `url`/`ref` 2048, `sid` 128
- `_detect_ai_source()` mappa l'host del referrer sul provider
- Timeout Supabase a **5 secondi** (più corto degli altri, che sono a 10)
- **Ritorna 204 in ogni caso**, anche in errore

Non c'è rate limiting. Limite noto ([04 · Modello
dati](04-data-model.md#tracking_event)).

---

## Altre route

### `POST /richiedi-audit`

Form della landing: raccoglie nome, email, sito. Manda due email — una notifica
interna al team e una conferma all'utente. Non lancia un audit: è pura lead
generation.

### `GET/POST /miei-report`

Flusso legacy: l'utente inserisce l'email e riceve la lista dei report generati
con quell'indirizzo, cercati su `pending_email`. Le due pagine sono **stringhe
inline** in `server.py` (`_MIEI_REPORT_PAGE`, `_MIEI_REPORT_SENT`), non file in
`templates/`.

Con il login obbligatorio questo flusso è **superato dalla dashboard** — resta per
gli utenti che hanno ricevuto un vecchio link.

### `POST /contact/{job_id}`

Dal CTA in coda al report: salva su `contact_requests` e notifica il team.

### `/robots.txt`, `/sitemap.xml`, `/llms.txt`

Generati come endpoint FastAPI ([server.py:891-925](../server.py#L891-L925)), non
come file statici. **Deve restare così**: aggiungerli come rewrite in
`vercel.json` romperebbe il routing nativo
([02 · Architettura](02-architettura.md#la-configurazione-minima-è-deliberata)).

La sitemap elenca solo le pagine pubbliche (`_SITEMAP_PATHS`): `/`, `/roadmap`,
`/privacy`, `/cookie-policy`. `/audit` e le pagine di prodotto sono escluse perché
richiedono login.

`llms.txt` è la nostra stessa raccomandazione applicata a noi: descrive il
prodotto in linguaggio naturale per gli assistenti AI che leggono il sito.
