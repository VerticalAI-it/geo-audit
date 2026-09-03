# 10 · Stato e debito tecnico

Inventario onesto di limiti, codice morto, incoerenze e rischi, verificato contro
il commit `b29a35d`. Serve a chi entra sul progetto per sapere dove sono le mine, e
a chi pianifica per sapere cosa costa non sistemare.

**Legenda:** 🔴 blocca o rischia · 🟡 attrito ricorrente · 🟢 cosmetico

---

## Riepilogo

| # | Voce | Gravità | Sforzo |
|---|---|---|---|
| 1 | [`render.parity` sempre `unknown` in produzione](#renderparity-non-viene-mai-calcolato-in-produzione) | 🔴 | Alto |
| 2 | [`CRON_SECRET` con default `"fallback-secret"`](#cron_secret-ha-un-default-pericoloso) | 🔴 | Minimo |
| 3 | [Autorizzazione non centralizzata](#lautorizzazione-è-copiata-in-ogni-route) | 🔴 | Medio |
| 4 | [Nessun test automatico](#nessun-test-automatico) | 🔴 | Medio |
| 5 | [Duplicazione della logica issue](#duplicazione-della-logica-issue) | ✅ risolto | — |
| 6 | [Duplicazione dei componenti email](#duplicazione-dei-componenti-email) | ✅ risolto | — |
| 7 | [La coda `pending` è vestigiale](#la-coda-pending-è-vestigiale) | 🟡 | Basso |
| 8 | [`audits.html` fa crescere la tabella](#auditshtml-fa-crescere-la-tabella-senza-limiti) | 🟡 | Medio |
| 9 | [AI Traffic aggrega in Python con tetto a 5000](#ai-traffic-non-scala) | 🟡 | Medio |
| 10 | [Nessun rate limiting su `/t`](#nessun-rate-limiting-sullendpoint-pubblico) | 🟡 | Basso |
| 11 | [Le email che falliscono spariscono](#le-email-che-falliscono-spariscono-senza-traccia) | 🟡 | Minimo |
| 12 | [Documentazione disallineata](#documentazione-disallineata) | 🟡 | Basso |
| 13 | [Soglie colore incoerenti](#soglie-colore-incoerenti) | 🟢 | Minimo |
| 14 | [Default del tema incoerente](#default-del-tema-incoerente) | 🟢 | Minimo |
| 15 | [Template orfani](#template-orfani) | 🟢 | Minimo |
| 16 | [`engine_version` scritto ma mai letto](#engine_version-è-scritto-ma-mai-letto) | 🟢 | — |
| 17 | [Il cron giornaliero non copre il portafoglio](#il-cron-giornaliero-non-copre-il-portafoglio) | ✅ risolto | — |
| 17 | [Lo scoring diluisce i check di sito](#lo-scoring-diluisce-i-check-di-sito) | 🟡 | Alto |
| 18 | [`server.py` a 2588 righe](#serverpy-concentra-tutto) | 🟡 | Medio |

---

## `render.parity` non viene mai calcolato in produzione

**Il limite funzionale più grave.**

Il check pesa 8 ed è uno dei segnali GEO più importanti: molti crawler AI non
eseguono JavaScript, quindi un sito che inietta il contenuto via JS è invisibile
per loro. Ma Vercel non ha Chromium, quindi **ogni** chiamata in produzione passa
`render=False` e il check restituisce `unknown`.

I check `unknown` sono esclusi dallo scoring: non penalizzano, ma il segnale manca
del tutto. **Un sito React senza SSR oggi può ottenere un punteggio alto pur
essendo completamente illeggibile per un assistente AI.**

Opzioni:

| Opzione | Costo | Effetto |
|---|---|---|
| Spostare gli audit su un container (Railway/Render) | Alto — cambia il deploy | Risolve del tutto |
| Microservizio di rendering separato su container | Medio | Risolve, ma introduce un servizio |
| API di rendering di terzi (Browserless, ScrapingBee) | Basso, ricorrente | Risolve, con costo per chiamata |
| Euristica statica: rapporto `<script>` / testo nell'HTML | Basso | Approssima, non risolve |

📄 [03 · Audit engine](03-audit-engine.md#livello-pagina--rendering--accesso)

---

## `CRON_SECRET` ha un default pericoloso

```python
_SECRET = os.environ.get("CRON_SECRET", "fallback-secret").encode()
```

`_SECRET` firma i **token HMAC di accesso ai report**. Se la variabile non è
valorizzata in produzione, i token sono calcolabili da chiunque conosca il
sorgente (che è la stringa letterale `"fallback-secret"`).

L'esposizione reale è limitata: i report legati a un account richiedono comunque
il login del proprietario, quindi il token da solo non basta. Restano esposti i
report legacy anonimi.

**Azione:** verificare che `CRON_SECRET` sia impostata in produzione; valutare di
farla fallire all'avvio come le due variabili Supabase.

📄 [08 · Setup e deploy](08-setup-e-deploy.md#comportamento-allavvio)

---

## L'autorizzazione è copiata in ogni route

L'app usa la service role key, che **bypassa RLS**. Le policy Postgres non
proteggono nulla nel percorso applicativo. L'unica difesa è questo blocco,
ripetuto a mano:

```python
project = _sb_project_get(project_id)
if not project or project.get("user_id") != user["id"]:
    return 404
```

**Dimenticarlo in una nuova route significa esporre i dati di tutti gli utenti.**
Non c'è un middleware, un decoratore o un test che lo garantisca.

**Azione:** introdurre una dependency FastAPI (`Depends(require_project_owner)`)
che risolva progetto e proprietà in un punto solo.

📄 [04 · Modello dati](04-data-model.md#row-level-security)

---

## Nessun test automatico

Zero file di test nel repository. Nessun CI. Le verifiche sono:

```bash
python3 -m py_compile server.py api/index.py geo_audit.py
```

che controlla solo la sintassi.

Il rischio è concreto perché il codice è pieno di **invarianti implicite**: il
pattern `_apply_refresh`, il controllo di proprietà, la stabilità dei `check_id`,
l'idempotenza della migration. Nessuna di queste è verificata da nulla.

**Primo lotto ad alto rendimento** (poche ore, copre i rischi principali):

| Test | Cosa protegge |
|---|---|
| `score_checks()` su check sintetici | La formula di scoring |
| `parse_robots_ai()` su robots.txt di esempio | Il check più pesante del catalogo |
| `is_page_url()` / `norm()` | La qualità del crawl |
| `_detect_ai_source()` | Il rilevamento provider |
| `_project_status()` sulle soglie | Lo stato mostrato in dashboard |
| Snapshot dei `check_id` emessi da `run_audit` | La continuità dello storico issue |

L'ultimo è il più prezioso: fallisce se qualcuno rinomina un `check_id`, che è
esattamente il cambiamento che spezza silenziosamente lo storico delle issue.

---

## Duplicazione della logica issue

**✅ Risolto in agosto 2026.**

Esistevano due implementazioni equivalenti — `_sb_issue_sync()` in `server.py`
(REST via `requests`) e `_sync_project_issues()` in `api/cron.py`
(`supabase-py`) — perché si riteneva che il cron girasse in una function
separata che non poteva importare `server.py`.

Quella premessa era falsa: `api/cron.py` non veniva mai costruito come function
(vedi [02 · Architettura](02-architettura.md#una-sola-function-apicron-incluso)).
Il cron è ora la route `/api/cron` dentro `server.py` e chiama direttamente
`_sb_issue_sync()`. Il file duplicato è stato rimosso.

---

## Duplicazione dei componenti email

**✅ Risolto in agosto 2026,** per la stessa ragione del punto precedente.

`_EMAIL_HEAD`, `_EMAIL_FONTS`, `_email_logo_row()`, `_email_footer()` e
`_score_band()` erano identici in `server.py` e `api/cron.py`. Rimosso
`api/cron.py`, `server.py` è l'unica copia e non c'è più niente da replicare.

Le copie in `api/cron.py` erano comunque tutte irraggiungibili: alimentavano solo
le email della coda `pending`, che nessun percorso riempie (punto successivo).

📄 [06 · Email](06-email.md)

---

## La coda `pending` è vestigiale

Residuo della Fase B. `audits.status` ha ancora default `'pending'`, ma
**nessun percorso inserisce righe `pending`**: `/scan`, `/rerun` e l'audit
periodico scrivono direttamente `'done'`.

Il consumatore della coda (`_process_next_job()` in `api/cron.py`) è stato
rimosso in agosto 2026 insieme al resto del file, quindi oggi **la coda non ha né
produttori né consumatori**.

Conseguenze residue:

- `_send_report_email()` e `_send_conferma_audit()` sono spariti col file
- `audits.started_at` e `audits.error` non vengono mai valorizzati
  (verificabile: ogni riga in produzione ha `started_at IS NULL`)
- `templates/waiting.html` (schermata di attesa) è orfano
- la colonna `status` è di fatto una costante `'done'`

**Due strade opposte, entrambe legittime:**

| Strada | Quando ha senso |
|---|---|
| **Rimuovere** coda, email correlate, template | Se `/scan` resta sincrono |
| **Riattivare** la coda | Se si alza `max_pages` o si abilita il rendering: l'audit non starebbe più nel timeout |

Da decidere **insieme** al punto su `render.parity`: sono la stessa decisione
architetturale vista da due angoli.

---

## `audits.html` fa crescere la tabella senza limiti

Ogni riga contiene il report HTML completo — decine o centinaia di KB. Con audit
settimanali su N progetti, la tabella cresce in modo lineare e senza tetto. Nessuna
politica di retention, nessuna compressione, nessun archiviazione su storage.

Il codice già mitiga il sintomo: `_sb_audits_by_project(full=False)` seleziona solo
le colonne leggere quando l'HTML non serve. Ma il dato resta.

**Opzioni:** spostare l'HTML su Supabase Storage tenendo in tabella solo la URL;
oppure una retention (es. conservare l'HTML solo degli ultimi N audit per progetto,
mantenendo sempre le colonne strutturate che alimentano dashboard e storico).

---

## AI Traffic non scala

`_tab_traffic()` carica **fino a 5000 eventi** degli ultimi 30 giorni e li aggrega
in Python ad ogni caricamento della pagina.

Due problemi distinti:

1. **Latenza** — nessuna cache, l'aggregazione si rifà ogni volta
2. **Troncamento silenzioso** — oltre 5000 eventi i dati sono incompleti **senza
   alcun avviso all'utente**, che vede numeri sbagliati credendoli giusti

Il secondo è il più serio: contraddice il principio "mai dati fuorvianti" che
regge il resto del prodotto.

**Azione minima e immediata:** avvisare quando si raggiunge il tetto.
**Azione strutturale:** aggregazione in SQL o tabella di rollup giornaliero.

📄 [05 · Applicazione web](05-applicazione-web.md#ai-traffic)

---

## Nessun rate limiting sull'endpoint pubblico

`POST /t` è pubblico, non autenticato e scrive su database. Chiunque conosca un
`project_id` — visibile nel sorgente del sito del cliente — può inserire eventi
arbitrari e inquinare le metriche AI Traffic di quel progetto.

Limite già dichiarato in [roadmap.md](roadmap.md) come accettato per la prima
versione.

**Mitigazioni possibili:** rate limit per IP, validazione che il referrer/origin
corrisponda al dominio del progetto, tetto giornaliero di eventi per progetto.

---

## Le email che falliscono spariscono senza traccia

```python
try:
    _send_unlock_email(...)
except Exception:
    pass
```

Il `pass` è deliberato — un'email non deve far fallire la richiesta dell'utente —
ma **nessun log, nessuna metrica, nessun retry**. Non c'è modo di sapere quante
notifiche di contatto (che sono lead commerciali) si sono perse.

**Azione:** aggiungere un `print()` con il tipo di eccezione in ogni `except`.
Cinque minuti di lavoro, e su Vercel i log sono già raccolti.

---

## Documentazione disallineata

| File | Problema |
|---|---|
| [`README.md`](../README.md) | **Interamente obsoleto.** Descrive la Fase A: audit anonimo senza login, deploy su Railway/Render come raccomandato, endpoint `GET /r/{id}.pdf` che **non esiste**, `POST /scan` con parametro `max_pages` che non è più accettato |
| [`design_system/DESIGN_SYSTEM.md`](../design_system/DESIGN_SYSTEM.md) | Cita `docs/design-system/ds.html`, path che non esiste (reale: `design_system/ds_components/ds.html`). La tabella delle route è ferma alla Fase B (niente `/dashboard`, `/project/*`, `/t`). La sezione "PR aperte e ordine di merge" descrive PR mergiate da giugno |

Il README è il più dannoso: è la prima cosa che legge chi arriva sul repository, e
lo indirizza verso un'architettura che non esiste più.

**Azione:** riscrivere il README come pagina di ingresso breve che punta a
`docs/`; aggiornare le sezioni stantie di `DESIGN_SYSTEM.md`.

---

## Soglie colore incoerenti

| Implementazione | Soglia intermedia |
|---|---|
| `_score_class()` in `server.py` | **50** ✅ |
| `_score_band()` in `server.py` / `cron.py` | **50** ✅ |
| `DESIGN_SYSTEM.md` (normativo) | **50** ✅ |
| **`geo_audit.barcol()`** [geo_audit.py:473](../geo_audit.py#L473) | **55** ❌ |

Un punteggio di 52 è **giallo nella dashboard e rosso nel report**. Un carattere da
cambiare.

---

## Default del tema incoerente

| Contesto | Default senza preferenza salvata |
|---|---|
| Pagine di prodotto (`templates/*.html`) | **Chiaro** (`:root` è light) |
| Report generato (`geo_audit.py`) | **Scuro** (`<html data-theme="dark">` e `\|\| 'dark'`) |

Un utente nuovo che passa dalla dashboard al report vede il tema cambiare.

📄 [07 · Design system](07-design-system.md#tema-chiaroscuro)

---

## Template orfani

| File | Stato |
|---|---|
| [`templates/gate.html`](../templates/gate.html) | Non caricato da `server.py` — il gate è costruito inline da `_inject_gate()` |
| [`templates/waiting.html`](../templates/waiting.html) | Non caricato — residuo del flusso asincrono |

Entrambi sono stati mantenuti allineati al design system (commit `b865a44`) pur
non essendo in uso: lavoro speso su codice morto, che è il costo tipico del non
sapere cosa è vivo.

**Azione:** rimuoverli, o documentare in testa al file perché sono conservati.

---

## `engine_version` è scritto ma mai letto

La colonna viene popolata da tutti e tre i percorsi di audit e inclusa nel `SELECT`
di `_AUDIT_FULL_FIELDS`, ma **nessuna logica la usa**.

Non è un difetto: è tracciamento predisposto in vista di quando servirà —
confrontare punteggi prodotti da versioni diverse del catalogo check. Vale la pena
saperlo perché il dato **è già lì** quando si vorrà mostrare "punteggio calcolato
con engine 1.1.0" o gestire un ricalcolo storico.

---

## Lo scoring diluisce i check di sito

Il punteggio complessivo è una media pesata su `site_checks + tutti i check di
tutte le pagine`. Con 6 pagine da ~26 check ciascuna, i 5 check di sito pesano ~21
su un denominatore di ~500.

**Conseguenza:** `crawl.ai` (peso 12, severità `critical`) — il check che rileva se
il sito **blocca completamente i crawler AI** — sposta il punteggio di circa 2
punti. Un sito che blocca GPTBot può ottenere 78/100.

Il report evidenzia la criticità nella sezione dedicata, quindi l'informazione non
si perde. Ma **il numero, che è ciò che l'utente ricorda, non riflette la gravità.**

Opzioni:

| Opzione | Nota |
|---|---|
| Media pesata a due livelli: 50 % sito, 50 % pagine | Semplice, cambia tutti i punteggi storici |
| Cap sul punteggio quando un check `critical` fallisce | Es. massimo 49 se i crawler AI sono bloccati |
| Peso proporzionale al numero di pagine | Mantiene la scala, riequilibra |

⚠️ Qualsiasi modifica **rende i punteggi non confrontabili con lo storico**. Da
fare insieme a un bump di `ENGINE_VERSION` e a una gestione esplicita della
discontinuità nel grafico storico.

---

## `server.py` concentra tutto

**✅ Risolto in settembre 2026,** prima del redesign UI/UX: quel lavoro riscrive
tutte le funzioni `_tab_*` e avrebbe raddoppiato un file già da 2588 righe.

Il taglio applicato è quello che questo documento raccomandava, meno `auth.py` e
`emails.py` (auth ed email restano in `server.py`: sono strettamente legate a
`Request`/`Response` e alla configurazione di Resend, e spostarle avrebbe dato
poco in cambio del rischio):

| File | Contenuto | Righe |
|---|---|---:|
| `config.py` | Variabili d'ambiente condivise | ~17 |
| `db.py` | Tutti gli helper Supabase (`_sb_*`), `_next_scan_at`, `_detect_ai_source` | ~314 |
| `views.py` | Costruzione HTML di dashboard e tab di progetto | ~926 |
| `server.py` | Route, auth, email, cron, template | ~1672 |

Lo spostamento è stato fatto **per intervalli di riga, senza riscrivere il
codice**: il testo delle funzioni è identico a prima. Verificato che le 152
definizioni top-level siano tutte ancora presenti e raggiungibili, e che le
pagine pubbliche rispondano con lo stesso identico numero di byte.

**Dipendenze:** `views.py` importa da `db.py` e `config.py`, `db.py` da
`config.py`. Mai il contrario — `db.py` e `views.py` non devono importare
`server.py`, altrimenti si crea un ciclo.

**Quel che resta:** le funzioni `_send_*` sono ancora in `server.py` insieme alle
route. Se un domani le email crescono, `emails.py` è il prossimo taglio naturale.

---

## Cosa NON è debito tecnico

Per evitare che qualcuno li "sistemi":

| Scelta | Perché è giusta così |
|---|---|
| **Niente framework frontend** | L'app ha poche pagine server-rendered; React aggiungerebbe superficie senza risolvere un problema esistente |
| **Niente template engine** | La string injection è sufficiente e non introduce dipendenze |
| **Supabase via REST diretta** | Non è una scorciatoia: è la soluzione a un'incompatibilità reale col runtime Vercel |
| **Report con CSS inline** | Deve restare autoconsistente e riprodurre esattamente com'era mesi dopo |
| **`try/except: pass` sulle email** | Deliberato — manca il log, non il `pass` |
| **Migration in un unico file idempotente** | Funziona, è riproducibile, non richiede un tool |
| **Tab "coming soon" espliciti** | Scelta di prodotto, non pigrizia: mai dati simulati |

---

## Il cron giornaliero non copre il portafoglio

**✅ Risolto in agosto 2026,** passando alla cadenza oraria sul piano Pro.

`vercel.json` schedulava `/api/cron` a `0 3 * * *`, una volta al giorno, con al
massimo `max_projects=3` progetti per invocazione. Con 21 progetti tutti a
cadenza `weekly` servono **3 audit al giorno** solo per stare in pari: il
margine era zero nel caso migliore, e un singolo giorno di cron saltato non
veniva mai recuperato.

La cadenza è ora `0 * * * *`. 24 invocazioni al giorno contro ~3 audit
necessari: in regime normale ogni invocazione trova 0 o 1 progetti scaduti, e un
eventuale arretrato si smaltisce in poche ore.

### Quel che resta da sorvegliare

Il rapporto capacità/fabbisogno degrada linearmente col numero di progetti. Il
tetto attuale è 24 × `max_projects` audit al giorno; con `max_projects=3` sono
72/giorno, cioè **~500 progetti settimanali** prima di tornare in sofferenza.
Ben oltre l'orizzonte attuale, ma non infinito.

Il vincolo più stretto è `maxDuration`, che non è dichiarato in `vercel.json` e
vale quindi il default del piano. Va alzato dal dashboard Vercel — vedi
[08 · Setup e deploy](08-setup-e-deploy.md#il-vincolo-fra-budget-e-maxduration)
per il calcolo e la ragione per cui non va messo in `vercel.json`.

---

## Gli audit falliti ora lasciano traccia (3 settembre 2026)

Fino a questa data un audit che falliva **non lasciava una riga**: l'errore
finiva in un `print`, cioè nei log della function su Vercel — che nessuno guarda
e che scadono. La conseguenza era che **se il monitoraggio automatico falliva su
un cliente, non lo sapeva nessuno**, e il pannello non poteva mostrarlo perché
non c'era niente da mostrare.

Ora i quattro punti che eseguono un audit (`/api/cron`, `/scan`,
`/project/{id}/rerun` e l'audit preliminare dei lead) scrivono una riga con
`status = 'failed'` e l'errore in `error`. Nessuna migrazione: quei valori erano
già previsti dallo schema.

⚠️ **La conseguenza da non sbagliare.** Aggiungendo righe fallite, «l'ultimo
audit» di un progetto sarebbe diventato il fallimento, e la dashboard avrebbe
mostrato un punteggio vuoto su un progetto sano — cioè la correzione avrebbe
rotto la schermata principale. Per questo `_sb_audits_by_project()` **esclude i
falliti di default**; chi li vuole (il Job log) passa `solo_riusciti=False`.

⚠️ **Vale da qui in avanti.** Quello che è fallito prima è perduto: non c'è modo
di ricostruirlo. Un elenco senza fallimenti significa «nessun fallimento da
settembre 2026», non «non è mai fallito niente».
