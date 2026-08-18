# Gap analysis — articolo ilmioposizionamento.it vs GEO Audit

Fonte: https://www.ilmioposizionamento.it/farsi-trovare-citare-scegliere-intelligenza-artificiale/
Analisi fatta il: 2026-08-08

Confronto tra cosa dice l'articolo (fattori che determinano se un sito viene trovato/citato/scelto
dalle AI) e cosa analizza oggi il nostro prodotto (`geo_audit.py` = check on-page, `server.py` =
dashboard/progetti a 12 tab).

Legenda: ✅ copriamo già · 🟡 copriamo in parte / superficialmente · ❌ non copriamo

---

## 0. Cosa copriamo già bene (nessuna azione richiesta)

- ✅ Blocco crawler AI in robots.txt (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, ecc.) — `crawl.ai`
- ✅ sitemap.xml, llms.txt, HTTPS
- ✅ Presenza/validità JSON-LD, tipi ad alto valore (Article, FAQPage, Organization, Person...), `sameAs`
- ✅ H2 in forma di domanda (il pattern che l'articolo indica come preferito da ChatGPT)
- ✅ TL;DR/riassunto iniziale (proxy della "atomic answer")
- ✅ Liste/tabelle come "formati estraibili"
- ✅ Parità contenuto statico/renderizzato via Playwright (critico: molti bot AI non eseguono JS)
- ✅ Segnali E-E-A-T di base: contatti, social, indicazione autore, HTML semantico

Questi punti sono già allineati con le checklist ChatGPT/Perplexity dell'articolo. Il gap non è
qui: è quasi tutto negli **outcome reali** (le AI mi citano davvero?) e in alcuni check on-page più
fini che oggi sono solo euristiche testuali.

---

## A. GAP PRIORITARIO — Monitoraggio delle citazioni reali (canary queries)

Questo è il gap più grande. L'articolo costruisce l'intera metodologia (citation share, brand
mention rate, source frequency, roadmap 90gg) attorno all'**osservazione periodica delle risposte
reali dei LLM**, non solo su check statici della pagina. Nella dashboard questo coincide 1:1 con i
tab già previsti ma marcati "coming soon": **AI Visibility, Prompts & Queries, Citations**.

- [ ] Definire un set di canary query non-branded per progetto (intento informazionale, verticali di
      settore — l'articolo dà criteri precisi di selezione)
- [ ] Interrogare periodicamente ChatGPT, Perplexity, Gemini, Claude con quel set e registrare:
      brand citato sì/no, posizione nella risposta, URL citato
- [ ] Calcolare i 3 KPI dell'articolo: **Citation Share** (% query con citazione), **Brand Mention
      Rate** (frequenza), **Source Frequency** (quante volte lo stesso URL è citato come fonte)
- [ ] Frequenza differenziata per motore: Perplexity settimanale, ChatGPT/Gemini mensile (l'articolo
      motiva questo con le diverse latenze di indicizzazione: Perplexity 2-8 settimane, ChatGPT/Gemini
      4-12 settimane, Claude 3-6+ mesi)
- [ ] Sbloccare i tab "AI Visibility", "Prompts & Queries", "Citations" con questi dati

**💬 Tuoi commenti:** questa è una scelta build-vs-buy con impatto diretto su costi e roadmap.
L'articolo cita tool verticali già pronti (BrandRank.ai, Profound, Otterly, Peec AI) e anche
Semrush AI Toolkit come opzione "SEO tradizionale con GEO integrato". Alternativa: costruirlo
in-house chiamando direttamente le API di OpenAI/Anthropic/Perplexity/Google con i nostri prompt.
Trade-off: build interno = controllo pieno e margine più alto ma costo ingegneristico e gestione
rate-limit/costi token; tool terzi = time-to-market rapido ma revenue share/licenza e meno
controllo sul dato. Scrivi qui la tua preferenza e il budget mensile che hai in mente:

_
Valuterei la possibilità di integrare uno dei servizi esterni, meglio se gratuito ma valutiamo i costi senza problemi. Importante che porti un valore reale. 
_

---

## B. Competitors / Share of Voice

Il tab "Competitors" è coming soon e dipende dallo stesso panel di canary query del punto A
(l'articolo non tratta la competitive analysis come modulo separato, ma la mail di follow-up del
report promette già "confronto con i concorrenti diretti" — quindi è una promessa da mantenere).

- [ ] Aggiungere ai progetti un campo "competitor URLs" (manuale) oppure un discovery automatico
- [ ] Nel calcolo del citation share, tracciare anche quando la risposta cita un competitor invece
      del cliente → Share of Voice
- [ ] Sbloccare il tab "Competitors" con gap competitivi (query dove il competitor è citato e noi no)

**💬 Tuoi commenti:** competitor a inserimento manuale (più semplice, ma richiede che il cliente li
sappia indicare) o auto-discovery (es. dai risultati organici top 10 per le stesse query, dato che
l'articolo conferma che l'80-90% delle fonti AI Overview viene dalla top 10 organica)? Il secondo
richiede un accesso a dati SERP (vedi anche punto F più sotto sul check "posizionamento organico
prerequisito"). Indica qui la preferenza:

_ Inserimento manuale _ manteniamo autodiscovery come sviluppo futuro e manteniamo un tasto "Autodiscovery" con tag coming soon. 

---

## C. AI Traffic (referral tracking)

Tab coming soon, richiede uno snippet di tracking first-party non ancora installato sui siti dei
clienti.

- [ ] Progettare snippet JS leggero da far installare al cliente (come il pixel di GA) che riconosce
      i referrer da chatgpt.com, perplexity.ai, gemini.google.com, copilot.microsoft.com, claude.ai
- [ ] Dashboard "AI Traffic": sessioni/eventi per motore nel tempo

**💬 Tuoi commenti:** snippet proprietario (dato pulito, ma serve installazione + privacy/consenso
da gestire) vs leggere i referrer da Google Analytics 4 se il cliente lo ha già installato (zero
setup aggiuntivo, ma dipendenza da GA4 e dati meno granulari)? Oppure entrambi, con GA4 come
fallback quando lo snippet non è installato? Indica qui la direzione preferita:

_ Abbiamo già uno snippet che facciamo istallare ai nostri clienti, capiamo se serve estenderlo, ma esiste già _

---

## D. Check on-page da aggiungere/approfondire in `geo_audit.py`

Questi non richiedono nuova infrastruttura di monitoraggio, sono estensioni del motore di scan
esistente — coerenti con checklist molto specifiche dell'articolo che oggi copriamo solo in modo
euristico o per nulla.

- [ ] **Core Web Vitals (CLS, LCP)**: oggi non misuriamo performance. L'articolo cita dati concreti
      (CLS > 0,1 → -29,8% inclusione in AI Overview; LCP > 2,5s → probabilità 1,47x inferiore).
      Nuovo check `perf.cls` / `perf.lcp`.
- [ ] **Atomic answer quality**: oggi rileviamo solo la presenza di un TL;DR/H2-domanda con regex.
      L'articolo chiede una struttura precisa (40-80 parole: affermazione diretta + dato/fonte +
      contesto). Serve uno scoring più fine del primo paragrafo, non solo presenza/assenza.
- [ ] **FAQPage: validazione lunghezza risposta** (50-100 parole in `acceptedAnswer`) e coerenza tra
      testo visibile e JSON-LD — oggi controlliamo solo che `FAQPage.mainEntity` esista.
- [ ] **`dateModified` esplicito nello schema Article** come check dedicato — oggi `content.fresh` è
      un regex generico ("aggiornat...", tag `<time>`), non verifica lo schema strutturato che
      l'articolo indica come segnale di freschezza primario per Perplexity/Gemini.
- [ ] **Dati numerici attribuiti a fonte** con cadenza (l'articolo suggerisce ogni 200-300 parole) —
      non rilevato oggi.
- [ ] **Contenuto critico bloccato in accordion/PDF**: l'articolo segnala che i LLM spesso non
      espandono accordion né leggono PDF linkati — nuovo check che verifica se sezioni chiave sono
      raggiungibili solo così.
- [ ] **Schema Person più ricco**: oggi controlliamo solo `sd.sameas` generico a livello di blocco
      JSON-LD. L'articolo vuole `sameAs` specificamente verso Wikipedia/Wikidata/Google
      Scholar/LinkedIn e una pagina autore dedicata (`/autori/nome/`) con bio 100-150 parole.

---

## E. Differenziazione per motore (ChatGPT / Gemini / Claude / Perplexity)

Oggi il report dà **un punteggio unico** con raccomandazioni generiche. L'articolo tratta i 4 motori
come target distinti con criteri, pesi e persino lunghezze di contenuto diverse (es. Claude preferisce
1.500-3.000 parole e tono anti-iperbolico, Perplexity vuole data di aggiornamento visibile e titoli
descrittivi, ecc.).

- [ ] Valutare uno scoring per-motore (4 sotto-punteggi) invece di un unico score aggregato
- [ ] Raccomandazioni segmentate per motore nella sezione "Interventi prioritari"

**💬 Tuoi commenti:** questo è un cambio di prodotto non banale — rischia di appesantire il report
gratuito (che oggi è volutamente snello e orientato alla conversione) o è meglio riservare la vista
per-motore alla dashboard/piano a pagamento, tenendo il report gratuito con lo score unico attuale
come teaser? Indica qui la preferenza:

_ giusto, cominciamo a differenziare i piani, gratuito solo score aggregato, paid invece da sia punteggio aggregato che differenziazione per motore (in quello gratuito mettiamo comunque il placeholder grigettatto, perchè anche se non lo calcoliamo e quindi non lo mostriamo ci serve come upsell strategy) _

---

## F. Entity & autorevolezza off-site

Il report attuale lo dichiara già esplicitamente in coda ("Fase 2: analisi semantica dei contenuti
via LLM e presenza off-site — Wikipedia/Wikidata, citazioni di terzi, visibilità reale nelle
risposte AI") — quindi è un gap noto e già preso in carico concettualmente, solo non ancora
costruito.

- [ ] Verifica automatica presenza dell'entità (brand/autore) su Wikipedia/Wikidata/Google Scholar
- [ ] Citation diversity: co-citazioni da fonti indipendenti/domini tematicamente affini (richiede
      dati di backlink — Ahrefs/Semrush/Moz API)
- [ ] Check "posizionamento organico top 10" come prerequisito, dato che l'80-90% delle fonti AI
      Overview arriva da lì secondo l'articolo (richiede accesso a dati SERP)

**💬 Tuoi commenti:** sia il backlink data sia i dati SERP sono a pagamento (Ahrefs/Semrush/DataForSEO
ecc.) e voci di costo ricorrenti per query. Vale la pena integrarli subito o solo quando ci sarà un
piano a pagamento che li giustifichi? Indica qui priorità e budget:

_ inseriamo ora la parte a pagamento e come prima, mettiamo le cose a pagamento. analizziamo come impostare per un cliente i progetti e settare se metterli a pagamento o gratuiti. potremmo gestirli dalla nostra dashboard e capire come renderli poi disponibili per il cliente _

---

## G. Roadmap 90 giorni come deliverable di prodotto

L'articolo propone una metodologia operativa completa in 3 fasi da 30 giorni (audit e fondamenta →
contenuto e autorevolezza → ottimizzazione LLM-specifica e misurazione). Potremmo trasformarla in un
output automatico del nostro tool invece che lasciarla come solo contenuto editoriale.

- [ ] Generare automaticamente, a partire dai check falliti/da migliorare, una roadmap 90gg (Fase 1/2/3
      con settimane e output attesi) nel tab "Opportunities" o "Reports"

**💬 Tuoi commenti:** la roadmap generata va offerta come teaser anche nel report gratuito (per
spingere la conversione, sulla falsariga del CTA attuale "ci occupiamo noi di tutto") oppure sbloccata
solo per i clienti che attivano il monitoraggio/servizio a pagamento? Indica qui la preferenza:

_ solo teaser su gratuito e greyed out il resto. tutto visibile su paid_

---

## Riepilogo priorità consigliata

1. **A — Monitoraggio citazioni reali**: è il gap più grande e sblocca da solo 3 tab già presenti in
   UI ma vuoti. È anche la promessa già fatta nel CTA del report attuale ("monitoriamo i progressi nel
   tempo").
2. **D — Check on-page mancanti** (Core Web Vitals, FAQPage, dateModified, Person/sameAs): a basso
   sforzo relativo perché estendono un motore di scan già esistente, nessuna nuova infrastruttura.
3. **C — AI Traffic** e **B — Competitors**: dipendono in parte da A, da sequenziare dopo.
4. **F — Entity off-site** e **E — Differenziazione per motore**: valore alto ma costi
   ricorrenti/rework di prodotto — da valutare in base ai commenti sopra prima di stimare l'effort.
5. **G — Roadmap 90gg automatica**: rifinitura finale, utile soprattutto come leva di conversione una
   volta che A è in piedi (senza dati di monitoraggio la roadmap sarebbe solo statica/genérica).
