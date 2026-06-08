-- GEO Audit · Fase B — Supabase migration
-- Eseguire nel SQL Editor di Supabase Dashboard

CREATE TABLE public.audits (
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

CREATE POLICY "own_audits" ON public.audits
    FOR ALL
    USING (auth.uid() = user_id);

-- Indici per performance del cron worker e del lookup pending_email
CREATE INDEX audits_status_created  ON public.audits (status, created_at);
CREATE INDEX audits_pending_email   ON public.audits (pending_email) WHERE pending_email IS NOT NULL;
