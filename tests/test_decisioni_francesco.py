# -*- coding: utf-8 -*-
"""Le decisioni di Francesco del 24/09/2026, una per test.

Ogni test qui fissa una scelta che qualcuno ha preso: se cade, non è un
dettaglio tecnico che si è rotto, è una decisione che è stata cambiata senza
dirlo.
"""
import re
import unittest

from tests import conftest_env  # noqa: F401

import ai_giro
import server


class SoglieDeiConcorrenti(unittest.TestCase):
    """2.2 · solo i primi 5, e serve comparire almeno 5 volte."""

    def test_servono_cinque_apparizioni(self):
        self.assertEqual(ai_giro._SOGLIA_RISPOSTE, 5)

    def test_al_massimo_cinque_concorrenti(self):
        self.assertEqual(ai_giro._MAX_PROPOSTI, 5)

    def test_il_tetto_non_e_piu_alto_della_soglia_di_ingresso(self):
        """⚠️ Non è una tautologia: se il tetto tornasse a 12 lasciando la
        soglia a 5, l'elenco si riempirebbe di nomi deboli senza che nessuna
        delle due costanti sembri sbagliata da sola."""
        self.assertLessEqual(ai_giro._MAX_PROPOSTI, 5)


class AvvisoTraffico(unittest.TestCase):
    """1.4 · acceso per tutti, e in copia a Vertical AI."""

    def test_acceso_di_default(self):
        from db import _REPORT_PREF_DEFAULT
        self.assertIs(_REPORT_PREF_DEFAULT["alert_traffico_ai"], True)

    def test_vertical_ai_e_un_destinatario_separato_non_un_cc(self):
        """⚠️ Il guscio dell'email porta in fondo il «disiscriviti» legato al
        progetto: in Cc, un clic distratto di chi sta in copia spegnerebbe gli
        avvisi al cliente."""
        import inspect
        self.assertEqual(server.EMAIL_VERTICALAI, "info@verticalai.it")
        sorgente = inspect.getsource(server._send_avviso_traffico)
        self.assertNotIn('"cc"', sorgente)
        self.assertIn("destinatari", sorgente)


class RiepilogoApprovazioni(unittest.TestCase):
    """1.1 · le domande non si approvano da sole, quindi qualcuno va avvisato."""

    RIGHE = [{"project_id": "11111111-1111-1111-1111-111111111111",
              "dominio": "esempio.it", "quante": 10,
              "piu_vecchia": "2026-09-01T10:00:00+00:00"},
             {"project_id": "22222222-2222-2222-2222-222222222222",
              "dominio": "altro.it", "quante": 3,
              "piu_vecchia": "2026-09-20T10:00:00+00:00"}]

    def setUp(self):
        self.catturato = {}
        self._vero_post = server._resend_post
        self._key, self._from = server.RESEND_KEY, server.FROM_EMAIL
        server._resend_post = lambda to, s, h: self.catturato.update(to=to, s=s, h=h)
        server.RESEND_KEY, server.FROM_EMAIL = "finta", "x@y.it"

    def tearDown(self):
        server._resend_post = self._vero_post
        server.RESEND_KEY, server.FROM_EMAIL = self._key, self._from

    def test_va_ai_due_indirizzi_chiesti(self):
        server._send_riepilogo_approvazioni(self.RIGHE)
        self.assertEqual(self.catturato["to"],
                         ["fdangelo8@gmail.com", "info@verticalai.it"])

    def test_l_oggetto_porta_il_totale(self):
        server._send_riepilogo_approvazioni(self.RIGHE)
        self.assertIn("13", self.catturato["s"])

    def test_un_link_per_progetto_alla_pagina_delle_domande(self):
        server._send_riepilogo_approvazioni(self.RIGHE)
        link = re.findall(r"/admin/progetti/([0-9a-f-]+)/ai", self.catturato["h"])
        self.assertEqual(len(link), 2)
        self.assertIn("11111111-1111-1111-1111-111111111111", link)

    def test_dice_da_quanto_aspettano(self):
        """⚠️ È il dato che fa agire: «dieci domande» non dice niente, «dieci
        da ventitré giorni» sì."""
        server._send_riepilogo_approvazioni(self.RIGHE)
        self.assertIn("in attesa da", self.catturato["h"])

    def test_se_non_c_e_niente_da_approvare_non_manda(self):
        """⚠️ Un riepilogo che arriva anche per dire «zero» diventa rumore, e
        dopo un mese non lo apre più nessuno: allora tanto valeva non averlo."""
        self.assertIs(server._send_riepilogo_approvazioni([]), False)
        self.assertEqual(self.catturato, {})

    def test_separa_i_singolari_dai_plurali(self):
        una = [{**self.RIGHE[0], "quante": 1}]
        server._send_riepilogo_approvazioni(una)
        self.assertIn("1 progetto", self.catturato["h"])
        self.assertNotIn("1 progetti", self.catturato["h"])


class GuardiaAntiDoppione(unittest.TestCase):
    """⚠️ Difetto trovato collaudando, non in teoria: il riepilogo non è legato
    a un progetto, e `report_log` vuole un uuid. Passandogli stringa vuota la
    guardia rispondeva `400 invalid input syntax for type uuid`, quindi non
    funzionava mai e l'email poteva ripartire a ogni invocazione."""

    def test_esistono_le_funzioni_senza_progetto(self):
        import db
        self.assertTrue(callable(db._sb_log_globale_ultimo))
        self.assertTrue(callable(db._sb_log_globale_scrivi))

    def test_il_cron_usa_la_guardia_globale_non_quella_per_progetto(self):
        import inspect
        sorgente = inspect.getsource(server.api_cron_approvazioni)
        self.assertIn("_sb_log_globale_ultimo", sorgente)
        self.assertNotIn('_sb_report_log_ultimo("",', sorgente)

    def test_scrive_sul_registro_con_progetto_nullo(self):
        import inspect
        sorgente = inspect.getsource(__import__("db")._sb_log_globale_scrivi)
        self.assertIn('"project_id": None', sorgente)


class ConfermaAnalisiPartita(unittest.TestCase):
    """3.1 · chi compila il form pubblico non riceveva niente."""

    def setUp(self):
        self.catturato = {}
        self._vero_post = server._resend_post
        self._key, self._from = server.RESEND_KEY, server.FROM_EMAIL
        server._resend_post = lambda to, s, h: self.catturato.update(to=to, s=s, h=h)
        server.RESEND_KEY, server.FROM_EMAIL = "finta", "x@y.it"

    def tearDown(self):
        server._resend_post = self._vero_post
        server.RESEND_KEY, server.FROM_EMAIL = self._key, self._from

    def test_va_a_chi_ha_compilato(self):
        server._send_conferma_analisi("mario@esempio.it", "fiori.it")
        self.assertEqual(self.catturato["to"], ["mario@esempio.it"])

    def test_l_oggetto_e_quello_scritto_da_francesco(self):
        server._send_conferma_analisi("mario@esempio.it", "fiori.it")
        self.assertEqual(self.catturato["s"],
                         "Abbiamo ricevuto la tua richiesta: l'analisi di fiori.it è partita")

    def test_nomina_i_tre_assistenti_e_dice_di_guardare_lo_spam(self):
        server._send_conferma_analisi("mario@esempio.it", "fiori.it")
        h = self.catturato["h"]
        for atteso in ("ChatGPT", "Gemini", "Perplexity", "spam"):
            self.assertIn(atteso, h, atteso)

    def test_non_promette_tempi(self):
        """⚠️ Il testo dice «a breve», non «entro N minuti»: l'audit gira in
        coda e un sito lento lo fa slittare. Una promessa oraria che non si
        rispetta fa più danno del silenzio."""
        server._send_conferma_analisi("mario@esempio.it", "fiori.it")
        h = self.catturato["h"].lower()
        for promessa in ("minuti", "entro un'ora", "24 ore", "immediat"):
            self.assertNotIn(promessa, h, promessa)

    def test_parte_dal_form_pubblico(self):
        import inspect
        sorgente = inspect.getsource(server.richiedi_accesso)
        self.assertIn("_send_conferma_analisi", sorgente)

    def test_parte_in_coda_e_non_prima_della_risposta(self):
        """⚠️ Se Resend è lento o giù, la richiesta resta comunque registrata e
        l'audit parte lo stesso: la conferma non deve poter far aspettare chi ha
        appena compilato, né far fallire la pagina."""
        import inspect
        sorgente = inspect.getsource(server.richiedi_accesso)
        self.assertIn("background.add_task(_send_conferma_analisi", sorgente)


if __name__ == "__main__":
    unittest.main()
