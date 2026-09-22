# -*- coding: utf-8 -*-
"""Credenziali finte, da importare PRIMA di `db` o `views`.

⚠️ `config.py` legge `os.environ["SUPABASE_URL"]` all'import e solleva
`KeyError` se manca: senza questo modulo, importare `views` in un test
fallisce prima ancora di arrivare alla riga da provare.

I valori sono volutamente inutilizzabili. Se un test arriva a fare una
richiesta vera fallisce con un errore di rete, invece di scrivere per sbaglio
sul database di produzione — che e' l'unico che esiste: non c'e' staging.
"""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "chiave-di-test-non-valida")
os.environ.setdefault("SUPABASE_ANON_KEY", "chiave-di-test-non-valida")
os.environ.setdefault("RESEND_API_KEY", "")
os.environ.setdefault("FROM_EMAIL", "test@test.invalid")
os.environ.setdefault("SITE_URL", "https://test.invalid")
os.environ.setdefault("CRON_SECRET", "segreto-di-test")
