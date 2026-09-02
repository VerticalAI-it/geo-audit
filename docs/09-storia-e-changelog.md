# 09 · Storia e changelog

Ricostruita dalla history git. Serve a capire **perché** il codice è com'è, e a
non ripercorrere strade già battute e abbandonate.

Periodo: **7 giugno → 11 agosto 2026** · 83 commit.

---

## Cronologia per fasi

| Fase | Periodo | Cosa |
|---|---|---|
| **A** | 7-8 giu | Motore di audit + servizio web sincrono |
| **B** | 8-10 giu | Persistenza Supabase, gate email, lead capture |
| — | 11 giu | *Parentesi pay2vertical* (estratta in altro repo) |
| **DS** | 12-15 giu | Design system, landing, GDPR |
| **C** | 25 lug | Account, progetti, dashboard a 12 tab |
| **D** | 26 lug | Tracking first-party, AI Traffic, roadmap pubblica |
| **E** | 11 ago | Audit periodici, SEO tecnica, grafico storico |

---

## Fase A — Il motore (7-8 giugno)

`621da44` · `24cc682` · `f7a514a` · `f96bb07`

L'inizio: `geo_audit.py` come scanner standalone con report HTML e PDF, più un
servizio FastAPI minimale con un form.

Nasce subito il primo attrito con Vercel: `f7a514a` "*fix macOS PDF generation*"
introduce la patch `ctypes.util.find_library` per Homebrew su Apple Silicon, che è
ancora nel codice ([geo_audit.py:934](../geo_audit.py#L934)).

### La prima decisione strutturale

`21743b5` — **"Remove WeasyPrint and Playwright from Vercel requirements"**.

È il commit che definisce il vincolo con cui il prodotto convive tuttora: Chromium
e le librerie PDF non girano su serverless. Da qui in poi la produzione fa audit
**senza rendering JS** e **senza PDF**, mentre la CLI e il Dockerfile mantengono
entrambe le capacità.

`00e24f0` — Rimozione della chiave `functions` da `vercel.json`, prima tappa verso
la configurazione zero-config.

---

## Fase B — Persistenza e lead capture (8-10 giugno)

### Il tentativo asincrono e il suo abbandono

Questa sequenza di cinque commit in un solo giorno è la parte più istruttiva della
storia del progetto:

| Commit | Cosa succede |
|---|---|
| `1c4c938` | **Implementa la Fase B**: coda job asincrona, storage Supabase, auth, gate email |
| `4baa5e7` | Rimuove il Cron Vercel (limite del piano Hobby) → trigger esterno |
| `320f557` | Rimuove di nuovo la chiave `functions` per l'auto-detection |
| `1877536` | Handler sincroni per non bloccare l'event loop con il client sincrono di `supabase-py` |
| `cfb7f41` | **Revert allo scan sincrono**: `httpx` (dipendenza di `supabase-py`) incompatibile col runtime Vercel |
| `4dd13e7` | Riscrive il salvataggio Supabase **senza `supabase-py`**, chiamando PostgREST via `requests` |

**Cosa resta oggi di questa vicenda:**

1. `server.py` parla con Supabase via **REST diretta**, non con l'SDK
   ([02 · Architettura](02-architettura.md#supabase-via-rest-diretta-non-supabase-py))
2. `/scan` è **sincrono**, con `max_pages=6` per stare dentro il timeout
3. La colonna `audits.status` e la coda `pending` sono **residui vestigiali** della
   coda mai completata ([doc 10](10-stato-e-debito-tecnico.md#la-coda-pending-è-vestigiale))
4. `api/cron.py`, nato per consumare quella coda, è sopravvissuto e nel 2026-08 ha
   trovato un secondo scopo — gli audit periodici — salvo poi scoprire che **non
   era mai stato deployato**: Vercel non lo costruiva come function e ogni
   `GET /api/cron` prendeva un 404 dal router FastAPI. Il cron è stato riscritto
   come route in `server.py` e il file rimosso
   ([02 · Architettura](02-architettura.md#una-sola-function-apicron-incluso))

> La lezione, se serve un giudizio: il tentativo asincrono è fallito non per il
> design ma per l'ambiente. Su un host a container sarebbe passato al primo colpo.
> Vale la pena ricordarlo se un giorno si valuta di lasciare Vercel.

### Lead capture

`bd86ad3` — "*Show gate even when Supabase save fails*": il gate appare comunque
se il salvataggio fallisce. È il primo esempio di una scelta ricorrente nel
codice — **degradare invece di fallire**.

`fa2ed92` · `aed1a29` — `/miei-report`: recupero dei link via email.
`1bdab83` — Form di contatto dal report.
`f0d2dbd` — Normalizzazione URL: accetta domini senza `http://`. Ricomparirà in
`f74c4a0` — un requisito banale che è stato risolto due volte in due punti diversi.

---

## Parentesi pay2vertical (11 giugno)

`a2f7132` → `5400367` · `4b3e0e1`

Un'app di checkout SaaS è stata sviluppata dentro questo repository e poi
**estratta** in `verticalai-it/pay2vai`. Cinque commit di sviluppo e due di
rimozione. Nessuna traccia residua nel codice attuale — la si incontra solo
scorrendo la history.

`132bcc1` — **Spostamento del tool da `/` a `/audit`**, con la landing marketing
alla radice. È il momento in cui il prodotto smette di essere un tool e diventa un
sito con un funnel.

`b783921` / `4f17ab6` — Un tentativo di "*resolve all GEO audit issues*" sulla
landing, revertito il giorno stesso.

---

## Fase Design System (12-15 giugno)

Tre PR parallele, mergiate nell'ordine previsto:

| Commit | Contenuto |
|---|---|
| `0a7408d` | Token CSS + serving degli static |
| `d1154cd` | Allineamento di tutti i template frontend |
| `9b3d8c7` | Allineamento di tutte le email |

Poi il consolidamento della landing (`13d43d0`, `53b675b`), il GDPR
(privacy/cookie policy + banner, `53b675b` e `b03b71b`) e il refresh visivo del
report (`3734ea3`).

`0d3becc` — **Nasce `CLAUDE.md`**, con la regola che governa tuttora ogni modifica
alla UI.

`415f3e0` — La CTA della landing apre il form e fa submit via `fetch` verso
`/richiedi-audit`: il funnel di lead generation prende la forma attuale.

---

## Fase C — Account e progetti (25 luglio)

Un mese e mezzo di pausa, poi il salto di prodotto più grande: da generatore di
report anonimi a **piattaforma con account e storico**.

### Autenticazione

`79fc9bb` introduce il login obbligatorio via magic link. I quattro commit
successivi sono tutti sul **redirect del magic link**:

| Commit | Tentativo |
|---|---|
| `fb8fff4` | `SITE_URL` fisso |
| `2a87fda` | Ritorno a `window.location.origin` |
| `e7660f3` | Rete di sicurezza per `redirect_to` non whitelistato |
| `4b2af28` | **Rimozione della query string dal `redirect_to`** ← la soluzione |

Quattro iterazioni per capire che Supabase valida la URL di redirect contro una
whitelist e la query string la faceva fallire. È il motivo per cui oggi la
destinazione post-login viaggia fuori dal `redirect_to`
([05 · Applicazione web](05-applicazione-web.md#autenticazione-magic-link-con-sessione-server-side)).

### Dashboard

`7f31923` — **Project Portfolio + Project Detail a 12 tab su dati reali.** Il
commit più grosso del progetto: introduce `project`, `issue`, le colonne
strutturate su `audits` e tutta la UI di dettaglio.

`0d9179c` — "*logga l'errore reale quando il salvataggio Supabase fallisce*". Il
messaggio del commit spiega bene il problema: senza log, *"un salvataggio rotto è
invisibile e l'utente ricade silenziosamente sul gate legacy"*.

`94143ba` · `a537069` — La migration diventa **interamente idempotente** e viene
documentato il `NOTIFY pgrst, 'reload schema'` — entrambe conseguenze di problemi
reali in fase di deploy.

### Rifinitura UI

`2851eee` (nav a categorie + Overview riepilogativa + seed demo) · `4ea97a9`
(tema chiaro/scuro ovunque, report riallineato) · `19f06b4` · `b7e94c3` ·
`8e2c495` · `8b9c10b`.

Da `2851eee` in avanti si consolida la regola che l'Overview **non mostra mai dati
simulati**: per le sezioni non disponibili, un blocco "coming soon" esplicito.

---

## Fase D — Tracking e trasparenza (26 luglio)

`e10f094` — **Pagina `/roadmap` pubblica**, collegata solo dal footer. Scelta
insolita e deliberata: dire ai clienti cosa non c'è ancora.

`b5a5b57` · `e74925f` — `roadmap.md` interno, poi espanso con il dettaglio tecnico.

`6bcd2b8` — **Tracking first-party**: snippet, endpoint `/t`, tabella
`tracking_event`, rilevamento provider, tab AI Traffic.

`76a3f69` — Lo snippet viene installato **sulla nostra stessa landing**: primo
dogfooding.

`cdaac71` — Sessioni di tracking demo per popolare la tab senza aspettare traffico
reale.

---

## Fase E — Automazione e SEO tecnica (11 agosto)

`498f746` — **Rifai audit manuale + cron di audit periodico.** Introduce
`scan_frequency`, `next_scan_at` e il claim atomico. È il commit che rende il
prodotto *monitoraggio* e non più solo *analisi*.

`1ccb850` — Cron da orario a giornaliero, budget di esecuzione più basso: *"per
escludere che la config del cron possa far fallire l'intero deploy"*.

`910ef87` — **Rimozione del rewrite catch-all.** Il bug di produzione più costoso
della storia del progetto: build verde, ogni pagina che rispondeva
`{"detail":"Not Found"}`. La spiegazione è finita in `CLAUDE.md` perché non si
ripeta.

`2e8f74d` — **Copertura dei gap del nostro stesso Technical GEO**: `/robots.txt`,
`/sitemap.xml`, `/llms.txt`, canonical, JSON-LD. Il tool che raccomanda `llms.txt`
adesso ce l'ha.

`9e72b92` — Gap analysis contro l'articolo di ilmioposizionamento.it, con le
decisioni di prodotto annotate direttamente nel file
([backlog/geo-gap-ilmioposizionamento.md](backlog/geo-gap-ilmioposizionamento.md)).

`b29a35d` — **Storico punteggio come grafico interattivo** con filtri 3/6 mesi/tutto.
Ultimo commit.

---

## Fase F — Redesign UI/UX (1-2 settembre 2026)

Il progetto passa di mano: lo sviluppatore che l'ha costruito lascia, e il
lavoro prosegue sulla specifica di un analista interno — un documento
funzionale più 16 pagine di prototipo, scelta «Opzione A».

Undici commit in due giorni, poi il merge in produzione. Il punto di rollback
è il tag **`prima-del-rework`**.

| Commit | Cosa |
|---|---|
| `204f26d` | Soglia colore a 50 e tema chiaro nel report |
| `d23c4b1` | Log sugli invii email falliti |
| `9dc51c6` | **Separazione di `server.py`** in config/db/views |
| `8990c30` | Dashboard sul design system nuovo |
| `17fc264` | Menu laterale e Overview con anello del punteggio |
| `d6ea296` | Pages con ricerca, filtri, ordinamento, CSV |
| `3a4b8d5` | Riepilogo, Technical GEO, Traffic, Settings |
| `76dab52` | Opportunities con paginazione reale |
| `7aea4ce` | Le 5 sezioni non attive con dati dimostrativi |
| `af7d727` | «Segna risolto» |

### Tre cose imparate, che valgono più del codice

**Un commento non è un vincolo.** `issue.status` era descritto come
`-- open | resolved` e per questo si stava per chiedere una migrazione: la
colonna non aveva nessun `CHECK` e accettava già il terzo valore. Prima di
chiedere di toccare un database di produzione, leggere lo schema vero.

**Il mobile va guardato, non dedotto.** Una regola CSS aggiunta per colorare la
colonna del menu batteva per specificità il `position:fixed` che la sidebar
assume sotto 980px: su telefono la pagina appariva **vuota**. Sul desktop non
si vedeva nulla di strano.

**L'applicativo non era utilizzabile in locale.** I cookie di sessione sono
`secure`, quindi su http il browser li scarta: si faceva il login e non si
entrava mai, senza nessun errore. Nessuno se n'era accorto perché nessuno ci
aveva provato.

### Regola di prodotto cambiata

Le sezioni non ancora attive mostravano una scatola vuota, per la regola «mai
dati simulati». Ora mostrano **dati dimostrativi con banner esplicito**: una
scatola vuota non fa capire cosa si otterrà. Il principio di fondo resta, ed è
scritto in `CLAUDE.md`: *un dato mostrato senza etichetta dev'essere un dato
misurato*.

---

## Cose provate e abbandonate

Utile saperlo prima di riproporle:

| Cosa | Quando | Perché è finita |
|---|---|---|
| **Coda job asincrona** | giu | `httpx`/`supabase-py` incompatibili col runtime Vercel |
| **`supabase-py` in `server.py`** | giu | Client sincrono che bloccava l'event loop |
| **WeasyPrint/Playwright su Vercel** | giu | Non supportati su serverless |
| **Cron orario** | ago | Portato a giornaliero per compatibilità con qualsiasi piano |
| **`rewrites` catch-all in `vercel.json`** | ago | Conflitto col routing FastAPI nativo → 404 ovunque |
| **`redirect_to` con query string** | lug | Fallisce la validazione della whitelist Supabase |
| **pay2vertical nel repo** | giu | Estratto in `verticalai-it/pay2vai` |

---

## Pattern ricorrenti nel codice

Tre abitudini emergono con chiarezza dalla history, e conviene rispettarle:

**1. Degradare, mai fallire.** Playwright manca → si continua senza rendering.
Supabase non risponde → il report si vede lo stesso. L'email non parte → la
richiesta va comunque a buon fine. Il tracking fallisce → 204 e il sito del cliente
non se ne accorge.

**2. Mai dati finti.** Le sezioni non disponibili dicono esplicitamente cosa manca
e perché. Il seed demo esiste apposta per non avere la tentazione di simulare in
produzione.

**3. Documentare i fallimenti dove servono.** Il `NOTIFY pgrst`, il divieto di
`rewrites`, il `redirect_to` senza query string: ogni bug costoso ha lasciato una
riga di documentazione nel punto in cui qualcuno rischierebbe di rifarlo.
