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
-- GEO Audit · Fase D — Rifai audit manuale + audit periodico via cron
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
