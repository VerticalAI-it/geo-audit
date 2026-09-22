# -*- coding: utf-8 -*-
"""Lo stato che la dashboard mostra accanto a ogni progetto.

Non e' un dato salvato: si ricalcola ogni volta dall'ultimo audit. Le soglie
sono la cosa che il cliente legge per prima, e cambiarle per sbaglio sposta
tutti i progetti di colonna senza che nulla segnali il cambiamento.
"""
import unittest
from datetime import datetime, timedelta, timezone

from tests import conftest_env  # noqa: F401  — credenziali finte prima di views

from views import _project_status


def audit(overall=90, critical=0, giorni_fa=1):
    quando = datetime.now(timezone.utc) - timedelta(days=giorni_fa)
    return {"overall": overall, "critical_count": critical,
            "created_at": quando.isoformat()}


class StatoDelProgetto(unittest.TestCase):

    def test_senza_audit(self):
        self.assertEqual(_project_status(None), "Audit required")
        self.assertEqual(_project_status({}), "Audit required")

    def test_audit_senza_punteggio(self):
        """Un audit fallito ha `overall` vuoto: non e' un progetto messo male,
        e' un progetto non misurato. Dire «Critical» sarebbe un'accusa al sito
        del cliente per un guasto nostro."""
        self.assertEqual(_project_status({"overall": None, "created_at": "2026-09-01"}),
                         "Audit required")

    def test_le_tre_soglie(self):
        self.assertEqual(_project_status(audit(overall=75)), "Healthy")
        self.assertEqual(_project_status(audit(overall=74)), "Needs attention")
        self.assertEqual(_project_status(audit(overall=50)), "Needs attention")
        self.assertEqual(_project_status(audit(overall=49)), "Critical")

    def test_una_criticita_batte_il_punteggio(self):
        """⚠️ Un sito con 95 e una criticita' critica aperta NON e' sano.
        E' la regola che rende lo stato diverso dal punteggio: il punteggio
        e' una media, lo stato e' un allarme."""
        self.assertEqual(_project_status(audit(overall=95, critical=1)), "Critical")

    def test_un_audit_vecchio_torna_da_rifare(self):
        """Oltre i trenta giorni il dato non descrive piu' il sito di oggi:
        mostrarlo come valido sarebbe peggio che dire che manca."""
        self.assertEqual(_project_status(audit(overall=95, giorni_fa=31)), "Audit required")
        self.assertEqual(_project_status(audit(overall=95, giorni_fa=29)), "Healthy")

    def test_la_scadenza_batte_anche_la_criticita(self):
        self.assertEqual(_project_status(audit(overall=20, critical=5, giorni_fa=40)),
                         "Audit required")

    def test_una_data_illeggibile_non_fa_esplodere_la_dashboard(self):
        """⚠️ La dashboard elenca tutti i progetti: se una riga solleva, la
        pagina intera non si apre. Meglio trattare la data come recente e
        mostrare il punteggio."""
        self.assertEqual(
            _project_status({"overall": 90, "critical_count": 0, "created_at": "boh"}),
            "Healthy")


if __name__ == "__main__":
    unittest.main()
