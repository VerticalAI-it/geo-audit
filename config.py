"""
GEO Audit — configurazione condivisa.

Le variabili d'ambiente lette qui sono usate da server.py, db.py e views.py.
SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY sono obbligatorie: se mancano il
processo non parte, ed e' voluto.
"""
import os

SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_SVC  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_ANON = os.environ.get("SUPABASE_ANON_KEY", "")
RESEND_KEY   = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL   = os.environ.get("FROM_EMAIL", "")
SITE_URL     = os.environ.get("SITE_URL", "").rstrip("/")
_SECRET      = os.environ.get("CRON_SECRET", "fallback-secret").encode()
