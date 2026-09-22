# -*- coding: utf-8 -*-
"""Nessuna route che tocca un progetto puo' saltare il controllo di proprieta'.

⚠️ Questo e' il test che chiude la classe di bug «nuova route esposta per
dimenticanza», e lo fa in un modo che nessuna astrazione puo' fare: **enumera
le route dal sorgente** e pretende che ognuna passi dal guardiano. Un helper
lo si puo' dimenticare; un elenco che si costruisce da solo, no.

Si legge il sorgente con `ast` invece di interrogare l'app perche' cosi' il
test gira senza credenziali e senza avviare niente — e perche' quello che
vogliamo controllare e' proprio il codice scritto, non il comportamento a
run time di una singola richiesta.
"""
import ast
import io
import os
import unittest

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sorgente() -> str:
    with io.open(os.path.join(RADICE, "server.py"), encoding="utf-8") as f:
        return f.read()

# Il guardiano del cliente e quello dell'admin. Una route che passa da uno dei
# due e' a posto: l'admin vede tutti i progetti per mestiere.
GUARDIANI = ("_progetto_del_cliente", "_cliente_ai_azione",
             "_admin_o_no", "_admin_ai_azione")

# ⚠️ Le uniche route con `{project_id}` che NON devono avere un proprietario.
# Ogni voce qui e' una deroga consapevole: se se ne aggiunge una, va scritto
# perche'.
DEROGHE = {
    # nessuna, oggi
}


def _route_con_progetto():
    """(metodo, percorso, nome della funzione, sorgente del corpo) per ogni
    route il cui percorso contiene `{project_id}`."""
    sorgente = _sorgente()
    albero = ast.parse(sorgente)
    righe = sorgente.splitlines()
    fuori = []
    for nodo in albero.body:
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in nodo.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if not (isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"):
                continue
            metodo = dec.func.attr
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            percorso = dec.args[0].value
            if "{project_id}" not in percorso:
                continue
            corpo = "\n".join(righe[nodo.lineno - 1:nodo.end_lineno])
            fuori.append((metodo.upper(), percorso, nodo.name, corpo))
    return fuori


class OgniRouteDiProgettoHaUnGuardiano(unittest.TestCase):

    def test_ne_troviamo_almeno_una_manciata(self):
        """Se l'analisi del sorgente si rompe, l'elenco diventa vuoto e tutti
        i test qui sotto passerebbero senza controllare niente."""
        self.assertGreaterEqual(len(_route_con_progetto()), 8)

    def test_nessuna_route_senza_controllo(self):
        scoperte = []
        for metodo, percorso, nome, corpo in _route_con_progetto():
            if percorso in DEROGHE:
                continue
            if not any(g in corpo for g in GUARDIANI):
                scoperte.append(f"{metodo} {percorso} ({nome})")
        self.assertFalse(scoperte, "route su progetto senza controllo di "
                                   "proprieta':\n  " + "\n  ".join(scoperte))

    def test_il_controllo_non_e_piu_copiato_a_mano(self):
        """Il confronto grezzo `project["user_id"] != user["id"]` deve esistere
        in UN posto solo: dentro il guardiano. Ogni altra occorrenza e' una
        copia che prima o poi divergera'."""
        sorgente = _sorgente()
        self.assertEqual(sorgente.count('user_id") != user["id"]'), 1)

    def test_a_un_progetto_altrui_si_risponde_404(self):
        """⚠️ Non 403: un 403 confermerebbe che quel progetto esiste.

        Si guardano gli `status_code` scritti nel CODICE, non il testo del
        file: «403» compare nel commento che spiega perché non si usa, e
        cercarlo nel sorgente faceva fallire il test sulla sua stessa
        spiegazione.
        """
        albero = ast.parse(_sorgente())
        guardiano = next(n for n in albero.body
                         if isinstance(n, ast.FunctionDef)
                         and n.name == "_progetto_del_cliente")
        stati = {k.value.value
                 for k in ast.walk(guardiano)
                 if isinstance(k, ast.keyword) and k.arg == "status_code"
                 and isinstance(k.value, ast.Constant)}
        self.assertIn(404, stati)
        self.assertNotIn(403, stati)
        self.assertIn(401, stati, "chi non è loggato deve avere un 401 o un redirect")


class OgniRouteAdminHaUnGuardiano(unittest.TestCase):

    def test_nessuna_route_admin_senza_controllo(self):
        """Il pannello mostra i dati di tutti i clienti: una route dimenticata
        li espone a chiunque conosca l'indirizzo."""
        sorgente = _sorgente()
        albero = ast.parse(sorgente)
        righe = sorgente.splitlines()
        scoperte = []
        for nodo in albero.body:
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in nodo.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                if not (isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"):
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                percorso = dec.args[0].value
                if not percorso.startswith("/admin"):
                    continue
                corpo = "\n".join(righe[nodo.lineno - 1:nodo.end_lineno])
                if not any(g in corpo for g in ("_admin_o_no", "_admin_ai_azione")):
                    scoperte.append(f"{dec.func.attr.upper()} {percorso} ({nodo.name})")
        self.assertFalse(scoperte, "route admin senza controllo di ruolo:\n  "
                         + "\n  ".join(scoperte))


if __name__ == "__main__":
    unittest.main()
