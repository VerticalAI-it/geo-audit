-- ════════════════════════════════════════════════════════════════════════════
-- Fase M · Archiviazione dei progetti
--
-- Da eseguire dal pannello SQL di Supabase (la service role key del prodotto
-- scrive righe ma non fa DDL).
--
-- È RI-ESEGUIBILE: lanciarlo due volte non fa danni e non tocca i dati.
--
-- ⚠️ `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` e non `CREATE TABLE IF NOT
-- EXISTS`: il secondo su una tabella che esiste già non aggiunge le colonne
-- nuove e non dice niente, quindi sembrerebbe andato a buon fine.
--
-- Perché archiviare e non cancellare: un progetto porta con sé gli audit, gli
-- eventi di tracking e lo storico del punteggio. Cancellarlo butterebbe mesi
-- di misure per far sparire una riga da un elenco, e non si torna indietro.
-- Archiviare nasconde il progetto e ferma tutto ciò che gira; i dati restano
-- e il ripristino è una riga.
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE public.project
  ADD COLUMN IF NOT EXISTS archived_at timestamptz,
  ADD COLUMN IF NOT EXISTS archived_by text;

COMMENT ON COLUMN public.project.archived_at IS
  'Quando il progetto è stato archiviato. NULL = attivo. Un progetto archiviato non compare in home, non viene più analizzato dal cron, non fa girare il monitoraggio AI e non manda email.';
COMMENT ON COLUMN public.project.archived_by IS
  'Chi lo ha archiviato (email). Serve a saperlo mesi dopo, quando nessuno ricorda perché quel progetto è sparito.';

-- Gli elenchi leggono sempre «i non archiviati»: l'indice parziale serve
-- esattamente quella domanda e resta piccolo perché gli archiviati sono pochi.
CREATE INDEX IF NOT EXISTS project_attivi_idx
  ON public.project (user_id, updated_at DESC)
  WHERE archived_at IS NULL;

-- ── Controprova ─────────────────────────────────────────────────────────────
-- Deve stampare due righe (archived_at, archived_by). Se ne stampa zero, lo
-- script non è andato: non fidarsi del «Success» del pannello.
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name = 'project'
   AND column_name IN ('archived_at', 'archived_by')
 ORDER BY column_name;
