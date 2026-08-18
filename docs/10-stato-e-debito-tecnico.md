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
| 5 | [Duplicazione della logica issue](#duplicazione-della-logica-issue) | 🟡 | Medio |
| 6 | [Duplicazione dei componenti email](#duplicazione-dei-componenti-email) | 🟡 | Basso |
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
python3 -m py_compile server.py api/cron.py geo_audit.py
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

La stessa logica esiste in due implementazioni:

| Funzione | File | Client Supabase |
|---|---|---|
| `_sb_issue_sync()` | [server.py:207](../server.py#L207) | REST via `requests` |
| `_sync_project_issues()` | [api/cron.py:371](../api/cron.py#L371) | `supabase-py` |

Sono funzionalmente equivalenti oggi. Un cambiamento applicato a una sola delle
due produce **audit manuali e audit automatici che si comportano diversamente** —
un bug difficile da notare perché richiede di confrontare due percorsi.

**Perché esistono separate:** `cron.py` non può importare `server.py` senza
tirarsi dietro l'intera app FastAPI e le sue variabili d'ambiente obbligatorie.

**Azione:** estrarre un modulo `issues.py` che riceva un client astratto, oppure
far usare a entrambi la stessa REST diretta.

---

## Duplicazione dei componenti email

`_EMAIL_HEAD`, `_EMAIL_FONTS`, `_email_logo_row()`, `_email_footer()`,
`_score_band()` sono identici in `server.py` e `api/cron.py`.

Ogni modifica al layout va replicata in due posti. Stessa causa strutturale del
punto precedente.

**Azione:** un `email_kit.py` importabile da entrambi senza dipendere da FastAPI.
Intervento pulito, rischio basso.

📄 [06 · Email](06-email.md#duplicazione-fra-serverpy-e-apicronpy)

---

## La coda `pending` è vestigiale

Residuo della Fase B. `audits.status` ha default `'pending'` e `api/cron.py`
espone `_process_next_job()` che consuma la coda — ma **nessun percorso inserisce
più righe `pending`**: `/scan`, `/rerun` e il cron scrivono direttamente `'done'`.

Conseguenze:

- `_process_next_job()` gira ad ogni invocazione del cron e non trova mai nulla
- `_send_report_email()` in `cron.py` è **irraggiungibile**
- `_send_conferma_audit()` è orfana per lo stesso motivo
- `audits.started_at` e `audits.error` non vengono mai valorizzati dal flusso attuale
- `templates/waiting.html` (schermata di attesa) è orfano

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

2588 righe con route, accesso ai dati, autenticazione, generazione email e
costruzione HTML. Non è un problema oggi — l'app è piccola e coesa, e il file è
ordinato per sezioni — ma:

- ogni modifica tocca lo stesso file → conflitti di merge garantiti se il team cresce
- la superficie da tenere a mente per un cambiamento è tutto il file
- rende difficile testare le parti in isolamento

**Taglio naturale:** `db.py` (helper Supabase) · `auth.py` · `emails.py` ·
`views.py` (costruzione HTML dei tab). Da fare **prima** di aggiungere il secondo
sviluppatore, non dopo.

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
