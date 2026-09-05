# -*- coding: utf-8 -*-
"""La Definition of Done del documento, voce per voce — comprese le due che
chiedono più di quanto avevo verificato: il logout su OGNI schermata, e i click
provati su ALMENO DUE progetti diversi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import server
from fastapi.testclient import TestClient

mancano = []
c = TestClient(server.app)


def esito(voce, ok, nota=""):
    print(f"   {'ok ' if ok else 'NO '} {voce}")
    if nota:
        print(f"        {nota}")
    if not ok:
        mancano.append(voce)


# due progetti diversi, come chiede la DoD
progetti = [p for p in db._sb_progetti_tutti()
            if db._sb_audits_by_project(p["id"], limit=1, full=False)][:2]
if len(progetti) < 2:
    raise SystemExit("servono due progetti con audit per rispettare la DoD")

UT = {"id": progetti[0]["user_id"], "email": "prova@verticalai.it", "app_metadata": {}}
server._current_user = lambda req: (UT, None)

print("DoD · BUG-02 — logout raggiungibile da OGNI schermata")
SCHERMATE = {
    "Dashboard": "/dashboard",
    "Nuova analisi": "/audit",
    "Pagina progetto": f"/project/{progetti[0]['id']}",
    "I miei report": "/miei-report",
    "Roadmap": "/roadmap",
}
for nome, url in SCHERMATE.items():
    r = c.get(url)
    if r.status_code != 200:
        esito(f"{nome}", False, f"HTTP {r.status_code}")
        continue
    esito(f"{nome}: c'è «Esci»", "/auth/logout" in r.text)

print("\nDoD · BUG-05/06/07a — click verificato su ALMENO DUE progetti")
for p in progetti:
    pid, dom = p["id"], p.get("domain", "?")
    pagine = c.get(f"/project/{pid}?tab=pages").text
    tech = c.get(f"/project/{pid}?tab=technical").text
    riep = c.get(f"/project/{pid}?tab=audit").text
    esito(f"{dom}: Pages porta alle criticità",
          "conta-link" in pagine and "tab=opportunities" in pagine)
    esito(f"{dom}: Technical ha i filtri", "kpi-filtro" in tech)
    esito(f"{dom}: Riepilogo ha i link", "conta-link" in riep)
    # e il link porta a una vista DAVVERO filtrata
    import re
    m = re.search(r'href="(/project/[^"]*tab=opportunities[^"]*)"', pagine)
    if m:
        dest = m.group(1).replace("&amp;", "&")
        r2 = c.get(dest)
        esito(f"{dom}: la vista filtrata si apre", r2.status_code == 200,
              dest[:96])
    else:
        esito(f"{dom}: la vista filtrata si apre", False, "nessun link trovato")

print("\nDoD · BUG-07b — «Mostra altro» non produce duplicati")
for p in progetti:
    u = db._sb_audits_by_project(p["id"], limit=1, full=True)
    azioni = (u[0] if u else {}).get("actions") or []
    h = c.get(f"/project/{p['id']}?tab=audit").text
    voci = h.count('class="interv-item')
    esito(f"{p.get('domain','?')}: {len(azioni)} interventi, {voci} voci in pagina",
          voci == len(azioni), "una voce per intervento, nessuna ripetuta")

print("\nDoD · BUG-08b — export in CSV e in formato Excel")
h = c.get(f"/project/{progetti[0]['id']}?tab=pages").text
esito("il CSV c'è ancora", 'id="pgCsv"' in h)
esito("e c'è anche l'Excel", "export.xlsx" in h)

print("\nESITO:", "la DoD è soddisfatta" if not mancano else f"MANCANO {len(mancano)} voci")
for m in mancano:
    print("   -", m)
raise SystemExit(1 if mancano else 0)
