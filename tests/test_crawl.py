# -*- coding: utf-8 -*-
"""Le funzioni che decidono cosa finisce nell'audit e cosa no.

`parse_robots_ai` regge il check piu' pesante del catalogo (`crawl.ai`,
peso 12); `is_page_url` e `norm` decidono la qualita' del crawl, cioe' su
quali pagine si calcola il punteggio.
"""
import unittest

import geo_audit as g


class RobotsEBotAI(unittest.TestCase):

    def test_nessun_blocco(self):
        self.assertEqual(g.parse_robots_ai("User-agent: *\nDisallow: /wp-admin/"), [])

    def test_un_bot_bloccato(self):
        robots = "User-agent: GPTBot\nDisallow: /"
        self.assertEqual(g.parse_robots_ai(robots), ["GPTBot"])

    def test_maiuscole_indifferenti(self):
        """robots.txt non distingue maiuscole nel nome dell'agente."""
        self.assertEqual(g.parse_robots_ai("user-agent: gptbot\ndisallow: /"), ["GPTBot"])

    def test_disallow_parziale_non_e_un_blocco(self):
        """⚠️ Il check dice «questo sito BLOCCA i crawler AI». Vietare una
        cartella non e' bloccare il sito: contarlo come blocco sarebbe un
        falso allarme su un check da 12 punti con severita' critica."""
        robots = "User-agent: GPTBot\nDisallow: /privato/"
        self.assertEqual(g.parse_robots_ai(robots), [])

    def test_lo_star_non_conta(self):
        """⚠️ `Disallow: /` sotto `User-agent: *` blocca tutti, compresi i
        bot AI. Oggi il check NON lo rileva: guarda solo i nomi espliciti.
        Il test fissa il comportamento attuale perche' e' una scelta da
        rivedere consapevolmente (blocco 2.1, `crawl.conflict`), non un
        dettaglio da cambiare per distrazione."""
        self.assertEqual(g.parse_robots_ai("User-agent: *\nDisallow: /"), [])

    def test_piu_bot_nello_stesso_file(self):
        robots = ("User-agent: GPTBot\nDisallow: /\n\n"
                  "User-agent: CCBot\nDisallow: /\n\n"
                  "User-agent: Googlebot\nDisallow: /")
        bloccati = g.parse_robots_ai(robots)
        self.assertIn("GPTBot", bloccati)
        self.assertIn("CCBot", bloccati)
        # Googlebot non e' un crawler AI: non deve finire in questo elenco
        self.assertNotIn("Googlebot", bloccati)

    def test_robots_vuoto_o_spazzatura(self):
        for corpo in ("", "   ", "<!DOCTYPE html><html>404</html>"):
            self.assertEqual(g.parse_robots_ai(corpo), [], repr(corpo))


class QualiPagineSiAnalizzano(unittest.TestCase):

    def test_le_pagine_normali_passano(self):
        for u in ("https://x.it/", "https://x.it/chi-siamo",
                  "https://x.it/blog/articolo-lungo"):
            self.assertTrue(g.is_page_url(u), u)

    def test_le_immagini_no(self):
        for u in ("https://x.it/foto.jpg", "https://x.it/logo.SVG",
                  "https://x.it/a/b/c.webp"):
            self.assertFalse(g.is_page_url(u), u)

    def test_le_cartelle_di_wordpress_no(self):
        for u in ("https://x.it/wp-content/uploads/a.pdf",
                  "https://x.it/wp-json/wp/v2/posts",
                  "https://x.it/feed"):
            self.assertFalse(g.is_page_url(u), u)

    def test_il_carrello_no(self):
        self.assertFalse(g.is_page_url("https://x.it/negozio?add-to-cart=12"))


class NormalizzazioneDegliIndirizzi(unittest.TestCase):

    def test_il_frammento_sparisce(self):
        self.assertEqual(g.norm("https://x.it/pagina#sezione"), "https://x.it/pagina")

    def test_la_barra_finale_sparisce_ma_la_home_resta(self):
        self.assertEqual(g.norm("https://x.it/pagina/"), "https://x.it/pagina")
        self.assertEqual(g.norm("https://x.it/"), "https://x.it/")

    def test_la_query_resta(self):
        """⚠️ La query NON si butta: su molti siti distingue due pagine
        diverse. Toglierla farebbe collassare pagine distinte in una sola,
        e il conteggio delle pagine analizzate sarebbe falso."""
        self.assertEqual(g.norm("https://x.it/p?id=2"), "https://x.it/p?id=2")

    def test_due_forme_della_stessa_pagina_coincidono(self):
        """E' il motivo per cui la funzione esiste: senza, la home verrebbe
        analizzata due volte e peserebbe il doppio nel punteggio."""
        self.assertEqual(g.norm("https://x.it/chi-siamo/#top"),
                         g.norm("https://x.it/chi-siamo"))


if __name__ == "__main__":
    unittest.main()
