# 11 · Next steps

Backlog operativo consolidato. Mette insieme tre fonti che finora vivevano
separate:

- [roadmap.md](roadmap.md) — roadmap di prodotto per versione
- [backlog/geo-gap-ilmioposizionamento.md](backlog/geo-gap-ilmioposizionamento.md) — gap analysis con le decisioni di prodotto già prese
- [10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md) — cosa va sanato nel codice

**Le stime di sforzo sono indicative** (S ≤ 1 giorno · M ≤ 1 settimana · L ≤ 1 mese
· XL > 1 mese) e vanno riviste in sede di pianificazione.

---

## Il gap in una riga

> Oggi misuriamo la **predisposizione** di un sito a essere citato dalle AI.
> Non misuriamo se venga **effettivamente** citato.

Tutto il blocco v2.x serve a chiudere quel gap. È anche la promessa già fatta nel
CTA del report attuale ("monitoriamo i progressi nel tempo") e le tre schede vuote
della dashboard (`AI Visibility`, `Prompts & Queries`, `Citations`) sono lì ad
aspettarlo.

---

## Blocco 0 · Quick win (≤ 1 giorno ciascuno)

Interventi con rapporto valore/sforzo alto, nessuna dipendenza, eseguibili subito.

| # | Intervento | Sforzo | Perché |
|---|---|---|---|
| 0.1 | Verificare/impostare `CRON_SECRET` in produzione | S | 🔴 Token report prevedibili col default |
| 0.2 | Log nell'`except` di ogni invio email | S | Oggi i lead persi sono invisibili |
| 0.3 | Allineare `barcol()` a 50 in `geo_audit.py` | S | Un carattere; toglie un'incoerenza visibile |
| 0.4 | Allineare il default del tema fra report e prodotto | S | Il tema cambia sotto i piedi all'utente |
| 0.5 | Rimuovere `templates/gate.html` e `waiting.html` | S | Codice morto già manutenuto per errore |
| 0.6 | Riscrivere il `README.md` come ingresso verso `docs/` | S | È la prima cosa che legge chi arriva |
| 0.7 | Aggiornare i path e la tabella route in `DESIGN_SYSTEM.md` | S | Riferimenti a file inesistenti |
| 0.8 | Avviso in AI Traffic al raggiungimento del tetto di 5000 eventi | S | Oggi tronca in silenzio |

📄 Dettaglio: [10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md)

---

## Blocco 1 · Fondamenta

Non aggiunge funzionalità visibili. Rende sostenibile tutto il resto — e va fatto
**prima** che il team cresca o che il codice raddoppi con il blocco v2.

### 1.1 · Primo lotto di test 🔴 · M

Zero test oggi. Il lotto minimo che copre i rischi reali:

| Test | Protegge |
|---|---|
| `score_checks()` su check sintetici | La formula di scoring |
| `parse_robots_ai()` su robots.txt di esempio | Il check più pesante del catalogo |
| `is_page_url()` / `norm()` | La qualità del crawl |
| `_detect_ai_source()` | Il rilevamento provider |
| `_project_status()` sulle soglie | Lo stato in dashboard |
| **Snapshot dei `check_id` emessi da `run_audit`** | La continuità dello storico issue |

L'ultimo è il più prezioso: fallisce se qualcuno rinomina un `check_id`, che è
esattamente il cambiamento che spezza silenziosamente lo storico delle issue senza
che nulla se ne accorga.

Aggiungere una GitHub Action che esegua i test + `py_compile` su ogni PR.

### 1.2 · Centralizzare l'autorizzazione 🔴 · M

Una dependency FastAPI `require_project_owner(project_id)` che risolva progetto e
proprietà in un punto solo, al posto del controllo copiato in ogni route.
Elimina la classe di bug "nuova route esposta per dimenticanza".

### 1.3 · Deduplicare issue-sync ed email-kit ✅ · fatto

Non serve più. La duplicazione esisteva perché `api/cron.py` era ritenuto una
Vercel Function separata che non poteva importare `server.py`. Non lo era mai
stato: il file non veniva costruito affatto
([02 · Architettura](02-architettura.md#una-sola-function-apicron-incluso)).

Il cron è diventato la route `/api/cron` in `server.py`, il file è stato rimosso,
e `_sb_issue_sync()` e i componenti email hanno di nuovo una sola copia.

**Subentra al suo posto:** dare al cron una cadenza che copra il portafoglio
([10 · Debito tecnico](10-stato-e-debito-tecnico.md#il-cron-giornaliero-non-copre-il-portafoglio)).

### 1.4 · Decidere il destino della coda asincrona 🟡 · S (decisione) + M (esecuzione)

**Decisione, non implementazione.** Due strade opposte:

| Strada | Conseguenze |
|---|---|
| **Rimuovere** coda, `_process_next_job`, email correlate, `waiting.html` | Semplifica; chiude la porta ad audit più lunghi |
| **Riattivare** la coda | Sblocca `max_pages` più alto, rendering JS, `_send_conferma_audit` |

È la **stessa decisione** del punto 1.5: vanno prese insieme.

### 1.5 · Ripristinare `render.parity` 🔴 · L

Il limite funzionale più grave del prodotto ([doc 10](10-stato-e-debito-tecnico.md#renderparity-non-viene-mai-calcolato-in-produzione)).

| Opzione | Costo | Effetto |
|---|---|---|
| Microservizio di rendering su container | Medio | Risolve, mantiene Vercel per l'app |
| API di rendering di terzi (Browserless, ScrapingBee) | Basso + ricorrente | Risolve, costo per chiamata |
| Spostare tutto su container (Railway/Render) | Alto | Risolve, sblocca anche il PDF |
| Euristica statica (rapporto `<script>`/testo) | Basso | Approssima soltanto |

**Raccomandazione:** partire da un'API di terzi per validare l'impatto reale sul
punteggio con costo di ingegneria quasi nullo; valutare l'internalizzazione solo
se i volumi lo giustificano.

### 1.6 · Retention di `audits.html` 🟡 · M

Spostare l'HTML su Supabase Storage, oppure conservarlo solo per gli ultimi N
audit per progetto — le colonne strutturate, che alimentano dashboard e storico,
restano sempre.

### 1.7 · AI Traffic in SQL 🟡 · M

Sostituire l'aggregazione Python a 5000 eventi con aggregazione SQL o tabella di
rollup giornaliero. Prerequisito per vendere il tracking a un cliente con volumi
reali.

---

## Blocco 2 · Hardening dell'audit engine

Lavoro puro su `geo_audit.py`. **Nessuna dipendenza esterna, nessuna nuova
infrastruttura**: è il modo più economico per aumentare il valore percepito del
report. Deriva sia da [roadmap.md](roadmap.md) che dalla sezione D della gap
analysis.

### 2.1 · Nuovi check on-page · M

| Check | Cosa verifica | Nota |
|---|---|---|
| `schema.datemodified` | `dateModified` esplicito nello schema `Article` | Oggi `content.fresh` è una regex generica; è il segnale di freschezza primario per Perplexity/Gemini |
| `faq.answerlen` | Lunghezza risposte in `acceptedAnswer` (50-100 parole) + coerenza col testo visibile | Oggi verifichiamo solo che `FAQPage.mainEntity` esista |
| `content.atomic` | Qualità del primo paragrafo: 40-80 parole, affermazione + dato/fonte + contesto | Oggi rileviamo solo la *presenza* di un TL;DR |
| `content.sources` | Dati numerici attribuiti a una fonte, con cadenza (~ogni 200-300 parole) | Non rilevato |
| `content.hidden` | Contenuto critico raggiungibile solo via accordion o PDF linkato | I LLM spesso non espandono accordion né leggono PDF |
| `sd.person` | `sameAs` verso Wikipedia/Wikidata/Scholar/LinkedIn + pagina autore dedicata | Oggi `sd.sameas` è generico |
| `page.redirects` | Catena di redirect e status HTTP intermedi | Da roadmap |
| `meta.canonical.consistency` | Coerenza dei canonical, `hreflang` dove applicabile | Da roadmap |
| `crawl.conflict` | Conflitti fra `robots.txt` e `meta robots` | Da roadmap |
| `crawl.coverage` | Copertura della sitemap rispetto alle pagine scoperte | Da roadmap |
| `content.duplicate` | Segnali di contenuto duplicato / thin content | Da roadmap |

⚠️ **Ogni nuovo check cambia il denominatore dello scoring**, quindi i punteggi non
saranno confrontabili con lo storico. Introdurli in un unico lotto con un bump di
`ENGINE_VERSION` e una gestione esplicita della discontinuità nel grafico storico.

### 2.2 · Core Web Vitals · M

`perf.cls` e `perf.lcp` via PageSpeed Insights API (gratuita entro quota) o
CrUX API. La gap analysis riporta dati concreti: CLS > 0,1 → -29,8 % di inclusione
in AI Overview; LCP > 2,5 s → probabilità 1,47× inferiore.

**Dipendenza:** chiave API Google, gestione della quota.

### 2.3 · Rivedere la formula di scoring · L

Oggi i check di sito si diluiscono fra le pagine: `crawl.ai` — il check che rileva
se il sito **blocca completamente i crawler AI** — sposta il punteggio di ~2 punti
([doc 10](10-stato-e-debito-tecnico.md#lo-scoring-diluisce-i-check-di-sito)).

⚠️ Rende i punteggi non confrontabili con lo storico. Da fare **insieme** a 2.1,
non separatamente.

### 2.4 · Timestamp e versione per singolo check · S

Oggi `engine_version` è a livello di `audit_run`. Portarlo a livello di check
permette di sapere quando un singolo controllo è cambiato. Il dato è già
predisposto ([doc 10](10-stato-e-debito-tecnico.md#engine_version-è-scritto-ma-mai-letto)).

---

## Blocco 3 · v2.0 — LLM monitoring 🎯

**È il blocco che definisce il prodotto.** Sblocca da solo tre schede già presenti
in UI e vuote.

### 3.1 · Decisione build vs buy ⛔ BLOCCANTE

Preferenza già espressa nella gap analysis:

> *"Valuterei la possibilità di integrare uno dei servizi esterni, meglio se
> gratuito ma valutiamo i costi senza problemi. Importante che porti un valore
> reale."*

Va trasformata in una scelta concreta:

| Opzione | Pro | Contro |
|---|---|---|
| **Tool verticale** (BrandRank.ai, Profound, Otterly, Peec AI) | Time-to-market rapido, metodologia già validata | Licenza/revenue share, poco controllo sul dato, dipendenza |
| **Semrush AI Toolkit** | Copre anche la SEO tradizionale | Costo, granularità non controllata |
| **In-house** (API OpenAI/Anthropic/Perplexity/Google) | Controllo pieno, margine più alto | Costo ingegneristico, rate limit, gestione token |

**Serve:** una valutazione comparativa con costo mensile stimato a 10 / 50 / 200
progetti. Finché non è presa, tutto il blocco 3 e 4 è fermo.

### 3.2 · Panel di prompt per progetto · L

- Set di **canary query non-branded** per progetto, intento informazionale,
  verticali di settore
- Criteri di selezione ripresi dalla gap analysis
- Interfaccia per gestire il panel (o generazione automatica dal settore del
  progetto — il campo `project.sector` esiste già ed è oggi inutilizzato)

### 3.3 · Motore di monitoraggio · L

Interrogazione periodica di ChatGPT, Perplexity, Gemini, Claude con il panel,
registrando: brand citato sì/no, posizione nella risposta, URL citato.

**Frequenza differenziata per motore**, motivata dalle diverse latenze di
indicizzazione:

| Motore | Frequenza | Latenza di indicizzazione |
|---|---|---|
| Perplexity | Settimanale | 2-8 settimane |
| ChatGPT / Gemini | Mensile | 4-12 settimane |
| Claude | Trimestrale | 3-6+ mesi |

**Dipendenza infrastrutturale:** il cron attuale gira **una volta al giorno** con
budget di 20 secondi. Un panel di prompt richiede uno scheduler più capace — è la
stessa infrastruttura che serve al punto 1.4.

### 3.4 · I tre KPI · M

| KPI | Definizione |
|---|---|
| **Citation Share** | % di query in cui il brand è citato |
| **Brand Mention Rate** | Frequenza delle menzioni |
| **Source Frequency** | Quante volte lo stesso URL è citato come fonte |

### 3.5 · Sbloccare le schede · M

`AI Visibility`, `Prompts & Queries`, `Citations`. La UI esiste già: vanno
sostituiti i blocchi `_coming_soon_tab()` con i dati reali.

> ⚠️ **Vincolo di prodotto esplicito da [roadmap.md](roadmap.md):** queste metriche
> **non vanno fuse nel GEO Score deterministico** finché la metodologia di
> campionamento non è stabile e validata. Devono restare un modulo affiancato, non
> un ingrediente del punteggio.

---

## Blocco 4 · v2.1 — Competitors e Citations

**Dipende interamente dal blocco 3** (riusa lo stesso panel e lo stesso motore).

### 4.1 · Gestione competitor · M

Decisione già presa nella gap analysis:

> *"Inserimento manuale. Manteniamo autodiscovery come sviluppo futuro e
> manteniamo un tasto 'Autodiscovery' con tag coming soon."*

- Campo "competitor URLs" per progetto, a inserimento manuale
- Pulsante "Autodiscovery" visibile ma marcato `coming soon`

### 4.2 · Share of Voice · M

Nel calcolo del citation share, tracciare anche quando la risposta cita un
competitor invece del cliente. Sblocca la scheda `Competitors` con i gap
competitivi (query dove il competitor è citato e noi no).

### 4.3 · Citation rate e top cited pages · M

URL citati, pagine più citate come fonte, trend nel tempo.

---

## Blocco 5 · v2.2 — Accuracy e off-site

### 5.1 · Ground truth per progetto · L

Fatti verificati sul brand, confrontati con quanto l'AI "crede": attributi
associati, claim, accuracy. Richiede una knowledge base per progetto.

### 5.2 · Presenza off-site · L

- Verifica automatica dell'entità su Wikipedia / Wikidata / Google Scholar
- Citation diversity: co-citazioni da fonti indipendenti (**richiede dati di
  backlink** — Ahrefs / Semrush / Moz API)
- Check "posizionamento organico top 10" come prerequisito (**richiede dati SERP**)

Motivazione dalla gap analysis: l'80-90 % delle fonti citate nelle AI Overview
proviene dalla top 10 organica.

### 5.3 · Decisione sui dati a pagamento ⛔ BLOCCANTE per 5.2

Backlink e SERP sono voci di costo ricorrenti per query. Indicazione già data:

> *"Inseriamo ora la parte a pagamento… analizziamo come impostare per un cliente
> i progetti e settare se metterli a pagamento o gratuiti. Potremmo gestirli dalla
> nostra dashboard."*

Implica il blocco 6.

---

## Blocco 6 · Monetizzazione

**Oggi nel codice non esiste alcun concetto di piano, entitlement o billing.** Le
decisioni di prodotto sono però già prese.

### 6.1 · Modello piani · M

| | Free | Paid |
|---|---|---|
| GEO Score aggregato | ✅ | ✅ |
| Report completo | ✅ | ✅ |
| Scoring per motore (ChatGPT/Gemini/Claude/Perplexity) | 🔒 placeholder greyed-out | ✅ |
| Roadmap 90 giorni | 🔒 solo teaser | ✅ completa |
| Monitoraggio citazioni | 🔒 | ✅ |
| Competitors | 🔒 | ✅ |

Il placeholder greyed-out sul free è **strategia di upsell esplicita**: si mostra
che la funzione esiste anche quando non la si calcola.

### 6.2 · Backoffice interno · M

Gestire da una dashboard interna quali progetti di quale cliente sono
free o paid, e come rendere l'attivazione visibile al cliente.

### 6.3 · Scoring per motore · L

Quattro sotto-punteggi invece di uno aggregato, con raccomandazioni segmentate.
I quattro motori hanno criteri diversi: Claude preferisce contenuti di 1.500-3.000
parole e tono anti-iperbolico, Perplexity vuole data di aggiornamento visibile e
titoli descrittivi, ecc.

**Dipende da:** blocco 3 (per validare i pesi per motore su dati reali) + 6.1.

---

## Blocco 7 · Trasversali

Nessuna dipendenza bloccante, si possono avviare in parallelo.

### 7.1 · KPI e data provenance · M

Da [roadmap.md](roadmap.md). Un badge su ogni KPI che ne dichiari la natura:

| Badge | Significato |
|---|---|
| **AUDIT** | Dato dal crawler deterministico |
| **MEASURED** | Dato osservato sul sito (tracking) |
| **MONITORED** | Test ripetibili su panel LLM |
| **PLATFORM** | Integrazione esterna |
| **ESTIMATED** | Dato inferito o modellato |

Con formula, sorgente, periodo e last-updated per ogni KPI.

**Principio, esplicito in roadmap:** mai usare espressioni tipo *"ricerche su
ChatGPT"* quando il dato è in realtà un referral identificato o un panel
monitorato.

**Può partire subito** sui dati AUDIT e MEASURED già esistenti, e diventa
indispensabile appena arriva il blocco 3 (dove la confusione fra osservato e
stimato sarebbe più facile e più dannosa).

### 7.2 · Roadmap 90 giorni automatica · M

Generare dai check falliti una roadmap operativa in 3 fasi da 30 giorni (audit e
fondamenta → contenuto e autorevolezza → ottimizzazione LLM-specifica e
misurazione), nella scheda `Opportunities` o `Reports`.

Decisione già presa: *"solo teaser su gratuito e greyed out il resto, tutto
visibile su paid"*.

Ha senso **dopo** il blocco 3: senza dati di monitoraggio, la roadmap generata
sarebbe statica e generica.

### 7.3 · Reports e alerts · M

Variazioni, anomalie, milestone cross-modulo.

**Dipendenza:** ha senso solo quando almeno un altro modulo è vivo. Oggi c'è il
tracking, quindi un primo alert su una variazione anomala del traffico AI sarebbe
già possibile.

Sblocca anche `_send_report_mensile()`, che è **già scritta** e aspetta uno
scheduler ([06 · Email](06-email.md#le-tre-email-orfane)).

---

## Blocco 8 · Verticale Hospitality

Layer opzionale sopra lo stesso modello di progetto (ogni hotel resta un progetto
indipendente). **È l'ultimo livello del piano**: dipende da tutto quanto sopra, in
particolare dal blocco 3 per il panel di prompt.

- Prompt taxonomy dedicata (luxury, family, spa, business, destination, near POI,
  amenities, wedding/conference)
- Hotel ground truth: nome, indirizzo, coordinate, stelle, check-in/out,
  ristoranti, spa, pool, parking, pet policy, amenities
- Destination Visibility — visibilità per destinazione e cluster geografici
- Recommendation Share — presenza nei prompt di raccomandazione hotel
- Amenity Knowledge — accuratezza della conoscenza AI dei servizi
- Hotel competitor gap — confronto per query/destinazione
- *(fase successiva)* Booking funnel e Group roll-up

📄 Dettaglio completo in [roadmap.md](roadmap.md#verticale--hospitality)

---

## Grafo delle dipendenze

```
Blocco 0 (quick win) ─── nessuna dipendenza, eseguibile subito
        │
Blocco 1 (fondamenta) ── 1.4 e 1.5 sono la STESSA decisione architetturale
        │                     (coda asincrona ⇄ rendering JS)
        │
        ├─→ Blocco 2 (hardening engine) ── indipendente, alto valore/sforzo
        │
        └─→ 3.1 DECISIONE build-vs-buy  ⛔ BLOCCA TUTTO QUANTO SEGUE
                   │
                   ├─→ Blocco 3 (v2.0 LLM monitoring)
                   │        │
                   │        ├─→ Blocco 4 (v2.1 competitors + citations)
                   │        ├─→ 6.3 (scoring per motore)
                   │        ├─→ 7.2 (roadmap 90gg automatica)
                   │        └─→ Blocco 8 (hospitality)
                   │
                   └─→ Blocco 5 (v2.2 accuracy + off-site)
                            └── richiede anche 5.3 (decisione dati a pagamento)
                                       └── implica Blocco 6 (piani)

Blocco 7.1 (KPI provenance) ─── indipendente, ma da fare PRIMA del blocco 3
Blocco 7.3 (alerts) ─────────── già possibile in forma minima sul tracking
```

---

## Sequenza raccomandata

| Ordine | Cosa | Perché adesso |
|---|---|---|
| **1** | Blocco 0 | Ore di lavoro, chiudono rischi e incoerenze visibili |
| **2** | 3.1 — decisione build vs buy | ⛔ Blocca metà della roadmap. Va presa **in parallelo** al lavoro tecnico, non dopo |
| **3** | 1.1 + 1.2 (test + autorizzazione) | Rendono sicuro tutto ciò che verrà dopo |
| **4** | Blocco 2 (hardening engine) | Miglior rapporto valore/sforzo: nessuna infrastruttura nuova, valore immediato sul report |
| **5** | 1.4 + 1.5 (coda + rendering) | Decisione unica; sblocca l'audit approfondito |
| **6** | 7.1 (KPI provenance) | Da avere **prima** di introdurre dati monitorati |
| **7** | Blocco 3 (v2.0) | Il cuore del prodotto, una volta che le fondamenta reggono |
| **8** | Blocco 6 (piani) + Blocco 4 (v2.1) | La monetizzazione ha senso quando c'è qualcosa da vendere |
| **9** | Blocco 5, 7.2, 7.3, Blocco 8 | Approfondimento e verticalizzazione |

---

## Decisioni aperte

Da chiudere prima di poter stimare seriamente. Le prime due bloccano il resto.

| # | Decisione | Blocca | Stato |
|---|---|---|---|
| D1 | Build vs buy per il monitoraggio LLM, con budget mensile | Blocchi 3, 4, 5, 6.3, 7.2, 8 | Preferenza espressa (servizio esterno), **non decisa** |
| D2 | Restare su Vercel o passare a container | 1.4, 1.5, blocco 3 (scheduler) | Aperta |
| D3 | Integrare dati backlink/SERP a pagamento, con budget | 5.2 | Indicazione data, **non quantificata** |
| D4 | Modello di pricing e confine free/paid | Blocco 6 | Impostazione definita, prezzi non decisi |
| D5 | Come gestire la discontinuità dello storico quando cambia lo scoring | 2.1, 2.3 | Non affrontata |

---

## Fonti

Questo documento consolida, senza sostituirli:

- [roadmap.md](roadmap.md) — roadmap di prodotto per versione, con dettaglio tecnico
- [backlog/geo-gap-ilmioposizionamento.md](backlog/geo-gap-ilmioposizionamento.md) — gap analysis con le decisioni annotate in prima persona
- [backlog/backlog.md](backlog/backlog.md) — note grezze
- [10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md) — debito tecnico verificato sul codice
