# -*- coding: utf-8 -*-
"""La favicon (task «GEO Minor: Manca la Favicon»).

⚠️ Il vero rischio non e' che manchi oggi: e' che il prodotto ha quindici
`<head>` diversi e nessuno condiviso, quindi la pagina che qualcuno aggiungera'
il mese prossimo nascera' senza icona e nessuno lo notera'. Questi test sono
quella guardia: una pagina nuova senza i link fa rosso.
"""
import os
import struct
import unittest

from tests import conftest_env  # noqa: F401

import geo_audit
import server

QUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(QUI, "static")
TEMPLATES = os.path.join(QUI, "templates")


class IFileEsistono(unittest.TestCase):

    def test_ci_sono_tutti_e_tre(self):
        for nome in ("favicon.svg", "favicon.ico", "favicon-180.png"):
            self.assertTrue(os.path.exists(os.path.join(STATIC, nome)), nome)

    def test_l_ico_e_un_ico_vero(self):
        """⚠️ Un .png rinominato .ico viene servito e poi ignorato in silenzio
        da chi chiede /favicon.ico: si vedrebbe la pagina senza icona senza un
        solo errore da nessuna parte."""
        with open(os.path.join(STATIC, "favicon.ico"), "rb") as f:
            testa = f.read(6)
        riserva, tipo, quante = struct.unpack("<HHH", testa)
        self.assertEqual((riserva, tipo), (0, 1))     # 1 = icona
        self.assertGreaterEqual(quante, 1)

    def test_il_png_e_un_png_vero(self):
        with open(os.path.join(STATIC, "favicon-180.png"), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_lo_svg_non_e_vuoto_e_disegna_qualcosa(self):
        with open(os.path.join(STATIC, "favicon.svg"), encoding="utf-8") as f:
            svg = f.read()
        self.assertIn("<svg", svg)
        self.assertIn("path", svg)

    def test_si_rigenerano_con_uno_script_nel_repo(self):
        """Un binario che nessuno sa piu' come rifare e' un vincolo: se il
        marchio cambia, lo script lo rifa'."""
        self.assertTrue(os.path.exists(os.path.join(QUI, "qa", "genera_favicon.py")))


class OgniPaginaLaPorta(unittest.TestCase):

    # ⚠️ L'unica esclusione, e col suo motivo: `_EMAIL_HEAD` e' l'intestazione
    # delle email. Un'icona del sito non c'entra, e alcuni client la
    # scaricherebbero facendo un viaggio in piu' per niente.
    def test_tutti_i_template_hanno_i_link(self):
        mancano = []
        for nome in sorted(os.listdir(TEMPLATES)):
            if not nome.endswith(".html"):
                continue
            with open(os.path.join(TEMPLATES, nome), encoding="utf-8") as f:
                if "/static/favicon.svg" not in f.read():
                    mancano.append(nome)
        self.assertEqual(mancano, [], "pagine senza favicon: %s" % mancano)

    def test_nessun_template_punta_piu_al_wordpress_vetrina(self):
        """⚠️ C'era un link all'SVG su verticalai.it: l'icona del prodotto non
        deve dipendere dall'uptime del sito vetrina, ne' far sapere a quel
        server chi apre il pannello."""
        for nome in sorted(os.listdir(TEMPLATES)):
            if not nome.endswith(".html"):
                continue
            with open(os.path.join(TEMPLATES, nome), encoding="utf-8") as f:
                testo = f.read()
            self.assertNotIn('rel="icon" href="https://verticalai.it', testo, nome)

    def test_le_intestazioni_scritte_nel_codice_usano_la_costante(self):
        import inspect
        self.assertIn("FAVICON_HEAD", inspect.getsource(server._page))
        with open(os.path.join(QUI, "server.py"), encoding="utf-8") as f:
            self.assertIn("geo_audit.FAVICON_HEAD\n    + _DS_LINK", f.read())

    def test_il_report_del_cliente_ce_l_ha(self):
        """Il report e' la pagina che il cliente apre e tiene aperta: e' la
        scheda su cui l'icona serve piu' che altrove."""
        import inspect
        self.assertIn("+ FAVICON_HEAD +", inspect.getsource(geo_audit))

    def test_la_costante_sta_in_un_posto_solo(self):
        """Tre copie dello stesso blocco divergono al primo cambio."""
        self.assertTrue(hasattr(geo_audit, "FAVICON_HEAD"))
        for pezzo in ("favicon.svg", "favicon.ico", "favicon-180.png"):
            self.assertIn(pezzo, geo_audit.FAVICON_HEAD, pezzo)


class LaRottaAllaRadice(unittest.TestCase):
    """⚠️ I <link> nelle pagine non bastano: /favicon.ico viene chiesto alla
    radice senza leggere l'HTML."""

    def test_la_rotta_esiste(self):
        percorsi = [r.path for r in server.app.routes if hasattr(r, "path")]
        self.assertIn("/favicon.ico", percorsi)

    def test_risponde_con_il_file(self):
        r = server.favicon_ico()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.media_type, "image/x-icon")
        self.assertGreater(len(r.body), 100)


if __name__ == "__main__":
    unittest.main()
