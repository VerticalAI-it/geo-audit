# -*- coding: utf-8 -*-
"""Il lotto di test del progetto.

Si lancia senza installare niente:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v

⚠️ Sono test **offline**: non toccano la rete né il database. Quello che
richiede dati veri sta in `qa/`, si lancia a mano e spende. I due servono a
cose diverse e non vanno mescolati — un test che ha bisogno della produzione
per girare smette di essere lanciato entro un mese.

⚠️ `db.py` e `views.py` leggono le credenziali all'import e sollevano se non
ci sono. Per questo `tests/conftest_env.py` mette dei valori finti PRIMA
dell'import: vanno importati da lì, mai direttamente in testa a un test.
"""
