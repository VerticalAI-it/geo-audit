# -*- coding: utf-8 -*-
"""Super User (GEO-40): il team apre i progetti dei clienti in sola lettura e lavora senza limiti di piano.

⚠️ La deroga sta nel guardiano, non in una route: `_progetto_del_cliente(..., lettura_team=True)`.
Vale solo in GET e solo per chi ha `app_metadata.role = "admin"`; le scritture restano del proprietario.
"""
import ast
import io
import os
import unittest
from unittest import mock

import tests.conftest_env  # noqa: F401

from starlette.requests import Request

import server

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTE = {"id": "u-cliente", "email": "cliente@example.it"}
TEAM = {"id": "u-team", "email": "team@example.it", "app_metadata": {"role": "admin"}}
ESTRANEO = {"id": "u-altro", "email": "altro@example.it"}
PROGETTO = {"id": "p1", "user_id": "u-cliente", "domain": "cliente.example", "plan": "free"}


def richiesta(metodo="GET"):
    return Request({"type": "http", "method": metodo, "path": "/project/p1", "headers": [], "query_string": b""})


class Guardiano(unittest.TestCase):
    def chiedi(self, chi, metodo="GET", lettura_team=True):
        with mock.patch.object(server, "_current_user", lambda r: (chi, None)), \
             mock.patch.object(server, "_sb_project_get", lambda pid: dict(PROGETTO) if pid == "p1" else None):
            return server._progetto_del_cliente(richiesta(metodo), "p1", lettura_team=lettura_team)

    def test_il_team_legge_il_progetto_del_cliente(self):
        user, project, _r, stop = self.chiedi(TEAM)
        self.assertIsNone(stop)
        self.assertEqual((user["id"], project["id"]), ("u-team", "p1"))
        self.assertNotEqual(project["user_id"], user["id"], "chi chiama riconosce la vista del team da qui")

    def test_il_team_non_scrive(self):
        stop = self.chiedi(TEAM, metodo="POST")[3]
        self.assertEqual(stop.status_code, 404)

    def test_senza_lettura_team_resta_404(self):
        self.assertEqual(self.chiedi(TEAM, lettura_team=False)[3].status_code, 404)

    def test_chi_non_e_del_team_resta_404(self):
        self.assertEqual(self.chiedi(ESTRANEO)[3].status_code, 404)

    def test_il_proprietario_come_prima(self):
        self.assertIsNone(self.chiedi(CLIENTE, lettura_team=False)[3])

    def test_user_metadata_non_basta(self):
        finto = {"id": "u-furbo", "email": "x@example.it", "user_metadata": {"role": "admin"}}
        self.assertEqual(self.chiedi(finto)[3].status_code, 404)


class SoloInLettura(unittest.TestCase):
    def test_lettura_team_solo_su_route_get(self):
        """Una route POST col permesso del team aprirebbe le scritture: la si trova dal sorgente."""
        with io.open(os.path.join(RADICE, "server.py"), encoding="utf-8") as f:
            albero = ast.parse(f.read())
        trovate = []
        for nodo in albero.body:
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            usa = any(isinstance(k, ast.keyword) and k.arg == "lettura_team"
                      and isinstance(k.value, ast.Constant) and k.value.value is True
                      for k in ast.walk(nodo))
            if not usa:
                continue
            metodi = {d.func.attr for d in nodo.decorator_list
                      if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)}
            trovate.append(nodo.name)
            self.assertEqual(metodi, {"get"}, nodo.name)
        self.assertEqual(sorted(trovate), ["project_detail", "project_export_xlsx"])


class Fascia(unittest.TestCase):
    def test_fascia_dice_di_chi_e_e_riporta_alla_scheda(self):
        with mock.patch.object(server, "_sb_auth_get_user", lambda uid: {"email": "cliente@example.it"}):
            html = server._fascia_vista_team(PROGETTO)
        self.assertIn("sola lettura", html)
        self.assertIn("cliente@example.it", html)
        self.assertIn('href="/admin/clienti/u-cliente"', html)


if __name__ == "__main__":
    unittest.main()
