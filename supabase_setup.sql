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


-- ════════════════════════════════════════════════════════════════════════════
-- FASE E · Rapporti: preferenze di invio e registro (6 settembre 2026)
--
-- Serve alla funzionalità Reports (documento GEO_Audit_Reports di Francesco).
-- ⚠️ Il codice FUNZIONA GIÀ SENZA queste tabelle: finché non ci sono, le
-- preferenze e gli invii vivono in `tracking_event`. Eseguendo questo blocco il
-- prodotto ci si sposta da solo, senza modifiche al codice — la scelta sta in
-- `_report_tabella_c_e()` in `db.py`. Le righe già scritte nel frattempo
-- vengono travasate qui sotto.
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.report_preferences (
    project_id                UUID        PRIMARY KEY
                                          REFERENCES public.project(id) ON DELETE CASCADE,
    client_digest_frequency   TEXT        NOT NULL DEFAULT 'monthly',
    team_digest_frequency     TEXT        NOT NULL DEFAULT 'weekly',
    alert_score_drop          BOOLEAN     NOT NULL DEFAULT TRUE,
    alert_new_critical        BOOLEAN     NOT NULL DEFAULT TRUE,
    -- Resta FALSE finché non esiste la sezione Competitors che dovrebbe
    -- farlo scattare: un avviso che non può partire è peggio di uno spento,
    -- perché chi lo vede acceso smette di controllare a mano.
    alert_competitor_overtake BOOLEAN     NOT NULL DEFAULT FALSE,
    updated_at                TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT report_pref_client_freq CHECK (client_digest_frequency IN ('weekly','monthly','off')),
    CONSTRAINT report_pref_team_freq   CHECK (team_digest_frequency   IN ('weekly','monthly','off'))
);

ALTER TABLE public.report_preferences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_report_prefs" ON public.report_preferences;
CREATE POLICY "own_report_prefs" ON public.report_preferences
    FOR ALL
    USING (EXISTS (SELECT 1 FROM public.project p
                   WHERE p.id = report_preferences.project_id AND p.user_id = auth.uid()));

CREATE TABLE IF NOT EXISTS public.report_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    report_type TEXT        NOT NULL,   -- client_digest | team_digest
                                        -- | alert_score_drop | alert_new_critical
    sent_to     TEXT        NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.report_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_report_log" ON public.report_log;
CREATE POLICY "own_report_log" ON public.report_log
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.project p
                   WHERE p.id = report_log.project_id AND p.user_id = auth.uid()));

-- ⚠️ Questo indice non è un dettaglio: `_sb_report_log_ultimo()` lo interroga
-- per OGNI progetto a ogni giro del cron, ed è quello che impedisce di
-- rimandare lo stesso riepilogo ogni ora.
CREATE INDEX IF NOT EXISTS report_log_progetto_tipo
    ON public.report_log (project_id, report_type, sent_at DESC);

-- ── Travaso di quello che nel frattempo è finito in tracking_event ──────────
-- Rieseguirlo non crea doppioni.

INSERT INTO public.report_preferences (
    project_id, client_digest_frequency, team_digest_frequency,
    alert_score_drop, alert_new_critical, updated_at)
SELECT DISTINCT ON (t.project_id)
    t.project_id,
    COALESCE(t.properties->>'client_digest_frequency', 'monthly'),
    COALESCE(t.properties->>'team_digest_frequency', 'weekly'),
    COALESCE((t.properties->>'alert_score_drop')::boolean, TRUE),
    COALESCE((t.properties->>'alert_new_critical')::boolean, TRUE),
    t.created_at
FROM public.tracking_event t
JOIN public.project p ON p.id = t.project_id
WHERE t.event_name = 'report_pref'
  AND t.project_id IS NOT NULL
ORDER BY t.project_id, t.created_at DESC      -- l'ultima scelta vince
ON CONFLICT (project_id) DO NOTHING;

INSERT INTO public.report_log (project_id, report_type, sent_to, sent_at)
SELECT t.project_id,
       COALESCE(t.properties->>'report_type', '?'),
       COALESCE(t.properties->>'sent_to', '?'),
       t.created_at
FROM public.tracking_event t
JOIN public.project p ON p.id = t.project_id
WHERE t.event_name = 'report_inviato'
  AND t.project_id IS NOT NULL
  AND t.created_at > COALESCE((SELECT MAX(sent_at) FROM public.report_log), '1970-01-01'::timestamptz);


-- ════════════════════════════════════════════════════════════════════════════
-- FASE F · Monitoraggio prompt AI (8 settembre 2026)
--
-- Serve alle 6 schermate del documento GEO_Audit_PromptMonitoring: le 2 admin
-- (Configurazione AI, Monitoraggio per progetto) e le 4 cliente (AI Visibility,
-- Prompts & Queries, Competitors, Citations).
--
-- ⚠️ A differenza della Fase E, QUI NON C'È RIPIEGO: queste tabelle sono
-- relazionali e legate fra loro, e non si possono appoggiare a `tracking_event`
-- come si è fatto per le preferenze dei rapporti. Finché questo blocco non è
-- eseguito, il monitoraggio non può partire.
--
-- Il motore che le riempirà è già scritto e provato: `ai_monitor.py` interroga
-- i quattro provider e legge le citazioni. Manca solo dove metterle.
-- ════════════════════════════════════════════════════════════════════════════

-- ── Chiavi API e modelli (globale, non per progetto) ────────────────────────

CREATE TABLE IF NOT EXISTS public.llm_provider_config (
    provider          TEXT        PRIMARY KEY,   -- openai | anthropic | gemini | perplexity
    -- ⚠️ CIFRATA, mai in chiaro. Il documento lo mette fra i requisiti non
    -- negoziabili: chi legge questa tabella non deve poter usare la chiave.
    api_key_encrypted TEXT        NOT NULL,
    default_model     TEXT,
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_by        TEXT                       -- email di chi ha fatto la modifica
);

ALTER TABLE public.llm_provider_config ENABLE ROW LEVEL SECURITY;
-- Nessuna policy: si legge solo con la service role key, dal server. Un client
-- non deve poter arrivare a questa tabella in nessun caso.

CREATE TABLE IF NOT EXISTS public.llm_available_models (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    provider            TEXT        REFERENCES public.llm_provider_config(provider)
                                    ON DELETE CASCADE,
    model_id            TEXT        NOT NULL,
    -- ⚠️ Un modello che non sa cercare sul web risponde a memoria, e a memoria
    -- non cita nessuno: sceglierlo darebbe zero citazioni per sempre, senza
    -- che si capisca il perché.
    supports_web_search BOOLEAN     NOT NULL DEFAULT FALSE,
    fetched_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (provider, model_id)
);

ALTER TABLE public.llm_available_models ENABLE ROW LEVEL SECURITY;

-- ── Impostazioni per progetto ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.ai_monitoring_settings (
    project_id         UUID        PRIMARY KEY REFERENCES public.project(id) ON DELETE CASCADE,
    -- Default TRUE come da Decisione 6: un progetto nuovo nasce monitorato.
    is_active          BOOLEAN     NOT NULL DEFAULT TRUE,
    schedule_frequency TEXT        NOT NULL DEFAULT 'weekly',
    sentiment_enabled  BOOLEAN     NOT NULL DEFAULT TRUE,
    last_run_at        TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_by         TEXT,
    CONSTRAINT ai_freq CHECK (schedule_frequency IN ('weekly','monthly','custom'))
);

ALTER TABLE public.ai_monitoring_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_ai_settings" ON public.ai_monitoring_settings;
CREATE POLICY "own_ai_settings" ON public.ai_monitoring_settings
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.project p
                   WHERE p.id = ai_monitoring_settings.project_id AND p.user_id = auth.uid()));

-- ── Cosa si chiede alle AI ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.monitored_topics (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    name       TEXT        NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.monitored_prompts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id    UUID        REFERENCES public.monitored_topics(id) ON DELETE CASCADE,
    prompt_text TEXT        NOT NULL,
    intent      TEXT,
    source      TEXT        NOT NULL DEFAULT 'auto_generated',  -- auto_generated | manual
    active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.monitored_topics  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.monitored_prompts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_topics" ON public.monitored_topics;
CREATE POLICY "own_topics" ON public.monitored_topics
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.project p
                   WHERE p.id = monitored_topics.project_id AND p.user_id = auth.uid()));

-- ── Cosa hanno risposto ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.prompt_runs (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id     UUID        REFERENCES public.monitored_prompts(id) ON DELETE CASCADE,
    project_id    UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    provider      TEXT        NOT NULL,
    model_used    TEXT        NOT NULL,
    run_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    response_text TEXT,
    raw_response  JSONB,
    -- ⚠️ 'failed' è uno stato che serve davvero: un provider che non risponde e
    -- un provider che risponde senza citare nessuno sono due cose diverse, e
    -- confonderle in uno zero falserebbe il punteggio di visibilità.
    status        TEXT        NOT NULL DEFAULT 'completed',
    error         TEXT,
    CONSTRAINT run_status CHECK (status IN ('completed','failed'))
);

ALTER TABLE public.prompt_runs ENABLE ROW LEVEL SECURITY;

-- Le due letture che il prodotto fa di continuo: «l'ultima esecuzione di questo
-- progetto» e «tutte le esecuzioni del periodo».
CREATE INDEX IF NOT EXISTS prompt_runs_progetto ON public.prompt_runs (project_id, run_at DESC);
CREATE INDEX IF NOT EXISTS prompt_runs_prompt   ON public.prompt_runs (prompt_id, run_at DESC);

CREATE TABLE IF NOT EXISTS public.extracted_citations (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_run_id     UUID        REFERENCES public.prompt_runs(id) ON DELETE CASCADE,
    project_id        UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    cited_domain      TEXT        NOT NULL,
    cited_url         TEXT,
    is_target         BOOLEAN     NOT NULL,
    -- Chi è il dominio citato, quando non è il cliente: un concorrente, una
    -- fonte terza che parla del brand, o rumore. Senza questa distinzione la
    -- schermata Citations non può separare le sue due tabelle.
    citation_category TEXT,
    sentiment         TEXT,
    context_snippet   TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT cit_categoria CHECK (citation_category IS NULL OR citation_category IN
        ('target','competitor','third_party_about_brand','noise'))
);

ALTER TABLE public.extracted_citations ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS citazioni_progetto ON public.extracted_citations (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS citazioni_dominio  ON public.extracted_citations (project_id, cited_domain);

-- ── I concorrenti ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.project_competitors (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    domain     TEXT        NOT NULL,
    -- Le tre fonti del documento: proposto dal motore, aggiunto dal team,
    -- aggiunto dal cliente — che qui ha voce, unica eccezione al resto del
    -- monitoraggio, perché il suo mercato lo conosce lui.
    source     TEXT        NOT NULL,
    added_by   TEXT,
    -- 'excluded' invece di cancellato: se il cliente toglie un concorrente
    -- proposto dal motore, al prossimo giro di suggerimenti non deve tornare.
    status     TEXT        NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, domain),
    CONSTRAINT comp_source CHECK (source IN ('ai_suggested','admin_added','client_added')),
    CONSTRAINT comp_status CHECK (status IN ('active','excluded'))
);

ALTER TABLE public.project_competitors ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_competitors" ON public.project_competitors;
CREATE POLICY "own_competitors" ON public.project_competitors
    FOR ALL
    USING (EXISTS (SELECT 1 FROM public.project p
                   WHERE p.id = project_competitors.project_id AND p.user_id = auth.uid()));

-- ── L'aggregato che leggono le schermate ───────────────────────────────────
-- Decisione 5: mai calcolo live in pagina, sempre pre-aggregato da un job.

CREATE TABLE IF NOT EXISTS public.ai_visibility_snapshots (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id            UUID        REFERENCES public.project(id) ON DELETE CASCADE,
    period_start          DATE        NOT NULL,
    period_end            DATE        NOT NULL,
    visibility_score      NUMERIC,
    breakdown_by_provider JSONB,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, period_start, period_end)
);

ALTER TABLE public.ai_visibility_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_snapshots" ON public.ai_visibility_snapshots;
CREATE POLICY "own_snapshots" ON public.ai_visibility_snapshots
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.project p
                   WHERE p.id = ai_visibility_snapshots.project_id AND p.user_id = auth.uid()));

CREATE INDEX IF NOT EXISTS snapshot_progetto
    ON public.ai_visibility_snapshots (project_id, period_end DESC);

-- ── I progetti che ci sono già nascono monitorati ──────────────────────────
-- Decisione 6: is_active default true. Rieseguirlo non crea doppioni.
INSERT INTO public.ai_monitoring_settings (project_id)
SELECT id FROM public.project
ON CONFLICT (project_id) DO NOTHING;
