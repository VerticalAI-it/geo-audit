# -*- coding: utf-8 -*-
"""Un giro di monitoraggio vero su un progetto: domande, esecuzione, punteggio.

⚠️ SPENDE e SCRIVE IN PRODUZIONE: genera le domande di un progetto vero, le
esegue sui quattro motori e salva risposte e citazioni. Si lancia di proposito,
su un progetto per volta, sapendo che costa qualche minuto e qualche centesimo.

    python qa/prova_giro_su_progetto.py [dominio] [--budget SECONDI]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_giro
import db

CHIAVI = {p: os.environ.get(v, "") for p, v in (
    ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"),
    ("gemini", "GEMINI_API_KEY"), ("perplexity", "PERPLEXITY_API_KEY"))}
if not any(CHIAVI.values()):
    raise SystemExit("nessuna chiave nell'ambiente: non c'è niente da interrogare")

argomenti = [a for a in sys.argv[1:] if not a.startswith("--")]
DOMINIO = argomenti[0] if argomenti else "amahorse.com"
BUDGET = 240
if "--budget" in sys.argv:
    BUDGET = int(sys.argv[sys.argv.index("--budget") + 1])

prog = next((p for p in db._sb_progetti_tutti()
             if (p.get("domain") or "").lower() == DOMINIO.lower()), None)
if not prog:
    raise SystemExit(f"progetto non trovato per {DOMINIO}")
PID = prog["id"]
print(f"progetto: {prog['domain']}\n")

# ── 1. le domande ──────────────────────────────────────────────────────────
print("[1] le domande da monitorare")
gia = db._sb_ai_domande(PID)
if gia:
    print(f"    ce ne sono già {len(gia)}: non ne genero altre")
else:
    t0 = time.time()
    quante = ai_giro.prepara_progetto(PID, prog["domain"], prog.get("sector") or "", CHIAVI)
    print(f"    generate {quante} domande in {time.time()-t0:.0f}s")
    gia = db._sb_ai_domande(PID)

for d in gia[:12]:
    print(f"      · [{d.get('argomento','?')[:22]:<22}] {d['prompt_text'][:74]}")

# ⚠️ il controllo che conta sulle domande: il nome del sito non deve comparire,
# o l'assistente lo citerebbe per forza e la misura non varrebbe niente
radice = prog["domain"].split(".")[0].replace("www", "").strip(".")
sporche = [d for d in gia if radice and radice.lower() in d["prompt_text"].lower()]
print(f"\n    {'NO ' if sporche else 'ok '} nessuna domanda nomina il sito "
      f"({len(sporche)} su {len(gia)})")

if not gia:
    raise SystemExit("nessuna domanda: il giro non può partire")

# ── 2. il giro ─────────────────────────────────────────────────────────────
print(f"\n[2] interrogo i motori (budget {BUDGET}s)")
imp = db._sb_ai_impostazioni(PID)
esito = ai_giro.esegui_giro(PID, prog["domain"], CHIAVI, budget_secondi=BUDGET,
                            sentiment=bool(imp.get("sentiment_enabled")))
print(f"    {esito['esito']}: {esito['eseguite']} risposte, "
      f"{esito['falliti']} fallite, {esito['citazioni']} citazioni, "
      f"{esito['secondi']}s")

# ── 3. il punteggio ────────────────────────────────────────────────────────
print("\n[3] il punteggio")
ris = ai_giro.aggrega(PID, giorni=30)
if ris["punteggio"] is None:
    print("    nessuna risposta riuscita: niente da calcolare")
else:
    print(f"    visibilità: {ris['punteggio']}% "
          f"({ris['citati']} risposte su {ris['risposte']} lo citano)")
    if ris.get("falliti"):
        print(f"    ⚠️ {ris['falliti']} esecuzioni fallite, escluse dal conto")
    for p, c in (ris.get("per_provider") or {}).items():
        print(f"      {p:<12} {c['percentuale']:>3}%  ({c['citati']}/{c['risposte']})")

# ── 4. cosa è finito nel database ──────────────────────────────────────────
print("\n[4] com'è rimasto il database")
cit = db._sb_ai_citazioni(PID, giorni=30)
per_cat = {}
for c in cit:
    per_cat[c.get("citation_category") or "?"] = per_cat.get(c.get("citation_category") or "?", 0) + 1
print(f"    citazioni salvate: {len(cit)}")
for k, v in sorted(per_cat.items(), key=lambda x: -x[1]):
    print(f"      {k:<26} {v}")
print(f"    il progetto ha dati: {db._sb_ai_ha_dati(PID)}")

domini = {}
for c in cit:
    if not c.get("is_target"):
        domini[c["cited_domain"]] = domini.get(c["cited_domain"], 0) + 1
print("\n    chi viene citato più spesso al posto nostro:")
for d, n in sorted(domini.items(), key=lambda x: -x[1])[:8]:
    print(f"      {n:>3} × {d}")
