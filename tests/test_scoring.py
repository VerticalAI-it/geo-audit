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

    def test_in_un_calderone_solo_i_check_di_sito_si_diluiscono(self):
        """Il difetto che c'era fino alla 1.1.0, lasciato qui come promemoria
        di cosa succede a mettere tutto in un pool unico: `crawl.ai` pesa 12,
        trenta pagine pesano ~2.500, e bloccare i crawler AI costa meno di
        mezzo punto."""
        crawl_ai_bloccato = ck(g.FAIL, 12, id_="crawl.ai")
        trenta_pagine = [ck(g.OK, 3) for _ in range(800)]
        self.assertGreaterEqual(g.score_checks([crawl_ai_bloccato] + trenta_pagine), 99)


class PunteggioComplessivo(unittest.TestCase):
    """La formula della 1.2.0: sito e pagine pesati separatamente."""

    SITO_OK = [ck(g.OK, 12, "crawl.ai"), ck(g.OK, 2), ck(g.OK, 3), ck(g.OK, 1), ck(g.OK, 3)]
    SITO_BLOCCATO = [ck(g.FAIL, 12, "crawl.ai"), ck(g.OK, 2), ck(g.OK, 3),
                     ck(g.OK, 1), ck(g.OK, 3)]
    PAGINE_PERFETTE = [ck(g.OK, 3) for _ in range(800)]

    def test_bloccare_i_crawler_ai_costa_davvero(self):
        """⚠️ E' il motivo per cui la formula e' cambiata. Con un pool unico
        costava meno di un punto; adesso ne costa diciassette, che e' una
        cifra proporzionata al fatto che il sito e' invisibile agli
        assistenti."""
        sano = g.score_complessivo(self.SITO_OK, self.PAGINE_PERFETTE)
        bloccato = g.score_complessivo(self.SITO_BLOCCATO, self.PAGINE_PERFETTE)
        self.assertEqual(sano, 100)
        self.assertGreaterEqual(sano - bloccato, 15)

    def test_senza_pagine_conta_solo_il_sito(self):
        """⚠️ Un sito le cui pagine non si sono potute analizzare non deve
        prendere 30 su 100: sarebbe una penalita' per un limite del crawler,
        non per un difetto suo."""
        self.assertEqual(g.score_complessivo(self.SITO_OK, []), 100)

    def test_niente_di_misurabile_fa_zero(self):
        self.assertEqual(g.score_complessivo([], []), 0)
        self.assertEqual(g.score_complessivo([ck(g.UNK, 5)], [ck(g.UNK, 5)]), 0)

    # ⚠️ I test sui PESI del punteggio complessivo sono stati spostati in
    # `test_scoring_blocchi.py` il 24/09/2026, e non è un trasloco per ordine.
    # Nella formula a due blocchi bastava lo stato di un check per sapere
    # quanto pesava; in quella a tre è l'ID a decidere in quale blocco cade,
    # e gli aiuti di questo file costruiscono check con un id finto («x»).
    # Riscriverli qui vorrebbe dire duplicare l'elenco dei blocchi in due
    # posti, che è il modo migliore per farli divergere.
    #
    # `score_checks` — la media pesata vera e propria — resta collaudata qui
    # sopra, perché quella logica la formula nuova la usa identica.

    def test_un_check_con_id_ignoto_non_sposta_il_punteggio(self):
        """⚠️ Conseguenza da conoscere: se un check ha un id che nessun blocco
        rivendica, esce dal punteggio in silenzio. In produzione lo impedisce
        `test_nessun_check_del_catalogo_resta_orfano`, che confronta il
        catalogo emesso coi tre elenchi. Qui si fissa il comportamento, per
        non scoprirlo un giorno leggendo un numero sbagliato."""
        import blocchi_punteggio as bp
        self.assertEqual(bp.complessivo([ck(g.FAIL, 9, id_="mai.visto")], []), 0)
        self.assertEqual(bp.per_blocco([ck(g.FAIL, 9, id_="mai.visto")], [])["orfani"],
                         ["mai.visto"])


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
