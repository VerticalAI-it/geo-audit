# -*- coding: utf-8 -*-
"""«Rigenera suggerimenti» non risponde mai `ok` con zero concorrenti (14/10/2026).

Dopo la correzione di «Genera proposte», Francesco ha trovato lo stesso
sintomo sul bottone dei concorrenti: `{"esito":"ok","nuovi":[]}`, pagina
ricaricata uguale, nessun messaggio. Qui zero può essere la risposta giusta
(su verticalai.it nessun giro era ancora partito: le domande erano da
approvare), ma va detto il perché. Questi test fissano un motivo per ogni
strada che finisce a zero.

Nessuna richiesta vera: il database è sostituito.
"""
import asyncio
import json
import unittest
from unittest import mock

from tests import conftest_env  # noqa: F401

import ai_giro
import ai_schermate
import server


def _citazioni(dominio, risposte):
    """Una citazione di `dominio` in ognuna di `risposte` risposte diverse."""
    return [{"cited_domain": dominio, "prompt_run_id": f"run-{dominio}-{i}", "is_target": False}
            for i in range(risposte)]


class PercheNessunConcorrente(unittest.TestCase):

    def _motivo(self, esecuzioni=(), citazioni=(), concorrenti=(), domande=()):
        with mock.patch.object(ai_giro, "_sb_ai_esecuzioni", return_value=list(esecuzioni)), \
             mock.patch.object(ai_giro, "_sb_ai_citazioni", return_value=list(citazioni)), \
             mock.patch.object(ai_giro, "_sb_ai_concorrenti", return_value=list(concorrenti)), \
             mock.patch.object(ai_giro, "_sb_ai_domande", return_value=list(domande)):
            return ai_giro.perche_nessun_concorrente("p", "verticalai.it")

    def test_domande_da_approvare_e_il_caso_del_bug(self):
        """verticalai.it il 14/10: dieci domande generate, nessuna approvata, nessun giro."""
        motivo = self._motivo(domande=[{"approved": False}] * 10)
        self.assertIn("nessun giro", motivo)
        self.assertIn("10 domande sono da approvare", motivo)

    def test_nessun_giro(self):
        self.assertIn("nessun giro", self._motivo())

    def test_giri_tutti_falliti_per_credito(self):
        """Lo stato di produzione di ottobre: ogni interrogazione in 429."""
        esecuzioni = [{"status": "failed", "error": 'OpenAI HTTP 429: {"error": {"message": '
                       '"You have no credits remaining.", "type": "insufficient_quota"}}'}] * 4
        motivo = self._motivo(esecuzioni=esecuzioni)
        self.assertIn("tutte fallite", motivo)
        self.assertIn("credito esaurito", motivo)

    def test_giri_falliti_per_altro_riportano_l_errore(self):
        motivo = self._motivo(esecuzioni=[{"status": "failed", "error": "timeout"}])
        self.assertIn("timeout", motivo)

    def test_nessun_sito_citato(self):
        motivo = self._motivo(esecuzioni=[{"status": "completed"}] * 3)
        self.assertIn("non è citato nessun sito", motivo)

    def test_contenitori_e_sito_proprio_non_contano(self):
        citazioni = (_citazioni("facebook.com", 9) + _citazioni("verticalai.it", 9)
                     + _citazioni("blog.verticalai.it", 9))
        motivo = self._motivo(esecuzioni=[{"status": "completed"}], citazioni=citazioni)
        self.assertIn("non è citato nessun sito", motivo)

    def test_sotto_soglia_dice_il_piu_citato(self):
        citazioni = _citazioni("rivale.it", 3) + _citazioni("altro.it", 1)
        motivo = self._motivo(esecuzioni=[{"status": "completed"}], citazioni=citazioni)
        self.assertIn(f"almeno {ai_giro._SOGLIA_RISPOSTE} risposte", motivo)
        self.assertIn("rivale.it, compare in 3", motivo)

    def test_elenco_pieno(self):
        piene = [{"domain": f"c{i}.it", "source": "ai_suggested"} for i in range(ai_giro._MAX_PROPOSTI)]
        motivo = self._motivo(esecuzioni=[{"status": "completed"}],
                              citazioni=_citazioni("rivale.it", 6), concorrenti=piene)
        self.assertIn("il massimo", motivo)

    def test_gia_in_elenco_o_esclusi(self):
        motivo = self._motivo(esecuzioni=[{"status": "completed"}],
                              citazioni=_citazioni("rivale.it", 6),
                              concorrenti=[{"domain": "rivale.it", "source": "admin_added"}])
        self.assertIn("già in elenco", motivo)


class ScopriConcorrentiInvariato(unittest.TestCase):
    """L'estrazione di `_domini_ricorrenti` non cambia cosa si propone."""

    def _scopri(self, citazioni, concorrenti=()):
        aggiunti = []
        with mock.patch.object(ai_giro, "_sb_ai_citazioni", return_value=citazioni), \
             mock.patch.object(ai_giro, "_sb_ai_concorrenti", return_value=list(concorrenti)), \
             mock.patch.object(ai_giro, "_sb_ai_concorrente_aggiungi",
                               side_effect=lambda p, d, o: aggiunti.append(d) or True):
            return ai_giro.scopri_concorrenti("p", "www.verticalai.it"), aggiunti

    def test_propone_sopra_soglia_dal_piu_ricorrente(self):
        citazioni = _citazioni("b.it", 6) + _citazioni("a.it", 8) + _citazioni("c.it", 2)
        nuovi, aggiunti = self._scopri(citazioni)
        self.assertEqual(nuovi, ["a.it", "b.it"])
        self.assertEqual(aggiunti, ["a.it", "b.it"])

    def test_stessa_risposta_conta_una_volta(self):
        citazioni = [{"cited_domain": "a.it", "prompt_run_id": "r1", "is_target": False}] * 12
        self.assertEqual(self._scopri(citazioni)[0], [])

    def test_non_ripropone_gli_esclusi(self):
        nuovi, _ = self._scopri(_citazioni("a.it", 8),
                                [{"domain": "a.it", "source": "ai_suggested", "status": "excluded"}])
        self.assertEqual(nuovi, [])


class LEndpointDiceIlMotivo(unittest.TestCase):
    """POST /admin/progetti/{id}/ai/competitor/rigenera"""

    def _chiama(self, scopri, motivo="non c'è ancora nessun giro"):
        progetto = {"id": "p", "domain": "verticalai.it"}

        async def azione(request, project_id):
            return {"email": "admin@test.invalid"}, progetto, {}, None

        with mock.patch.object(server, "_admin_ai_azione", side_effect=azione), \
             mock.patch.object(server, "_admin_traccia"), \
             mock.patch.object(ai_giro, "scopri_concorrenti", side_effect=scopri), \
             mock.patch.object(ai_giro, "riclassifica_citazioni") as riclassifica, \
             mock.patch.object(ai_giro, "perche_nessun_concorrente", return_value=motivo):
            r = asyncio.run(server.admin_progetto_ai_comp_rigenera(None, "p"))
        return r.status_code, json.loads(r.body), riclassifica

    def test_zero_non_e_mai_ok(self):
        stato, corpo, riclassifica = self._chiama(lambda *a: [])
        self.assertEqual(stato, 200)
        self.assertEqual(corpo["esito"], "nessuno")
        self.assertIn("nessun giro", corpo["motivo"])
        riclassifica.assert_not_called()

    def test_successo_riclassifica(self):
        stato, corpo, riclassifica = self._chiama(lambda *a: ["rivale.it"])
        self.assertEqual((stato, corpo), (200, {"esito": "ok", "nuovi": ["rivale.it"]}))
        riclassifica.assert_called_once()

    def test_errore_imprevisto_e_un_errore(self):
        def scopri(*a):
            raise RuntimeError("database giù")
        stato, corpo, _ = self._chiama(scopri)
        self.assertEqual(stato, 500)
        self.assertEqual(corpo["esito"], "errore")
        self.assertIn("database giù", corpo["motivo"])


class LaPaginaMostraLEsito(unittest.TestCase):

    def test_banner_e_spinner_del_bottone_concorrenti(self):
        import inspect
        sorgente = inspect.getsource(ai_schermate)
        self.assertIn('id="esito-concorrenti"', sorgente)
        self.assertIn("rigeneraConcorrenti(b)", sorgente)
        # prima passava da `manda`, che ricarica la pagina senza dire niente
        self.assertNotIn("manda(BASE + '/competitor/rigenera'", sorgente)
        # zero risultati: banner giallo, non verde e non rosso
        self.assertIn("j.esito === 'nessuno'", sorgente)


if __name__ == "__main__":
    unittest.main()
