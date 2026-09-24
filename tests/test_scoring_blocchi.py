# -*- coding: utf-8 -*-
"""Il punteggio a tre blocchi (specifica del 24/09/2026)."""
import unittest

from tests import conftest_env  # noqa: F401

import blocchi_punteggio as bp
import geo_audit as g


def ck(cid, stato="ok", peso=3):
    return {"id": cid, "status": stato, "weight": peso}


_B1 = [("crawl.ai", 12), ("crawl.robots", 2), ("crawl.sitemap", 3), ("crawl.llms", 1)]
_B2 = [("crawl.https", 3), ("sd.present", 18), ("sd.valid", 4), ("sd.highvalue", 6),
       ("sd.completeness", 4), ("sd.sameas", 3), ("meta.og", 3), ("meta.canonical", 2),
       ("meta.lang", 2), ("meta.twitter", 1), ("sem.html", 3), ("trust.social", 3)]
_B3 = [("content.h1", 6), ("content.len", 5), ("content.q", 4), ("content.struct", 4),
       ("content.hier", 3), ("content.tldr", 3), ("content.fresh", 2), ("content.alt", 2),
       ("meta.description", 5), ("meta.title", 4), ("page.noindex", 6),
       ("page.status", 4), ("render.parity", 2), ("trust.contact", 4), ("trust.author", 2)]


class LaFormulaDellaSpecifica(unittest.TestCase):

    def test_il_caso_di_collaudo_del_documento_da_80(self):
        """⚠️ È il numero scritto nella specifica: sito che blocca i crawler AI
        e perfetto in tutto il resto. Prima della revisione prendeva 98."""
        sito = [ck("crawl.ai", "fail", 12)] + [ck(i, "ok", p) for i, p in _B1[1:]]
        pag = [ck(i, "ok", p) for i, p in _B2 + _B3]
        self.assertEqual(bp.complessivo(sito, pag), 80)

    def test_le_quote_sono_quelle_concordate(self):
        self.assertEqual(bp.QUOTA, {1: 0.30, 2: 0.52, 3: 0.18})
        self.assertAlmostEqual(sum(bp.QUOTA.values()), 1.0)

    def test_tutto_perfetto_fa_cento(self):
        sito = [ck(i, "ok", p) for i, p in _B1]
        pag = [ck(i, "ok", p) for i, p in _B2 + _B3]
        self.assertEqual(bp.complessivo(sito, pag), 100)

    def test_il_massimo_col_blocco_1_azzerato_e_settanta(self):
        """⚠️ Non c'è un tetto scritto da nessuna parte: esce dalla formula.
        Se qualcuno aggiungesse un cap esplicito sarebbe la stessa regola in
        due posti, e due regole uguali divergono al primo cambio."""
        sito = [ck(i, "fail", p) for i, p in _B1]
        pag = [ck(i, "ok", p) for i, p in _B2 + _B3]
        self.assertEqual(bp.complessivo(sito, pag), 70)

    def test_i_check_di_sito_non_si_diluiscono_piu_con_le_pagine(self):
        """⚠️ Il difetto che la revisione esiste per correggere: prima il peso
        dei check di sito si schiacciava al crescere delle pagine analizzate."""
        sito = [ck("crawl.ai", "fail", 12)] + [ck(i, "ok", p) for i, p in _B1[1:]]
        una = bp.complessivo(sito, [ck(i, "ok", p) for i, p in _B2 + _B3])
        trenta = bp.complessivo(sito, [ck(i, "ok", p) for i, p in _B2 + _B3] * 30)
        self.assertEqual(una, trenta)

    def test_un_blocco_senza_dati_non_conta_come_zero(self):
        """⚠️ Un sito di cui non si è potuta leggere nessuna pagina non deve
        prendere 82: sarebbe un voto su un limite del crawler, non sul sito."""
        sito = [ck(i, "ok", p) for i, p in _B1] + [ck("crawl.https", "ok", 3)]
        self.assertEqual(bp.complessivo(sito, []), 100)

    def test_senza_niente_di_misurabile_e_zero(self):
        self.assertEqual(bp.complessivo([], []), 0)
        self.assertEqual(bp.complessivo([ck("crawl.ai", "unknown", 12)], []), 0)

    def test_gli_unknown_restano_fuori_dal_denominatore(self):
        soli_ok = bp.per_blocco([ck("crawl.ai", "ok", 12)], [])[1]["punteggio"]
        con_unk = bp.per_blocco([ck("crawl.ai", "ok", 12),
                                 ck("crawl.llms", "unknown", 1)], [])[1]["punteggio"]
        self.assertEqual(soli_ok, con_unk)

    def test_geo_audit_usa_la_formula_nuova(self):
        sito = [ck("crawl.ai", "fail", 12)] + [ck(i, "ok", p) for i, p in _B1[1:]]
        pag = [ck(i, "ok", p) for i, p in _B2 + _B3]
        self.assertEqual(g.score_complessivo(sito, pag), 80)


class OgniCheckHaUnBlocco(unittest.TestCase):
    """⚠️ Il modo più silenzioso in cui questa revisione può sbagliare.

    La specifica elencava 31 check; il motore ne emette 42, perché è stata
    scritta prima dei rilasci del 22-23 settembre. Un check non assegnato non
    toglie e non aggiunge punti: esce dal punteggio senza errore né avviso.
    """

    def _tutti_gli_id(self):
        import tests.test_catalogo_check as t
        ids = set()
        for nome in dir(t):
            o = getattr(t, nome)
            if isinstance(o, type) and hasattr(o, "ATTESI"):
                ids |= set(o.ATTESI)
        ids |= {"sd.completeness", "content.alt"}   # emessi solo se pertinenti
        return ids

    def test_nessun_check_del_catalogo_resta_orfano(self):
        orfani = bp.orfani_del_catalogo(self._tutti_gli_id())
        self.assertEqual(orfani, [], "check fuori dal punteggio: %s" % orfani)

    def test_nessun_check_in_due_blocchi(self):
        tutti = list(bp.BLOCCO_1) + list(bp.BLOCCO_2) + list(bp.BLOCCO_3)
        self.assertEqual(len(tutti), len(set(tutti)))

    def test_gli_orfani_vengono_segnalati_a_chi_calcola(self):
        d = bp.per_blocco([ck("check.inventato", "fail", 9)], [])
        self.assertIn("check.inventato", d["orfani"])


class PaginaNoindex(unittest.TestCase):

    def _checks(self, url):
        from bs4 import BeautifulSoup
        checks = []
        g.checks_indexing(BeautifulSoup(
            '<html><head><meta name="robots" content="noindex"></head></html>', "lxml"),
            checks, 200, 0, url)
        return next(c for c in checks if c.id == "page.noindex")

    def test_un_noindex_inatteso_ora_penalizza(self):
        """⚠️ Era `unknown`: il caso più grave del catalogo, una pagina
        invisibile ai motori, usciva dal denominatore invece di pesare."""
        c = self._checks("https://x.it/servizi/consulenza")
        self.assertEqual(c.status, g.FAIL)
        self.assertEqual(c.weight, 6)              # invariati per specifica
        self.assertEqual(c.severity, "high")

    def test_su_una_pagina_di_servizio_resta_corretto(self):
        for url in ("https://x.it/privacy-policy", "https://x.it/pagina/2",
                    "https://x.it/tag/vino", "https://x.it/?s=cerca"):
            self.assertEqual(self._checks(url).status, g.OK, url)


class PaginePreseConNoindexVoluto(unittest.TestCase):
    """⚠️ L'ordine conta: il regex va esteso PRIMA di alzare la gravità. Al
    contrario ogni WordPress con paginazione e tag produce falsi positivi a
    centinaia, e ora ognuno è un FAIL, non un avviso."""

    SERVIZIO = ("/privacy-policy", "/cookie-policy", "/carrello", "/checkout",
                "/mio-account", "/grazie", "/404", "/page/3", "/pagina/2",
                "/page-4", "/tag/vino", "/tags/rossi", "/categoria/rossi",
                "/categorie/vini", "/category/news", "/categories/x",
                "/archivio/2024", "/autore/mario", "/author/mario",
                "/filtri/prezzo", "/?s=abc", "/search?q=x", "/registrazione")

    # Pagine vere che la vecchia ricerca per sottostringa scambiava per pagine
    # di servizio: `cart` dentro `cartoleria`, `tag` dentro `tag-heuer`.
    VERE = ("/cartoleria", "/cartografia-storica", "/cartagine", "/pagelle",
            "/tagliatelle", "/tag-heuer-orologi", "/categoriale", "/loginox",
            "/pages-nostre", "/searchlight-hotel", "/pagina-bianca-del-museo",
            "/archivio-storico-comunale-di-siena", "/filtrazione-industriale",
            "/accountant-services", "/prodotti/vino-rosso", "/chi-siamo")

    def test_riconosce_le_pagine_di_servizio(self):
        for u in self.SERVIZIO:
            self.assertTrue(g.UTILITY_RE.search(u), u)

    def test_non_scambia_una_pagina_vera_per_una_di_servizio(self):
        for u in self.VERE:
            self.assertFalse(g.UTILITY_RE.search(u), u)

    def test_la_paginazione_vuole_un_numero(self):
        self.assertTrue(g.UTILITY_RE.search("/pagina/2"))
        self.assertFalse(g.UTILITY_RE.search("/pagina-bianca"))

    def test_le_tassonomie_vogliono_la_barra(self):
        self.assertTrue(g.UTILITY_RE.search("/tag/x"))
        self.assertFalse(g.UTILITY_RE.search("/tag-heuer"))


class RenderParity(unittest.TestCase):

    def test_il_peso_e_due(self):
        self.assertEqual(g._PESO_PARITA, 2)

    def test_la_stima_non_produce_mai_fail(self):
        """⚠️ Per specifica: è un indizio indiretto — quanto codice c'è
        rispetto al testo — non una misura della parità. La nostra euristica
        sa restituire FAIL, quindi va ammorbidita sul percorso di produzione."""
        html = ('<html><body><div id="root"></div><script>'
                + "var x=1;" * 400 + "</script><p>poco testo</p></body></html>")
        checks = []
        g.check_js_parity(checks, html, False, None)
        c = next(c for c in checks if c.id == "render.parity")
        self.assertIn(c.status, (g.OK, g.WARN))

    def test_resta_nel_terzo_blocco(self):
        self.assertEqual(bp.DI_BLOCCO["render.parity"], 3)


if __name__ == "__main__":
    unittest.main()
