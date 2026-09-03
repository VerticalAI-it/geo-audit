-- GEO Audit · Fase B — Supabase migration
-- Eseguire nel SQL Editor di Supabase Dashboard
-- Idempotente: sicuro da rieseguire per intero anche se una parte esiste già.

CREATE TABLE IF NOT EXISTS public.audits (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        REFERENCES auth.users(id) ON DELETE SET NULL,
    pending_email   TEXT,
    url             TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending',  -- pending|processing|done|failed
    domain          TEXT,
    overall         INTEGER,
    grade           TEXT,
    band            TEXT,
    pages_count     INTEGER,
    html            TEXT,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

-- Row Level Security: gli utenti vedono solo i propri audit
ALTER TABLE public.audits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_audits" ON public.audits;
CREATE POLICY "own_audits" ON public.audits
    FOR ALL
    USING (auth.uid() = user_id);

-- Indici per performance del cron worker e del lookup pending_email
CREATE INDEX IF NOT EXISTS audits_status_created  ON public.audits (status, created_at);
CREATE INDEX IF NOT EXISTS audits_pending_email   ON public.audits (pending_email) WHERE pending_email IS NOT NULL;

-- ── Richieste di contatto ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.contact_requests (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id    UUID        REFERENCES public.audits(id) ON DELETE SET NULL,
    email       TEXT        NOT NULL,
    phone       TEXT,
    preference  TEXT,       -- 'email' | 'phone'
    domain      TEXT,
    overall     INTEGER,
    grade       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.contact_requests ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS contact_requests_created ON public.contact_requests (created_at DESC);

-- ════════════════════════════════════════════════════════════════════════════
-- GEO Audit · Fase C — Dashboard v2 (Project Portfolio + Project Detail)
-- Migration incrementale: da eseguire dopo la Fase B.
-- `audits` continua a fare da audit_run — si estende, non si duplica.
-- ════════════════════════════════════════════════════════════════════════════

-- ── Progetti (Account → Progetto → Sito) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.project (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        REFERENCES auth.users(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    domain      TEXT        NOT NULL,
    sector      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, domain)
);

ALTER TABLE public.project ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_projects" ON public.project;
CREATE POLICY "own_projects" ON public.project
    FOR ALL
    USING (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS project_user ON public.project (user_id);

-- ── Estensione di audits: link al progetto + dati strutturati dell'audit ────
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS project_id      UUID REFERENCES public.project(id) ON DELETE SET NULL;
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS engine_version  TEXT;
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS areas           JSONB;   -- [{key, score}] per macro-area
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS site_checks     JSONB;   -- [Check] livello sito
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS pages_detail    JSONB;   -- [{url, type, title, score, checks:[Check]}]
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS actions         JSONB;   -- quick win / interventi prioritari con URL interessati
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS issues_count    INTEGER;
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS critical_count  INTEGER;

CREATE INDEX IF NOT EXISTS audits_project_created ON public.audits (project_id, created_at DESC);

-- ── Issue lifecycle (persistente fra più audit dello stesso progetto) ───────
CREATE TABLE IF NOT EXISTS public.issue (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    user_id           UUID        REFERENCES auth.users(id) ON DELETE CASCADE,
    check_id          TEXT        NOT NULL,
    category          TEXT,
    url               TEXT,                              -- NULL per issue site-level
    title             TEXT,
    severity          TEXT,
    fingerprint       TEXT        NOT NULL,               -- check_id || '|' || coalesce(url,'')
    status            TEXT        NOT NULL DEFAULT 'open', -- open | resolved
    first_seen_audit  UUID        REFERENCES public.audits(id) ON DELETE SET NULL,
    last_seen_audit   UUID        REFERENCES public.audits(id) ON DELETE SET NULL,
    first_seen_at     TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at       TIMESTAMPTZ,
    UNIQUE (project_id, fingerprint)
);

ALTER TABLE public.issue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_issues" ON public.issue;
CREATE POLICY "own_issues" ON public.issue
    FOR ALL
    USING (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS issue_project_status ON public.issue (project_id, status);

-- ════════════════════════════════════════════════════════════════════════════
-- GEO Audit · Fase D — Tracking first-party (v1.3, sblocca "AI Traffic")
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.tracking_event (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    event_name  TEXT        NOT NULL DEFAULT 'pageview',  -- pageview | nome evento custom
    session_id  TEXT,
    page_url    TEXT,
    referrer    TEXT,
    ai_source   TEXT,                                     -- provider AI rilevato dal referrer, NULL se non AI
    properties  JSONB,                                     -- payload libero per eventi di conversione
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.tracking_event ENABLE ROW LEVEL SECURITY;

-- Nessuna policy per utenti anonimi: l'endpoint di ingestion scrive con la
-- service role (bypassa RLS). Questa resta un backstop in caso di accesso
-- diretto via anon key da un client autenticato.
DROP POLICY IF EXISTS "own_tracking_events" ON public.tracking_event;
CREATE POLICY "own_tracking_events" ON public.tracking_event
    FOR ALL
    USING (project_id IN (SELECT id FROM public.project WHERE user_id = auth.uid()));

CREATE INDEX IF NOT EXISTS tracking_event_project_created ON public.tracking_event (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS tracking_event_project_ai      ON public.tracking_event (project_id, ai_source) WHERE ai_source IS NOT NULL;

-- ════════════════════════════════════════════════════════════════════════════
-- GEO Audit · Fase E — Rifai audit manuale + audit periodico via cron
-- ════════════════════════════════════════════════════════════════════════════

-- ── Cadenza di audit automatico per progetto ────────────────────────────────
ALTER TABLE public.project ADD COLUMN IF NOT EXISTS scan_frequency TEXT NOT NULL DEFAULT 'weekly';
ALTER TABLE public.project ADD COLUMN IF NOT EXISTS next_scan_at   TIMESTAMPTZ;

ALTER TABLE public.project DROP CONSTRAINT IF EXISTS project_scan_frequency_check;
ALTER TABLE public.project ADD CONSTRAINT project_scan_frequency_check
    CHECK (scan_frequency IN ('daily', 'weekly', 'monthly'));

-- Backfill: progetti esistenti senza next_scan_at partono da adesso + 7 giorni
UPDATE public.project SET next_scan_at = NOW() + INTERVAL '7 days' WHERE next_scan_at IS NULL;

-- Indice per la query del cron worker ("prossimo progetto scaduto")
CREATE INDEX IF NOT EXISTS project_next_scan ON public.project (next_scan_at) WHERE next_scan_at IS NOT NULL;

-- IMPORTANTE: dopo aver eseguito questa migration, forza il reload dello
-- schema cache di PostgREST — altrimenti le nuove tabelle/colonne restano
-- invisibili all'API REST (errore PGRST205 "Could not find the table ...
-- in the schema cache") finché Supabase non lo ricarica da sé:
NOTIFY pgrst, 'reload schema';

-- ════════════════════════════════════════════════════════════════════════════
-- GEO Audit · Origine del run (manuale vs automatico)
-- ════════════════════════════════════════════════════════════════════════════

-- Distingue gli audit lanciati da una persona (/scan, /project/{id}/rerun) da
-- quelli prodotti dal cron (/api/cron). Serve al riquadro "Ultimi run" in home,
-- che senza questo dato non può dire se l'automazione sta girando.
ALTER TABLE public.audits ADD COLUMN IF NOT EXISTS source TEXT;

ALTER TABLE public.audits DROP CONSTRAINT IF EXISTS audits_source_check;
ALTER TABLE public.audits ADD CONSTRAINT audits_source_check
    CHECK (source IN ('manual', 'auto'));

-- Backfill: prima di questa colonna il cron non aveva mai prodotto un audit
-- (girava a vuoto, vedi doc 02), quindi tutto lo storico è manuale.
UPDATE public.audits SET source = 'manual' WHERE source IS NULL;

-- Indice per la query del riquadro "Ultimi run"
CREATE INDEX IF NOT EXISTS audits_user_created ON public.audits (user_id, created_at DESC);

-- IMPORTANTE: come sopra, senza questo reload PostgREST continua a rispondere
-- PGRST204 sulla colonna nuova finché non ricarica lo schema da sé.
NOTIFY pgrst, 'reload schema';


-- ════════════════════════════════════════════════════════════════════════════
-- GEO Audit · Fase D — Pannello del team (settembre 2026)
-- Migration incrementale, idempotente come le precedenti.
--
-- Sblocca le tre cose che il pannello /admin oggi non può fare: le note interne
-- su un cliente, lo storico dei suoi accessi, e i promemoria a chi non ha
-- installato il tracking. Più lo stato «contattato» sulla coda dei lead.
--
-- ⚠️ NON esiste una tabella `clients`: i clienti SONO `auth.users`. Il documento
-- funzionale ne proponeva una, ma il prodotto non ce l'ha e non serve — «essere
-- in auth.users è essere approvati». Le chiavi esterne qui sotto puntano quindi
-- ad auth.users, non a una tabella intermedia.
--
-- ⚠️ RLS attiva su tutte: sono dati interni, e nessuna policy significa che
-- nessun utente autenticato ci arriva. Il pannello legge con la service role,
-- che le RLS le bypassa per definizione.
-- ════════════════════════════════════════════════════════════════════════════

-- ── Note interne su un cliente ──────────────────────────────────────────────
-- Elenco che si aggiunge e basta: nessuna modifica, nessuna cancellazione. Una
-- nota commerciale che qualcuno può riscrivere dopo non è più una traccia.
CREATE TABLE IF NOT EXISTS public.client_notes (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    author_id   UUID        REFERENCES auth.users(id) ON DELETE SET NULL,
    author_email TEXT,      -- denormalizzato: la nota resta leggibile anche se
                            -- l'account di chi l'ha scritta viene rimosso
    text        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.client_notes ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS client_notes_client ON public.client_notes (client_id, created_at DESC);


-- ── Storico degli accessi ───────────────────────────────────────────────────
-- ⚠️ Supabase Auth non espone uno storico per-utente: `last_sign_in_at` dice
-- solo l'ultima volta. Queste righe le scrive l'applicazione, nei due momenti
-- in cui sa cosa sta succedendo: quando parte un link e quando la sessione si
-- apre davvero. Le due cose insieme dicono anche quanti link non vengono mai
-- cliccati, che è un dato che oggi non abbiamo.
CREATE TABLE IF NOT EXISTS public.login_events (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   UUID        REFERENCES auth.users(id) ON DELETE CASCADE,
    email       TEXT,       -- serve per i tentativi di chi un account non ce l'ha
    event_type  TEXT        NOT NULL,   -- 'link_richiesto' | 'accesso_riuscito'
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.login_events ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS login_events_client ON public.login_events (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS login_events_email  ON public.login_events (email, created_at DESC);


-- ── Promemoria «installa il tracking» ───────────────────────────────────────
-- Esiste per NON rimandare lo stesso messaggio a raffica: prima di scrivere a
-- qualcuno si guarda quando gli si è scritto l'ultima volta.
CREATE TABLE IF NOT EXISTS public.tracking_reminders (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID        NOT NULL REFERENCES public.project(id) ON DELETE CASCADE,
    sent_by     UUID        REFERENCES auth.users(id) ON DELETE SET NULL,
    sent_to     TEXT,       -- a chi è andato, denormalizzato
    sent_at     TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.tracking_reminders ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS tracking_reminders_project ON public.tracking_reminders (project_id, sent_at DESC);


-- ── Lo stato di una richiesta ───────────────────────────────────────────────
-- Oggi lo stato di un lead è un fatto e non una colonna: se l'email ha un
-- account, è stato approvato. Regge per «in attesa» e «approvato», ma non per
-- lo stato intermedio — «l'ho chiamato, non ho ancora deciso» — che non
-- corrisponde a nessun fatto osservabile. Solo per quello serve una colonna.
--
-- ⚠️ Niente CHECK sul valore, coerentemente col resto dello schema (vedi
-- `issue.status`): il commento descrive l'uso, non lo impone.
ALTER TABLE public.contact_requests
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'nuova';  -- nuova | contattata | ignorata

CREATE INDEX IF NOT EXISTS contact_requests_status ON public.contact_requests (status, created_at DESC);


-- ── Registro delle azioni del pannello ──────────────────────────────────────
-- ⚠️ Oggi le azioni admin finiscono in `tracking_event` con
-- `event_name = 'admin_action'`: funziona, ma quella tabella è nata per il
-- traffico di un sito e sta diventando un registro eventi generico. Questa è la
-- sua casa vera. Le righe già scritte si portano dietro con la SELECT in fondo,
-- che è sicura da rieseguire (ON CONFLICT non serve: si filtra per data).
CREATE TABLE IF NOT EXISTS public.admin_audit_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_email TEXT        NOT NULL,   -- chi: l'email, che resta leggibile nel tempo
    action_type TEXT        NOT NULL,   -- approva_lead | disabilita_cliente | ...
    target      TEXT,                   -- su chi/cosa
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.admin_audit_log ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS admin_audit_log_created ON public.admin_audit_log (created_at DESC);

-- Travaso delle azioni già registrate in tracking_event. Rieseguirlo non crea
-- doppioni: si copiano solo le righe più vecchie di quelle già presenti qui.
INSERT INTO public.admin_audit_log (actor_email, action_type, target, created_at)
SELECT
    COALESCE(properties->>'attore', '?'),
    COALESCE(properties->>'azione', '?'),
    properties->>'bersaglio',
    created_at
FROM public.tracking_event
WHERE event_name = 'admin_action'
  AND created_at > COALESCE((SELECT MAX(created_at) FROM public.admin_audit_log), '1970-01-01'::timestamptz);
