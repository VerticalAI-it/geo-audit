# -*- coding: utf-8 -*-
"""Richieste di contatto → lead nel CRM VerticalAI Ops (14/10/2026).

Chi chiede l'analisi completa da un report diventa in Ops un cliente Lead con un
task per Marco. Le due cose che contano: il lead arriva con punteggio e link
al report apribile, e se Ops non risponde il modulo pubblico non se ne accorge.
"""
import unittest

from fastapi import BackgroundTasks

from tests import conftest_env  # noqa: F401

import lead_ops
import server


class _Risposta:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text


class IlPayload(unittest.TestCase):

    def test_porta_dominio_contatti_e_punteggio(self):
        p = lead_ops.payload_lead("job1", "acme.it", 62, "C", "mario@acme.it",
                                  "+39 333", "phone", "https://geo/r/job1?token=t")
        self.assertEqual(p["dominio"], "acme.it")
        self.assertEqual(p["email"], "mario@acme.it")
        self.assertEqual(p["telefono"], "+39 333")
        self.assertEqual(p["fonte"], "geo_audit")
        self.assertEqual(p["dettagli"]["overall"], 62)
        self.assertEqual(p["dettagli"]["grade"], "C")
        self.assertEqual(p["dettagli"]["audit_id"], "job1")
        self.assertEqual(p["dettagli"]["preferenza_contatto"], "telefono")
        self.assertIn("token=", p["dettagli"]["report_url"])

    def test_senza_telefono_il_campo_non_c_e(self):
        p = lead_ops.payload_lead("j", "acme.it", 50, "D", "a@acme.it", "", "email", "u")
        self.assertNotIn("telefono", p)
        self.assertEqual(p["dettagli"]["preferenza_contatto"], "email")

    def test_senza_dominio_niente_lead(self):
        """⚠️ Il dominio dell'email (gmail.com) creerebbe in Ops un cliente
        sbagliato, condiviso da tutti quelli che scrivono da Gmail."""
        for dominio in ("", "—", None, "  "):
            self.assertIsNone(lead_ops.payload_lead("j", dominio, 0, "?", "a@gmail.com", "", "email", "u"))


class LInvio(unittest.TestCase):

    def setUp(self):
        self._post, self._token = lead_ops.requests.post, lead_ops.OPS_LEAD_TOKEN
        self.chiamate = []

    def tearDown(self):
        lead_ops.requests.post, lead_ops.OPS_LEAD_TOKEN = self._post, self._token

    def _invia(self):
        lead_ops.invia_lead_a_ops("job1", "acme.it", 62, "C", "mario@acme.it", "", "email", "u")

    def test_senza_token_non_parte_niente(self):
        lead_ops.OPS_LEAD_TOKEN = ""
        lead_ops.requests.post = lambda *a, **k: self.chiamate.append(k)
        self._invia()
        self.assertEqual(self.chiamate, [])

    def test_con_token_va_a_ops_col_bearer_e_un_timeout(self):
        lead_ops.OPS_LEAD_TOKEN = "vai_pat_prova"

        def finto(url, **k):
            self.chiamate.append((url, k))
            return _Risposta(201)

        lead_ops.requests.post = finto
        self._invia()
        self.assertEqual(len(self.chiamate), 1)
        url, k = self.chiamate[0]
        self.assertEqual(url, lead_ops.OPS_LEAD_URL)
        self.assertEqual(k["headers"]["Authorization"], "Bearer vai_pat_prova")
        self.assertEqual(k["json"]["dominio"], "acme.it")
        self.assertTrue(k["timeout"])

    def test_ops_giu_o_in_errore_non_solleva(self):
        """Se Ops non risponde, l'invio si perde nel log: non deve diventare
        un'eccezione nella coda del modulo pubblico."""
        lead_ops.OPS_LEAD_TOKEN = "vai_pat_prova"

        def giu(*a, **k):
            raise ConnectionError("Ops non risponde")

        for finto in (giu, lambda *a, **k: _Risposta(500, "errore"), lambda *a, **k: _Risposta(400, "{}")):
            lead_ops.requests.post = finto
            self._invia()  # non deve sollevare


class LaRouteDiContatto(unittest.TestCase):
    """La route mette il lead in coda: la risposta all'utente non lo aspetta."""

    def setUp(self):
        self._veri = (server._sb_get, server._sb_insert_contact, server._send_contact_notif)
        server._sb_get = lambda job_id: {"domain": "acme.it", "overall": 62, "grade": "C"}
        server._sb_insert_contact = lambda dati: None
        server._send_contact_notif = lambda *a: None

    def tearDown(self):
        server._sb_get, server._sb_insert_contact, server._send_contact_notif = self._veri

    def test_il_lead_va_in_coda_col_link_firmato(self):
        coda = BackgroundTasks()
        r = server.contact("job1", coda, email=" Mario@Acme.it ", phone="", preference="email")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(coda.tasks), 1)
        t = coda.tasks[0]
        self.assertIs(t.func, lead_ops.invia_lead_a_ops)
        self.assertEqual(t.args[1], "acme.it")
        self.assertEqual(t.args[4], "mario@acme.it")
        self.assertEqual(t.args[-1], f"{server.SITE_URL}/r/job1?token={server._make_token('job1')}")


if __name__ == "__main__":
    unittest.main()
