# -*- coding: utf-8 -*-
"""I controlli aggiunti nel motore 1.2.0.

Ognuno di questi check può far fallire l'audit di un cliente vero, quindi la
cosa che conta di più non è che sappia dire «male»: è che **sappia tacere**
quando non ha niente da misurare. Un falso allarme accusa un sito di un
difetto che non ha, e su check da peso 3-5 si vede nel punteggio.
"""
import unittest

from bs4 import BeautifulSoup as BS

import geo_audit as g


def _pagina(html, url="https://esempio.it/p"):
    f = g.Fetched(url=url, status=200, final_url=url, html=html,
                  is_html=True, redirects=0, rendered=False)
    return {c.id: c for c in g.analyze_page(url, f, f, render_used=False).checks}


def _corpo(interno):
    return f"<!doctype html><html lang='it'><head><title>t</title></head><body>{interno}</body></html>"


class ParagrafoDApertura(unittest.TestCase):

    def test_quello_giusto(self):
        p = "<p>" + ("parola " * 50) + "nel 2025 erano 1.200 unità.</p>"
        self.assertEqual(_pagina(_corpo(p))["content.atomic"].status, g.OK)

    def test_senza_dati_avverte_ma_non_boccia(self):
        p = "<p>" + ("parola " * 55) + "</p>"
        self.assertEqual(_pagina(_corpo(p))["content.atomic"].status, g.WARN)

    def test_troppo_corto(self):
        self.assertEqual(_pagina(_corpo("<p>" + ("x " * 20) + "</p>"))["content.atomic"].status,
                         g.WARN)

    def test_nessun_paragrafo_e_un_fallimento(self):
        self.assertEqual(_pagina(_corpo("<div>solo div</div>"))["content.atomic"].status, g.FAIL)

    def test_i_paragrafi_brevissimi_non_contano_come_apertura(self):
        """Un «Home / Prodotti» di tre parole in cima non è il paragrafo di
        apertura: si cerca il primo blocco che dice davvero qualcosa."""
        html = _corpo("<p>Home</p><p>" + ("parola " * 50) + "con 12 dati.</p>")
        self.assertEqual(_pagina(html)["content.atomic"].status, g.OK)


class DatiAttribuiti(unittest.TestCase):

    def test_tace_sulle_pagine_brevi(self):
        """⚠️ Su una pagina di contatti chiedere le fonti non ha senso.
        Meglio `unknown` che un rosso su un requisito che non si applica."""
        self.assertEqual(_pagina(_corpo("<p>" + ("x " * 80) + "</p>"))["content.sources"].status,
                         g.UNK)

    def test_un_testo_lungo_senza_fonti_fallisce(self):
        self.assertEqual(_pagina(_corpo("<p>" + ("parola " * 400) + "</p>"))["content.sources"].status,
                         g.FAIL)

    def test_le_attribuzioni_si_riconoscono(self):
        testo = " ".join(["Secondo l'Istat il dato è salito." + ("parola " * 60)
                          for _ in range(5)])
        self.assertEqual(_pagina(_corpo(f"<p>{testo}</p>"))["content.sources"].status, g.OK)


class ContenutoNascosto(unittest.TestCase):

    def test_una_pagina_normale_passa(self):
        self.assertEqual(_pagina(_corpo("<p>" + ("parola " * 200) + "</p>"))["content.hidden"].status,
                         g.OK)

    def test_mezzo_testo_in_accordion_fallisce(self):
        html = _corpo("<p>" + ("fuori " * 50) + "</p>"
                      '<div class="accordion">' + ("dentro " * 100) + "</div>")
        self.assertEqual(_pagina(html)["content.hidden"].status, g.FAIL)

    def test_gli_accordion_annidati_non_si_contano_due_volte(self):
        """⚠️ La prima versione sommava tutti i contenitori corrispondenti, e
        siccome gli accordion sono quasi sempre annidati dichiarava «il 128%
        del testo è nascosto» — un numero impossibile, stampato in un report
        che va al cliente."""
        html = _corpo("<p>" + ("fuori " * 60) + "</p>"
                      '<div class="accordion"><div class="accordion-collapse">'
                      '<div class="collapse">' + ("dentro " * 40) + "</div></div></div>")
        c = _pagina(html)["content.hidden"]
        percentuale = int("".join(ch for ch in c.detail if ch.isdigit()) or 0)
        self.assertLessEqual(percentuale, 100, c.detail)
        self.assertGreaterEqual(percentuale, 30, c.detail)

    def test_un_pdf_linkato_e_un_avviso(self):
        html = _corpo("<p>" + ("parola " * 200) + '</p><a href="/listino.pdf">Listino</a>')
        self.assertEqual(_pagina(html)["content.hidden"].status, g.WARN)


class DatiStrutturatiFini(unittest.TestCase):

    def _con_jsonld(self, oggetto):
        import json
        return _corpo('<script type="application/ld+json">' + json.dumps(oggetto)
                      + "</script><p>" + ("parola " * 60) + "</p>")

    def test_datemodified_tace_senza_article(self):
        self.assertEqual(_pagina(_corpo("<p>x</p>"))["schema.datemodified"].status, g.UNK)

    def test_article_senza_datemodified(self):
        html = self._con_jsonld({"@type": "Article", "headline": "t"})
        self.assertEqual(_pagina(html)["schema.datemodified"].status, g.WARN)

    def test_article_con_datemodified(self):
        html = self._con_jsonld({"@type": "Article", "headline": "t",
                                 "dateModified": "2026-09-22"})
        self.assertEqual(_pagina(html)["schema.datemodified"].status, g.OK)

    def test_faq_con_risposte_della_lunghezza_giusta(self):
        risposta = " ".join(["parola"] * 70)
        html = self._con_jsonld({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f"D{i}?",
             "acceptedAnswer": {"@type": "Answer", "text": risposta}} for i in range(3)]})
        self.assertEqual(_pagina(html)["faq.answerlen"].status, g.OK)

    def test_faq_con_risposte_troppo_corte(self):
        html = self._con_jsonld({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": "D?",
             "acceptedAnswer": {"@type": "Answer", "text": "Sì."}}]})
        self.assertEqual(_pagina(html)["faq.answerlen"].status, g.WARN)

    def test_persona_collegata_a_una_fonte_di_identita(self):
        html = self._con_jsonld({"@type": "Person", "name": "Mario Rossi",
                                 "sameAs": ["https://it.wikipedia.org/wiki/Mario_Rossi"]})
        self.assertEqual(_pagina(html)["sd.person"].status, g.OK)

    def test_persona_senza_collegamenti(self):
        html = self._con_jsonld({"@type": "Person", "name": "Mario Rossi"})
        self.assertEqual(_pagina(html)["sd.person"].status, g.WARN)


class CanonicalCoerente(unittest.TestCase):

    def test_canonical_a_se_stesso(self):
        html = _corpo("<p>x</p>").replace(
            "<head>", '<head><link rel="canonical" href="https://esempio.it/p">')
        self.assertEqual(_pagina(html)["meta.canonical.consistency"].status, g.OK)

    def test_canonical_altrove_e_un_avviso(self):
        html = _corpo("<p>x</p>").replace(
            "<head>", '<head><link rel="canonical" href="https://esempio.it/altra">')
        self.assertEqual(_pagina(html)["meta.canonical.consistency"].status, g.WARN)

    def test_la_barra_finale_non_e_una_differenza(self):
        """⚠️ `/p` e `/p/` sono la stessa pagina: segnalarlo sarebbe un falso
        allarme su un check da peso 3, sui moltissimi siti che scrivono il
        canonical con la barra."""
        html = _corpo("<p>x</p>").replace(
            "<head>", '<head><link rel="canonical" href="https://esempio.it/p/">')
        self.assertEqual(_pagina(html)["meta.canonical.consistency"].status, g.OK)

    def test_tace_se_non_c_e_canonical(self):
        self.assertEqual(_pagina(_corpo("<p>x</p>"))["meta.canonical.consistency"].status, g.UNK)


class ControlliDiSito(unittest.TestCase):

    def _sito(self, home_html=None, pagine=None, **kw):
        s = g.Site(base_url="https://esempio.it", https=True)
        for k, v in kw.items():
            setattr(s, k, v)
        g.build_site_checks(s, BS(home_html, "lxml") if home_html else None, pagine)
        return {c.id: c for c in s.site_checks}

    def test_noindex_in_sitemap_e_una_contraddizione(self):
        c = self._sito('<html><head><meta name="robots" content="noindex"></head><body></body></html>',
                       [], sitemap_found=True)
        self.assertEqual(c["crawl.conflict"].status, g.FAIL)

    def test_nessuna_contraddizione(self):
        c = self._sito("<html><head></head><body></body></html>", [], sitemap_found=True)
        self.assertEqual(c["crawl.conflict"].status, g.OK)

    def test_copertura_completa(self):
        c = self._sito("<html></html>", ["https://esempio.it/a", "https://esempio.it/b"],
                       sitemap_urls=["https://esempio.it/a", "https://esempio.it/b"])
        self.assertEqual(c["crawl.coverage"].status, g.OK)

    def test_meta_pagine_fuori_sitemap(self):
        c = self._sito("<html></html>",
                       ["https://esempio.it/a", "https://esempio.it/b",
                        "https://esempio.it/c", "https://esempio.it/d"],
                       sitemap_urls=["https://esempio.it/a"])
        self.assertEqual(c["crawl.coverage"].status, g.WARN)

    def test_senza_home_i_due_check_tacciono_ma_esistono(self):
        """⚠️ Devono esserci comunque: se comparissero solo a volte, il
        catalogo di sito cambierebbe da audit a audit e con lui il
        denominatore del punteggio."""
        c = self._sito()
        self.assertEqual(c["crawl.conflict"].status, g.UNK)
        self.assertEqual(c["crawl.coverage"].status, g.UNK)


if __name__ == "__main__":
    unittest.main()
