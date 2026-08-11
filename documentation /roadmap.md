# Roadmap — GEO Audit (Vertical AI)

Roadmap completa e dettagliata della piattaforma: cosa è già stato costruito,
cosa arriva dopo, con dipendenze e note tecniche. Versione interna — la
pagina pubblica `/roadmap` ne è la sintesi ad uso cliente.

---

## Disponibile oggi

### MVP — Le fondamenta
Login e prima analisi GEO del sito, con storico.

- Autenticazione passwordless via Supabase Auth (magic link email), nessuna password
- Motore di audit GEO (`geo_audit.py`): crawl, controlli deterministici su 6 macro-aree
  (Rendering & accesso, Dati strutturati, Meta & social, HTML semantico, Contenuti &
  answerability, Autorità & trust), punteggio 0-100, report HTML/PDF
- Salvataggio audit su Supabase con associazione all'utente loggato
- Dashboard "Project Portfolio": card per progetto con punteggio corrente, stato
  (Healthy / Needs attention / Critical / Audit required), ricerca e filtri

### v1.1 — Intelligence di progetto
Ogni sito diventa un progetto con una sua storia nel tempo, non solo l'ultimo scan.

- Modello dati **Account → Progetto → Sito**: tabella `project`, `audits` estesa con
  `project_id` e colonne strutturate (`areas`, `site_checks`, `pages_detail`, `actions`,
  `issues_count`, `critical_count`)
- Pagina di dettaglio progetto con overview, punteggio per area, salute controlli,
  quick win e interventi prioritari, elenco pagine con score e criticità
- Tabella `issue` con ciclo di vita persistente (fingerprint stabile su check+URL,
  `first_seen`/`last_seen`/`status`/`resolved_at`): le issue vengono aperte,
  aggiornate o marcate risolte automaticamente ad ogni nuovo audit dello stesso progetto
- Storico audit e delta di punteggio tra un'analisi e la successiva sullo stesso sito
- Sezione Technical GEO (crawler AI, robots.txt, sitemap, llms.txt, HTTPS, canonical,
  render parity) e sezione dati strutturati/entity (JSON-LD, sameAs, contatti, social)

### v1.2 — Esperienza e coerenza
Stesso prodotto, navigazione più chiara e look coerente ovunque.

- IA della dashboard di progetto raggruppata in 5 categorie (Overview, Audit, AI
  Intelligence, Traffic & Reports, Settings) invece di 12 voci piatte; le categorie non
  ancora disponibili sono marcate "soon" già nel menu
- Overview con riepilogo di ogni sezione (numero in evidenza + link al dettaglio), mai
  dati simulati per le sezioni non disponibili — solo blocco "coming soon" esplicito
- Tema chiaro/scuro con toggle in header, preferenza salvata in localStorage, su tutte
  le pagine di prodotto **e** sul report completo (che aveva uno stile proprio,
  riallineato mantenendo intatta la resa in stampa/PDF)
- Coerenza visiva: badge, colori soglia punteggio, componenti condivisi da
  `design-system.css`

### v1.3 — Tracking first-party → sblocca "AI Traffic"
Non solo un audit statico: sapere chi arriva davvero dal sito dagli assistenti AI.

- Snippet `static/js/geo-track.js` (sendBeacon, sessione via `sessionStorage`, eventi
  custom via `window.geoTrack(nome, props)`), da installare con un tag `<script data-project="...">`
- Endpoint pubblico `POST /t`, nessuna autenticazione (gira su siti di terzi),
  validazione minima e fallimento silenzioso per non rompere mai il sito del cliente
- Tabella `tracking_event` (project_id, event_name, session_id, page_url, referrer,
  ai_source, properties, created_at)
- Rilevamento provider AI dal referrer (ChatGPT, Perplexity, Gemini, Claude, Copilot,
  You.com, Meta AI — mappa estendibile in `_AI_REFERRER_DOMAINS`)
- Tab AI Traffic: sessioni totali e da AI (30gg), breakdown per provider, landing page
  più visitate da AI, andamento ultimi 14 giorni
- Settings: stato installazione (rilevato al primo evento ricevuto, nessun "ping" di
  verifica dedicato) e snippet pronto da copiare
- **Nota**: nessun rate-limiting dedicato sull'endpoint pubblico in questa prima
  versione — da valutare se il volume lo richiede

---

## Prossimi passi (in ordine)

### v2.0 — LLM monitoring → sblocca "AI Visibility" e "Prompts & Queries"
Quanto e come il brand viene menzionato dai principali assistenti AI.

- Panel di prompt controllati da interrogare periodicamente sui provider AI (ChatGPT,
  Gemini, Perplexity)
- Motore di monitoraggio: cluster prompt, mention rate, visibility by provider/topic,
  trend, storico risposte
- **Dipendenze**: costo/accesso alle API dei provider LLM, un job schedulato (cron),
  metodologia di campionamento da definire e validare **prima** di esporre i numeri.
  Per esplicita indicazione di prodotto, queste metriche non vanno fuse nel GEO Score
  deterministico finché la metodologia non è stabile

### v2.1 — Competitors + Citations
Come ci si posiziona rispetto a chi compete nelle stesse risposte AI.

- Share of Voice, gap competitivi, competitor emergenti
- Citation rate, URL citati, top cited pages
- **Dipendenze**: v2.0 (riusa lo stesso panel/motore), serve anche un modo per
  registrare/gestire la lista competitor per progetto

### v2.2 — Accuracy + off-site
Verificare che le AI raccontino il brand in modo corretto, dentro e fuori dal sito.

- Ground truth per progetto (fatti verificati sul brand) confrontato con quanto l'AI
  "crede" — attributi associati, claim, accuracy
- Presenza off-site: Wikipedia/Wikidata, profili, autorevolezza, citazioni di terzi
- **Dipendenze**: una knowledge base di ground truth da qualche parte, crawl/API
  esterne controllate

---

## Trasversali (non ancora in sequenza, nessuna dipendenza bloccante)

### KPI e data provenance
Applicabile a qualunque modulo, può partire già oggi sui dati AUDIT esistenti.

- Badge per ogni KPI: **AUDIT** (dato dal crawler deterministico) · **MEASURED** (dato
  osservato sul sito) · **MONITORED** (test ripetibili su panel LLM) · **PLATFORM**
  (integrazione esterna) · **ESTIMATED** (dato inferito/modellato)
- Ogni KPI mostra formula, sorgente, periodo e last updated
- Principio: mai usare espressioni tipo "ricerche su ChatGPT" quando il dato è in
  realtà un referral identificato o un panel monitorato

### Hardening dell'audit engine
Lavoro puro su `geo_audit.py`, nessuna dipendenza esterna, migliora da subito
Technical GEO e Opportunities.

- Canonical consistency, hreflang dove applicabile
- HTTP status / redirect chain
- Schema validity/duplication più approfondita
- Conflitti robots / meta-robots
- Copertura sitemap
- Segnali di contenuto duplicato / thin-content
- Page identity / entity consistency
- Timestamp e versione engine per ogni singolo check (oggi solo a livello di audit_run)

### Reports & alerts
- Variazioni, anomalie, milestone cross-modulo
- **Dipendenze**: ha senso solo quando almeno un altro modulo (tracking o LLM
  monitoring) è vivo — oggi non c'è nulla da cui generare alert

---

## Verticale — Hospitality
Layer opzionale sopra lo stesso modello di progetto (ogni hotel resta un
progetto/sito indipendente).

- Prompt taxonomy dedicata (luxury, family, spa, business, destination, near POI,
  amenities, wedding/conference, ecc.)
- Hotel ground truth: nome, indirizzo, coordinate, stelle, check-in/out, ristoranti,
  spa, pool, parking, pet policy, amenities
- Destination Visibility: visibilità per destinazione e cluster geografici
- Recommendation Share: presenza nei prompt di raccomandazione hotel
- Amenity Knowledge: accuratezza della conoscenza AI dei servizi
- Hotel competitor gap: confronto con strutture concorrenti per query/destinazione
- *(fase successiva)* Booking funnel (click/start/room selection/checkout/completed
  booking) e Group roll-up (vista aggregata solo quando i progetti sono comparabili)
- **Dipendenze**: tutto quanto sopra, in particolare v2.0 per il panel prompt — è
  l'ultimo livello del piano
