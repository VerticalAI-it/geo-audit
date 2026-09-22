# -*- coding: utf-8 -*-
"""Lo SNAPSHOT del catalogo dei check: gli id che il motore emette davvero.

⚠️ E' il test piu' prezioso del lotto, e protegge una cosa che nessun altro
controllo vede: **rinominare un `check_id`**.

Le criticita' sono legate al progetto tramite l'id del check. Cambiarlo non
rompe niente e non solleva nessun errore — semplicemente, da quel momento le
criticita' vecchie restano aperte per sempre (il loro id non compare piu' fra
quelli emessi) e ne nascono di nuove identiche a fianco. Lo storico si spezza
in silenzio, e ce ne si accorge mesi dopo guardando un grafico che non torna.

Se questo test fallisce hai due strade, tutte e due deliberate:
  · hai AGGIUNTO un check -> aggiungi l'id qui sotto, e alza `ENGINE_VERSION`
    perche' il denominatore del punteggio e' cambiato (vedi `docs/11`, 2.1);
  · hai RINOMINATO un check -> fermati. Serve una migrazione delle issue
    esistenti, o lo storico di quel controllo riparte da zero.

Gira offline: le pagine sono HTML costruito qui, nessuna richiesta di rete.
"""
import unittest

import geo_audit as g


PAGINA_COMPLETA = """<!doctype html>
<html lang="it"><head>
<title>Pompe volumetriche a ingranaggi — Casali</title>
<meta name="description" content="Produciamo pompe volumetriche autoadescanti dal 1955.">
<link rel="canonical" href="https://esempio.it/pompe">
<meta property="og:title" content="Pompe volumetriche">
<meta property="og:image" content="https://esempio.it/og.jpg">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Casali",
 "url":"https://esempio.it","logo":"https://esempio.it/logo.png",
 "sameAs":["https://it.wikipedia.org/wiki/Casali"]}
</script>
</head><body>
<h1>Pompe volumetriche a ingranaggi</h1>
<p>Le pompe volumetriche autoadescanti trasferiscono fluidi viscosi a portata
costante. Casali le produce dal 1955 in Emilia Romagna, con certificazione
ISO 9001 e ATEX per le atmosfere esplosive.</p>
<h2>Applicazioni</h2>
<p>Bitume, olio diatermico, fluidi alimentari e cosmetici.</p>
<a href="/chi-siamo">Chi siamo</a>
</body></html>"""

PAGINA_VUOTA = "<!doctype html><html><body></body></html>"


def _pagina(html, url="https://esempio.it/pompe", stato=200):
    f = g.Fetched(url=url, status=stato, final_url=url, html=html,
                  is_html=True, redirects=0, rendered=False)
    return g.analyze_page(url, f, f, render_used=False)


class CatalogoDeiCheckDiPagina(unittest.TestCase):

    # ⚠️ Aggiornare solo insieme a un bump di ENGINE_VERSION.
    ATTESI = {
        "content.fresh", "content.h1", "content.hier", "content.len",
        "content.q", "content.struct", "content.tldr", "meta.canonical",
        "meta.description", "meta.lang", "meta.og", "meta.title",
        "meta.twitter", "page.noindex", "page.status", "render.parity",
        "sd.highvalue", "sd.present", "sd.sameas", "sd.valid", "sem.html",
        "trust.author", "trust.contact", "trust.social",
    }

    def test_gli_id_emessi_sono_quelli_attesi(self):
        emessi = {c.id for c in _pagina(PAGINA_COMPLETA).checks}
        nuovi = emessi - self.ATTESI
        spariti = self.ATTESI - emessi
        self.assertFalse(nuovi, f"check NUOVI non dichiarati: {sorted(nuovi)}")
        self.assertFalse(spariti, f"check SPARITI o rinominati: {sorted(spariti)}")

    # ⚠️ Questi tre NON vengono emessi se la pagina non ha dati strutturati:
    # non si puo' validare cio' che non c'e'. La conseguenza pero' e' che una
    # pagina senza JSON-LD ha un DENOMINATORE PIU' PICCOLO, quindi la mancanza
    # di dati strutturati la penalizza MENO di quanto dovrebbe. E' la stessa
    # famiglia del difetto di diluizione (docs/11, 2.3) e va sciolta insieme
    # a quello: o si emettono sempre, in stato `fail`, o si accetta e si
    # scrive nel documento del motore.
    SOLO_CON_JSONLD = {"sd.valid", "sd.highvalue", "sd.sameas"}

    def test_il_catalogo_di_base_non_dipende_dal_contenuto(self):
        """Tutti i check tranne i tre sui dati strutturati vengono emessi
        comunque: cambia il loro *stato*, non la loro esistenza. Se un check
        comparisse solo su certe pagine, il denominatore cambierebbe da pagina
        a pagina e i punteggi non sarebbero confrontabili fra loro."""
        emessi = {c.id for c in _pagina(PAGINA_VUOTA).checks}
        self.assertEqual(emessi, self.ATTESI - self.SOLO_CON_JSONLD)

    def test_i_tre_check_sui_dati_strutturati_compaiono_solo_col_jsonld(self):
        """Fissa per iscritto l'asimmetria, cosi' che chi rivede la formula
        (2.3) la trovi gia' misurata invece di riscoprirla."""
        con = {c.id for c in _pagina(PAGINA_COMPLETA).checks}
        senza = {c.id for c in _pagina(PAGINA_VUOTA).checks}
        self.assertEqual(con - senza, self.SOLO_CON_JSONLD)

    def test_senza_dati_strutturati_il_denominatore_si_restringe(self):
        """La conseguenza in numeri: la pagina vuota ha meno peso totale, e
        per quella via la penalita' e' piu' leggera del dovuto."""
        peso = lambda p: sum(c.weight for c in p.checks if c.status != g.UNK)
        self.assertLess(peso(_pagina(PAGINA_VUOTA)), peso(_pagina(PAGINA_COMPLETA)))

    def test_ogni_check_ha_categoria_peso_e_severita(self):
        for c in _pagina(PAGINA_COMPLETA).checks:
            self.assertTrue(c.category, c.id)
            self.assertGreaterEqual(c.weight, 1, c.id)
            self.assertIn(c.severity, ("critical", "high", "medium", "low", "info"), c.id)
            self.assertIn(c.status, (g.OK, g.WARN, g.FAIL, g.UNK), c.id)

    def test_un_check_fallito_dice_come_si_risolve(self):
        """Una criticita' senza rimedio e' una lamentela: il report deve
        dire cosa fare, non solo cosa non va."""
        for c in _pagina(PAGINA_VUOTA).checks:
            if c.status == g.FAIL:
                self.assertTrue(c.recommendation.strip(),
                                f"{c.id} fallisce senza dire come si risolve")

    def test_le_categorie_sono_quelle_del_design_system(self):
        aree = {c.category for c in _pagina(PAGINA_COMPLETA).checks}
        self.assertTrue(aree <= {
            "Autorità & trust",
            "Contenuti & answerability",
            "Dati strutturati",
            "HTML semantico",
            "Meta & social",
            "Rendering & accesso",
        }, f"categoria fuori catalogo: {aree}")

    def test_render_parity_stima_quando_il_rendering_non_gira(self):
        """Dalla 1.2.0 il check non e' piu' sempre `unknown`: quando il
        rendering headless non gira (su Vercel non gira mai) prova a stimare
        dal solo HTML, e DICE che e' una stima.

        ⚠️ Resta `unknown` nella zona grigia — fra le 60 e le 250 parole senza
        contenitori sospetti — perche' su un check da peso 8 un falso allarme
        accusa il sito del cliente di un difetto che non ha."""
        parity = next(c for c in _pagina(PAGINA_COMPLETA).checks if c.id == "render.parity")
        self.assertIn(parity.status, (g.OK, g.WARN, g.FAIL, g.UNK))
        if parity.status != g.UNK:
            self.assertIn("stima", (parity.title + parity.detail).lower())

    def test_una_spa_vuota_viene_riconosciuta(self):
        spa = ('<!doctype html><html><body><div id="root"></div>'
               '<script src="/bundle.js"></script></body></html>')
        parity = next(c for c in _pagina(spa).checks if c.id == "render.parity")
        self.assertEqual(parity.status, g.FAIL)
        self.assertIn("root", parity.detail)

    def test_nella_zona_grigia_il_check_tace(self):
        """Fra le 60 e le 250 parole, senza gusci sospetti, non si puo' dire
        niente di utile: meglio `unknown` che tirare a indovinare."""
        grigia = "<!doctype html><html><body><p>" + ("parola " * 100) + "</p></body></html>"
        parity = next(c for c in _pagina(grigia).checks if c.id == "render.parity")
        self.assertEqual(parity.status, g.UNK)

    def test_ogni_check_dichiara_in_che_versione_e_nato(self):
        """2.4 · serve a leggere uno storico con un gradino: se il check e'
        cambiato il gradino e' nostro, se non e' cambiato e' del sito."""
        for c in _pagina(PAGINA_COMPLETA).checks:
            self.assertTrue(c.versione, c.id)
        parity = next(c for c in _pagina(PAGINA_COMPLETA).checks if c.id == "render.parity")
        self.assertEqual(parity.versione, "1.2.0")


class CatalogoDeiCheckDiSito(unittest.TestCase):

    ATTESI = {"crawl.ai", "crawl.https", "crawl.llms", "crawl.robots", "crawl.sitemap"}

    def _sito(self, **kw):
        s = g.Site(base_url="https://esempio.it", https=True)
        for k, v in kw.items():
            setattr(s, k, v)
        g.build_site_checks(s)
        return s

    def test_gli_id_di_sito_sono_quelli_attesi(self):
        emessi = {c.id for c in self._sito(robots_found=True, sitemap_found=True).site_checks}
        self.assertEqual(emessi, self.ATTESI)

    def test_crawl_ai_fallisce_se_i_bot_sono_bloccati(self):
        s = self._sito(ai_bots_blocked=["GPTBot", "CCBot"])
        c = next(x for x in s.site_checks if x.id == "crawl.ai")
        self.assertEqual(c.status, g.FAIL)
        self.assertIn("GPTBot", c.detail)

    def test_crawl_ai_e_il_check_piu_pesante(self):
        """Il peso 12 e' quello che rende `crawl.ai` il controllo singolo piu'
        importante del catalogo di sito. Se cambia, cambia il significato del
        punteggio."""
        c = next(x for x in self._sito().site_checks if x.id == "crawl.ai")
        self.assertEqual(c.weight, 12)
        self.assertEqual(c.severity, "critical")


if __name__ == "__main__":
    unittest.main()
