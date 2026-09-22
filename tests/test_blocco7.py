# -*- coding: utf-8 -*-
"""Blocco 7 · provenienza dei dati, roadmap a 90 giorni, anomalia del traffico."""
import unittest
from datetime import date, timedelta

from tests import conftest_env  # noqa: F401  — credenziali finte prima di views

import roadmap90
import views


class ProvenienzaDeiDati(unittest.TestCase):
    """7.1 · ogni numero dichiara com'è stato ottenuto."""

    def test_le_cinque_nature_esistono(self):
        self.assertEqual(set(views.PROVENIENZA),
                         {"audit", "misurato", "monitorato", "piattaforma", "stimato"})

    def test_ognuna_ha_sigla_e_spiegazione(self):
        for chiave, (sigla, spiega) in views.PROVENIENZA.items():
            self.assertTrue(sigla.isupper(), chiave)
            self.assertGreater(len(spiega), 30, chiave)

    def test_il_badge_porta_la_spiegazione_nel_titolo(self):
        h = views._badge_provenienza("misurato")
        self.assertIn("prov--misurato", h)
        self.assertIn("title=", h)
        self.assertIn("MISURATO", h)

    def test_una_natura_inventata_non_stampa_niente(self):
        """⚠️ Meglio nessun badge che un badge sbagliato: un'etichetta di
        provenienza è un'affermazione sul dato, non una decorazione."""
        self.assertEqual(views._badge_provenienza("boh"), "")
        self.assertEqual(views._badge_provenienza(""), "")

    def test_il_kpi_senza_provenienza_resta_com_era(self):
        self.assertNotIn("prov--", views._kpi_semplice(3, "Cose"))


def _issue(check_id, severity="medium", url="/p", stato="open"):
    return {"check_id": check_id, "severity": severity, "url": url,
            "status": stato, "title": check_id, "category": "X"}


class RoadmapA90Giorni(unittest.TestCase):
    """7.2 · le criticità aperte diventano un piano in tre fasi."""

    def test_sempre_tre_fasi(self):
        fasi = roadmap90.costruisci([_issue("content.h1")])
        self.assertEqual([f["numero"] for f in fasi], [1, 2, 3])

    def test_l_accesso_viene_prima_del_contenuto(self):
        """⚠️ È la regola che dà senso alla roadmap: sistemare le FAQ su un
        sito che blocca GPTBot è lavoro sprecato."""
        fasi = roadmap90.costruisci([_issue("crawl.ai", "critical"),
                                     _issue("faq.answerlen", "low")])
        self.assertEqual([v["check_id"] for v in fasi[0]["voci"]], ["crawl.ai"])
        self.assertEqual([v["check_id"] for v in fasi[2]["voci"]], ["faq.answerlen"])

    def test_una_voce_per_check_non_per_pagina(self):
        """«Aggiungi la meta description» ripetuto quattordici volte è un
        elenco, non un piano."""
        issues = [_issue("meta.description", url=f"/p{i}") for i in range(14)]
        fasi = roadmap90.costruisci(issues)
        voci = [v for f in fasi for v in f["voci"]]
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["pagine"], 14)

    def test_le_risolte_non_entrano(self):
        """La roadmap dice cosa fare, non cosa è stato fatto."""
        fasi = roadmap90.costruisci([_issue("content.h1", stato="resolved")])
        self.assertEqual(roadmap90.quante_voci(fasi), 0)

    def test_dentro_una_fase_prima_le_gravi(self):
        fasi = roadmap90.costruisci([_issue("content.tldr", "low"),
                                     _issue("content.h1", "critical")])
        self.assertEqual(fasi[1]["voci"][0]["check_id"], "content.h1")

    def test_un_check_sconosciuto_finisce_comunque_in_una_fase(self):
        """⚠️ Un controllo aggiunto domani e non ancora mappato non deve
        sparire dalla roadmap: si colloca dal prefisso."""
        fasi = roadmap90.costruisci([_issue("crawl.qualcosa_di_nuovo")])
        self.assertEqual(roadmap90.quante_voci(fasi), 1)
        self.assertEqual(len(fasi[0]["voci"]), 1)

    def test_il_rimedio_arriva_dall_ultimo_audit(self):
        fasi = roadmap90.costruisci([_issue("content.h1")],
                                    {"content.h1": "Usa un solo H1."})
        self.assertEqual(fasi[1]["voci"][0]["rimedio"], "Usa un solo H1.")

    def test_niente_criticita_niente_roadmap(self):
        self.assertEqual(roadmap90.quante_voci(roadmap90.costruisci([])), 0)


class AnomaliaDelTrafficoAI(unittest.TestCase):
    """7.3 · quando vale la pena mandare un'email, e quando no."""

    OGGI = date(2026, 9, 22)

    def _giorni(self, ultima_settimana, tre_settimane_prima):
        d = {}
        for i in range(7):
            d[(self.OGGI - timedelta(days=i)).isoformat()] = ultima_settimana
        for i in range(7, 28):
            d[(self.OGGI - timedelta(days=i)).isoformat()] = tre_settimane_prima
        return d

    def _valuta(self, a, b):
        import server
        return server.valuta_traffico_ai(self._giorni(a, b), self.OGGI.isoformat())

    def test_traffico_stabile_non_dice_niente(self):
        self.assertIsNone(self._valuta(10, 10))

    def test_una_oscillazione_normale_non_basta(self):
        """⚠️ +40% non è un fatto, è una settimana. La soglia è il doppio."""
        self.assertIsNone(self._valuta(14, 10))

    def test_il_raddoppio_si_segnala(self):
        r = self._valuta(30, 10)
        self.assertEqual(r["verso"], "salito")
        self.assertGreaterEqual(r["rapporto"], 2.0)

    def test_il_dimezzamento_si_segnala(self):
        r = self._valuta(3, 30)
        self.assertEqual(r["verso"], "sceso")

    def test_sui_numeri_piccoli_tace(self):
        """⚠️ Da tre a sei passaggi è «+100%», e non significa niente. È il
        caso in cui un avviso automatico fa più danno che bene."""
        self.assertIsNone(self._valuta(1, 0))
        self.assertIsNone(self._valuta(2, 1))

    def test_il_traffico_che_compare_dal_nulla_e_una_notizia(self):
        r = self._valuta(8, 0)
        self.assertEqual(r["verso"], "comparso")
        self.assertIsNone(r["rapporto"])

    def test_nasce_spento(self):
        """⚠️ A differenza degli altri due avvisi. Quelli partono dopo un
        audit, che è un evento raro e voluto; questo guarda il traffico, che
        oscilla da solo."""
        from db import _REPORT_PREF_DEFAULT
        self.assertIs(_REPORT_PREF_DEFAULT["alert_traffico_ai"], False)


if __name__ == "__main__":
    unittest.main()
