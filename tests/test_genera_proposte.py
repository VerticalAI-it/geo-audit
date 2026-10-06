# -*- coding: utf-8 -*-
"""«Genera proposte» non risponde mai `ok` con zero domande (bug del 05/10/2026).

Su verticalai.it il bottone rispondeva `{"esito":"ok","generate":0}` e sembrava
non fare nulla. La causa era un credito OpenAI esaurito: il 429 finiva in una
stringa vuota, la stringa vuota in una lista vuota, la lista vuota in «zero
domande» e lo zero in un successo. Questi test fissano che ogni anello della
catena dica perché, invece di tacere.

Nessuna richiesta vera: provider e database sono sostituiti.
"""
import asyncio
import json
import unittest
from unittest import mock

from tests import conftest_env  # noqa: F401

import ai_giro
import server


class _Risposta:
    def __init__(self, stato, corpo):
        self.status_code = stato
        self._corpo = corpo
        self.text = json.dumps(corpo) if not isinstance(corpo, str) else corpo

    def json(self):
        if isinstance(self._corpo, str):
            raise ValueError("non JSON")
        return self._corpo


def _openai_testo(testo):
    return _Risposta(200, {"choices": [{"message": {"content": testo}}]})


_DIECI = json.dumps([{"domanda": f"Quale agenzia AI scegliere a Roma? Cita le fonti ({i})",
                      "argomento": "Agenzie AI", "intento": "comparativo"} for i in range(10)])


class IlProviderDiceIlMotivo(unittest.TestCase):
    """`_chiedi_senza_cercare` non trasforma più un errore in una stringa vuota."""

    def _errore(self, risposta, provider="openai"):
        with mock.patch("requests.post", return_value=risposta):
            with self.assertRaises(ai_giro.GenerazioneFallita) as ctx:
                ai_giro._chiedi_senza_cercare(provider, "ciao", "chiave")
        return ctx.exception.motivo

    def test_credito_openai_esaurito_e_il_caso_del_bug(self):
        """La risposta esatta ricevuta da OpenAI il 06/10 riproducendo il bug."""
        motivo = self._errore(_Risposta(429, {"error": {
            "message": "You have no credits remaining.", "type": "insufficient_quota",
            "code": "credit_balance_exhausted"}}))
        self.assertIn("credito esaurito", motivo)
        self.assertIn("OpenAI", motivo)

    def test_credito_anthropic_esaurito(self):
        motivo = self._errore(_Risposta(400, {"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API."}}),
            provider="anthropic")
        self.assertIn("credito esaurito", motivo)

    def test_chiave_non_valida(self):
        motivo = self._errore(_Risposta(401, {"error": {"message": "Incorrect API key"}}))
        self.assertIn("non valida", motivo)

    def test_limite_di_frequenza_non_e_credito(self):
        motivo = self._errore(_Risposta(429, {"error": {"message": "Rate limit reached",
                                                         "type": "requests"}}))
        self.assertIn("troppe richieste", motivo)
        self.assertNotIn("credito", motivo)

    def test_provider_irraggiungibile(self):
        with mock.patch("requests.post", side_effect=ConnectionError("giù")):
            with self.assertRaises(ai_giro.GenerazioneFallita) as ctx:
                ai_giro._chiedi_senza_cercare("openai", "ciao", "chiave")
        self.assertIn("non risponde", ctx.exception.motivo)

    def test_risposta_buona_torna_il_testo(self):
        with mock.patch("requests.post", return_value=_openai_testo("[]")):
            self.assertEqual(ai_giro._chiedi_senza_cercare("openai", "ciao", "k"), "[]")


class LaGenerazioneDiceIlMotivo(unittest.TestCase):
    """`genera_domande` solleva invece di tornare una lista vuota."""

    def _genera(self, testo):
        with mock.patch("requests.post", return_value=_openai_testo(testo)):
            return ai_giro.genera_domande("verticalai.it", "", "k", "openai", "Home")

    def _fallisce(self, testo):
        with self.assertRaises(ai_giro.GenerazioneFallita) as ctx:
            self._genera(testo)
        return ctx.exception.motivo

    def test_risposta_vuota(self):
        self.assertIn("senza testo", self._fallisce(""))

    def test_niente_json(self):
        self.assertIn("JSON", self._fallisce("Ecco alcune domande utili per te."))

    def test_json_rotto(self):
        self.assertIn("JSON non valido", self._fallisce('[{"domanda": "a",]'))

    def test_tutte_col_nome_del_sito(self):
        voci = json.dumps([{"domanda": "Cosa fa VerticalAI? Cita le fonti"}] * 3)
        self.assertIn("nome del sito", self._fallisce(voci))

    def test_dieci_domande_buone(self):
        self.assertEqual(len(self._genera(_DIECI)), 10)


class PreparaProgetto(unittest.TestCase):
    """`prepara_progetto`: il cron vede 0 solo per «ce le ha già»."""

    def setUp(self):
        self.creati = []
        p = [
            mock.patch.object(ai_giro, "_sb_ai_domande", return_value=[]),
            mock.patch.object(ai_giro, "com_e_fatto_il_sito", return_value="Home · Servizi"),
            mock.patch.object(ai_giro, "_sb_ai_argomento_crea", return_value="topic-1"),
            mock.patch.object(ai_giro, "_sb_ai_domanda_crea",
                              side_effect=lambda t, d, i: self.creati.append(d) or "id"),
        ]
        self.mock = {m.attribute: m.start() for m in p}
        for m in p:
            self.addCleanup(m.stop)

    def _con(self, proposte=None, errore=None):
        if errore:
            return mock.patch.object(ai_giro, "genera_domande", side_effect=errore)
        return mock.patch.object(ai_giro, "genera_domande", return_value=proposte)

    def _proposte(self, n):
        return [{"domanda": f"Domanda {i}", "argomento": "A", "intento": ""} for i in range(n)]

    def test_senza_audit_e_un_motivo_dedicato(self):
        self.mock["com_e_fatto_il_sito"].return_value = ""
        with self.assertRaises(ai_giro.SenzaAudit):
            ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"})

    def test_senza_chiavi(self):
        with self.assertRaises(ai_giro.GenerazioneFallita) as ctx:
            ai_giro.prepara_progetto("p", "x.it", "", {"perplexity": "k"})
        self.assertNotIsInstance(ctx.exception, ai_giro.SenzaAudit)

    def test_l_errore_del_provider_risale(self):
        with self._con(errore=ai_giro.GenerazioneFallita("credito esaurito sull'account OpenAI")):
            with self.assertRaises(ai_giro.GenerazioneFallita) as ctx:
                ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"})
        self.assertIn("credito", ctx.exception.motivo)

    def test_il_database_che_rifiuta_tutto_non_e_un_successo(self):
        self.mock["_sb_ai_domanda_crea"].side_effect = lambda *a: ""
        with self._con(self._proposte(10)):
            with self.assertRaises(ai_giro.GenerazioneFallita) as ctx:
                ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"})
        self.assertIn("database", ctx.exception.motivo)

    def test_crea_le_domande(self):
        with self._con(self._proposte(10)):
            self.assertEqual(ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"}), 10)

    def test_il_cron_non_tocca_un_progetto_che_ha_gia_domande(self):
        self.mock["_sb_ai_domande"].return_value = [{"prompt_text": "Domanda 0"}]
        with self._con(self._proposte(10)) as g:
            self.assertEqual(ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"}), 0)
        g.assert_not_called()

    def test_rigenera_aggiunge_scartando_i_doppioni(self):
        """§10.1: rigenera = aggiunge. Prima tornava 0 su qualunque progetto
        che avesse già una domanda, anche se il bottone prometteva di aggiungere."""
        self.mock["_sb_ai_domande"].return_value = [{"prompt_text": "domanda 0"},
                                                    {"prompt_text": "Domanda 1"}]
        with self._con(self._proposte(5)):
            n = ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"}, aggiungi=True)
        self.assertEqual(n, 3)
        self.assertNotIn("Domanda 0", self.creati)

    def test_rigenera_controlla_anche_le_disattivate(self):
        """Una domanda tolta dal monitoraggio non rientra alla rigenerazione."""
        with self._con(self._proposte(1)):
            ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"}, aggiungi=True)
        self.mock["_sb_ai_domande"].assert_called_with("p", solo_attive=False)

    def test_rigenera_senza_niente_di_nuovo_lo_dice(self):
        self.mock["_sb_ai_domande"].return_value = [{"prompt_text": "Domanda 0"}]
        with self._con(self._proposte(1)):
            with self.assertRaises(ai_giro.GenerazioneFallita) as ctx:
                ai_giro.prepara_progetto("p", "x.it", "", {"openai": "k"}, aggiungi=True)
        self.assertIn("già presenti", ctx.exception.motivo)


class LEndpointNonRispondeOkConZero(unittest.TestCase):
    """POST /admin/progetti/{id}/ai/prompt/rigenera"""

    def _chiama(self, prepara):
        progetto = {"id": "p", "domain": "verticalai.it", "sector": ""}

        async def azione(request, project_id):
            return {"email": "admin@test.invalid"}, progetto, {}, None

        with mock.patch.object(server, "_admin_ai_azione", side_effect=azione), \
             mock.patch.object(server, "_admin_traccia"), \
             mock.patch.object(ai_giro, "chiavi_configurate",
                               return_value={"chiavi": {"openai": "k"}}), \
             mock.patch.object(ai_giro, "prepara_progetto", side_effect=prepara):
            r = asyncio.run(server.admin_progetto_ai_prompt_rigenera(None, "p"))
        return r.status_code, json.loads(r.body)

    def test_credito_esaurito_e_un_errore_con_motivo(self):
        def prepara(*a, **k):
            raise ai_giro.GenerazioneFallita("credito esaurito sull'account OpenAI: va ricaricato")
        stato, corpo = self._chiama(prepara)
        self.assertGreaterEqual(stato, 400)
        self.assertEqual(corpo["esito"], "errore")
        self.assertIn("credito esaurito", corpo["motivo"])

    def test_senza_audit_e_409(self):
        def prepara(*a, **k):
            raise ai_giro.SenzaAudit("il progetto non ha ancora un audit completato")
        stato, corpo = self._chiama(prepara)
        self.assertEqual(stato, 409)
        self.assertEqual(corpo["esito"], "errore")

    def test_zero_non_e_mai_ok(self):
        stato, corpo = self._chiama(lambda *a, **k: 0)
        self.assertNotEqual(corpo["esito"], "ok")
        self.assertGreaterEqual(stato, 400)

    def test_successo(self):
        stato, corpo = self._chiama(lambda *a, **k: 10)
        self.assertEqual((stato, corpo), (200, {"esito": "ok", "generate": 10}))

    def test_il_bottone_aggiunge(self):
        visti = {}

        def prepara(*a, **k):
            visti.update(k)
            return 3
        self._chiama(prepara)
        self.assertIs(visti.get("aggiungi"), True)


class LaNotaDelModello(unittest.TestCase):
    """Configurazione AI: l'avviso «senza ricerca web» solo quando è vero."""

    def _pagina(self, modello, cerca):
        import ai_schermate
        lista = [{"model_id": modello, "supports_web_search": cerca, "fetched_at": "2026-09-22"}]
        return ai_schermate.admin_configurazione_ai(
            {"openai": {"default_model": modello}}, {"openai": lista},
            True, {"openai": "sk-…a83f"})

    def _nota_nascosta(self, html):
        i = html.index('data-nota-web="openai"')
        return " hidden" in html[i:html.index(">", i)]

    def test_modello_con_ricerca_web_nessun_avviso(self):
        self.assertTrue(self._nota_nascosta(self._pagina("gpt-4o-mini", True)))

    def test_modello_senza_ricerca_web_avviso_giallo(self):
        html = self._pagina("gpt-3.5-turbo", False)
        self.assertFalse(self._nota_nascosta(html))
        self.assertIn('class="ai-nota warn"', html)

    def test_mai_piu_spunta_verde_su_un_avviso(self):
        self.assertNotIn('ai-nota ok">✓ Un modello senza ricerca web',
                         self._pagina("gpt-4o-mini", True))


if __name__ == "__main__":
    unittest.main()
