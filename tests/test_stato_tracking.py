# -*- coding: utf-8 -*-
"""La label «Tracking attivo» in homepage (bug segnalato da Silvio il 06/10).

Difetto misurato sui dati veri, non ipotizzato: 31 progetti su 41 mostravano
«Tracking attivo», e solo 6 avevano mandato un evento nell'ultima settimana.
Venti avevano l'ultimo evento piu' vecchio di un mese, tredici dei quali lo
stesso giorno — un colpo solo e mai piu'. La label non guardava il tempo.
"""
import inspect
import unittest
from datetime import datetime, timedelta, timezone

from tests import conftest_env  # noqa: F401

import db
import server


def _iso(giorni_fa):
    return (datetime.now(timezone.utc) - timedelta(days=giorni_fa)).isoformat()


class StatoDelTracking(unittest.TestCase):

    def test_un_evento_di_oggi_e_attivo(self):
        self.assertEqual(server._stato_tracking(_iso(0))["stato"], "attivo")

    def test_nessun_evento_e_assente(self):
        d = server._stato_tracking(None)
        self.assertEqual(d["stato"], "assente")
        self.assertEqual(d["label"], "Tracking non installato")

    def test_un_evento_di_un_mese_fa_non_e_attivo(self):
        """⚠️ Il caso del bug: prima questo era «Tracking attivo»."""
        d = server._stato_tracking(_iso(36))
        self.assertEqual(d["stato"], "fermo")
        self.assertNotEqual(d["label"], "Tracking attivo")

    def test_il_fermo_dice_da_quanto(self):
        """Senza il numero, «fermo» non fa agire: con 36 giorni si capisce che
        lo snippet e' stato rimosso o il sito non ha piu' visite."""
        self.assertIn("36", server._stato_tracking(_iso(36))["label"])

    def test_dentro_la_finestra_resta_attivo(self):
        """⚠️ Il rovescio del bug, altrettanto sbagliato: un sito di cliente
        piccolo che non ha visite da tre giorni non e' rotto, e marcarlo «non
        attivo» farebbe inseguire un guasto che non c'e'."""
        for g in (1, 3, server._GIORNI_TRACKING_VIVO):
            self.assertEqual(server._stato_tracking(_iso(g))["stato"], "attivo", g)

    def test_appena_oltre_la_finestra_e_fermo(self):
        self.assertEqual(
            server._stato_tracking(_iso(server._GIORNI_TRACKING_VIVO + 1))["stato"], "fermo")

    def test_una_data_illeggibile_non_diventa_attiva(self):
        """⚠️ Il default non e' «attivo»: non si promuove a funzionante cio'
        che non si e' riusciti a datare."""
        for sporca in ("", "ieri", "2026-13-45", "null"):
            self.assertNotEqual(server._stato_tracking(sporca)["stato"], "attivo", sporca)

    def test_una_data_senza_fuso_non_fa_esplodere_il_conto(self):
        """Postgres puo' restituire un timestamp senza fuso: sottrarre un
        datetime naive da uno aware alza TypeError e la dashboard andrebbe in
        500 invece di mostrare un badge."""
        naive = (datetime.now(timezone.utc) - timedelta(days=2)).replace(tzinfo=None).isoformat()
        self.assertEqual(server._stato_tracking(naive)["stato"], "attivo")


class LaDashboardUsaLaData(unittest.TestCase):

    def test_legge_l_ultimo_evento_non_l_insieme(self):
        """⚠️ `_sb_projects_with_tracking` risponde «l'ha installato una
        volta», che e' la domanda del promemoria, non quella della label."""
        sorgente = inspect.getsource(server.dashboard)
        self.assertIn("_sb_projects_tracking_ultimo", sorgente)
        self.assertNotIn("_sb_projects_with_tracking", sorgente)

    def test_il_kpi_conta_solo_i_vivi(self):
        sorgente = inspect.getsource(server.dashboard)
        self.assertIn('tr["stato"] == "attivo"', sorgente)

    def test_porta_anche_il_conto_dei_fermi(self):
        self.assertIn("tracking_fermo", inspect.getsource(server.dashboard))


class IlPannelloAdminRestaSullaDomandaSua(unittest.TestCase):
    """⚠️ Il pannello chiede «l'ha installato?» per decidere a chi mandare il
    promemoria «installa il tracking». Chi l'ha installato e poi si e' fermato
    NON va sollecitato a installarlo: quella schermata era corretta, e un fix
    fatto cambiando la semantica sotto i piedi l'avrebbe rotta."""

    def test_la_funzione_per_il_promemoria_esiste_ancora(self):
        self.assertTrue(callable(db._sb_projects_with_tracking))

    def test_ed_e_derivata_dalla_stessa_lettura(self):
        """Due query separate per lo stesso fatto divergono al primo cambio."""
        sorgente = inspect.getsource(db._sb_projects_with_tracking)
        self.assertIn("_sb_projects_tracking_ultimo", sorgente)

    def test_la_schermata_tracking_non_e_stata_toccata(self):
        sorgente = inspect.getsource(server.admin_tracking)
        self.assertIn("_sb_projects_with_tracking", sorgente)


class IlBadgeHaTreStati(unittest.TestCase):

    def test_il_template_distingue_fermo_da_assente(self):
        with open("templates/dashboard.html", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("trackingBadge", html)
        for stato in ("attivo", "fermo", "assente"):
            self.assertIn(stato, html, stato)

    def test_non_resta_il_booleano_di_prima_nel_badge(self):
        """⚠️ Il vecchio ternario su `tracking_active` scriveva «Tracking
        attivo» a chiunque avesse un evento: se torna, torna il bug."""
        with open("templates/dashboard.html", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("? '<span class=\"badge good\">Tracking attivo</span>'", html)


if __name__ == "__main__":
    unittest.main()
