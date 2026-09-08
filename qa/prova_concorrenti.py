# -*- coding: utf-8 -*-
"""La scoperta automatica dei concorrenti, provata sui dati veri di un progetto.

⚠️ SCRIVE IN PRODUZIONE (elenco concorrenti e categorie delle citazioni), ma
non spende: lavora sulle citazioni gia' raccolte, non interroga i motori.

    python qa/prova_concorrenti.py [dominio]

Il controllo che conta e' il terzo: un concorrente ESCLUSO dal cliente non deve
tornare al giro dopo. `_sb_ai_concorrente_aggiungi` fonde sui duplicati e
rimette lo stato ad `active`, quindi e' un errore facile da fare e invisibile
finche' non se ne accorge il cliente.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_giro
import db

DOMINIO = sys.argv[1] if len(sys.argv) > 1 else "amahorse.com"

prog = next((p for p in db._sb_progetti_tutti()
             if (p.get("domain") or "").lower() == DOMINIO.lower()), None)
if not prog:
    raise SystemExit(f"progetto non trovato per {DOMINIO}")
PID = prog["id"]
print(f"progetto: {prog['domain']}\n")

# ── 1. chi propone ─────────────────────────────────────────────────────────
print("[1] i concorrenti proposti dalle risposte")
prima = db._sb_ai_concorrenti(PID, solo_attivi=False)
print(f"    in elenco prima: {len(prima)}")
proposti = ai_giro.scopri_concorrenti(PID, prog["domain"])
print(f"    proposti ora: {len(proposti)}")
for c in db._sb_ai_concorrenti(PID, solo_attivi=False):
    print(f"      · {c['domain']:<28} {c['source']:<14} {c['status']}")

# ── 2. le citazioni vecchie si adeguano ────────────────────────────────────
print("\n[2] le citazioni gia' salvate")
def conta():
    per = {}
    for c in db._sb_ai_citazioni(PID, giorni=30):
        k = c.get("citation_category") or "?"
        per[k] = per.get(k, 0) + 1
    return per

print(f"    prima: {conta()}")
corretti = ai_giro.riclassifica_citazioni(PID, prog["domain"])
dopo = conta()
print(f"    dopo:  {dopo}   ({corretti} domini corretti)")
print(f"    {'ok ' if dopo.get('competitor') else 'NO '} ci sono citazioni di concorrenti")

# ── 3. il caso negativo: un escluso non deve tornare ───────────────────────
print("\n[3] un concorrente escluso non torna")
attivi = db._sb_ai_concorrenti(PID)
if not attivi:
    print("    nessun concorrente attivo: non c'e' niente da escludere")
    raise SystemExit(0)

cavia = attivi[0]["domain"]
db._sb_ai_concorrente_escludi(PID, cavia)
stato = {c["domain"]: c["status"] for c in db._sb_ai_concorrenti(PID, solo_attivi=False)}
print(f"    escluso {cavia} -> {stato.get(cavia)}")

ai_giro.scopri_concorrenti(PID, prog["domain"])
stato = {c["domain"]: c["status"] for c in db._sb_ai_concorrenti(PID, solo_attivi=False)}
tornato = stato.get(cavia) == "active"
print(f"    dopo un altro giro di scoperta: {cavia} -> {stato.get(cavia)}")
print(f"    {'NO ' if tornato else 'ok '} l'esclusione {'e stata annullata' if tornato else 'ha retto'}")

# ⚠️ e la prova che il controllo sa ancora fallire: chiamando la funzione che
# aggiunge senza il filtro, il dominio DEVE tornare attivo. Se non torna, il
# controllo qui sopra non stava misurando niente.
db._sb_ai_concorrente_aggiungi(PID, cavia, "ai_suggested")
stato = {c["domain"]: c["status"] for c in db._sb_ai_concorrenti(PID, solo_attivi=False)}
risuscitato = stato.get(cavia) == "active"
print(f"    (controprova: aggiungendolo senza filtro -> {stato.get(cavia)}, "
      f"{'il rischio e reale' if risuscitato else 'ATTENZIONE: la prova non misura niente'})")

db._sb_ai_concorrente_escludi(PID, cavia)
print(f"    rimesso come era: {cavia} escluso")
