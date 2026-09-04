# -*- coding: utf-8 -*-
"""Il rilancio in blocco: compare quando serve, e rilancia esattamente quelli.

⚠️ In produzione i fallimenti aperti sono zero, quindi il caso «il bottone
compare» non era verificato da niente. Qui se ne creano tre veri, si prova, e si
cancellano — con la verifica finale che non ne resti nessuno.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests as rq
import server, admin, db
from config import SUPABASE_URL, SUPABASE_SVC
from fastapi.testclient import TestClient

H = {"apikey": SUPABASE_SVC, "Authorization": f"Bearer {SUPABASE_SVC}",
     "Content-Type": "application/json"}
TEAM = {"id": "u-team", "email": "team@verticalai.it", "app_metadata": {"role": "admin"}}
server._current_user = lambda req: (TEAM, None)
server._sb_admin_traccia = lambda *a, **k: True

partiti = []


async def _finto(audit_id, url, project_id, user_id):
    partiti.append(url)


server._rilancia_audit = _finto
c = TestClient(server.app)
fall, da_pulire = [], []

# ── tre fallimenti veri ─────────────────────────────────────────────────────
progetti = [p for p in db._sb_progetti_tutti() if p.get("domain")][:3]
print(f"creo {len(progetti)} fallimenti di prova")
for p in progetti:
    db._sb_audit_fallito(f"https://{p['domain']}", "PROVA CLAUDE — rilancio in blocco",
                         project_id=p["id"], user_id=p.get("user_id"), origine="auto")
time.sleep(2)

righe = rq.get(f"{SUPABASE_URL}/rest/v1/audits", headers=H, timeout=20,
               params={"error": "like.PROVA CLAUDE*", "select": "id,url,domain",
                       "order": "created_at.desc"}).json()
da_pulire = [r["id"] for r in righe]
print(f"   creati: {len(da_pulire)}\n")

try:
    # ── 1. il bottone compare, e dice il numero giusto ──────────────────────
    print("[1] il bottone")
    audit = db._sb_audits_recenti(limit=200)
    aperti = admin.falliti_da_rilanciare(audit)
    h = admin.schermata_job(audit)
    ok = "/admin/job/rilancia-tutti" in h
    print(f"   {'ok ' if ok else 'NO '} compare con {len(aperti)} fallimenti aperti")
    if not ok:
        fall.append("il bottone non compare")
    atteso = f"Rilancia tutti e {len(aperti)}"
    ok = atteso in h
    print(f"   {'ok ' if ok else 'NO '} dice «{atteso}»")
    if not ok:
        fall.append(f"il bottone non dice il numero giusto ({atteso})")

    # ── 2. rilancia esattamente quelli, non altri ───────────────────────────
    print("\n[2] il rilancio")
    r = c.post("/admin/job/rilancia-tutti", json={})
    esito = r.json()
    print(f"   HTTP {r.status_code} · {esito}")
    ok = r.status_code == 200 and esito.get("quanti") == len(aperti)
    print(f"   {'ok ' if ok else 'NO '} ne ha accodati {len(partiti)}, attesi {len(aperti)}")
    if not ok:
        fall.append(f"accodati {len(partiti)} invece di {len(aperti)}")
    attesi = {a["url"] for a in aperti}
    ok = set(partiti) == attesi
    print(f"   {'ok ' if ok else 'NO '} sono esattamente i siti falliti")
    if not ok:
        fall.append(f"siti sbagliati: {set(partiti) ^ attesi}")

    # ── 3. il numero sul bottone e quello della route coincidono ────────────
    print("\n[3] bottone e server dicono lo stesso numero")
    ok = esito.get("quanti") == len(aperti) == h.count("data-azione=\"/admin/job/rilancia\"") + 0 or True
    quanti_riga = h.count('data-azione="/admin/job/rilancia"')
    ok = quanti_riga == len(aperti)
    print(f"   {'ok ' if ok else 'NO '} {quanti_riga} bottoni di riga, {len(aperti)} nel blocco")
    if not ok:
        fall.append(f"i bottoni di riga ({quanti_riga}) non corrispondono al blocco ({len(aperti)})")

    # ── 4. a vuoto non fa danni ─────────────────────────────────────────────
    print("\n[4] quando non c'è niente da rifare")
    vero = db._sb_audits_recenti
    db._sb_audits_recenti = lambda **k: []
    server._sb_audits_recenti = lambda **k: []
    prima = len(partiti)
    r = c.post("/admin/job/rilancia-tutti", json={})
    ok = r.status_code == 200 and r.json().get("quanti") == 0 and len(partiti) == prima
    print(f"   {'ok ' if ok else 'NO '} risponde {r.json()} e non accoda niente")
    if not ok:
        fall.append("il rilancio a vuoto accoda comunque qualcosa")
    db._sb_audits_recenti = vero
    server._sb_audits_recenti = vero

finally:
    # ── pulizia ─────────────────────────────────────────────────────────────
    for rid in da_pulire:
        rq.delete(f"{SUPABASE_URL}/rest/v1/audits", headers=H,
                  params={"id": f"eq.{rid}"}, timeout=15)
    resta = rq.get(f"{SUPABASE_URL}/rest/v1/audits", headers=H, timeout=15,
                   params={"error": "like.PROVA CLAUDE*", "select": "id"}).json()
    print(f"\n   righe di prova cancellate · residui: {len(resta)}")
    if resta:
        fall.append(f"{len(resta)} righe di prova rimaste in produzione")

print("\nESITO:", "TUTTO A POSTO" if not fall else "PROBLEMI")
for f in fall:
    print("   -", f)
raise SystemExit(1 if fall else 0)
