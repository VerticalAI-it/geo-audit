# 01 · Il prodotto

## Cos'è

**GEO Audit** è la piattaforma di Vertical AI per la **Generative Engine
Optimization**: misura quanto un sito è leggibile, citabile e consigliabile dagli
assistenti AI (ChatGPT, Gemini, Claude, Perplexity) e indica cosa correggere.

Non è un tool SEO. La differenza sostanziale: la SEO ottimizza per *comparire in
una lista di link*, la GEO ottimizza per *essere la fonte che l'assistente legge,
sintetizza e cita nella risposta*. Cambiano i segnali che contano — dati
strutturati, parità del contenuto senza JavaScript, accesso dei crawler AI in
`robots.txt`, contenuti in forma di domanda/risposta — e cambia il modo di
misurare l'esito.

## Per chi

| Segmento | Uso |
|---|---|
| **PMI italiane** (target primario) | Report gratuito autoservito dalla landing: capiscono di avere un problema |
| **Clienti Vertical AI** | Dashboard multi-progetto con storico, issue tracking, traffico AI |
| **Team Vertical AI** | Strumento di prevendita: il report è il gancio commerciale |

Il prodotto oggi è tutto in **italiano**, senza i18n.

## Come lo usa un cliente, oggi

```
Landing (/)  →  login magic link  →  form URL  →  audit sincrono (~30-60s)
                                                          ↓
                                          report HTML completo (/r/{id})
                                                          ↓
                                        dashboard progetti (/dashboard)
                                                          ↓
                                  dettaglio progetto (/project/{id}) — 12 tab
                                                          ↓
                              audit automatico ricorrente (cron giornaliero)
```

Il **login è obbligatorio** prima di poter lanciare un audit: è la scelta che ha
trasformato il tool da "generatore di report anonimi" a piattaforma con account,
progetti e storico. Il flusso anonimo con gate email esiste ancora ma solo come
retrocompatibilità per i report generati prima ([05 ·
Applicazione web](05-applicazione-web.md#il-doppio-regime-dei-report)).

---

## Cosa è disponibile oggi

### ✅ Motore di audit deterministico

31 check distinti su 6 macro-aree (5 a livello di sito, 26 di pagina), punteggio
0-100, report HTML autoconsistente con infografiche SVG. Nessun LLM coinvolto:
tutti i check sono deterministici e riproducibili. Catalogo completo in
[03 · Audit engine](03-audit-engine.md#catalogo-completo-dei-check).

| Macro-area | Cosa misura |
|---|---|
| Rendering & accesso | Crawler AI sbloccati, HTTPS, robots/sitemap/llms.txt, parità senza JS |
| Dati strutturati | JSON-LD presente/valido, tipi ad alto valore, `sameAs`, completezza |
| Meta & social | Title, description, canonical, Open Graph, Twitter card, `lang` |
| Contenuti & answerability | H1, gerarchia, profondità, titoli-domanda, liste/tabelle, TL;DR, freschezza |
| HTML semantico | `main`/`article`/`section`, alt text |
| Autorità & trust | Contatti, profili social, indicazione autore |

### ✅ Account e progetti

Autenticazione passwordless via Supabase Auth (magic link, nessuna password).
Modello **Account → Progetto → Sito**: ogni dominio analizzato diventa un
progetto con la sua storia nel tempo.

### ✅ Dashboard portfolio

Card per progetto con punteggio corrente, delta rispetto all'audit precedente,
stato calcolato (Healthy / Needs attention / Critical / Audit required), ricerca
e filtri.

### ✅ Dettaglio progetto

12 tab raggruppati in 5 categorie. Cinque sono su dati reali (Overview, Audit,
Pages, Technical GEO, Opportunities), uno è su dati reali quando lo snippet è
installato (AI Traffic), Settings è operativo, cinque sono esplicitamente
"coming soon" ([05 · Applicazione web](05-applicazione-web.md#i-12-tab-di-progetto)).

### ✅ Ciclo di vita delle issue

Le criticità non sono un'istantanea: hanno un `first_seen` / `last_seen` /
`resolved_at` con fingerprint stabile su `check_id + URL`. Ad ogni nuovo audit
dello stesso progetto vengono aperte, aggiornate o marcate risolte
automaticamente. È quello che permette di dire *"questa issue è aperta da 40
giorni"* invece che *"oggi ci sono N problemi"*.

### ✅ Storico punteggio

Grafico interattivo SVG con filtri 3 mesi / 6 mesi / tutto, renderizzato lato
client per evitare round-trip al server sui cambi di filtro.

### ✅ Tracking first-party → AI Traffic

Snippet JS proprietario (`static/js/geo-track.js`, ~1.5 KB) che il cliente
installa sul proprio sito. Rileva le sessioni provenienti da assistenti AI
leggendo il referrer e alimenta la tab **AI Traffic**: sessioni totali e da AI,
breakdown per provider, landing page più visitate da AI, andamento a 14 giorni.

Provider riconosciuti: ChatGPT, Perplexity, Gemini, Claude, Copilot, You.com,
Meta AI (mappa estendibile in `_AI_REFERRER_DOMAINS`, [server.py:246](../server.py#L246)).

### ✅ Audit automatici ricorrenti

Cadenza per progetto (giornaliera / settimanale / mensile) con claim atomico
anti-concorrenza. Il cron gira una volta al giorno alle 03:00 UTC e recupera fino
a 3 progetti scaduti per invocazione.

### ✅ Email transazionali

9 template allineati al design system, inviati via Resend. 5 sono agganciate a un
trigger raggiungibile, 4 sono pronte ma orfane o irraggiungibili
([06 · Email](06-email.md)).

### ✅ Pagine legali e SEO tecnica

Privacy policy, cookie policy con banner, `/robots.txt`, `/sitemap.xml`,
`/llms.txt` — quest'ultimo è anche un atto di coerenza: il tool che raccomanda
`llms.txt` ce l'ha.

---

## Cosa NON è disponibile

Sono tutte assenze **note e volute**.

> **Aggiornamento 1 settembre 2026.** Fino ad allora queste sezioni mostravano
> una scatola vuota che dichiarava cosa mancava, per la regola «mai dati
> simulati». La regola è cambiata: ora mostrano **dati dimostrativi con un
> banner esplicito** che dice a chiare lettere che non sono misurazioni del sito
> in esame. Motivo: una scatola vuota non fa capire al cliente cosa otterrà
> attivando la funzione.
>
> Il banner è obbligatorio, e il principio di fondo resta: **un dato mostrato
> senza etichetta dev'essere un dato misurato.** Vedi `CLAUDE.md`.

| Funzionalità | Perché non c'è | Sbloccato da |
|---|---|---|
| **AI Visibility** | Serve un panel di prompt da interrogare periodicamente sui provider LLM | v2.0 |
| **Prompts & Queries** | Idem | v2.0 |
| **Competitors** | Serve lo stesso panel + gestione lista competitor | v2.1 |
| **Citations** | Serve l'osservazione delle citazioni nelle risposte AI | v2.1 |
| **Reports & alerts** | Non c'è ancora nulla da cui generare un alert | almeno un modulo di monitoraggio |
| **Piani a pagamento** | Nessuna logica di billing/entitlement nel codice | decisione di prodotto presa, non implementata |
| **Scoring per motore** | Oggi c'è un punteggio unico aggregato | v2.0 + decisione free/paid |
| **Presenza off-site** | Serve integrazione Wikipedia/Wikidata + dati backlink | v2.2 |

Il gap più grande, in una riga: **oggi misuriamo la *predisposizione* di un sito a
essere citato, non se venga *effettivamente* citato.** Tutto il blocco v2.x serve
a chiudere quel gap. Vedi [11 · Next steps](11-next-steps.md).

---

## Modello di business (stato delle decisioni)

Le decisioni sono state prese nella gap analysis
([backlog/geo-gap-ilmioposizionamento.md](backlog/geo-gap-ilmioposizionamento.md))
ma **non sono ancora implementate**:

- **Free**: punteggio aggregato, report completo, roadmap 90gg solo come teaser.
  Le funzionalità paid appaiono come placeholder greyed-out — servono da upsell.
- **Paid**: punteggio aggregato + differenziazione per motore, monitoraggio
  citazioni, competitor, roadmap completa.
- **Competitor**: inserimento manuale; l'auto-discovery resta un pulsante marcato
  "coming soon".
- **Monitoraggio LLM**: preferenza per l'integrazione di un servizio esterno
  (meglio se gratuito, ma il budget è aperto) invece del build in-house.

Nel codice non esiste oggi alcun concetto di piano, entitlement o billing.
