# -*- coding: utf-8 -*-
"""La formula del punteggio, su check costruiti a mano.

Protegge il numero che il cliente vede per primo. Ogni caso qui e' una regola
che il prodotto dichiara altrove: se cambia la formula, uno di questi cade.
"""
import unittest

import geo_audit as g


def ck(stato, peso=1, id_="x", categoria="Test"):
    return g.Check(id=id_, category=categoria, title="t", status=stato, weight=peso)


class FormulaDelPunteggio(unittest.TestCase):

    def test_tutto_a_posto_fa_cento(self):
        self.assertEqual(g.score_checks([ck(g.OK), ck(g.OK, 5)]), 100)

    def test_tutto_fallito_fa_zero(self):
        self.assertEqual(g.score_checks([ck(g.FAIL), ck(g.FAIL, 5)]), 0)

    def test_un_warn_vale_meta(self):
        self.assertEqual(g.score_checks([ck(g.WARN)]), 50)

    def test_il_peso_conta(self):
        # un fail da 9 contro un ok da 1: 10% e non 50%
        self.assertEqual(g.score_checks([ck(g.OK, 1), ck(g.FAIL, 9)]), 10)

    def test_unknown_non_premia_e_non_penalizza(self):
        """⚠️ E' la regola meno ovvia della formula: un check non misurabile
        esce da numeratore E denominatore. Se entrasse solo nel denominatore,
        un sito su cui non riusciamo a misurare qualcosa verrebbe punito per
        un limite nostro."""
        solo_ok = g.score_checks([ck(g.OK)])
        con_unknown = g.score_checks([ck(g.OK), ck(g.UNK, 100)])
        self.assertEqual(solo_ok, con_unknown)
        self.assertEqual(con_unknown, 100)

    def test_nessun_check_misurabile_non_esplode(self):
        self.assertEqual(g.score_checks([]), 0)
        self.assertEqual(g.score_checks([ck(g.UNK)]), 0)

    def test_i_check_di_sito_si_diluiscono(self):
        """⚠️ Non e' una regola voluta, e' il difetto dichiarato in
        `docs/10`: `crawl.ai` pesa 12 e con trenta pagine il denominatore
        arriva a ~2.500, quindi un sito che blocca del tutto i crawler AI
        perde meno di mezzo punto. Il test lo fissa per iscritto: quando
        si rivede la formula (blocco 2.3) deve CADERE, ed e' il segnale
        che il difetto e' stato corretto."""
        crawl_ai_bloccato = ck(g.FAIL, 12, id_="crawl.ai")
        trenta_pagine = [ck(g.OK, 3) for _ in range(800)]
        punteggio = g.score_checks([crawl_ai_bloccato] + trenta_pagine)
        self.assertGreaterEqual(punteggio, 99,
                                "il difetto della diluizione e' cambiato: rivedere 2.3")


class LettereEBande(unittest.TestCase):

    def test_le_lettere_sulle_soglie(self):
        for punteggio, atteso in ((100, "A"), (90, "A"), (89, "B"), (75, "B"),
                                  (74, "C"), (60, "C"), (59, "D"), (45, "D"),
                                  (44, "E"), (30, "E"), (29, "F"), (0, "F")):
            self.assertEqual(g.grade(punteggio), atteso, f"punteggio {punteggio}")

    def test_le_bande_seguono_le_lettere(self):
        self.assertEqual(g.band(90), "Eccellente")
        self.assertEqual(g.band(75), "Buono")
        self.assertEqual(g.band(60), "Discreto")
        self.assertEqual(g.band(45), "Da rafforzare")
        self.assertEqual(g.band(44), "Critico")


class PunteggioPerArea(unittest.TestCase):

    def test_raggruppa_per_categoria(self):
        # torna (mappa categoria -> check, lista di coppie (nome, punteggio))
        _, aree = g.compute_area_scores([
            ck(g.OK, id_="a", categoria="Alfa"),
            ck(g.FAIL, id_="b", categoria="Beta"),
        ])
        per_nome = dict(aree)
        self.assertEqual(per_nome["Alfa"], 100)
        self.assertEqual(per_nome["Beta"], 0)

    def test_ordinate_dalla_peggiore(self):
        """La scheda mostra per prima l'area su cui c'e' piu' da lavorare."""
        _, aree = g.compute_area_scores([
            ck(g.OK, id_="a", categoria="Buona"),
            ck(g.FAIL, id_="b", categoria="Pessima"),
            ck(g.WARN, id_="c", categoria="Media"),
        ])
        self.assertEqual([nome for nome, _ in aree], ["Pessima", "Media", "Buona"])

    def test_unknown_non_crea_un_area(self):
        """Un'area i cui check sono tutti non misurabili non deve comparire
        con uno zero: zero vuol dire «misurato e fallito»."""
        _, aree = g.compute_area_scores([
            ck(g.OK, id_="a", categoria="Vera"),
            ck(g.UNK, id_="b", categoria="Nonmisurata"),
        ])
        self.assertEqual([nome for nome, _ in aree], ["Vera"])


if __name__ == "__main__":
    unittest.main()
