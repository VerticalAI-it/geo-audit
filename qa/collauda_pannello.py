# -*- coding: utf-8 -*-
"""Le otto schermate si aprono davvero, e le cinque cose nuove ci sono.

⚠️ Importare `server` non prova niente: `roadmap_nomi()` mancante sarebbe
passato lo stesso e sarebbe esploso solo aprendo la pagina. Qui le pagine si
aprono per davvero, con dati veri.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server
from fastapi.testclient import TestClient

TEAM = {"id": "u-team", "email": "team@verticalai.it", "app_metadata": {"role": "admin"}}
server._current_user = lambda req: (TEAM, None)
server._sb_admin_traccia = lambda *a, **k: True
c = TestClient(server.app)

fall = []

PAGINE = [
    ("Overview", "/admin"),
    ("Overview 7 giorni", "/admin?giorni=7"),
    ("Overview 90 giorni", "/admin?giorni=90"),
    ("Overview valore assurdo", "/admin?giorni=99999"),
    ("Lead", "/admin/lead"),
    ("Clienti", "/admin/clienti"),
    ("Job log", "/admin/job-log"),
    ("Tracking", "/admin/tracking"),
    ("Interesse", "/admin/interesse"),
    ("Log azioni", "/admin/log"),
]
print("── le pagine si aprono")
pagine = {}
for nome, url in PAGINE:
    r = c.get(url)
    pagine[nome] = r.text
    ok = r.status_code == 200
    print(f"   {'ok ' if ok else 'NO '} {nome:<24} HTTP {r.status_code}")
    if not ok:
        fall.append(f"{nome}: HTTP {r.status_code} — {r.text[:200]}")

if fall:
    print("\nESITO: PROBLEMI")
    for f in fall:
        print("   -", f)
    raise SystemExit(1)

# ── le cinque cose che dovevamo fare ────────────────────────────────────────
print("\n── 1. modulo «Aggiungi cliente» (§4.3)")
h = pagine["Clienti"]
for cosa, atteso in [("il bottone che lo apre", 'data-apri="agg-cliente"'),
                     ("il modulo", 'id="agg-cliente"'),
                     ("il campo email", 'name="email"'),
                     ("la scelta se avvisare", 'name="avvisa"'),
                     ("la route giusta", '/admin/clienti/aggiungi')]:
    ok = atteso in h
    print(f"   {'ok ' if ok else 'NO '} {cosa}")
    if not ok:
        fall.append(f"aggiungi cliente: manca {cosa}")

print("\n── 2. rilancio in blocco (§4.5)")
h = pagine["Job log"]
import db, admin
aperti = admin.falliti_da_rilanciare(db._sb_audits_recenti(limit=200))
print(f"   fallimenti ancora aperti nei dati veri: {len(aperti)}")
if len(aperti) > 1:
    ok = "/admin/job/rilancia-tutti" in h
    print(f"   {'ok ' if ok else 'NO '} il bottone compare")
    if not ok:
        fall.append("rilancio in blocco: bottone assente con più di un fallito")
else:
    ok = "/admin/job/rilancia-tutti" not in h
    print(f"   {'ok ' if ok else 'NO '} con {len(aperti)} da rifare il bottone NON compare "
          "(il bottone di riga basta)")
    if not ok:
        fall.append("rilancio in blocco: compare anche quando non serve")

print("\n── 3. durata nel Job log (§4.5)")
ok = "<th>Durata</th>" in h
print(f"   {'ok ' if ok else 'NO '} la colonna c'è")
if not ok:
    fall.append("manca la colonna Durata")
# ⚠️ e non deve dire «0s» sui vecchi falliti, dove l'inizio non era registrato
finti = [{"created_at": "2026-09-01T10:00:00+00:00", "completed_at": "2026-09-01T10:00:00+00:00"},
         {"created_at": "2026-09-01T10:00:00+00:00", "completed_at": "2026-09-01T10:01:30+00:00"},
         {"created_at": "2026-09-01T10:00:00+00:00", "completed_at": None}]
attesi = ["—", "1m 30s", "—"]
for f, atteso in zip(finti, attesi):
    got = admin._durata(f)
    ok = got == atteso
    print(f"   {'ok ' if ok else 'NO '} durata {got!r} (atteso {atteso!r})")
    if not ok:
        fall.append(f"durata sbagliata: {got!r} invece di {atteso!r}")

print("\n── 4. interesse commerciale: tutte e tre le fonti (§4.7)")
h = pagine["Interesse"]
for cosa, atteso in [("richieste dal report", "Richieste"),
                     ("iscrizioni roadmap", "Iscrizioni Roadmap"),
                     ("voti per funzionalità", "Voti per funzionalit")]:
    presente = atteso in h
    print(f"   {'ok ' if presente else '·  '} {cosa}: {'mostrata' if presente else 'assente (nessun dato)'}")
# le sezioni vuote non si disegnano: si verifica che il codice le sappia fare
finto = admin.schermata_interesse(
    [], {}, set(),
    voti={"visibilita-ai": 7, "prompt": 3},
    iscrizioni=[{"email": "tizio@esempio.it", "feature": "prompt",
                 "created_at": "2026-09-01T10:00:00+00:00"}],
    nomi_feature={"visibilita-ai": "AI Visibility", "prompt": "Prompt e argomenti"})
for cosa, atteso in [("il nome leggibile, non la chiave", "AI Visibility"),
                     ("la barra proporzionale", "vote-bar-fill"),
                     ("la funzionalità più votata in cima", "pi&ugrave; votata"),
                     ("le iscrizioni", "tizio@esempio.it")]:
    ok = atteso in finto
    print(f"   {'ok ' if ok else 'NO '} {cosa}")
    if not ok:
        fall.append(f"interesse: manca {cosa}")
ok = "visibilita-ai" not in finto
print(f"   {'ok ' if ok else 'NO '} la chiave tecnica non si vede")
if not ok:
    fall.append("interesse: si vede la chiave tecnica invece del nome")

print("\n── 4-bis. il numero in cima non contraddice la tabella sotto")
finto2 = admin.schermata_interesse(
    [{"id": "r1", "email": "gia@cliente.it", "audit_id": "a1", "domain": "x.it",
      "created_at": "2026-09-01T10:00:00+00:00", "status": None}],
    {"a1": {"id": "a1", "source": "manual"}},
    {"gia@cliente.it"})
ok = "da contattare" not in finto2.split("Iscrizioni")[0]
print(f"   {'ok ' if ok else 'NO '} chi è già cliente non risulta «da contattare»")
if not ok:
    fall.append("il KPI conta come da contattare chi è già cliente")

print("\n── 5. Overview completa (§4.1)")
h = pagine["Overview"]
for cosa, atteso in [("KPI punteggio medio", "Punteggio medio portfolio"),
                     ("KPI audit falliti", "Audit falliti (30gg)"),
                     ("le card «Richiede attenzione»", "attention-grid"),
                     ("il grafico nel tempo", "Salute del portfolio nel tempo"),
                     ("la scelta del periodo", "range-toggle"),
                     ("l'attività recente", "Attivit")]:
    ok = atteso in h
    print(f"   {'ok ' if ok else 'NO '} {cosa}")
    if not ok:
        fall.append(f"overview: manca {cosa}")

# ⚠️ il periodo assurdo non deve essere accettato
ok = 'href="/admin?giorni=30"><span class="active"' in pagine["Overview valore assurdo"]
print(f"   {'ok ' if ok else 'NO '} «?giorni=99999» ricade su 30")
if not ok:
    fall.append("overview: un periodo fuori scala non viene riportato a 30")

# ⚠️ e la linea dei fallimenti non deve essere disegnata prima che li tracciassimo
print("\n── il grafico non inventa il periodo cieco")
from datetime import datetime, timezone, timedelta
def giorni_fa(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


# un periodo che comincia PRIMA del 3 settembre, con fallimenti veri dopo
con_falliti = admin._grafico_portfolio(
    [{"created_at": giorni_fa(60), "overall": 70, "status": "done"},
     {"created_at": giorni_fa(59), "overall": 72, "status": "done"},
     {"created_at": giorni_fa(1), "overall": 80, "status": "done"},
     {"created_at": giorni_fa(1), "status": "failed", "error": "timeout"},
     {"created_at": giorni_fa(0), "status": "failed", "error": "dns"}], 90)
ok = "3 settembre 2026" in con_falliti
print(f"   {'ok ' if ok else 'NO '} con la linea dei fallimenti, dichiara da quando parte")
if not ok:
    fall.append("il grafico non dichiara il periodo cieco quando disegna i fallimenti")

# ⚠️ e la nota NON deve comparire quando quella linea non c'è: spiegherebbe
# qualcosa di invisibile
g = admin._grafico_portfolio(
    [{"created_at": giorni_fa(60), "overall": 70, "status": "done"},
     {"created_at": giorni_fa(59), "overall": 72, "status": "done"}], 90)
ok = "3 settembre 2026" not in g
print(f"   {'ok ' if ok else 'NO '} senza fallimenti, non spiega una linea che non c'è")
if not ok:
    fall.append("la nota compare anche senza la linea che spiega")
ok = "state-critical" not in g.split("trend-legend")[0]
print(f"   {'ok ' if ok else 'NO '} non disegna fallimenti dove non li registravamo")
if not ok:
    fall.append("il grafico disegna la linea dei fallimenti nel periodo cieco")

# ── il controllo del ruolo vale anche sulle route nuove ────────────────────
print("\n── un cliente non può usare le route nuove")
server._current_user = lambda req: ({"id": "u-cli", "email": "c@x.it", "app_metadata": {}}, None)
for nome, url, corpo in [("aggiungi cliente", "/admin/clienti/aggiungi", {"email": "x@y.it"}),
                         ("rilancia tutti", "/admin/job/rilancia-tutti", {})]:
    r = c.post(url, json=corpo)
    ok = r.status_code == 404
    print(f"   {'ok ' if ok else 'NO '} {nome:<20} HTTP {r.status_code} (atteso 404)")
    if not ok:
        fall.append(f"{nome}: un cliente riceve {r.status_code}")

# ── e l'email storta viene rifiutata ──────────────────────────────────────
print("\n── email non valide rifiutate")
server._current_user = lambda req: (TEAM, None)
for storta in ["", "senzachiocciola", "tizio@", "@dominio.it", "tizio@dominio"]:
    r = c.post("/admin/clienti/aggiungi", json={"email": storta})
    ok = r.status_code == 400
    print(f"   {'ok ' if ok else 'NO '} {storta or '(vuota)':<18} HTTP {r.status_code}")
    if not ok:
        fall.append(f"email {storta!r} accettata (HTTP {r.status_code})")

print("\nESITO:", "TUTTO A POSTO" if not fall else "PROBLEMI")
for f in fall:
    print("   -", f)
raise SystemExit(1 if fall else 0)
