# 05 · Applicazione web (`server.py`)

Route, autenticazione, email e cron. Da settembre 2026 l'app è divisa in quattro
moduli: `config.py` (variabili d'ambiente), `db.py` (accesso Supabase),
`views.py` (costruzione HTML di dashboard e tab) e `server.py`, che li mette
insieme. I riferimenti a `server.py:NNN` in questo documento precedono la
separazione: la funzione citata esiste ancora con lo stesso nome, ma può trovarsi
in `db.py` (se inizia per `_sb_`) o in `views.py` (se costruisce HTML).

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
| `/auth/richiedi-link` | POST | Decide se il magic link parte: e' qui il controllo accessi |
| `/richiedi-accesso` | GET/POST | Form lead + avvio dell'audit preliminare |
| `/richiesta-ricevuta` | GET | Conferma al lead |
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
| `/project/{project_id}/issue/{issue_id}/resolve` | POST | Chiude a mano una criticità (settembre 2026) |
| `/preferenze/tema` | POST | Salva il tema sul profilo, così segue l'utente (settembre 2026) |

Le route protette redirigono a `/login?next=<destinazione>` quando manca la
sessione. `/preferenze/tema` e la chiusura manuale rispondono invece **401**:
sono chiamate da JavaScript, e un redirect al login non servirebbe a nulla.

### Roadmap pubblica (settembre 2026)

| Route | Metodo | Cosa fa | Auth |
|---|---|---|---|
| `/roadmap` | GET | Pagina pubblica: funzionalità disponibili, in arrivo e voti | — |
| `/roadmap/voto` | POST | Registra un «mi interessa» | — |
| `/roadmap/avvisami` | POST | Raccoglie chi vuole essere avvisato | — |

Sono **endpoint pubblici**, come richiede una roadmap che chiunque deve poter
votare. Valgono quindi le stesse cautele di `/t`: campi troncati, nessuna
fiducia nell'input, e la consapevolezza che **non c'è rate limiting**.

L'anti-voto-multiplo è un identificativo casuale generato dal browser, più il
rifiuto lato server del secondo voto dello stesso votante sulla stessa voce.
È una barriera **debole per costruzione**: serve a misurare l'interesse, non a
garantire l'unicità del voto. Se un domani quei numeri dovessero contare, il
punto dove aggiungere un limite per IP è segnato in `server.py`.

---

## Chi può entrare

> **L'invariante, e sta scritta in un posto solo: essere in `auth.users` **è**
> essere approvati.** Non esiste un secondo stato da tenere allineato — chi ha un
> account entra, chi non ce l'ha è un lead. Ne discende che la migrazione degli
> utenti esistenti **non serve**: chi c'è oggi è approvato per costruzione.

Fino al 3 settembre 2026 entrava chiunque, e il motivo stava in una riga di
`templates/login.html`: il browser chiamava Supabase per conto suo con
`signInWithOtp(..., shouldCreateUser: true)`, quindi **ogni email inserita si
creava l'account da sola** e riceveva il link.

Ora la pagina chiede al server (`POST /auth/richiedi-link`), che decide:

| Caso | Cosa succede |
|---|---|
| l'email ha un account | si genera il link e si spedisce **con Resend** |
| l'email non ha un account | **nessuna mail**, si va a `/richiedi-accesso` con l'email già scritta |

⚠️ **Il controllo sta sul server perché in una pagina non sarebbe un
controllo:** la chiave pubblica di Supabase è visibile a chiunque apra il
sorgente. Per questo la difesa non è una sola:

1. il nostro flusso non chiama più Supabase dal browser;
2. `_sb_auth_magiclink()` **verifica l'esistenza dell'account al proprio
   interno**, non si fida di chi la chiama.

⚠️⚠️ **`generate_link` con `type=magiclink` CREA l'account se non esiste.** Non
fallisce: risponde 200 e restituisce un link valido. Verificato il 03/09/2026 —
una chiamata con un indirizzo inventato ha creato l'utente. È il motivo per cui
il controllo è dentro la funzione: una difesa che dipende dal fatto che tutti si
ricordino di controllare prima, prima o poi cede.

### Il link lo spediamo noi, non Supabase

`_sb_auth_magiclink()` usa l'**admin API** per *generare* il link, e la mail
parte con Resend. Due motivi, e il secondo è quello che risolve un problema
aperto: la posta predefinita di Supabase **non consegna** — la chiamata risponde
200 e la mail non arriva mai, ed è per questo che il login non funzionava. Così
non serve più configurare l'SMTP nel pannello Supabase.

⚠️ `redirect_to` va al **primo livello** del corpo JSON: dentro `options` viene
ignorato in silenzio e il link porta all'indirizzo predefinito del progetto
invece che a `/auth/callback`.

### Chi non ha un account: il lead

`/richiedi-accesso` raccoglie email, telefono (facoltativo) e **sito da
analizzare**. Al salvataggio:

1. la richiesta finisce in `contact_requests` (vedi [04 · Modello
   dati](04-data-model.md#contact_requests));
2. **parte davvero un audit preliminare** sul sito indicato — con lo stesso
   motore dei clienti attivi, in `BackgroundTasks` per non far aspettare chi ha
   compilato, e con `source = 'lead'`. Non è una frase di cortesia: la schermata
   promette che l'analisi è già partita, e deve essere vero;
3. il team riceve la notifica via email;
4. quando l'audit finisce, punteggio e `audit_id` si agganciano alla richiesta —
   così chi richiama ha già i numeri in mano.

L'URL scritto da una persona viene normalizzato (`_normalizza_sito`): senza,
metà degli audit partirebbe su indirizzi che non rispondono.

**Chi approva un lead** lo fa creando l'account (`_sb_auth_create_user`,
verificato: la service role può). L'Admin Dashboard è la schermata che lo farà;
finché non c'è, si fa da script.

---

## Autenticazione: magic link con sessione server-side

Nessuna password. Il magic link porta la sessione **dal client ai cookie
HttpOnly**:

```
1. /login                → POST /auth/richiedi-link → il server genera e spedisce
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
| | Reports | ✅ | `audits` + `issue` + `tracking_event` |

**Reports** era una sezione dimostrativa, ed è diventata reale il 2 settembre
2026: ogni numero del digest d'esempio — punteggio, criticità risolte, traffico
AI — era già calcolabile sui dati del progetto. Il rapporto si legge e si copia
in testo semplice, pronto da girare al cliente finale.

⚠️ Quello che manca **non è il rapporto ma la sua spedizione automatica**, che
richiede cron e notifiche. La scheda lo dichiara e non mette interruttori: degli
interruttori che promettono email non recapitate sono peggio di una riga che
spiega perché non ci sono ancora.

Il riepilogo (`_riepilogo_periodo`) non riempie mai un buco con uno zero: dove il
tracking non è installato il valore resta `None` e il rapporto scrive «non
misurato», perché «nessun evento» e «non stiamo guardando» sono due cose diverse.
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

### Due fenomeni, non uno

| | Chi | Come si vede | Chi lo manda a `/t` |
|---|---|---|---|
| **Crawler AI** | GPTBot, ClaudeBot, PerplexityBot… | User-Agent, **solo lato server** | il plugin sul sito |
| **Referral AI** | una persona che clicca un link dentro ChatGPT | `Referer` / `utm_source` | lo snippet nel browser |

⚠️ **I crawler non eseguono JavaScript**: lo snippet non ne vedrà mai nemmeno
uno, per costruzione. È il motivo per cui AI Traffic sembrava non funzionare —
misurava solo il fenomeno raro (qualcuno *arriva* da un assistente) e non poteva
vedere quello frequente (gli assistenti *ti leggono*). Verificato sui dati veri
il 2 settembre 2026: **4.089 eventi in `tracking_event`, tutti `pageview`, zero
crawler.**

Le regole di riconoscimento stanno in [ai_sources.py](../ai_sources.py), portate
dal plugin GEO Suite di Octoplug dove sono in esercizio da mesi. I criteri che
contano, ognuno nato da un errore già pagato lì:

- il dominio si confronta **col solo host e per suffisso** — cercarlo dentro
  l'URL faceva contare `html.it/articoli/chatgpt-guida/` come visita *da* ChatGPT;
- `utm_source` è il **secondo segnale**, e vale per **parola intera** — molti
  assistenti mandano traffico senza `Referer`, ma «you» dentro «youtube» non è
  You.com;
- alcune voci richiedono anche il **percorso**: solo `bing.com/chat` è Copilot,
  `bing.com/search` è un motore di ricerca.

Effetto misurato sui 4.089 eventi già in database: gli eventi riconosciuti come
AI passano da **11 a 29** (+164%), senza una sola riclassificazione errata in
senso opposto. Il grosso erano visite con `utm_source=chatgpt.com` **e nessun
referrer**, che finivano fra il traffico diretto.

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
- Troncamento difensivo: `event` 64 char, `url`/`ref` 2048, `sid` 128, `ua` 512
- `_detect_ai_source()` riconosce il referral da `ref` **e** dall'`utm_source`
  dentro `url`
- Timeout Supabase a **5 secondi** (più corto degli altri, che sono a 10)
- **Ritorna 204 in ogni caso**, anche in errore

**Il campo `ua`** distingue i due mittenti. Se il body lo porta, la richiesta
arriva da un server (il plugin) e non da un browser: l'endpoint riconosce il
crawler dallo User-Agent e scrive `event_name = "crawler"`, `ai_source` = nome
del bot, `session_id` vuoto (un bot non ha sessione: contarlo come tale
gonfierebbe le sessioni del sito con visite che nessuno ha fatto), e la finalità
del passaggio in `properties.categoria`. Uno UA che non è di un bot noto viene
registrato come pageview normale, non buttato via.

Il riconoscimento sta **qui e non nel plugin** di proposito: la lista dei bot
invecchia in fretta, e così si aggiorna sulla piattaforma senza toccare i siti
dei clienti.

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

---

## Quante pagine guarda il motore

`MAX_PAGINE = 30` in `server.py` (e `MAX_PAGINE_LEAD = 10` per l'audit
preliminare di un lead).

⚠️ **Fino al 4 settembre 2026 era 6, scritto a mano in cinque punti.** Nessuno
se n'era accorto perché la dashboard mostrava «6 pagine» su quasi tutti i
progetti e sembrava un dato, non un tetto: l'ha trovato il consulente facendo il
giro del prodotto. La conseguenza non era estetica — **ogni punteggio consegnato
ai clienti era calcolato su al massimo sei pagine**, quindi su un campione.

Su un sito di prova il punteggio passa da 90 (6 pagine) a 88 (30): il numero
cambia davvero quando si guarda tutto. Il 4 settembre gli audit di tutti i
progetti sono stati rifatti col tetto nuovo.

Il costo misurato è circa **un secondo a pagina** (12 s con 6, 33 s con 30), e il
tetto di durata della function è 300 s. Alzarlo ancora si può, ma va rivista
anche la finestra del cron, che di audit ne fa più d'uno di fila.

## Il tema chiaro, e dove si rompe

⚠️ Tre pagine (`form`, `gate`, `waiting`) avevano un **gradiente fisso e scuro
sul body** senza variante chiara, e due di quelle non avevano nemmeno lo script
che legge la preferenza: restavano scure sempre. È lo stesso difetto già trovato
sul login, e il tema chiaro è quello predefinito del prodotto.

**Due trappole, entrambe incontrate correggendolo:**

1. La regola `[data-theme="light"] body{...}` va **fuori** dal blocco `body{}`.
   Infilata dentro — subito dopo la riga del gradiente, che è dove verrebbe
   naturale metterla — spezza il blocco: il fondo chiaro non arriva *e* si
   perdono le proprietà che seguono. Il difetto sembra corretto e non lo è.
2. Un controllo che verifica «esiste la regola?» dice di sì anche quando il CSS
   è malformato. Serve **guardare la pagina**: `qa/controlla_tool.py`.

⚠️ E nessun template deve dichiarare `data-theme="dark"` nell'HTML: senza
preferenza salvata il prodotto parte in chiaro, e un attributo fisso lo
contraddice.

## Il pannello del team (`/admin`)

Otto schermate a uso interno, in `admin.py` + `templates/admin.html`. Chiudono
il cerchio del flusso di accesso: i lead diventano clienti qui.

| Route | Cosa fa |
|---|---|
| `/admin` | Overview: KPI, cosa richiede attenzione, andamento nel tempo, attività recente |
| `/admin/lead` | Coda delle richieste, con l'audit preliminare e «Valida cliente» |
| `/admin/clienti` | Elenco account, abilita/disabilita, **aggiungi cliente** |
| `/admin/clienti/{id}` | Scheda del singolo cliente: note, accessi, progetti |
| `/admin/job-log` | Esecuzioni del motore, con durata e rilancio (singolo o in blocco) |
| `/admin/tracking` | Progetti che non hanno mai mandato un evento |
| `/admin/interesse` | Segnali commerciali: report esterno **e** roadmap pubblica |
| `/admin/log` | Chi ha fatto cosa nel pannello |

### Il ruolo, che prima non esisteva

⚠️ Il ruolo vive in **`app_metadata`**, mai in `user_metadata`. Si somigliano e
fanno cose opposte: `user_metadata` lo riscrive l'utente stesso con la sua chiave
(è lì che sta il tema), `app_metadata` lo tocca solo la service role. Metterlo
nel campo sbagliato vorrebbe dire lasciare che chiunque **si promuova admin da
solo**.

Non serve una tabella `team_members`: crearla vuole un DDL, e `app_metadata` è il
posto che Supabase prevede per l'autorizzazione.

⚠️ **Il controllo sta prima di ogni route, sul server** (`_admin_o_no`). Nascondere
un link dal menu non è un controllo, e non lo è un redirect JavaScript: queste
pagine mostrano i dati di tutti i clienti. **Anche le azioni POST** verificano il
ruolo, non solo le pagine.

A chi non è del team si risponde **404, non 403**: un 403 confermerebbe che a
quell'indirizzo c'è qualcosa.

### Approvare, disabilitare

**Approvare un lead = creare l'account** (`_sb_auth_create_user`), e subito dopo
gli si manda il link: un cliente approvato che non riceve niente non sa di
esserlo. Non c'è nessuno stato da aggiornare — l'account *è* l'approvazione.

**Disabilitare** scrive `app_metadata.disabled`, che `_sb_auth_magiclink()`
legge: il divieto è applicato dove il link nasce, quindi «disabilita» impedisce
davvero il login invece di essere una spunta che non fa niente. ⚠️ Non ci si può
disabilitare da soli: ci si chiuderebbe fuori dal pannello, e non c'è una
schermata per rientrare.

### Il registro delle azioni

Ogni azione del pannello scrive una riga in **`admin_audit_log`** (vedi più
avanti). Il registro non deve poter far fallire l'azione che sta registrando: se
la scrittura non riesce, l'approvazione resta valida e l'errore viene ingoiato.

⚠️ Restano invece in `tracking_event` i **voti e le iscrizioni della roadmap**,
salvati come `event_name = 'roadmap_vote'` / `'roadmap_signup'` con i dati nel
JSON `properties`. Il documento funzionale proponeva due tabelle dedicate
(`roadmap_votes`, `roadmap_signups`): si è preferito non aggiungere DDL per due
elenchi che oggi sono corti. **Il limite è noto**: nessun vincolo di unicità sul
votante, e i filtri passano da `properties->>...`. Il punto da cui migrare sono
`_sb_roadmap_voti` / `_sb_roadmap_iscrizioni` in `db.py`.

### La scheda del singolo cliente (`/admin/clienti/{id}`)

Progetti col punteggio, **note interne**, **storico accessi**, e le azioni:
rimanda il link, abilita/disabilita.

**Le note non si modificano e non si cancellano.** Una nota commerciale che
qualcuno può riscrivere dopo non è più una traccia: `client_notes` è
append-only per scelta, e ogni riga porta l'email di chi l'ha scritta —
denormalizzata, così resta leggibile anche se quell'account sparisce.

**Lo storico accessi** distingue due momenti: `link_richiesto` e
`accesso_riuscito`. Presi insieme dicono una cosa che nessuno dei due direbbe da
solo — **quanti link non vengono mai cliccati**, cioè quante email non arrivano.
È la risposta alla domanda che ci si fa quando un cliente dice «non riesco a
entrare». Supabase espone solo `last_sign_in_at`: l'ultima volta, e basta.

⚠️ **Con lo storico vuoto la scheda NON scrive «mai entrato».** Il nostro
registro parte da settembre 2026, mentre Supabase sa da sempre qual è stato
l'ultimo accesso: dire «mai entrato» a chi è entrato quaranta giorni fa
significherebbe far passare «non lo sappiamo» per «non è successo», e su questa
scheda si prendono decisioni commerciali.

### Le altre azioni sbloccate

| Azione | Dove | Cosa impedisce |
|---|---|---|
| **Segna contattato** | coda lead | è l'unico stato che ha bisogno di una colonna: gli altri due — in attesa, approvato — sono fatti che si leggono dall'esistenza dell'account |
| **Invia promemoria** | tracking non installato | dopo l'invio il bottone sparisce e resta «mandato N giorni fa»: `tracking_reminders` esiste per non riscrivere a raffica alla stessa persona |

Il promemoria non sollecita: spiega **la conseguenza** (senza snippet la scheda
AI Traffic resterà vuota) e dà la riga da incollare. Chi non l'ha installato
quasi mai l'ha dimenticato — non sa che serve.

### Rilanciare un audit fallito

Il bottone **Rilancia** nel Job log ha senso solo da quando i fallimenti lasciano
una riga: prima non c'era niente da rilanciare.

⚠️ **Come si ottiene l'idempotenza senza lucchetti:** il bottone compare solo se
quel fallimento è *ancora l'ultima parola* per quel progetto. Se qualcuno ha già
rilanciato — o se il cron è ripassato da solo — al suo posto c'è «poi riuscito»,
perché non c'è più niente da fare. Il documento chiedeva che il rilancio «non
crei risultati duplicati né si confonda con l'esecuzione fallita precedente»: la
regola risponde a entrambe le cose senza stato aggiuntivo.

Il rilancio **non ripara la riga fallita**: ne scrive una nuova. Il fallimento
resta dov'è, ed è giusto — sapere che quel sito ha dato problemi prima di
riuscire vale più di una storia ripulita. E se rifallisce, si scrive di nuovo,
così si vede che il problema è ricorrente.

Gira in `BackgroundTasks`: un audit richiede un paio di minuti, e la richiesta
HTTP non può restare aperta tanto.

### Il registro delle azioni ha la sua tabella

`admin_audit_log`, non più `tracking_event`: colonne vere al posto di un JSON
libero, con `actor_email` e `action_type` `NOT NULL` — una riga monca non ci
entra.

### Rilanciare in blocco

`/admin/job/rilancia-tutti` rifà tutti i fallimenti ancora aperti in una volta.

⚠️ **La lista la calcola `admin.falliti_da_rilanciare()`, non la route.** È la
stessa funzione che decide cosa scrivere sul bottone: se il conto lo facessero
separatamente, prima o poi il bottone direbbe «rilancia tutti e 5» e il server ne
rifarebbe sette. Il bottone compare solo con più di un fallimento aperto — con
uno solo, quello della sua riga fa già la stessa cosa.

⚠️ **C'è un tetto** (`admin.MAX_RILANCIO_BLOCCO`, oggi 10). Ogni audit è un giro
di crawler da un paio di minuti: farne partire trenta insieme vuol dire vederli
morire tutti sul limite di durata della function, e ritrovarsi con trenta
fallimenti nuovi al posto di quelli vecchi. Quando il tetto morde, il bottone lo
dice: «Rilancia i primi 10 di 23».

### La durata di un'esecuzione

Si calcola da `created_at` → `completed_at`, già presenti sulla riga.

⚠️ **Zero non vuol dire «istantaneo», vuol dire «non lo sappiamo».** Fino al 3
settembre 2026 i fallimenti registravano inizio e fine nello stesso istante,
perché l'ora la prendeva il ramo d'errore; su quelle righe la colonna scrive
«—». Da adesso chi lancia il motore passa `iniziato=` a `_sb_audit_fallito()`,
così la durata di un timeout è quella vera — che è poi l'unica informazione per
cui la colonna esiste, perché distingue un timeout da un DNS che non risolve.

### Aggiungere un cliente a mano

`/admin/clienti/aggiungi` crea un account già attivo, saltando la coda lead.

⚠️ La casella **«mandagli subito il link»** esiste perché *avvisare o no* è una
decisione di prodotto ancora aperta (documento Admin Dashboard §7.2). Finché non
è presa, non la prende il codice: la prende chi crea l'account, una volta per
volta. Il valore predefinito è «sì», perché un cliente creato e mai avvisato non
sa di esistere e resterebbe in elenco come «mai entrato» per sempre.

### Il grafico dell'Overview

Due linee, punteggio medio e fallimenti, sull'intervallo scelto (7/30/90).

⚠️ **Le due linee non coprono lo stesso periodo, e non è un difetto.** Quella dei
fallimenti comincia dal 3 settembre 2026, da quando i fallimenti lasciano una
riga: prolungarla indietro a zero direbbe «prima non ne falliva nessuno», che è
esattamente ciò che non sappiamo. Quando la linea c'è, una nota sotto il grafico
lo dichiara; quando non c'è, la nota sparisce con lei — una spiegazione senza il
suo oggetto confonde invece di chiarire.

⚠️ Le **sparkline nei KPI** si disegnano solo dove l'andamento è ricostruibile
davvero. Per «lead in attesa» non lo è — un lead approvato esce dalla coda e non
lascia il conteggio di ieri — quindi lì non c'è nessuna sparkline, invece di
inventarne una piatta.

⚠️ L'intervallo arriva dall'indirizzo (`?giorni=`) e **si valida**: un valore
fuori dai tre previsti ricade su 30. `?giorni=100000` costruirebbe centomila
secchi vuoti prima ancora di disegnare qualcosa.

### Indirizzi email: un controllo solo, su sei porte

`email_plausibile()` in `server.py`, usata da tutte e sei le route che accettano
un indirizzo da fuori (login, richiesta accesso, approva lead, aggiungi cliente,
link manuale, «avvisami» della roadmap).

⚠️ Cercare la chiocciola non basta: **`@dominio.it` ce l'ha e non è un
indirizzo**. Nemmeno «chiocciola più un punto» basta, perché guarda solo la parte
dopo. Senza qualcosa *prima* della chiocciola la richiesta arrivava fino a
Supabase, che rispondeva con un errore di rete buio — e sul form pubblico quello
lo vedeva l'utente, senza capire cosa avesse sbagliato.
