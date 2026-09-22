# -*- coding: utf-8 -*-
"""Blocco 5 · presenza off-site, solo per quanto si verifica gratis."""
import unittest

from tests import conftest_env  # noqa: F401

import geo_audit as g
import presenza_offsite as po


class FormeDelDominio(unittest.TestCase):

    def test_copre_www_barra_e_http(self):
        """⚠️ Wikidata conserva l'URL come l'ha scritto chi ha compilato la
        voce: cercare una sola forma vuol dire non trovare entità che ci sono."""
        f = po._forme("Esempio.it")
        for atteso in ("https://esempio.it", "https://www.esempio.it/",
                       "http://esempio.it", "http://www.esempio.it/"):
            self.assertIn(atteso, f)

    def test_normalizza_url_interi(self):
        self.assertEqual(po._forme("https://www.esempio.it/pagina"),
                         po._forme("esempio.it"))

    def test_un_dominio_senza_punto_non_produce_query(self):
        self.assertEqual(po._forme("localhost"), [])
        self.assertEqual(po._forme(""), [])

    def test_dominio_non_interpretabile_non_e_una_risposta(self):
        """⚠️ «Non l'ho chiesto» non è «non c'è»: senza questa distinzione il
        check direbbe «nessuna entità» senza aver interrogato nulla."""
        r = po.guarda("localhost")
        self.assertFalse(r["raggiunto"])
        self.assertIsNone(r["entita"])


def _sito():
    s = type("S", (), {})()
    s.site_checks = []
    s.sameas_urls = []
    return s


def _stato(checks, cid):
    return next(c.status for c in checks if c.id == cid)


class CheckOffSite(unittest.TestCase):

    def test_esistono_sempre_nel_catalogo(self):
        """⚠️ Un check che compare solo quando è stato eseguito cambia il
        denominatore del punteggio, e due audit smettono di confrontarsi."""
        s = _sito()
        g.checks_offsite(s, None)
        self.assertEqual({c.id for c in s.site_checks},
                         {"entity.wikidata", "entity.sameas.fonti"})

    def test_senza_verifica_sono_unknown(self):
        s = _sito()
        g.checks_offsite(s, None)
        self.assertEqual(_stato(s.site_checks, "entity.wikidata"), g.UNK)
        self.assertEqual(_stato(s.site_checks, "entity.sameas.fonti"), g.UNK)

    def test_non_essere_su_wikidata_non_toglie_punti(self):
        """⚠️ Il cuore della scelta: un'officina non può avere una voce, le
        regole di rilevanza lo vietano. Farla fallire sarebbe una penalità per
        qualcosa che il cliente non può sistemare."""
        s = _sito()
        g.checks_offsite(s, {"raggiunto": True, "entita": None, "lingue": []})
        self.assertEqual(_stato(s.site_checks, "entity.wikidata"), g.UNK)

    def test_e_non_le_suggerisce_di_crearsi_una_voce(self):
        s = _sito()
        g.checks_offsite(s, {"raggiunto": True, "entita": None, "lingue": []})
        testo = next(c.recommendation for c in s.site_checks if c.id == "entity.wikidata").lower()
        self.assertNotIn("crea", testo)

    def test_l_entita_trovata_e_un_ok_e_dice_quale(self):
        s = _sito()
        g.checks_offsite(s, {"raggiunto": True, "lingue": ["it", "en"],
                             "entita": {"qid": "Q27586", "etichetta": "Ferrari",
                                        "url": "https://www.wikidata.org/wiki/Q27586"}})
        c = next(c for c in s.site_checks if c.id == "entity.wikidata")
        self.assertEqual(c.status, g.OK)
        self.assertIn("Q27586", c.detail)
        self.assertIn("2 lingue", c.detail)

    def test_entita_nota_ma_non_richiamata_e_un_avviso(self):
        """Questo sì che dipende dal cliente: il collegamento lo scrive lui."""
        s = _sito()
        g.checks_offsite(s, {"raggiunto": True, "lingue": [],
                             "entita": {"qid": "Q1", "etichetta": "X",
                                        "url": "https://www.wikidata.org/wiki/Q1"}})
        c = next(c for c in s.site_checks if c.id == "entity.sameas.fonti")
        self.assertEqual(c.status, g.WARN)
        self.assertIn("Q1", c.recommendation)

    def test_il_collegamento_dichiarato_e_un_ok(self):
        s = _sito()
        s.sameas_urls = ["https://it.wikipedia.org/wiki/X", "https://linkedin.com/x"]
        g.checks_offsite(s, {"raggiunto": True, "lingue": [],
                             "entita": {"qid": "Q1", "etichetta": "X",
                                        "url": "https://www.wikidata.org/wiki/Q1"}})
        self.assertEqual(_stato(s.site_checks, "entity.sameas.fonti"), g.OK)

    def test_i_social_da_soli_non_bastano(self):
        """⚠️ `sd.sameas` si accontenta di qualsiasi URL. Qui contano solo le
        fonti che un assistente riconosce come enciclopediche."""
        s = _sito()
        s.sameas_urls = ["https://facebook.com/x", "https://instagram.com/x"]
        g.checks_offsite(s, {"raggiunto": True, "lingue": [],
                             "entita": {"qid": "Q1", "etichetta": "X",
                                        "url": "https://www.wikidata.org/wiki/Q1"}})
        self.assertEqual(_stato(s.site_checks, "entity.sameas.fonti"), g.WARN)


class SameAsDallaHome(unittest.TestCase):

    def _leggi(self, html):
        from bs4 import BeautifulSoup
        return g._sameas_dalla_home(BeautifulSoup(html, "lxml"))

    def test_legge_una_lista(self):
        self.assertEqual(self._leggi(
            '<script type="application/ld+json">{"@type":"Organization",'
            '"sameAs":["https://a.it","https://b.it"]}</script>'),
            ["https://a.it", "https://b.it"])

    def test_legge_anche_una_stringa_sola(self):
        """⚠️ `sameAs` ammette entrambe le forme, e in natura si trovano
        entrambe: leggerne una sola perde metà dei siti."""
        self.assertEqual(self._leggi(
            '<script type="application/ld+json">{"sameAs":"https://a.it"}</script>'),
            ["https://a.it"])

    def test_json_rotto_non_fa_saltare_niente(self):
        self.assertEqual(self._leggi(
            '<script type="application/ld+json">{non json</script>'), [])

    def test_senza_home_nessun_collegamento(self):
        self.assertEqual(g._sameas_dalla_home(None), [])


if __name__ == "__main__":
    unittest.main()


class StrozzamentoDiWikidata(unittest.TestCase):
    """⚠️ Trovato in collaudo: due audit di fila e il servizio pubblico
    strozza, così un sito che l'entità ce l'ha risultava «non verificato»."""

    def _finta(self, risposte):
        chiamate = {"n": 0}

        class R:
            def __init__(self, codice, headers=None):
                self.status_code, self.headers = codice, headers or {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError("HTTP %d" % self.status_code)

            def json(self):
                return {"results": {"bindings": [{"ok": 1}]}}

        def get(*a, **k):
            r = risposte[min(chiamate["n"], len(risposte) - 1)]
            chiamate["n"] += 1
            return R(*r)
        return get, chiamate

    def test_riprova_dopo_un_429(self):
        get, chiamate = self._finta([(429, {"Retry-After": "0"}), (200,)])
        vecchio_get, vecchio_sleep = po.requests.get, po.time.sleep
        po.requests.get, po.time.sleep = get, lambda s: None
        try:
            self.assertEqual(po._query("X"), [{"ok": 1}])
            self.assertEqual(chiamate["n"], 2)
        finally:
            po.requests.get, po.time.sleep = vecchio_get, vecchio_sleep

    def test_l_attesa_dichiarata_non_blocca_l_audit_all_infinito(self):
        get, _ = self._finta([(429, {"Retry-After": "9000"}), (200,)])
        attese = []
        vecchio_get, vecchio_sleep = po.requests.get, po.time.sleep
        po.requests.get, po.time.sleep = get, attese.append
        try:
            po._query("X")
            self.assertLessEqual(attese[0], 30.0)
        finally:
            po.requests.get, po.time.sleep = vecchio_get, vecchio_sleep
