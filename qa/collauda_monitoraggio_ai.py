# -*- coding: utf-8 -*-
"""Le sei schermate del monitoraggio AI e le loro azioni, sui dati veri.

⚠️ SCRIVE IN PRODUZIONE, in modo reversibile: approva le domande di prova,
aggiunge e toglie una domanda e un concorrente, spegne e riaccende il
monitoraggio di un progetto, salva la chiave di un provider (se
CHIAVE_CIFRATURA e OPENAI_API_KEY sono nell'ambiente). Tutto viene rimesso
com'era, tranne le approvazioni — che sono il motivo per cui esiste la scheda.

Con `--giro` fa anche due fette da 25 secondi di un giro vero (spende qualche
centesimo): prova che il giro e' ripartibile e che la seconda fetta salta
quello che la prima ha gia' fatto.

    python qa/collauda_monitoraggio_ai.py [--giro] [--visivo]
"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_dati
import ai_giro
import db
import server
from fastapi.testclient import TestClient

fall = []


def controlla(voce, ok, nota=""):
    print(f"   {'ok ' if ok else 'NO '} {voce}" + (f"\n        {nota}" if nota else ""))
    if not ok:
        fall.append(voce)


progetti = db._sb_progetti_tutti()
prog = next(p for p in progetti if (p.get("domain") or "") == "amahorse.com")
PID = prog["id"]
altro = next(p for p in progetti if p["id"] != PID and (p.get("domain") or "")
             and not db._sb_ai_ha_dati(p["id"]))
PID2 = altro["id"]

# lo stesso utente e' proprietario del progetto E del team: cosi' un solo
# TestClient copre le schede cliente e il pannello
UTENTE = {"id": prog["user_id"], "email": "qa@verticalai.it", "app_metadata": {"role": "admin"}}
server._current_user = lambda req: (UTENTE, None)
c = TestClient(server.app)
print(f"progetto con dati: {prog['domain']} · progetto in attesa: {altro['domain']}\n")

# ── 1. i tre stati ─────────────────────────────────────────────────────────
print("I tre stati delle schede cliente")
controlla("amahorse ha dati", ai_dati.stato(PID) == "dati")
controlla(f"{altro['domain']} e' in attesa", ai_dati.stato(PID2) == "in_attesa")
h = c.get(f"/project/{PID2}?tab=ai-visibility").text
controlla("in attesa: la scheda lo dice", "In attesa dei primi dati" in h)
controlla("in attesa: nessun numero finto", "gauge-score" not in h)

db._sb_ai_impostazioni_salva(PID2, {"is_active": False})
try:
    controlla("spento: lo stato lo vede", ai_dati.stato(PID2) == "non_attivo")
    h = c.get(f"/project/{PID2}?tab=competitors").text
    controlla("spento: la scheda rimanda a VerticalAI", "Contatta VerticalAI" in h)
    controlla("spento: niente self-service", "chip-aggiungi" not in h)
finally:
    db._sb_ai_impostazioni_salva(PID2, {"is_active": True})
controlla("riacceso", ai_dati.stato(PID2) == "in_attesa")

# ── 2. le quattro schede con i dati ────────────────────────────────────────
print("\nLe quattro schede di amahorse")
h = c.get(f"/project/{PID}?tab=ai-visibility").text
v = ai_dati.visibilita(PID)
controlla("AI Visibility: il punteggio e' quello vero",
          f'gauge-score">{v["punteggio"]}<' in h, f"punteggio {v['punteggio']}")
controlla("quattro motori, non tre", all(n in h for n in ("ChatGPT", "Gemini", "Perplexity", "Claude")))
# ⚠️ Un motore senza chiave configurata non deve comparire a 0%: zero si legge
# «non ti cita mai», mentre la verita' e' «non gli abbiamo chiesto niente».
import ai_schermate as _sch
_finti = [{"provider": "openai", "nome": "ChatGPT", "colore": "#10A37F", "percentuale": 30,
           "risposte": 10, "citati": 3, "interrogato": True},
          {"provider": "gemini", "nome": "Gemini", "colore": "#4285F4", "percentuale": 0,
           "risposte": 0, "citati": 0, "interrogato": False}]
_h = _sch.tab_ai_visibility({"domain": "prova.it"}, {
    "punteggio": 30, "delta": None, "trend": [], "motori": _finti, "argomenti": [],
    "risposte": 10, "motori_interrogati": 1, "motori_totali": 4, "domande_contate": None})
controlla("un motore senza chiave dice «non interrogato», non 0%",
          "non interrogato" in _h and 'area-fill" style="--w:0%' not in _h)
controlla("e la nota non promette quattro assistenti quando ce n'e' uno",
          "di 1 assistente su 4" in _h and "dei quattro assistenti" not in _h)
controlla("nessun residuo di Google AI Overview/Mode", "AI Overview" not in h and "AI Mode" not in h)
controlla("la legenda competitor e' bloccata col lucchetto", "Confronto competitor" in h and "not-allowed" in h)
controlla("gli argomenti sono quelli veri", v["argomenti"][0]["nome"] in h)
# ⚠️ trovato dagli screenshot: con `width:` inline le barre uscivano tutte
# piene, anche a 0%. Il CSS del design system legge la variabile --w.
controlla("le barre per motore hanno la larghezza del valore",
          all(f'--w:{m["percentuale"]}%' in h for m in v["motori"]) and 'area-fill" style="width' not in h)

h = c.get(f"/project/{PID}?tab=prompts").text
pq = ai_dati.prompt_e_argomenti(PID)
controlla("Prompts: il toggle argomenti/prompt coi conteggi",
          f'data-vista="argomenti">Argomenti <span class="issue-count">{pq["n_argomenti"]}' in h)
controlla("il chevron al posto di «Monitora»", 'class="chev"' in h and "Monitora →" not in h)
controlla("il dettaglio espandibile con la risposta", "Risposta di" in h)
controlla("il cliente non modifica le domande", "data-elimina" not in h and "data-modifica" not in h)

h = c.get(f"/project/{PID}?tab=competitors").text
co = ai_dati.concorrenti(PID, "amahorse.com")
controlla("Competitors: i chip con la provenienza", 'class="filter-chip"' in h and ">AI<" in h)
controlla("il sito del cliente e' il primo", co["righe"][0]["tuo"])
controlla("l'insight e' scritto sui numeri", co["insight"][0] in h)
controlla("il campo per aggiungere", 'id="nuovo-competitor"' in h)
controlla("il bottone × per togliere non usa una classe che lo nasconde",
          "data-rimuovi=" in h and 'class="row-action" data-rimuovi' not in h)

h = c.get(f"/project/{PID}?tab=citations").text
ci = ai_dati.citazioni(PID)
controlla("Citations: i quattro KPI", h.count('class="kpi"') == 4)
controlla("gli argomenti al posto delle «fonti terze» (Francesco, 8/9)",
          "Argomenti di discussione" in h and "Fonti terze" not in h)
controlla("nessun URL di redirect di Google fra le pagine", "grounding-api-redirect" not in h)

# ── 3. il resto del prodotto sa che non e' piu' «coming soon» ──────────────
print("\nNiente piu' «coming soon»")
h = c.get(f"/project/{PID}?tab=overview").text
controlla("overview: nessuna card coming soon", "Coming soon" not in h)
controlla("overview: la card AI Visibility col punteggio", f'section-stat-num">{v["punteggio"]}<' in h)
controlla("sidebar: nessun badge SOON", "nav-soon" not in h)

# ── 4. il pannello admin: configurazione AI ────────────────────────────────
print("\nAdmin · Configurazione AI")
r = c.get("/admin/ai")
controlla("la pagina si apre", r.status_code == 200, f"HTTP {r.status_code}")
h = r.text
controlla("quattro provider", all(n in h for n in ("OpenAI", "Anthropic", "Google", "Perplexity")))
controlla("la voce nel menu", 'href="/admin/ai"' in h and "Configurazione AI" in h)
r = c.post("/admin/ai/chiave", json={"provider": "openai", "chiave": "sk-chiave-finta-123"})
controlla("una chiave sbagliata NON si salva", r.status_code == 400, f"HTTP {r.status_code}: {r.text[:80]}")
r = c.post("/admin/ai/chiave", json={"provider": "inventato", "chiave": "x"})
controlla("un provider inventato viene rifiutato", r.status_code == 400)
import ai_chiavi
vera = os.environ.get("OPENAI_API_KEY", "")
if ai_chiavi.configurata() and vera:
    r = c.post("/admin/ai/chiave", json={"provider": "openai", "chiave": vera})
    controlla("la chiave vera si salva (e viene provata sul provider)", r.status_code == 200, r.text[:100])
    h = c.get("/admin/ai").text
    controlla("in pagina compare mascherata, mai intera", vera[-4:] in h and vera not in h)
    controlla("la lista modelli e' popolata", 'data-modello="openai"' in h and "gpt-" in h)
    r = c.post("/admin/ai/modello", json={"provider": "openai", "modello": "gpt-4o-mini"})
    controlla("il modello di default si sceglie", r.status_code == 200)
    conf = ai_giro.chiavi_configurate()
    controlla("il motore ora la legge dal pannello", conf["provenienza"].get("openai") == "pannello")
else:
    print("   -- salto il salvataggio della chiave: manca CHIAVE_CIFRATURA o OPENAI_API_KEY")

# ── 5. il pannello admin: monitoraggio per progetto ────────────────────────
print("\nAdmin · Monitoraggio AI per progetto")
r = c.get(f"/admin/progetti/{PID}/ai")
controlla("la pagina si apre", r.status_code == 200, f"HTTP {r.status_code}")
h = r.text
da_appr = len(db._sb_ai_domande_da_approvare(PID))
# ⚠️ si guarda il MARKUP (class="…"), non l'intera pagina: il commento nel CSS
# del template nomina proprio le classi da evitare, e faceva scattare il test
controlla("la pagina usa le classi dell'admin, non quelle del prodotto",
          'class="ai-card"' in h and 'class="card"' not in h and 'class="toggle-switch' not in h)
controlla("i moduli «aggiungi» partono nascosti senza display inline",
          'id="nuovo-prompt" hidden' in h and "display:flex" not in h.split('id="nuovo-prompt"')[1][:80])
controlla("il link dal dettaglio cliente", f'href="/admin/progetti/{PID}/ai"' in c.get(f"/admin/clienti/{prog['user_id']}").text)

# ⚠️ ripetibile: una domanda torna «da approvare» prima della prova, sennò dal
# secondo lancio in poi «approva tutte» non ha niente da fare e sembra rotto
import requests as _rq
from config import SUPABASE_URL as _U, SUPABASE_SVC as _K
_una = db._sb_ai_domande(PID)[0]["id"]
_rq.patch(f"{_U}/rest/v1/monitored_prompts", headers={"apikey": _K, "Authorization": f"Bearer {_K}"},
          params={"id": f"eq.{_una}"}, json={"approved": False}, timeout=15)
h = c.get(f"/admin/progetti/{PID}/ai").text
controlla("la domanda da approvare si vede con l'etichetta", "DA APPROVARE" in h and "Approva le 1 in attesa" in h)
r = c.post(f"/admin/progetti/{PID}/ai/prompt/approva", json={"tutte": True})
controlla("approva tutte", r.status_code == 200 and r.json().get("approvate", 0) >= 1, r.text[:80])
controlla("non resta niente da approvare", len(db._sb_ai_domande_da_approvare(PID)) == 0)
prima = len(db._sb_ai_domande(PID))
r = c.post(f"/admin/progetti/{PID}/ai/prompt/aggiungi",
           json={"argomento": "collaudo", "testo": "Domanda di collaudo, da togliere subito"})
controlla("aggiungi una domanda", r.status_code == 200, r.text[:80])
nuova = r.json().get("id")
controlla("una domanda del team nasce approvata",
          all(d.get("approved") for d in db._sb_ai_domande(PID) if d["id"] == nuova))
r = c.post(f"/admin/progetti/{PID}/ai/prompt/modifica", json={"id": nuova, "testo": "Domanda di collaudo modificata"})
controlla("modifica il testo", r.status_code == 200)
controlla("modificata diventa manuale",
          any(d["id"] == nuova and d.get("source") == "manual" and "modificata" in d["prompt_text"]
              for d in db._sb_ai_domande(PID)))
esecuzioni_prima = len(db._sb_ai_esecuzioni(PID, giorni=90))
r = c.post(f"/admin/progetti/{PID}/ai/prompt/elimina", json={"id": nuova})
controlla("elimina", r.status_code == 200)
controlla("eliminare disattiva, non cancella lo storico",
          len(db._sb_ai_domande(PID)) == prima
          and len(db._sb_ai_esecuzioni(PID, giorni=90)) == esecuzioni_prima)
h = c.get(f"/project/{PID}?tab=prompts").text
controlla("il cliente non vede la domanda disattivata", "Domanda di collaudo" not in h and "collaudo" not in h.split("vista-argomenti")[1][:3000])
# ⚠️ pulizia: la domanda di prova non ha storico, quindi si puo' cancellare
# davvero (e con lei l'argomento «collaudo», se resta vuoto)
_rq.delete(f"{_U}/rest/v1/monitored_prompts", headers={"apikey": _K, "Authorization": f"Bearer {_K}"},
           params={"id": f"eq.{nuova}"}, timeout=15)
for _a in db._sb_ai_argomenti(PID):
    if _a["name"] == "collaudo":
        _rq.delete(f"{_U}/rest/v1/monitored_topics", headers={"apikey": _K, "Authorization": f"Bearer {_K}"},
                   params={"id": f"eq.{_a['id']}"}, timeout=15)

r = c.post(f"/admin/progetti/{PID}/ai/competitor/aggiungi", json={"dominio": "https://www.collaudo-qa.it/pagina"})
controlla("aggiungi un concorrente (ripulendo l'URL)", r.status_code == 200
          and any(x["domain"] == "collaudo-qa.it" for x in db._sb_ai_concorrenti(PID)))
r = c.post(f"/admin/progetti/{PID}/ai/competitor/rimuovi", json={"dominio": "collaudo-qa.it"})
controlla("rimuovi = escluso, non cancellato", r.status_code == 200
          and any(x["domain"] == "collaudo-qa.it" and x["status"] == "excluded"
                  for x in db._sb_ai_concorrenti(PID, solo_attivi=False)))

imp = db._sb_ai_impostazioni(PID)
r = c.post(f"/admin/progetti/{PID}/ai/impostazioni", json={"campo": "schedule_frequency", "valore": "monthly"})
controlla("frequenza mensile", r.status_code == 200 and db._sb_ai_impostazioni(PID).get("schedule_frequency") == "monthly")
r = c.post(f"/admin/progetti/{PID}/ai/impostazioni", json={"campo": "schedule_frequency", "valore": "ogni-tanto"})
controlla("una frequenza inventata viene rifiutata", r.status_code == 400)
db._sb_ai_impostazioni_salva(PID, {"schedule_frequency": imp.get("schedule_frequency") or "weekly"})
ultimo = imp.get("last_run_at")
r = c.post(f"/admin/progetti/{PID}/ai/giro", json={})
controlla("«esegui adesso» mette in coda", r.status_code == 200 and db._sb_ai_impostazioni(PID).get("last_run_at") is None)
if ultimo:
    db._sb_ai_impostazioni_salva(PID, {"last_run_at": ultimo})

# ── 6. il cliente: i concorrenti sono l'unica azione ───────────────────────
print("\nCliente · concorrenti")
r = c.post(f"/project/{PID}/competitors/aggiungi", json={"dominio": "amahorse.com"})
controlla("il proprio sito viene rifiutato", r.status_code == 400)
r = c.post(f"/project/{PID}/competitors/aggiungi", json={"dominio": "cliente-qa.it"})
controlla("aggiunge con provenienza TU", r.status_code == 200
          and any(x["domain"] == "cliente-qa.it" and x["source"] == "client_added"
                  for x in db._sb_ai_concorrenti(PID)))
h = c.get(f"/project/{PID}?tab=competitors").text
controlla("e in pagina si vede col badge", "cliente-qa.it" in h and ">TU<" in h)
r = c.post(f"/project/{PID}/competitors/rimuovi", json={"dominio": "cliente-qa.it"})
controlla("e si toglie", r.status_code == 200)
# un altro utente non puo' toccare questo progetto
server._current_user = lambda req: ({"id": "qualcun-altro", "email": "x@y.it", "app_metadata": {}}, None)
r = c.post(f"/project/{PID}/competitors/aggiungi", json={"dominio": "intruso.it"})
controlla("un altro cliente non puo' aggiungere", r.status_code == 404)
r = c.get(f"/admin/progetti/{PID}/ai")
controlla("e non vede il pannello (404, non 403)", r.status_code == 404)
server._current_user = lambda req: (UTENTE, None)

# ── 6b. il cron non deve restare fermo ─────────────────────────────────────
print("\nIl cron del monitoraggio")
_segreto = server._CRON_SECRET
server._CRON_SECRET = ""
try:
    # ⚠️ Il controllo che conta: il cron NON deve mai tornare «nessuna_domanda».
    # Fino al 22/09 lo faceva — usciva sul primo progetto della coda, e siccome
    # 27 progetti su 28 non avevano domande non e' partito niente per una
    # settimana, senza lasciare una riga da nessuna parte.
    r = c.get("/api/cron-ai")
    e = r.json()
    controlla("un passaggio del cron non torna «nessuna_domanda»",
              e.get("esito") != "nessuna_domanda", str(e)[:120])
    controlla("e fa qualcosa di sensato",
              e.get("esito") in ("domande_generate", "completato", "parziale",
                                 "niente_da_fare", "nessuna_chiave"), str(e)[:120])
finally:
    server._CRON_SECRET = _segreto

# un progetto senza audit non riceve domande: il generatore indovinerebbe il
# mercato dal nome del dominio, che e' l'errore di amahorse
_senza_audit = next((p for p in progetti
                     if not db._sb_audits_by_project(p["id"], limit=1)
                     and not db._sb_ai_domande(p["id"])), None)
if _senza_audit:
    n_prima = len(db._sb_ai_domande(_senza_audit["id"]))
    ai_giro.prepara_progetto(_senza_audit["id"], _senza_audit.get("domain") or "",
                             "", ai_giro.chiavi_configurate()["chiavi"])
    controlla("senza audit non si generano domande",
              len(db._sb_ai_domande(_senza_audit["id"])) == n_prima,
              _senza_audit.get("domain"))
else:
    print("   -- nessun progetto senza audit: salto")

# ── 7. due fette di un giro vero ───────────────────────────────────────────
if "--giro" in sys.argv:
    print("\nIl giro a fette (spende)")
    conf = ai_giro.chiavi_configurate()
    controlla("ci sono chiavi", bool(conf["chiavi"]), str(conf["provenienza"]))
    e1 = ai_giro.esegui_giro(PID, "amahorse.com", conf["chiavi"], budget_secondi=25,
                             sentiment=False, modelli=conf["modelli"])
    print(f"      fetta 1: {e1['esito']}, {e1['eseguite']} risposte, {e1.get('saltate', 0)} saltate")
    controlla("la prima fetta e' parziale", e1["esito"] == "parziale" and e1["eseguite"] >= 1)
    controlla("una fetta parziale NON scrive last_run_at",
              db._sb_ai_impostazioni(PID).get("last_run_at") in (None, ultimo))
    e2 = ai_giro.esegui_giro(PID, "amahorse.com", conf["chiavi"], budget_secondi=25,
                             sentiment=False, modelli=conf["modelli"])
    print(f"      fetta 2: {e2['esito']}, {e2['eseguite']} risposte, {e2.get('saltate', 0)} saltate")
    controlla("la seconda fetta salta quello che la prima ha fatto", e2.get("saltate", 0) >= e1["eseguite"])
    controlla("le due fette hanno lo stesso batch_id", e1["batch_id"] == e2["batch_id"])

# ── 8. l'aspetto ───────────────────────────────────────────────────────────
if "--visivo" in sys.argv:
    print("\nL'aspetto: due temi, due larghezze")
    import uvicorn
    from playwright.async_api import async_playwright
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from controlla_pagine import CONTRASTO
    PORTA, BASE = 8124, "http://127.0.0.1:8124"
    OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_schermate")
    os.makedirs(OUT, exist_ok=True)
    threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORTA,
                                                log_level="error"), daemon=True).start()
    time.sleep(2)
    PAGINE = {
        "ai-config": "/admin/ai",
        "ai-progetto": f"/admin/progetti/{PID}/ai",
        "ai-visibility": f"/project/{PID}?tab=ai-visibility",
        "ai-prompts": f"/project/{PID}?tab=prompts",
        "ai-competitors": f"/project/{PID}?tab=competitors",
        "ai-citations": f"/project/{PID}?tab=citations",
        "ai-in-attesa": f"/project/{PID2}?tab=ai-visibility",
    }

    async def visivo():
        problemi = []
        async with async_playwright() as p:
            b = await p.chromium.launch()
            for nome, url in PAGINE.items():
                for tema in ("light", "dark"):
                    for larghezza in (1280, 390):
                        pg = await b.new_page(viewport={"width": larghezza, "height": 900})
                        err = []
                        pg.on("pageerror", lambda e: err.append(str(e)))
                        pg.on("console", lambda m: err.append(m.text) if m.type == "error" else None)
                        await pg.add_init_script(f"try{{localStorage.setItem('geo-theme','{tema}')}}catch(e){{}}")
                        await pg.goto(BASE + url, timeout=60000)
                        await pg.wait_for_timeout(600)
                        scarsi = await pg.evaluate(CONTRASTO)
                        if scarsi:
                            problemi.append(f"{nome} · {tema} @{larghezza}: CONTRASTO {scarsi}")
                        sbordo = await pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                        if sbordo > 2:
                            problemi.append(f"{nome} · {tema} @{larghezza}: sborda di {sbordo}px")
                        reali = [e for e in err if "favicon" not in e.lower()]
                        if reali:
                            problemi.append(f"{nome} · {tema} @{larghezza}: console {reali[:2]}")
                        if tema == "light" or larghezza == 390:
                            await pg.screenshot(path=os.path.join(OUT, f"{nome}-{tema}-{larghezza}.png"), full_page=True)
                        await pg.close()
            # il chevron apre davvero il dettaglio
            pg = await b.new_page(viewport={"width": 1280, "height": 900})
            await pg.goto(BASE + PAGINE["ai-prompts"], timeout=60000)
            await pg.click(".riga-apri")
            await pg.wait_for_timeout(200)
            aperto = await pg.evaluate("() => !document.querySelector('.riga-apri').nextElementSibling.hidden")
            if not aperto:
                problemi.append("prompts: il click sulla riga non apre il dettaglio")
            await pg.close()
            await b.close()
        return problemi

    problemi = asyncio.run(visivo())
    for pr in problemi:
        print("   NO", pr)
    controlla("nessun problema visivo", not problemi)
    print(f"   schermate in qa/_schermate/ai-*.png")

print(f"\n{'TUTTO OK' if not fall else str(len(fall)) + ' PROBLEMI'}")
for f in fall:
    print("  -", f)
sys.exit(1 if fall else 0)
