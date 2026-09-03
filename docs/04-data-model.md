# 04 · Modello dati (Supabase)

Tutto lo schema vive in [supabase_setup.sql](../supabase_setup.sql), **un unico
file idempotente** organizzato in fasi storiche. Rieseguirlo per intero è sempre
sicuro: ogni statement usa `IF NOT EXISTS` / `DROP … IF EXISTS` / `ADD COLUMN IF
NOT EXISTS`. È una proprietà voluta (commit `94143ba`) — la migrazione si applica
a un DB vuoto come a uno già popolato.

---

## Gerarchia

```
auth.users  (gestita da Supabase Auth)
    │
    ├─ project           1 utente → N progetti   (unique su user_id + domain)
    │     │
    │     ├─ audits      1 progetto → N audit run (storico)
    │     ├─ issue       1 progetto → N issue con ciclo di vita
    │     └─ tracking_event
    │
    └─ audits            anche direttamente (report legacy senza progetto)

contact_requests         indipendente, lead generation
```

---

## `project`

Il progetto è l'entità centrale: **un dominio monitorato nel tempo**.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → `auth.users` | `ON DELETE CASCADE` |
| `name` | TEXT NOT NULL | Editabile; default = dominio |
| `domain` | TEXT NOT NULL | Chiave naturale |
| `sector` | TEXT | Libero, non usato in logica |
| `scan_frequency` | TEXT NOT NULL DEFAULT `'weekly'` | CHECK: `daily`\|`weekly`\|`monthly` |
| `next_scan_at` | TIMESTAMPTZ | **Guida il cron** |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

**`UNIQUE (user_id, domain)`** è ciò che rende sicuro l'upsert: un utente che
rilancia l'audit sullo stesso dominio non crea un secondo progetto.

**`next_scan_at` non è solo uno scheduling: è anche il lock.** Vedi
[Il claim atomico](#il-claim-atomico).

Indici: `project_user (user_id)`, `project_next_scan (next_scan_at) WHERE next_scan_at IS NOT NULL`.

---

## `audits`

Ogni riga è un **audit run**. La tabella è cresciuta per accrescimento (Fase B →
Fase C) invece di essere duplicata in una `audit_run` separata — scelta
deliberata, annotata nel SQL stesso: *"`audits` continua a fare da audit_run — si
estende, non si duplica"*.

### Colonne originali (Fase B)

| Colonna | Tipo | Note |
|---|---|---|
| `id` | UUID PK | È il `job_id` nelle URL `/r/{job_id}` |
| `user_id` | UUID FK | `ON DELETE SET NULL` — NULL sui report anonimi legacy |
| `pending_email` | TEXT | Email del gate anonimo (legacy) |
| `url` | TEXT NOT NULL | |
| `status` | TEXT NOT NULL DEFAULT `'pending'` | `pending`\|`processing`\|`done`\|`failed` |
| `domain`, `overall`, `grade`, `band`, `pages_count` | | Riepilogo |
| `html` | TEXT | **Report completo, servito così com'è** |
| `error` | TEXT | |
| `created_at` / `started_at` / `completed_at` | TIMESTAMPTZ | |

> ⚠️ **`status` in pratica è sempre `'done'`.** Sia `/scan` che `/rerun` che il
> cron inseriscono direttamente righe completate. Il default `'pending'` e la coda
> asincrona che lo consumava sono residui della Fase B
> ([doc 10](10-stato-e-debito-tecnico.md#la-coda-pending-è-vestigiale)).

> ⚠️ **`html` contiene il report intero** (decine/centinaia di KB per riga). È
> comodo — il report è immutabile e riproducibile a distanza di mesi — ma la
> tabella cresce in fretta e ogni `SELECT *` la trascina. Per questo
> `_sb_audits_by_project()` ha un parametro `full` che seleziona le colonne
> leggere quando l'HTML non serve ([server.py:177](../server.py#L177)).

### Colonne strutturate (Fase C)

Aggiunte per non dover ri-parsare l'HTML per popolare la dashboard:

| Colonna | Tipo | Contenuto |
|---|---|---|
| `project_id` | UUID FK → `project` | `ON DELETE SET NULL` |
| `engine_version` | TEXT | Es. `"1.1.0"` — traccia con che motore è stato prodotto |
| `areas` | JSONB | `[{key, score}]` per macro-area |
| `site_checks` | JSONB | `[Check]` a livello di sito |
| `pages_detail` | JSONB | `[{url, type, title, score, checks:[Check]}]` |
| `actions` | JSONB | Interventi aggregati con URL interessate |
| `issues_count` | INTEGER | Check `warn` + `fail` |
| `critical_count` | INTEGER | Check `fail` |
| `source` | TEXT | `'manual'` (`/scan`, `/rerun`) o `'auto'` (`/api/cron`) — vedi sotto |

### `source` — chi ha lanciato il run

Distingue gli audit lanciati da una persona da quelli prodotti dal cron. Senza
questa colonna non è possibile rispondere alla domanda "il monitoraggio
automatico sta girando?", che è esattamente ciò che il riquadro **Ultimi run** in
home mostra ([05 · Applicazione web](05-applicazione-web.md)).

| Valore | Scritto da |
|---|---|
| `'manual'` | `POST /scan`, `POST /project/{id}/rerun` |
| `'auto'` | `GET /api/cron` (`_run_project_scan`) |
| `NULL` | Run precedenti all'introduzione della colonna, resi come `n.d.` |

Il backfill ha marcato tutto lo storico come `'manual'`: prima di agosto 2026 il
cron non aveva mai prodotto un audit, perché girava a vuoto
([02 · Architettura](02-architettura.md#una-sola-function-apicron-incluso)).

Vincolo: `CHECK (source IN ('manual','auto'))`. Il `NULL` resta ammesso apposta,
per non invalidare le righe storiche.
Indice: `audits_user_created (user_id, created_at DESC)` per la query del riquadro.

`engine_version` è la chiave per interpretare correttamente lo storico: se il
catalogo dei check cambia, un confronto fra punteggi prodotti da versioni diverse
va contestualizzato. **Oggi nessuna query lo usa** — è tracciato in vista di
quando servirà.

Indici: `audits_status_created`, `audits_pending_email` (parziale),
`audits_project_created (project_id, created_at DESC)`.

---

## `issue` — il ciclo di vita delle criticità

La tabella che trasforma un'istantanea in una serie storica.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | UUID PK | |
| `project_id` / `user_id` | UUID FK | `ON DELETE CASCADE` |
| `check_id` | TEXT NOT NULL | Es. `sd.present` |
| `category`, `title`, `severity` | TEXT | Denormalizzati dal check |
| `url` | TEXT | NULL per issue a livello di sito |
| `fingerprint` | TEXT NOT NULL | `check_id \|\| '\|' \|\| coalesce(url,'')` |
| `status` | TEXT NOT NULL DEFAULT `'open'` | `open` \| `resolved` \| `resolved_manually` |
| `first_seen_audit` / `last_seen_audit` | UUID FK → `audits` | |
| `first_seen_at` / `last_seen_at` / `resolved_at` | TIMESTAMPTZ | |

**`UNIQUE (project_id, fingerprint)`**.

### Come funziona la sincronizzazione

`_sb_issue_sync()` ([server.py:207](../server.py#L207)) gira dopo ogni audit:

```
1. carica tutte le issue del progetto, indicizzate per fingerprint
2. per ogni check warn|fail del nuovo audit:
     ├─ fingerprint già noto? → UPDATE status='open', last_seen_*, resolved_at=NULL
     └─ nuovo?                → INSERT status='open', first_seen_* = last_seen_*
3. issue aperte NON viste in questo run → UPDATE status='resolved', resolved_at=now
```

Il passo 3 è quello che dà il valore: una issue risolta viene chiusa da sola,
senza intervento manuale. E una issue che **riappare** viene riaperta mantenendo
il suo `first_seen_at` originale — quindi si sa che è un problema ricorrente, non
nuovo.

### I tre stati, e perché l'audit vince (settembre 2026)

Con l'azione «Segna risolto» su Opportunities gli stati sono diventati tre:

| Stato | Significato |
|---|---|
| `open` | criticità aperta |
| `resolved` | chiusa dall'audit, che non l'ha più rilevata |
| `resolved_manually` | chiusa a mano dall'utente |

**Non è servita nessuna migrazione.** `issue.status` è una colonna `TEXT` senza
vincolo `CHECK`: il commento `-- open | resolved` nello schema descrive l'uso,
non lo impone. Vale la pena saperlo anche al contrario — se un giorno si
volesse impedire davvero valori arbitrari lì dentro, il vincolo andrebbe
aggiunto sul serio.

La regola concordata è che **l'audit vince sullo stato manuale**: se un check
torna a fallire sulla stessa pagina, la riga torna `open` qualunque fosse il
suo stato. Era già rispettata dal codice per come è scritto, e ora è
documentata nel docstring di `_sb_issue_sync()` — due dettagli da non toccare:

1. il ramo che riapre **non guarda** lo stato precedente;
2. la chiusura automatica filtra su `status == "open"`, quindi non tocca le
   righe chiuse a mano.

Chi ha chiuso e quando si ricavano da `user_id` (un progetto ha un proprietario
solo) e da `resolved_at`: per questo non sono state aggiunte colonne.

### Dove stanno le cose che non hanno una tabella

Due funzionalità di settembre 2026 usano posti che esistevano già, invece di
tabelle nuove. È una scelta di proporzione, ed è reversibile:

| Cosa | Dove | Perché |
|---|---|---|
| Tema chiaro/scuro dell'utente | `auth.users.user_metadata.theme` | Un solo campo non giustifica una tabella. Se le preferenze diventeranno molte (notifiche, lingua, fuso) allora sì: il punto di innesto è `_sb_user_theme_set()` |
| Voti e iscrizioni della roadmap | `tracking_event` con `event_name` `roadmap_vote` / `roadmap_signup` | La tabella ha già un campo libero (`properties`) e `project_id` facoltativo. Restano **fuori** dalle statistiche di AI Traffic, che filtrano sempre per progetto |

> ⚠️ Se un domani si contano i voti con query aggregate, `tracking_event` non è
> il posto giusto: le tre funzioni in `db.py` sono il punto da cui migrare.

### Il fingerprint è un contratto

`fingerprint = check_id + "|" + url`. Ne discendono due vincoli:

1. **Rinominare un `check_id` in `geo_audit.py` spezza la continuità storica**: le
   issue vecchie vengono chiuse come risolte e ne nascono di nuove con
   `first_seen_at` di oggi. Se un `check_id` deve cambiare, serve una migrazione
   che riscriva i fingerprint esistenti.
2. **L'URL deve essere normalizzato allo stesso modo fra audit successivi**,
   altrimenti `https://x.it/pagina` e `https://x.it/pagina/` generano due issue
   distinte. `norm()` in `geo_audit.py` se ne occupa a monte.

### Un'unica implementazione

`_sb_issue_sync()` in [server.py](../server.py) è l'unico punto in cui le issue
vengono sincronizzate: la chiamano `/scan`, `/project/{id}/rerun` e l'audit
periodico `/api/cron`.

Fino ad agosto 2026 esisteva un secondo `_sync_project_issues()` in
`api/cron.py`, scritto con `supabase-py` invece che con la REST diretta, da
tenere allineato a mano. Con il cron diventato una route FastAPI il file è stato
rimosso e la duplicazione è sparita.

Indice: `issue_project_status (project_id, status)`.

---

## `tracking_event`

Alimentata dallo snippet first-party.

| Colonna | Tipo | Note |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK → `project` | `ON DELETE CASCADE` |
| `event_name` | TEXT NOT NULL DEFAULT `'pageview'` | `pageview`, **`crawler`**, o nome evento custom |
| `session_id` | TEXT | Da `sessionStorage` lato client. **Vuoto sui `crawler`**: un bot non ha sessione |
| `page_url` / `referrer` | TEXT | Troncati a 2048 caratteri dal server |
| `ai_source` | TEXT | Sui `pageview` l'assistente da cui arriva la visita; sui `crawler` il nome del bot. **NULL se non AI** |
| `properties` | JSONB | Payload libero per eventi di conversione. Sui `crawler`: `categoria` (`training` / `search` / `user`) e `ua` |
| `created_at` | TIMESTAMPTZ | |

⚠️ **`event_name` non ha un CHECK**: `crawler` è una convenzione applicativa, non
un vincolo del database. Chi legge la tabella deve separare le due famiglie —
`_tab_traffic` lo fa, e chi non lo facesse conterebbe i passaggi dei bot fra le
sessioni delle persone.

`ai_source` è **calcolato al momento dell'inserimento**, non a query time. È una
denormalizzazione voluta: rende banale sia l'indice parziale sia il breakdown per
provider, e congela il risultato del rilevamento anche se la mappa dei domini
cambia in futuro.

Indici: `tracking_event_project_created (project_id, created_at DESC)`,
`tracking_event_project_ai (project_id, ai_source) WHERE ai_source IS NOT NULL`.

> ⚠️ **Non c'è rate limiting sull'endpoint `/t`**, che è pubblico e non
> autenticato. Chiunque conosca un `project_id` (visibile nel sorgente del sito
> del cliente) può inserire eventi arbitrari. Limite noto e accettato in questa
> prima versione, dichiarato anche in [roadmap.md](roadmap.md).

---

## `contact_requests`

Lead generation, indipendente dalla gerarchia progetti.

| Colonna | Tipo |
|---|---|
| `id` | UUID PK |
| `audit_id` | UUID FK → `audits`, `ON DELETE SET NULL` |
| `email` | TEXT NOT NULL |
| `phone` | TEXT |
| `preference` | TEXT — `'email'` \| `'phone'` |
| `domain`, `overall`, `grade` | Snapshot al momento della richiesta |
| `created_at` | TIMESTAMPTZ |

I campi di snapshot sono denormalizzati apposta: la richiesta di contatto deve
restare leggibile anche se l'audit collegato viene cancellato.

### Ci vivono anche i lead del flusso di accesso

Dal 3 settembre 2026 questa tabella raccoglie **due sorgenti**:

| Sorgente | Come si riconosce | Cosa contiene |
|---|---|---|
| form del report esterno | l'audit collegato ha `source` `manual`/`auto` | richiesta su un audit già fatto |
| **richiesta di accesso** (`/richiedi-accesso`) | l'audit collegato ha **`source = 'lead'`** | `domain` = sito da analizzare, `audit_id` = audit preliminare |

⚠️ **Perché qui e non in una tabella nuova**, che pure il documento funzionale
proponeva: crearla richiede un DDL, e le chiavi di servizio non fanno DDL —
servirebbe qualcuno che apre il pannello Supabase, e la funzionalità resterebbe
ferma lì. Questa tabella nasce come raccolta lead e ha già tutti i campi utili:
`email`, `phone`, `domain`, più `audit_id` e lo snapshot `overall`/`grade`, che
sono esattamente il collegamento all'audit preliminare e il suo esito.

⚠️ **Lo stato del lead non è una colonna, è un fatto:** se l'email ha un account
in `auth.users` la richiesta è stata approvata, altrimenti sta ancora aspettando.
Così non esistono due verità da tenere allineate. Lo stato intermedio
«contattato», che serve all'Admin Dashboard e non a questo flusso, è la cosa che
un domani richiederà una colonna in più.

---

## Row Level Security

RLS è **abilitata su tutte le tabelle**. Le policy:

| Tabella | Policy | Predicato |
|---|---|---|
| `audits` | `own_audits` | `auth.uid() = user_id` |
| `project` | `own_projects` | `auth.uid() = user_id` |
| `issue` | `own_issues` | `auth.uid() = user_id` |
| `tracking_event` | `own_tracking_events` | `project_id IN (SELECT id FROM project WHERE user_id = auth.uid())` |
| `contact_requests` | *(nessuna)* | RLS attiva senza policy = nessun accesso via anon key |

> ⚠️ **Le policy non sono il meccanismo di autorizzazione effettivo.** L'app usa
> la **service role key**, che bypassa RLS. Sono un backstop per un eventuale
> accesso diretto via anon key da un client autenticato.
>
> L'autorizzazione reale è nel codice, con questo pattern ripetuto in ogni route:
> ```python
> if not project or project.get("user_id") != user["id"]:
>     return 404
> ```
> **Ogni nuova route che tocca dati di progetto deve ripeterlo.** Non c'è un
> middleware che lo garantisca — è il rischio di sicurezza principale
> dell'architettura attuale.

---

## Il claim con lease

Il cron può essere invocato in modo concorrente (retry Vercel, invocazioni
manuali). Il claim è un `UPDATE` condizionale in `_sb_project_claim_due()`
([server.py](../server.py)):

```python
now = datetime.now(timezone.utc).isoformat()

# 1. leggi il prossimo progetto scaduto
GET /project?next_scan_at=lte.{now}&order=next_scan_at.asc&limit=1

# 2. rivendicalo con una LEASE BREVE, solo se è ancora scaduto
PATCH /project?id=eq.{id}&next_scan_at=lte.{now}
  { "next_scan_at": now + 20 minuti }

# risposta [] → un'altra invocazione l'ha già preso, questa si sfila
```

Il predicato è `next_scan_at <= now`, **non** l'uguaglianza con il valore appena
letto. Postgres rivaluta la `WHERE` sulla riga bloccata, quindi la seconda
invocazione concorrente non trova più nulla da aggiornare (il primo claim ha già
spostato `next_scan_at` nel futuro) e riceve `[]`. Rispetto al compare-and-swap
sul valore esatto non dipende dalla fedeltà del round-trip del timestamp
attraverso PostgREST.

### Perché una lease breve e non l'intervallo pieno

Fino ad agosto 2026 il claim scriveva direttamente `now + intervallo`, con la
motivazione che così un audit fallito non richiedeva rollback. Il problema è il
caso che quella logica non copre: **la function uccisa dal timeout a metà audit**.
Lì nessun codice applicativo gira, `next_scan_at` è già una settimana avanti, e
il progetto sparisce per sette giorni senza errore e senza traccia.

Con la lease a 20 minuti quel caso si autoripara: il progetto torna scaduto e
viene ritentato al giro successivo del cron.

Il caso "errore esplicito" (sito irraggiungibile, Supabase KO) resta invece
gestito come prima — `_sb_project_bump_scan()` porta `next_scan_at`
all'intervallo pieno, così un sito rotto non viene martellato a ogni ciclo.

---

## Migrazioni

Non c'è un tool di migration (Alembic, Prisma…). Il processo è manuale:

1. Aggiungi statement **idempotenti** in fondo a `supabase_setup.sql`, sotto una
   nuova intestazione di fase.
2. Esegui l'intero file nel SQL Editor di Supabase.
3. **Forza il reload dello schema cache di PostgREST.**

Il passo 3 non è opzionale. È l'ultima riga del file:

```sql
NOTIFY pgrst, 'reload schema';
```

Senza, le nuove tabelle e colonne restano **invisibili all'API REST** con errore
`PGRST205 "Could not find the table … in the schema cache"` finché Supabase non
ricarica da sé. È stato un problema reale in passato (commit `a537069`) — un DDL
applicato correttamente ma un'app che continuava a fallire.

### Seed demo

[supabase_seed_demo.sql](../supabase_seed_demo.sql) popola un progetto
`demo-website` con:

- **4 audit** su date diverse (60/40/20/0 giorni fa) con punteggio in
  miglioramento — serve a mostrare il grafico dello storico
- Dati plausibili per tutte le sezioni coperte dall'engine reale (aree, check,
  pagine, azioni, issue con ciclo di vita)
- **12 sessioni di tracking** (7 da assistenti AI, 5 organiche) per popolare la
  tab AI Traffic senza installare davvero lo snippet

È **parzialmente idempotente**, e la distinzione conta:

| Parte | Comportamento al rilancio |
|---|---|
| `project` | `ON CONFLICT (user_id, domain)` → aggiorna |
| `issue` | `ON CONFLICT (fingerprint)` → aggiorna |
| `tracking_event` | Ripulite e reinserite identiche → sicuro |
| **`audits`** | ⚠️ **Nessuna chiave naturale: rilanciare AGGIUNGE 4 nuovi audit** |

Per uno storico pulito, cancellare gli audit demo a mano prima di rilanciare (in
fondo al file c'è una query di cleanup commentata).

L'`user_id` è **hardcoded** (`05ba0f8c-…`, utente `verticalai00@gmail.com`): per
usarlo su un altro ambiente va sostituito.
