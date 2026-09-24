-- ══════════════════════════════════════════════════════════════════════════
-- FASE L · La gravita' diventa un ENUM, per ordinarla come si legge
-- 24 settembre 2026 — richiesta di Francesco, verifica chiesta da Silvio
--
-- IL PROBLEMA
-- Nel codice la gravita' e' ordinata bene (critical < high < medium < low <
-- info). Sul database la colonna e' TEXT, quindi PostgREST la ordina in
-- alfabetico: critical, high, info, low, medium. Risultato: "info" compare
-- prima di "low" e di "medium", e le criticita' meno gravi salgono in cima.
-- Si vede in due punti che il cliente guarda: l'export Excel delle criticita'
-- e la scheda Opportunita'.
--
-- LA CORREZIONE
-- Un ENUM Postgres. Gli ENUM si ordinano per ordine di DICHIARAZIONE, non in
-- alfabetico, quindi basta dichiararli nell'ordine giusto e ogni ORDER BY
-- diventa corretto da solo — nel codice non serve cambiare niente.
--
-- ⚠️ Rieseguibile per intero quante volte si vuole.
-- ⚠️ Non distrugge dati: se qualche riga avesse un valore fuori dai cinque
-- previsti, lo script SI FERMA e lo dice, invece di convertire a forza.
-- ══════════════════════════════════════════════════════════════════════════

-- ── 1 · Il tipo, se non c'e' gia' ─────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'issue_severity') THEN
        CREATE TYPE public.issue_severity AS ENUM
            ('critical', 'high', 'medium', 'low', 'info');
    END IF;
END $$;

-- ── 2 · Controllo prima di toccare la colonna ─────────────────────────────
-- ⚠️ Questo blocco esiste per FERMARE lo script, non per decorarlo. Un
-- ALTER ... USING su un valore non previsto fallisce a metà tabella: meglio
-- sapere prima quali sono, e deciderlo con calma.
DO $$
DECLARE
    intrusi TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'issue'
                 AND column_name = 'severity' AND data_type = 'text') THEN
        SELECT string_agg(DISTINCT COALESCE(severity, '<vuoto>'), ', ')
          INTO intrusi
          FROM public.issue
         WHERE severity IS NULL
            OR severity NOT IN ('critical', 'high', 'medium', 'low', 'info');
        IF intrusi IS NOT NULL THEN
            RAISE EXCEPTION
                'Valori di severity fuori dai cinque previsti: %. '
                'Sistemarli prima di convertire la colonna.', intrusi;
        END IF;
    END IF;
END $$;

-- ── 3 · La conversione ────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'issue'
                 AND column_name = 'severity' AND data_type = 'text') THEN
        -- Un eventuale DEFAULT testuale va togliato prima: il tipo cambia
        -- sotto di lui e la conversione si blocca.
        ALTER TABLE public.issue ALTER COLUMN severity DROP DEFAULT;
        ALTER TABLE public.issue
            ALTER COLUMN severity TYPE public.issue_severity
            USING severity::public.issue_severity;
        ALTER TABLE public.issue
            ALTER COLUMN severity SET DEFAULT 'medium'::public.issue_severity;
    END IF;
END $$;

-- ── 4 · Come si verifica che sia servito ──────────────────────────────────
-- Questa query deve restituire le gravita' in quest'ordine esatto:
--     critical, high, medium, low, info
-- Se le restituisce in alfabetico (critical, high, info, low, medium) la
-- conversione non e' avvenuta.
--
--     SELECT DISTINCT severity FROM public.issue ORDER BY severity;
