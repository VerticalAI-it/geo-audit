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
| `status` | TEXT NOT NULL DEFAULT `'open'` | `open` \| `resolved` |
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
| `event_name` | TEXT NOT NULL DEFAULT `'pageview'` | O nome evento custom |
| `session_id` | TEXT | Da `sessionStorage` lato client |
| `page_url` / `referrer` | TEXT | Troncati a 2048 caratteri dal server |
| `ai_source` | TEXT | Provider AI dal referrer, **NULL se non AI** |
| `properties` | JSONB | Payload libero per eventi di conversione |
| `created_at` | TIMESTAMPTZ | |

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
