# 12 · Scoring: come è calcolato e dove guardare per verificarlo

Questo documento isola **solo l'algoritmo di scoring** — la formula, il peso di
ogni check, come i pesi si aggregano in un punteggio — con l'obiettivo di poterne
verificare la coerenza. È un complemento di [03 · Audit engine](03-audit-engine.md),
non un sostituto: qui si scende nel dettaglio numerico (quanto pesa cosa, cosa
succede quando N pagine si sommano) e si segnalano alcune incoerenze trovate
confrontando codice e documentazione esistente.

Tutti i riferimenti sono a `geo_audit.py`, verificati contro l'HEAD del branch
`claude/scoring-algorithm-docs-a6i61l` (allineato a `main`).

---

## 1. La formula

[geo_audit.py:413-418](../geo_audit.py#L413-L418):

```python
def score_checks(checks):
    frac = {OK: 1.0, WARN: 0.5, FAIL: 0.0}; num = den = 0.0
    for c in checks:
        if c.status in frac:
            den += c.weight; num += c.weight * frac[c.status]
    return round(100 * num / den) if den else 0
```

Media pesata a tre livelli (`ok`=1, `warn`=0.5, `fail`=0), con arrotondamento
finale all'intero più vicino. Due proprietà da tenere presenti quando si valuta
se un peso "conta" davvero:

- **I check `unknown` sono invisibili alla formula**: non entrano né al
  numeratore né al denominatore. Non è un dettaglio da poco — vedi §4.3 e §4.4:
  due dei check più pesanti del catalogo (`render.parity`, peso 8, e talvolta
  `page.noindex`, peso 6) finiscono spesso in `unknown` proprio in produzione.
- **La severità (`severity`) non entra mai nella formula.** Determina solo colore
  e ordinamento nella UI (vedi §3). Un check `critical` e uno `info` con lo
  stesso peso contano *esattamente* uguale nel punteggio: la parola "critico" è
  una spiegazione data all'utente, non un moltiplicatore applicato al calcolo.

Il punteggio complessivo (`overall`, [geo_audit.py:698](../geo_audit.py#L698))
si ottiene applicando `score_checks` a **`site_checks` + tutti i check di tutte
le pagine analizzate, concatenati in un'unica lista**
([geo_audit.py:918](../geo_audit.py#L918)). Non è una media di medie (non è
`media(overall_pagine)`): è un'unica somma pesata su ogni singolo check emesso
nell'intero audit. Questo è il fatto strutturale da cui discende tutto il §4.

Il punteggio per **area** (`compute_area_scores`,
[geo_audit.py:686-694](../geo_audit.py#L686-L694)) applica la stessa identica
formula, ma raggruppando i check per `category` invece che su tutti insieme. Il
punteggio per **pagina** (`Page.score`, assegnato in `analyze_page`,
[geo_audit.py:451-460](../geo_audit.py#L451-L460)) la applica solo ai check di
quella pagina — **non include mai i 5 check di sito**, che vivono solo
nell'`overall` e nei punteggi per area.

---

## 2. Il tipo `Check` e i suoi campi

[geo_audit.py:79-82](../geo_audit.py#L79-L82):

```python
@dataclass
class Check:
    id: str; category: str; title: str; status: str
    weight: int = 1; severity: str = "medium"; detail: str = ""; recommendation: str = ""
```

- `weight` è **sempre passato esplicitamente** a ogni `ck(...)` nel codice: non
  c'è nessun check che si affida silenziosamente al default `1`. Verificato
  check per check nel catalogo del §5.
- `severity` **non sempre** è passato esplicitamente: quando manca, vale
  `"medium"` (es. `crawl.sitemap`, `content.len`, `content.struct`, `meta.og`,
  `trust.contact`, `sd.highvalue`). Questo è coerente con la tabella del
  catalogo in [03](03-audit-engine.md), ma vale la pena saperlo perché non è
  visibile leggendo solo l'ID del check.
- `status` ∈ `ok | warn | fail | unknown`. Solo i primi tre pesano sul punteggio.

---

## 3. Le scale di lettura del punteggio — tre, non due

Il prodotto usa **tre soglie diverse** sullo stesso numero 0-100, per scopi
diversi:

| Scala | Dove | Soglie | Definita in |
|---|---|---|---|
| **Grade** (lettera) | Report `geo_audit.py` | A ≥90 · B ≥75 · C ≥60 · D ≥45 · E ≥30 · F | [`grade()`, geo_audit.py:420](../geo_audit.py#L420) |
| **Band** (etichetta) | Report `geo_audit.py` | Eccellente ≥90 · Buono ≥75 · Discreto ≥60 · Da rafforzare ≥45 · Critico | [`band()`, geo_audit.py:421](../geo_audit.py#L421) |
| **Colore** | Report + dashboard | Verde ≥75 · Ambra ≥50 · Rosso <50 | [`barcol()`, geo_audit.py:473](../geo_audit.py#L473) e `views.py` |

Grade/Band sono a 6 fasce e servono per la lettura "editoriale" del report.
Il colore è a 3 fasce e serve per lo scan rapido (gauge, dashboard, email).
Sono scale intenzionalmente diverse — non è un bug che un punteggio 65 sia
"Discreto/C" e contemporaneamente verde.

**Verifica fatta in questa sessione:** [10 · Stato e debito
tecnico](10-stato-e-debito-tecnico.md#soglie-colore-incoerenti) elenca come
debito aperto il fatto che `geo_audit.barcol()` userebbe **55** invece di 50
come soglia intermedia, mentre `_score_class()`/`_score_band()` in `server.py`
e `views.py` userebbero 50 — con l'esempio "52 giallo in dashboard, rosso nel
report". **Non è più così nel codice attuale**: `barcol()` a
[geo_audit.py:473](../geo_audit.py#L473) usa `s>=50`, identico a
[`views.py:1105`](../views.py#L1105) (`v >= 50`) e a
[`views.py:529`](../views.py#L529) (`overall >= 50`). O il bug è stato corretto
senza aggiornare `10-stato-e-debito-tecnico.md`, o la mia lettura del commit
citato lì (`b29a35d`) differisce dall'HEAD attuale — in ogni caso **la voce #13
di quel documento va riverificata prima di fidarsene**: oggi le tre soglie
colore risultano allineate a 50.

---

## 4. Il catalogo dei pesi

### 4.1 Check di sito (una volta per audit)

[`build_site_checks()`, geo_audit.py:866-884](../geo_audit.py#L866-L884):

| ID | Peso | Severità | Sempre emesso? |
|---|---:|---|---|
| `crawl.ai` | **12** | `critical` | sì |
| `crawl.https` | 3 | `high` | sì |
| `crawl.sitemap` | 3 | `medium` (default) | sì |
| `crawl.robots` | 2 | `low` | sì |
| `crawl.llms` | 1 | `info` | sì |
| **Totale sito** | **21** | | |

`crawl.ai` è l'unico check `critical` del catalogo e [03 · Audit
engine](03-audit-engine.md#livello-sito--eseguiti-una-volta-per-audit) lo
definisce "il check più pesante e l'unico `critical`... a ragione: se
robots.txt blocca GPTBot, tutto il resto è irrilevante". Il §4.5 quantifica
quanto questa intenzione sia effettivamente rispettata dal numero finale.

### 4.2 Check di pagina — per categoria

Raggruppati come li raggruppa `compute_area_scores` (per `category`), con nota
su quali sono condizionali (non sempre emessi).

**Rendering & accesso** — [`checks_indexing()`, geo_audit.py:373-391](../geo_audit.py#L373-L391) e [`check_js_parity()`, geo_audit.py:393-410](../geo_audit.py#L393-L410)

| ID | Peso | Severità | Condizione di emissione |
|---|---:|---|---|
| `render.parity` | **8** | `high` | sempre emesso, ma **`unknown` se il rendering non è stato eseguito** |
| `page.noindex` | 6 | `medium`/`info`/**`unknown`** | `unknown` (severità `high`) se noindex non atteso su pagina non di servizio |
| `page.status` | 4 | `high` | sempre |
| Totale nominale | **18** | | |

**Dati strutturati** — [`checks_structured()`, geo_audit.py:230-262](../geo_audit.py#L230-L262)

| ID | Peso | Severità | Condizione di emissione |
|---|---:|---|---|
| `sd.present` | **18** | `high` | sempre |
| `sd.highvalue` | 6 | `medium` (default) | solo se ≥1 blocco JSON-LD |
| `sd.valid` | 4 | `high` | solo se ≥1 blocco JSON-LD |
| `sd.completeness` | 4 | `low` | **solo se mancano proprietà richieste — vedi nota sotto** |
| `sd.sameas` | 3 | `low` | solo se ≥1 blocco JSON-LD |
| Totale se JSON-LD assente | **18** | | |
| Totale se JSON-LD presente e completo | **31** | | |
| Totale se JSON-LD presente e incompleto | **35** | | |

> ⚠️ **`sd.completeness` non può mai valere `ok`.** Vedi anche la sezione [Dati
> strutturati](03-audit-engine.md#livello-pagina--dati-strutturati) in 03. È
> costruito dentro
> `if miss:` ([geo_audit.py:254-257](../geo_audit.py#L254-L257)) con
> `status=WARN` fisso — se il blocco JSON-LD identificato ha tutte le
> proprietà richieste, il check semplicemente **non viene emesso**, non
> emesso-come-ok. È un check "solo penalità": esiste per segnalare un problema,
> mai per premiare la sua assenza. Da un punto di vista di coerenza dei pesi
> è corretto (non gonfia il punteggio quando tutto va bene), ma va tenuto a
> mente leggendo il totale "35" sopra: quel 35 non è mai il denominatore di un
> sito che ha *tutto* a posto, è il denominatore di un sito con *qualcosa* che
> manca.

**Contenuti & answerability** — [`checks_content()`, geo_audit.py:310-347](../geo_audit.py#L310-L347) (sempre tutti emessi)

| ID | Peso | Severità |
|---|---:|---|
| `content.h1` | 6 | `medium` |
| `content.len` | 5 | `medium` (default) |
| `content.q` | 4 | `low` |
| `content.struct` | 4 | `medium` (default) |
| `content.hier` | 3 | `low` |
| `content.tldr` | 3 | `low` |
| `content.fresh` | 2 | `low` |
| **Totale** | **27** | |

**HTML semantico** — split fra due funzioni (vedi nota in [03](03-audit-engine.md))

| ID | Peso | Severità | Condizione |
|---|---:|---|---|
| `sem.html` | 3 | `low` | sempre (`checks_eeat()`) |
| `content.alt` | 2 | `low` | solo se la pagina contiene `<img>` (`checks_content()`) |
| Totale | **3–5** | | |

**Meta & social** — [`checks_meta()`, geo_audit.py:273-308](../geo_audit.py#L273-L308) (sempre tutti emessi)

| ID | Peso | Severità |
|---|---:|---|
| `meta.description` | 5 | `high` se assente, `medium` altrimenti |
| `meta.title` | 4 | `medium` |
| `meta.og` | 3 | `medium` (default) |
| `meta.canonical` | 2 | `low` |
| `meta.lang` | 2 | `low` |
| `meta.twitter` | 1 | `low` |
| **Totale** | **17** | |

**Autorità & trust** — [`checks_eeat()`, geo_audit.py:349-371](../geo_audit.py#L349-L371) (sempre tutti emessi)

| ID | Peso | Severità |
|---|---:|---|
| `trust.contact` | 4 | `medium` (default) |
| `trust.social` | 3 | `low` |
| `trust.author` | 2 | `low` |
| **Totale** | **9** | |

### 4.3 Peso massimo teorico per pagina

Sommando i totali del §4.2 nelle condizioni "migliori" (JSON-LD presente e
completo, immagini presenti, rendering eseguito, noindex non ambiguo):

```
18 (rendering) + 31 (dati strutturati) + 27 (contenuti) + 5 (html semantico)
+ 17 (meta) + 9 (trust) = 107
```

**Ma in produzione il rendering non gira mai** (Vercel non ha Chromium — vedi
[10 · Stato e debito tecnico](10-stato-e-debito-tecnico.md#renderparity-non-viene-mai-calcolato-in-produzione)
e §4.4 sotto): `render.parity` è **sempre `unknown`**, quindi **sempre
escluso**. Il peso di pagina effettivamente in gioco su ogni audit reale è:

```
107 - 8 (render.parity, sempre unknown in prod) = 99
```

### 4.4 Cosa sparisce silenziosamente dallo scoring in produzione

Due check pesanti possono finire in `unknown` — e quindi, per costruzione
della formula (§1), **non contare affatto**, né in positivo né in negativo:

1. **`render.parity` (peso 8, severità `high`)** è `unknown` su *ogni* audit
   servito da Vercel, perché `render=False` in ogni chiamata a `run_audit` da
   `server.py` ([server.py:127](../server.py#L127),
   [1023](../server.py#L1023), [1333](../server.py#L1333),
   [1909](../server.py#L1909), [2273](../server.py#L2273)). È il segnale
   descritto nel codice come "uno dei più importanti per la GEO" — la parità
   di contenuto fra HTML statico e renderizzato — e oggi **non pesa mai** sul
   punteggio che l'utente vede, per nessun sito. Solo la CLI (`--out
   report.html` a mano) lo valorizza davvero.
2. **`page.noindex` (peso 6, severità `high`)** diventa `unknown` quando la
   pagina ha `noindex` e **non** è riconosciuta come pagina di servizio da
   `UTILITY_RE` ([geo_audit.py:387-391](../geo_audit.py#L387-L391)). È
   l'unico ramo dei tre in cui il check finisce `unknown` invece di `ok`/`fail`
   — e per costruzione **un noindex probabilmente involontario, il caso più
   grave, è quello che pesa zero sul punteggio finale** invece di penalizzarlo.
   Compare comunque nelle azioni consigliate (`derive_actions`), ma non nel
   numero.

Questi due casi meritano attenzione in una verifica dei pesi: non sono un
errore nella *definizione* del peso (8 e 6 sono ragionevoli), ma nel fatto che
la condizione più comune in produzione (`render.parity`) o il caso più grave
(`page.noindex` involontario) escludono il check dal calcolo invece di farlo
contribuire a favore o contro.

### 4.5 L'effetto diluizione — con numeri

Il denominatore cresce linearmente con le pagine analizzate (§1: non è media
di medie), mentre il totale di sito resta fisso a 21. Con il peso di pagina
"tipico" in produzione stimato al §4.3 (99, assumendo JSON-LD presente e
completo, immagini presenti — la variante più favorevole; scende a 86 se manca
il JSON-LD, perché resta solo `sd.present`):

| Contesto | N pagine | Denominatore stimato (21 + 99·N) | Peso di `crawl.ai` (12) sul totale |
|---|---:|---:|---:|
| CLI, default | 20 | 2001 | 0,60 % |
| Produzione, audit standard | **6** | **615** | **1,95 %** |
| Produzione, form lead ([server.py:1023](../server.py#L1023)) | 4 | 417 | 2,88 % |
| Ipotetico, solo home | 1 | 120 | 10,0 % |

**Caso concreto — sito che blocca GPTBot/ClaudeBot/ecc. in robots.txt ma è
perfetto su tutto il resto**, nell'audit di produzione standard (6 pagine):

```
num = (615 − 12)·1.0 + 12·0.0 = 603
score = round(100 · 603 / 615) = 98   →  Grade A, "Eccellente", verde
```

Un sito che blocca esplicitamente ogni crawler AI conosciuto — il fallimento
che il codice stesso descrive come quello che rende "irrilevante" tutto il
resto — **ottiene comunque 98/100** in un audit di produzione reale, perché il
suo peso (12) è annegato in un denominatore di ~615. Con 4 pagine (flusso
lead) sale leggermente a ~97; solo analizzando la sola home (N=1, mai il caso
reale) si scende a 90.

Questo è già segnalato come debito noto in [03 · Audit
engine](03-audit-engine.md#formula) e in [10 · Stato e debito
tecnico](10-stato-e-debito-tecnico.md#lo-scoring-diluisce-i-check-di-sito): lo
riporto qui con il numero concreto (98, non "un punteggio comunque alto")
perché è il primo posto da controllare in una verifica di coerenza dei pesi —
il gap fra intento dichiarato nel codice ("il resto è irrilevante") e output
numerico effettivo è il più grande del sistema.

### 4.6 Punteggi non comparabili fra loro

Conseguenza diretta del §4.5: **lo stesso sito, analizzato con `max_pages`
diverso, produce punteggi diversi non per differenze reali nel sito ma solo
per quanto il totale di sito (21) si diluisce.** Nel codice attuale
`max_pages` cambia in base al punto di ingresso:

| Flusso | `max_pages` | `render` | Dove |
|---|---:|---|---|
| Audit standard (dashboard, `/audit`, cron) | 6 | `False` | [server.py:127](../server.py#L127), [1333](../server.py#L1333), [1909](../server.py#L1909), [2273](../server.py#L2273) |
| Form lead (senza account) | 4 | `False` | [server.py:1023](../server.py#L1023) |
| CLI | 20 (default, `--max-pages`) | `True` (se Playwright installato) | [geo_audit.py:887](../geo_audit.py#L887) |

Confrontare un punteggio ottenuto dal form lead (4 pagine) con uno della
dashboard (6 pagine) — o peggio con uno CLI (fino a 20 pagine, rendering
attivo) — **non è un confronto omogeneo**: cambia sia il denominatore (§4.5)
sia se `render.parity` (peso 8) è nel calcolo o no (§4.4). Se lo storico di un
progetto mescola audit fatti da flussi diversi, i trend che se ne leggono
possono riflettere il flusso usato, non un cambiamento reale del sito.

---

## 5. Aree, azioni, e cosa NON entra nel punteggio

- `compute_area_scores()` ([geo_audit.py:686-694](../geo_audit.py#L686-L694))
  applica la stessa formula del §1 filtrata per categoria — stesse regole,
  stesse esclusioni di `unknown`.
- `derive_actions_full()` ([geo_audit.py:664-684](../geo_audit.py#L664-L684))
  aggrega i check in `warn`/`fail` per `check_id`, li ordina per `SEV_ORDER`
  (`critical` < `high` < `medium` < `low` < `info`,
  [geo_audit.py:74](../geo_audit.py#L74)) e poi per frequenza discendente. Le
  azioni **non hanno un proprio punteggio**: sono una vista derivata dagli
  stessi check che alimentano `score_checks`, non un canale di scoring
  separato — non c'è doppio conteggio, ma nemmeno un modo per l'utente di
  vedere "quanto vale" un'azione se non tornando al peso del check da cui
  proviene.
- `SEV_PRIO` ([geo_audit.py:465-466](../geo_audit.py#L465-L466)) comprime
  `medium`, `low` e `info` tutti sull'etichetta "media" nel report: tre livelli
  di severità diventano due nella UI, mentre nel calcolo del punteggio (§1)
  la severità non ha mai contato comunque.

---

## 6. Scostamenti trovati fra documentazione e codice attuale

Verificando riga per riga per questo documento sono emersi tre disallineamenti
fra `docs/03-audit-engine.md` (o `docs/10`) e `geo_audit.py` — non riguardano
lo scoring in sé ma vale la pena segnalarli perché una lista di bot o di
schema letta dalla documentazione, se usata per giudicare "il sito X è
penalizzato correttamente perché blocca il bot Y", porterebbe a una verifica
sbagliata:

- **`AI_BOTS`** ([geo_audit.py:47-49](../geo_audit.py#L47-L49)) include oggi
  14 bot: oltre ai 10 elencati in [03](03-audit-engine.md#livello-sito--eseguiti-una-volta-per-audit), anche
  `Perplexity-User`, `Amazonbot` e `Meta-ExternalAgent`.
- **`SCHEMA_HIGH_VALUE`** ([geo_audit.py:51-54](../geo_audit.py#L51-L54))
  nel codice attuale include `QAPage`, `WebSite`, `AggregateRating`,
  `VideoObject` — assenti dalla tabella in [03](03-audit-engine.md#livello-pagina--dati-strutturati)
  — e **non** include `Recipe`, `Course`, `JobPosting`, che invece la tabella
  in [03](03-audit-engine.md#livello-pagina--dati-strutturati) elenca.
- La soglia colore `barcol()` (§3): il debito #13 in
  [10](10-stato-e-debito-tecnico.md#soglie-colore-incoerenti) descrive un
  disallineamento (55 vs 50) non riscontrabile nel codice attuale, che usa 50
  ovunque.

Questi tre punti sono discrepanze doc↔codice, non bug di scoring: li segnalo
qui perché chi verifica i pesi partendo dalla documentazione (invece che dal
codice, come fatto qui) rischia di validare contro liste sbagliate.

---

## 7. Checklist per la verifica

In sintesi, i punti su cui concentrare una revisione della calibratura dei
pesi, in ordine di impatto stimato:

1. **`crawl.ai` diluito a ~2% del punteggio in produzione** (§4.5) — se
   l'intento è che bloccare i crawler AI sia "irrilevante il resto", la
   formula attuale (media pesata unica su sito+pagine concatenati) non lo
   traduce in un numero coerente con quell'intento, a prescindere da quanto
   alto sia il peso nominale (12).
2. **`render.parity` sempre escluso in produzione** (§4.4.1) — un peso di 8
   pensato per uno dei segnali più importanti non influisce mai sul punteggio
   che utenti e dashboard vedono davvero.
3. **`page.noindex` involontario escluso invece che penalizzato** (§4.4.2).
4. **Punteggi non comparabili fra flussi con `max_pages` diverso** (§4.6) —
   rilevante se lo storico/trend di un progetto mescola audit da fonti diverse.
5. **`sd.completeness` come check solo-penalità** (§4.2) — corretto per
   costruzione ma da tenere presente leggendo i totali per area.
6. **Severità disaccoppiata dal punteggio** (§1) — se in futuro si vuole che
   "critical" pesi di più di "low" a parità di `weight`, oggi non succede: va
   introdotto un moltiplicatore esplicito, non c'è già.
