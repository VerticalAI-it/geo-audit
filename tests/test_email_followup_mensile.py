# -*- coding: utf-8 -*-
"""Le due email decise il 24/09: proposta dopo il report (3.2) e rapporto
mensile al cliente (3.3)."""
import unittest

from tests import conftest_env  # noqa: F401

import server


def _catturatore(caso):
    caso.catturato = {}
    caso._vero_post = server._resend_post
    caso._key, caso._from = server.RESEND_KEY, server.FROM_EMAIL
    server._resend_post = lambda to, s, h: caso.catturato.update(to=to, s=s, h=h)
    server.RESEND_KEY, server.FROM_EMAIL = "finta", "geo@verticalai.it"


def _ripristina(caso):
    server._resend_post = caso._vero_post
    server.RESEND_KEY, server.FROM_EMAIL = caso._key, caso._from


class FollowupDopoIlReport(unittest.TestCase):
    """3.2 · tre giorni dopo il report, la proposta di approfondimento."""

    def setUp(self):
        _catturatore(self)

    def tearDown(self):
        _ripristina(self)

    def test_l_oggetto_e_quello_scritto_da_francesco(self):
        server._send_followup_analisi("a@b.it", "fiori.it", 62, "")
        self.assertEqual(self.catturato["s"],
                         "fiori.it: il report ti dice dove sei, non da dove partire")

    def test_senza_dato_di_monitoraggio_la_sezione_si_omette(self):
        """⚠️ Decisione esplicita di Francesco: «quando non c'è ometti quella
        sezione». Non un ripiego su un altro dato — omettere."""
        server._send_followup_analisi("a@b.it", "fiori.it", 62, "")
        self.assertNotIn("Il dato che ci ha colpito", self.catturato["h"])

    def test_col_dato_la_sezione_compare(self):
        server._send_followup_analisi("a@b.it", "fiori.it", 62,
                                      "il sito viene citato in 6 delle 10 domande")
        h = self.catturato["h"]
        self.assertIn("Il dato che ci ha colpito di più", h)
        self.assertIn("6 delle 10 domande", h)

    def test_niente_link_al_calendario(self):
        """⚠️ Per sua indicazione: si risponde all'email e basta."""
        server._send_followup_analisi("a@b.it", "fiori.it", 62, "")
        h = self.catturato["h"].lower()
        for parola in ("calendly", "cal.com", "calendario", "prenota", "scegli un orario"):
            self.assertNotIn(parola, h, parola)
        # ⚠️ Spazi normalizzati: l'HTML manda a capo dentro la frase, e un
        # confronto letterale fallirebbe su un testo corretto.
        import re
        piano = re.sub(r"\s+", " ", self.catturato["h"])
        self.assertIn("rispondi a questa email", piano)

    def test_firmata_marco(self):
        server._send_followup_analisi("a@b.it", "fiori.it", 62, "")
        self.assertIn("Marco", self.catturato["h"])

    def test_senza_punteggio_non_scrive_un_numero_finto(self):
        server._send_followup_analisi("a@b.it", "fiori.it", None, "")
        self.assertNotIn("/100", self.catturato["h"])

    def test_la_finestra_e_di_un_giorno_non_un_da_qui_in_poi(self):
        """⚠️ Senza il limite superiore, il primo giro del cron scriverebbe a
        tutto lo storico in una volta: quattordici persone che non sentono
        parlare di noi da mesi riceverebbero una proposta commerciale lo stesso
        giorno."""
        import inspect

        import db
        sorgente = inspect.getsource(db._sb_report_da_seguire)
        self.assertIn("created_at.lt.", sorgente)
        self.assertIn("gte.", sorgente)

    def test_mai_due_volte_allo_stesso_indirizzo(self):
        import inspect
        sorgente = inspect.getsource(server.api_cron_followup)
        self.assertIn("_sb_followup_gia_mandati", sorgente)
        self.assertIn("gia_scritti.add", sorgente)

    def test_la_popolazione_e_chi_ha_ricevuto_il_report_non_i_lead(self):
        """⚠️ Ai lead del form pubblico nessun report è mai stato spedito:
        scrivere «qualche giorno fa ti abbiamo inviato il report» sarebbe
        falso."""
        import inspect

        import db
        sorgente = inspect.getsource(db._sb_report_da_seguire)
        self.assertIn("pending_email", sorgente)
        self.assertNotIn("contact_requests", sorgente)


class RapportoMensile(unittest.TestCase):
    """3.3 · il rapporto che giustifica il rinnovo."""

    PROGETTO = {"id": "33333333-3333-3333-3333-333333333333", "domain": "fiori.it"}
    PIENO = {"punteggio": 80, "delta": -3, "aperte": 126,
             "per_sev": {"critical": 2, "high": 4, "medium": 20},
             "risolte_voci": [{"titolo": "Alt text immagini", "pagine": 4}],
             "priorita": [{"check_id": "meta.description", "titolo": "Meta description",
                           "severita": "high", "pagine": 6},
                          {"check_id": "trust.contact", "titolo": "Contatti presenti",
                           "severita": "medium", "pagine": 12}]}

    def setUp(self):
        _catturatore(self)
        self._vera_riga = server._riga_monitoraggio
        server._riga_monitoraggio = lambda pid: ""

    def tearDown(self):
        _ripristina(self)
        server._riga_monitoraggio = self._vera_riga

    def test_l_oggetto_porta_dominio_punteggio_e_variazione(self):
        server._send_report_mensile_cliente("a@b.it", self.PROGETTO, self.PIENO)
        s = self.catturato["s"]
        self.assertIn("fiori.it", s)
        self.assertIn("80", s)
        self.assertIn("-3", s)

    def test_le_due_priorita_ci_sono_e_dicono_perche(self):
        server._send_report_mensile_cliente("a@b.it", self.PROGETTO, self.PIENO)
        h = self.catturato["h"]
        self.assertIn("Le 2 cose da fare adesso", h)
        self.assertIn("Meta description", h)
        self.assertIn("tocca 6 pagine", h)

    def test_senza_punteggio_non_manda_niente(self):
        """L'oggetto stesso dell'email contiene il punteggio: senza, non c'è un
        rapporto da mandare."""
        esito = server._send_report_mensile_cliente("a@b.it", self.PROGETTO,
                                                   {"punteggio": None})
        self.assertIs(esito, False)
        self.assertEqual(self.catturato, {})

    def test_le_sezioni_senza_dati_si_omettono(self):
        """⚠️ Niente «nessun intervento» scritto per riempire: una riga assente
        e una che dice zero si distinguono, e il cliente lo nota al secondo
        mese."""
        server._send_report_mensile_cliente(
            "a@b.it", self.PROGETTO,
            {"punteggio": 70, "delta": None, "aperte": 0,
             "risolte_voci": [], "priorita": []})
        h = self.catturato["h"]
        self.assertNotIn("Cosa è stato sistemato", h)
        self.assertNotIn("Le 2 cose da fare adesso", h)
        self.assertNotIn("Cosa resta aperto", h)

    def test_il_primo_mese_lo_dice_invece_di_inventare_una_variazione(self):
        server._send_report_mensile_cliente("a@b.it", self.PROGETTO,
                                            {"punteggio": 70, "delta": None, "aperte": 0})
        self.assertIn("primo mese di misura", self.catturato["h"])

    def test_la_riga_di_monitoraggio_compare_solo_se_c_e(self):
        server._send_report_mensile_cliente("a@b.it", self.PROGETTO, self.PIENO)
        self.assertNotIn("domande che monitoriamo", self.catturato["h"])
        server._riga_monitoraggio = lambda pid: "il sito viene citato in 6 delle 10 domande"
        server._send_report_mensile_cliente("a@b.it", self.PROGETTO, self.PIENO)
        self.assertIn("6 delle 10 domande", self.catturato["h"])

    def test_firmata_marco(self):
        server._send_report_mensile_cliente("a@b.it", self.PROGETTO, self.PIENO)
        self.assertIn("Marco", self.catturato["h"])

    def test_e_agganciata_al_digest_mensile_del_cliente(self):
        import inspect
        sorgente = inspect.getsource(server._manda_digest)
        self.assertIn("_send_report_mensile_cliente", sorgente)
        # il riepilogo interno al team resta quello di prima
        self.assertIn("_send_digest", sorgente)


class SistematoENonAncoraFatto(unittest.TestCase):
    """⚠️ Difetto visto sul rapporto vero di amahorse: «Contatti presenti»
    compariva sia fra le cose sistemate sia fra quelle da fare. Vero due volte
    — risolto su una pagina, aperto su ventisei — ma in un'email si legge come
    una contraddizione."""

    def test_un_check_ancora_aperto_non_entra_fra_i_risolti(self):
        import inspect

        import views
        self.assertIn("ancora_aperti", inspect.getsource(views._riepilogo_periodo))


if __name__ == "__main__":
    unittest.main()
