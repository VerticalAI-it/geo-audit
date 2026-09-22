# -*- coding: utf-8 -*-
"""Chi manda persone e chi legge il sito: le due cose che AI Traffic distingue.

⚠️ Il caso che questi test proteggono e' gia' costato un numero sbagliato in
produzione, sul plugin: un articolo che *parla* di ChatGPT veniva contato come
visita *da* ChatGPT, e quel numero gonfiato era proprio quello presentato al
cliente come «e' questo che paga».
"""
import unittest

from tests import conftest_env  # noqa: F401  — credenziali finte prima di db

from ai_sources import detect_ai_crawler, detect_ai_referral
from db import _detect_ai_source


class ChiMandaPersone(unittest.TestCase):

    def test_i_quattro_assistenti_principali(self):
        for referrer, atteso in (
            ("https://chatgpt.com/", "ChatGPT"),
            ("https://chat.openai.com/c/abc", "ChatGPT"),
            ("https://claude.ai/chat/xyz", "Claude"),
            ("https://www.perplexity.ai/search/qualcosa", "Perplexity"),
            ("https://gemini.google.com/app", "Gemini"),
        ):
            self.assertEqual(detect_ai_referral(referrer), atteso, referrer)

    def test_il_redirect_di_gemini(self):
        """Senza questa voce il traffico da Gemini si perde quasi tutto: i
        link delle fonti passano dal redirect di grounding, non dal sito."""
        self.assertEqual(
            detect_ai_referral("https://vertexaisearch.cloud.google.com/grounding-api-redirect/AB"),
            "Gemini")

    def test_un_articolo_CHE_PARLA_di_chatgpt_non_e_una_visita_da_chatgpt(self):
        """⚠️ Il difetto misurato sul plugin. Il confronto va fatto sull'host,
        non cercando il nome dentro l'indirizzo."""
        self.assertIsNone(detect_ai_referral("https://www.html.it/articoli/chatgpt-guida/"))
        self.assertIsNone(detect_ai_referral("https://oroscopo.it/segni/gemini/"))
        self.assertIsNone(detect_ai_referral("https://www.claudeshop.it/prodotti"))

    def test_bing_e_un_motore_di_ricerca_tranne_chat(self):
        self.assertIsNone(detect_ai_referral("https://www.bing.com/search?q=scarpe"))
        self.assertEqual(detect_ai_referral("https://www.bing.com/chat"), "Copilot")

    def test_utm_source_quando_il_referrer_manca(self):
        """Molti assistenti mandano traffico senza `Referer`: link copiato a
        mano, app mobile, https -> http. Li' il referral c'e' ma e' muto."""
        self.assertEqual(
            detect_ai_referral("", "https://sito.it/pagina?utm_source=chatgpt.com"),
            "ChatGPT")

    def test_traffico_normale_resta_normale(self):
        for referrer in ("", "https://www.google.com/search?q=x",
                         "https://www.facebook.com/", "https://sito.it/altra-pagina"):
            self.assertIsNone(detect_ai_referral(referrer), referrer)

    def test_la_funzione_di_db_e_la_stessa(self):
        """`_detect_ai_source` e' il punto da cui passa il tracking: se
        divergesse da `detect_ai_referral`, i dati salvati e quelli mostrati
        racconterebbero due cose diverse."""
        self.assertEqual(_detect_ai_source("https://chatgpt.com/"), "ChatGPT")
        self.assertIsNone(_detect_ai_source("https://www.html.it/chatgpt-guida/"))


class ChiLeggeIlSito(unittest.TestCase):

    def test_i_crawler_noti(self):
        for ua in ("Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)",
                   "Mozilla/5.0 (compatible; ClaudeBot/1.0)",
                   "Mozilla/5.0 (compatible; PerplexityBot/1.0)"):
            self.assertIsNotNone(detect_ai_crawler(ua), ua)

    def test_torna_etichetta_e_categoria(self):
        esito = detect_ai_crawler("Mozilla/5.0 (compatible; GPTBot/1.0)")
        self.assertIsNotNone(esito)
        etichetta, categoria = esito
        # l'etichetta porta il nome di chi lo manda, non solo del bot:
        # e' quello che il cliente riconosce nella scheda
        self.assertEqual(etichetta, "OpenAI GPTBot")
        self.assertIn(categoria, ("training", "search", "user"))

    def test_un_browser_non_e_un_crawler(self):
        umano = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
        self.assertIsNone(detect_ai_crawler(umano))

    def test_user_agent_vuoto(self):
        self.assertIsNone(detect_ai_crawler(""))


if __name__ == "__main__":
    unittest.main()
