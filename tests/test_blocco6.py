# -*- coding: utf-8 -*-
"""Blocco 6 · piani, cosa sblocca ognuno, e le priorità per assistente."""
import unittest

from tests import conftest_env  # noqa: F401  — credenziali finte prima di views

import piani
import punteggi_motore as pm


class PianoDelProgetto(unittest.TestCase):

    def test_chi_non_ha_piano_scritto_vede_tutto(self):
        """⚠️ La regola che protegge i progetti nati prima dei piani: farli
        diventare `free` toglierebbe da un giorno all'altro funzioni in uso."""
        self.assertEqual(piani.piano_del_progetto({}), piani.PAID)
        self.assertEqual(piani.piano_del_progetto(None), piani.PAID)
        self.assertEqual(piani.piano_del_progetto({"plan": None}), piani.PAID)

    def test_un_piano_inventato_non_declassa(self):
        self.assertEqual(piani.piano_del_progetto({"plan": "gold"}), piani.PAID)

    def test_free_si_assegna_esplicitamente(self):
        self.assertEqual(piani.piano_del_progetto({"plan": "free"}), piani.FREE)
        self.assertEqual(piani.piano_del_progetto({"plan": " FREE "}), piani.FREE)

    def test_il_punteggio_e_incluso_anche_nel_base(self):
        self.assertTrue(piani.incluso({"plan": "free"}, "punteggio"))
        self.assertTrue(piani.incluso({"plan": "free"}, "criticita"))

    def test_le_funzioni_a_pagamento_sono_teaser_nel_base(self):
        for f in ("roadmap_90", "punteggio_motore", "citazioni", "competitors"):
            self.assertTrue(piani.solo_assaggio({"plan": "free"}, f), f)
            self.assertTrue(piani.incluso({"plan": "paid"}, f), f)

    def test_una_funzione_non_governata_resta_visibile(self):
        """⚠️ Il default è APERTO: una funzione aggiunta domani e dimenticata
        qui dentro si vede, non sparisce in silenzio per tutti."""
        self.assertTrue(piani.incluso({"plan": "free"}, "qualcosa_di_nuovo"))

    def test_i_prezzi_restano_vuoti(self):
        """Decisione di Vertical AI: un prezzo messo «per ora» nel codice
        diventa il prezzo vero il giorno che qualcuno lo legge."""
        for p in piani.PIANI:
            self.assertIsNone(piani.LISTINO[p]["prezzo"], p)

    def test_ogni_funzione_a_pagamento_ha_un_nome_leggibile(self):
        for f, riga in piani.FUNZIONI.items():
            if riga[piani.FREE] is not True:
                self.assertIn(f, piani.ETICHETTA, f)


def _ck(cid, stato="fail", peso=3, titolo="x"):
    return {"check_id": cid, "status": stato, "weight": peso, "title": titolo}


class PrioritaPerAssistente(unittest.TestCase):
    """6.3 · quattro elenchi, non quattro numeri."""

    def test_sempre_i_quattro_motori(self):
        r = pm.priorita_per_motore([_ck("crawl.ai")], [])
        self.assertEqual([b["motore"] for b in r], list(pm.MOTORI))

    def test_chi_e_a_posto_non_entra_in_nessun_elenco(self):
        r = pm.priorita_per_motore([_ck("crawl.ai", "ok")], [])
        self.assertEqual(sum(len(b["voci"]) for b in r), 0)

    def test_il_moltiplicatore_cambia_l_ordine(self):
        """⚠️ È l'unica ragione per cui la funzione esiste: se due motori
        dessero sempre lo stesso ordine, sarebbero lo stesso elenco stampato
        quattro volte."""
        checks = [_ck("render.parity", peso=3, titolo="Parità statica"),
                  _ck("sd.present", peso=3, titolo="Dati strutturati")]
        per = {b["motore"]: [v["check_id"] for v in b["voci"]]
               for b in pm.priorita_per_motore(checks, [])}
        self.assertEqual(per["gemini"][0], "render.parity")
        self.assertEqual(per["openai"][0], "sd.present")

    def test_un_fail_batte_un_warn_di_pari_peso(self):
        r = pm.priorita_per_motore([_ck("a", "warn"), _ck("b", "fail")], [])
        self.assertEqual(r[0]["voci"][0]["check_id"], "b")

    def test_una_voce_per_check_non_per_pagina(self):
        pag = [_ck("meta.description") for _ in range(9)]
        voci = pm.priorita_per_motore([], pag)[0]["voci"]
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0]["volte"], 9)

    def test_dichiara_quando_il_motivo_e_specifico_del_motore(self):
        r = {b["motore"]: b["voci"][0] for b in pm.priorita_per_motore([_ck("render.parity")], [])}
        self.assertTrue(r["gemini"]["specifico"])
        self.assertFalse(r["perplexity"]["specifico"])

    def test_il_rimedio_arriva_dall_audit(self):
        v = pm.priorita_per_motore([_ck("crawl.ai")], [],
                                   {"crawl.ai": "Sblocca GPTBot."})[0]["voci"][0]
        self.assertEqual(v["rimedio"], "Sblocca GPTBot.")

    def test_i_sotto_punteggi_restano_calcolabili_ma_sono_vicini(self):
        """⚠️ Misurato sui progetti veri: la forbice è di 2-3 punti. Per
        questo il prodotto non li mostra come quattro numeri."""
        self.assertLessEqual(pm.FORBICE_OSSERVATA, 5)
        p = [v["punteggio"] for v in pm.per_motore([_ck("crawl.ai", "ok")], [_ck("a", "warn")])]
        self.assertEqual(len(p), 4)


if __name__ == "__main__":
    unittest.main()
