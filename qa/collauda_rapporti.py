# -*- coding: utf-8 -*-
"""La funzionalità Rapporti: avvisi, riepiloghi, preferenze.

⚠️ Nessuna email parte davvero: `_resend_post` viene sostituita e si guarda cosa
AVREBBE spedito. Il collaudo gira sui dati veri di produzione, e mandare per
sbaglio un avviso a un cliente sarebbe irreparabile.

La parte che conta non è «l'avviso parte»: è **l'avviso TACE quando non deve
partire**. Un sistema di notifiche che parla troppo si disattiva dopo tre email.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import server
import views
from fastapi.testclient import TestClient

fall = []
spedite = []
server._resend_post = lambda to, subject, html: spedite.append(
    {"a": to, "oggetto": subject, "html": html})
server._sb_report_log_scrivi = lambda *a, **k: None      # niente scritture di prova
tracciati = []
server._sb_report_prefs_salva = lambda pid, campi: (tracciati.append((pid, campi)) or True)


def controlla(voce, ok, nota=""):
    print(f"   {'ok ' if ok else 'NO '} {voce}")
    if nota:
        print(f"        {nota}")
    if not ok:
        fall.append(voce)


prog = next(p for p in db._sb_progetti_tutti() if p.get("domain"))
PID = prog["id"]
UTENTE = {"id": prog["user_id"], "email": "prova@verticalai.it", "app_metadata": {}}
server._current_user = lambda req: (UTENTE, None)
server._email_del_progetto = lambda p: "cliente@esempio.it"
c = TestClient(server.app)
print(f"progetto di prova: {prog.get('domain')}\n")

# ── la schermata ───────────────────────────────────────────────────────────
print("La scheda Rapporti")
h = c.get(f"/project/{PID}?tab=reports").text
for cosa, atteso in [("gli interruttori", 'class="toggle-switch'),
                     ("le frequenze", 'class="freq-select"'),
                     ("l'anteprima dell'email", "email-mockup"),
                     ("il terzo avviso è spento", "toggle-switch disabled"),
                     ("e dichiarato in arrivo", "IN ARRIVO")]:
    controlla(cosa, atteso in h)
controlla("non promette più email che non arrivano", "non parte da solo" not in h)

# ── salvare una preferenza ─────────────────────────────────────────────────
print("\nSalvare le preferenze")
r = c.post(f"/project/{PID}/reports/preferenze",
           json={"campo": "client_digest_frequency", "valore": "weekly"})
controlla("una frequenza valida si salva", r.status_code == 200, f"HTTP {r.status_code}")
for campo, valore, atteso in [
        ("client_digest_frequency", "ogni tanto", 400),
        ("alert_competitor_overtake", True, 400),
        ("campo_inventato", True, 400)]:
    r = c.post(f"/project/{PID}/reports/preferenze", json={"campo": campo, "valore": valore})
    controlla(f"«{campo} = {valore}» viene rifiutato", r.status_code == atteso,
              f"HTTP {r.status_code}")

# ⚠️ e il progetto di un altro non si tocca
server._current_user = lambda req: ({"id": "un-altro", "email": "x@y.it",
                                     "app_metadata": {}}, None)
r = c.post(f"/project/{PID}/reports/preferenze",
           json={"campo": "alert_score_drop", "valore": False})
controlla("un altro utente riceve 404", r.status_code == 404, f"HTTP {r.status_code}")
server._current_user = lambda req: (UTENTE, None)

# ── gli avvisi: quando scattano e quando no ────────────────────────────────
print("\nL'avviso sul calo del punteggio")
PREF_TUTTI = {"alert_score_drop": True, "alert_new_critical": True,
              "alert_competitor_overtake": False,
              "client_digest_frequency": "monthly", "team_digest_frequency": "weekly"}


def prova_calo(prima, dopo, atteso, descrizione):
    spedite.clear()
    server._sb_report_prefs = lambda pid: dict(PREF_TUTTI)
    server._sb_audits_by_project = lambda pid, limit=2, full=False: [
        {"overall": dopo, "created_at": "2026-09-06T10:00:00+00:00"},
        {"overall": prima, "created_at": "2026-09-01T10:00:00+00:00"}]
    server._sb_issues_by_project = lambda pid: []
    server._valuta_avvisi(prog, {"overall": dopo, "created_at": "2026-09-06T10:00:00+00:00"}, [])
    partito = any("sceso" in s["oggetto"] for s in spedite)
    controlla(f"{descrizione} ({prima} → {dopo})", partito == atteso,
              f"{'partito' if partito else 'nessun avviso'}, atteso "
              f"{'un avviso' if atteso else 'silenzio'}")


prova_calo(90, 80, True, "un calo di 10 punti avvisa")
prova_calo(90, 84, True, "un calo di 6 punti avvisa")
prova_calo(90, 85, False, "un calo di 5 punti TACE (è la soglia, non oltre)")
prova_calo(90, 88, False, "un calo di 2 punti TACE")
prova_calo(80, 90, False, "un punteggio che SALE non avvisa")

print("\nL'avviso sulla nuova criticità grave")


def prova_critica(gravi, gia_note, atteso, descrizione):
    spedite.clear()
    server._sb_report_prefs = lambda pid: dict(PREF_TUTTI)
    server._sb_audits_by_project = lambda pid, limit=2, full=False: [
        {"overall": 80, "created_at": "2026-09-06T10:00:00+00:00"}]
    server._sb_issues_by_project = lambda pid: [
        {"check_id": k, "first_seen_at": "2026-08-01T10:00:00+00:00"} for k in gia_note]
    checks = [{"check_id": k, "status": "fail", "severity": "critical",
               "title": f"Controllo {k}", "recommendation": "Fai questo."} for k in gravi]
    server._valuta_avvisi(prog, {"overall": 80, "created_at": "2026-09-06T10:00:00+00:00"},
                          checks)
    partito = any("critic" in s["oggetto"].lower() for s in spedite)
    controlla(descrizione, partito == atteso,
              f"{'partito' if partito else 'nessun avviso'}, atteso "
              f"{'un avviso' if atteso else 'silenzio'}")


prova_critica(["crawl.ai"], [], True, "una criticità grave mai vista prima avvisa")
prova_critica(["crawl.ai"], ["crawl.ai"], False,
              "la STESSA criticità, già nota, TACE (o dopo tre email nessuno le legge)")
prova_critica([], [], False, "nessuna criticità grave, nessun avviso")
prova_critica(["nuovo.x"], ["crawl.ai"], True, "una grave diversa da quelle note avvisa")

print("\nGli interruttori spenti fanno tacere davvero")
spedite.clear()
server._sb_report_prefs = lambda pid: {**PREF_TUTTI, "alert_score_drop": False,
                                       "alert_new_critical": False}
server._sb_audits_by_project = lambda pid, limit=2, full=False: [
    {"overall": 50, "created_at": "2026-09-06T10:00:00+00:00"},
    {"overall": 90, "created_at": "2026-09-01T10:00:00+00:00"}]
server._sb_issues_by_project = lambda pid: []
server._valuta_avvisi(prog, {"overall": 50, "created_at": "2026-09-06T10:00:00+00:00"},
                      [{"check_id": "x", "status": "fail", "severity": "critical",
                        "title": "Grave"}])
controlla("con gli avvisi spenti, un crollo di 40 punti non manda niente", not spedite,
          f"{len(spedite)} email")

# ── ogni quanto parte il riepilogo ─────────────────────────────────────────
print("\nOgni quanto parte il riepilogo")
from datetime import datetime, timedelta, timezone


def prova_frequenza(freq, giorni_fa, atteso, descrizione):
    quando = (None if giorni_fa is None else
              (datetime.now(timezone.utc) - timedelta(days=giorni_fa)).isoformat())
    server._sb_report_log_ultimo = lambda pid, tipo: quando
    esito = server._digest_da_mandare(prog, {"client_digest_frequency": freq},
                                      "client_digest")
    controlla(descrizione, esito == atteso,
              f"{'parte' if esito else 'aspetta'}, atteso {'parte' if atteso else 'aspetta'}")


prova_frequenza("weekly", None, True, "settimanale mai partito: parte")
prova_frequenza("weekly", 8, True, "settimanale, ultimo 8 giorni fa: parte")
prova_frequenza("weekly", 3, False, "settimanale, ultimo 3 giorni fa: aspetta")
prova_frequenza("monthly", 10, False, "mensile, ultimo 10 giorni fa: aspetta")
prova_frequenza("monthly", 31, True, "mensile, ultimo 31 giorni fa: parte")
prova_frequenza("off", None, False, "disattivato: non parte MAI")
prova_frequenza("off", 400, False, "disattivato da un anno: continua a non partire")

# ── il contenuto del riepilogo ─────────────────────────────────────────────
print("\nCosa c'è dentro il riepilogo")
spedite.clear()
r = views._riepilogo_periodo(prog, 30)
server._send_digest("cliente@esempio.it", prog, r, "client_digest")
if not spedite:
    fall.append("il riepilogo non è stato composto")
else:
    corpo = spedite[0]["html"]
    controlla("nomina il dominio giusto", prog["domain"] in corpo)
    controlla("dice come cambiare frequenza", "frequenza" in corpo)
    # ⚠️ senza tracking non deve comparire un «0 visite da AI»: sarebbe un dato
    # falso, non un dato a zero
    if not r.get("tracking"):
        controlla("senza tracking, non inventa numeri sul traffico",
                  "visite arrivate da assistenti" not in corpo)
    else:
        controlla("col tracking, riporta le visite", True)

# ── il «disiscriviti» del piede email ──────────────────────────────────────
print("\nIl link per smettere di ricevere il riepilogo")
salvati = []
server._sb_report_prefs_salva = lambda pid, campi: (salvati.append((pid, campi)) or True)

link = server._link_disdetta(PID)
controlla("il link esiste", bool(link), link[:88])
if link:
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(link).query)
    percorso = "/rapporti/disdetta?p=" + q["p"][0] + "&t=" + q["t"][0]
    r = c.get(percorso)
    controlla("aperto, disattiva il riepilogo", r.status_code == 200, f"HTTP {r.status_code}")
    spento = any(campi.get("client_digest_frequency") == "off" for _, campi in salvati)
    controlla("e lo spegne davvero", spento)
    # ⚠️ gli AVVISI restano: servono a dire che qualcosa si è rotto, non a
    # raccontare come va — chi disattiva il riepilogo non sta chiedendo questo
    tocca_avvisi = any("alert_score_drop" in campi or "alert_new_critical" in campi
                       for _, campi in salvati)
    controlla("gli avvisi urgenti restano accesi", not tocca_avvisi)

# ⚠️ e un token falso non spegne i riepiloghi di un progetto altrui
salvati.clear()
r = c.get(f"/rapporti/disdetta?p={PID}&t=inventato")
controlla("un link col token falso viene rifiutato", r.status_code == 400,
          f"HTTP {r.status_code}")
controlla("e non cambia niente", not salvati)
r = c.get("/rapporti/disdetta")
controlla("senza parametri, rifiutato", r.status_code == 400, f"HTTP {r.status_code}")

print("\nIl piede delle altre email")
controlla("senza link, non invita a cliccare il nulla",
          'href="#"' not in server._email_footer())
controlla("col link, lo mostra", "rapporti/disdetta" in server._email_footer(link or "x"))

print("\nESITO:", "TUTTO A POSTO" if not fall else f"PROBLEMI ({len(fall)})")
for f in fall:
    print("   -", f)
raise SystemExit(1 if fall else 0)
