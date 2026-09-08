# -*- coding: utf-8 -*-
"""I quattro motori rispondono davvero, e le citazioni si leggono.

⚠️ Questo collaudo SPENDE: ogni giro è una chiamata a pagamento con ricerca web
su quattro provider. Si lancia quando si tocca `ai_monitor.py`, non a ogni
modifica del prodotto.

Le chiavi arrivano dall'ambiente (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, `PERPLEXITY_API_KEY`): non si scrivono qui e non si leggono
da un file del repo.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_monitor

CHIAVI = {
    "openai": os.environ.get("OPENAI_API_KEY", ""),
    "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
    "gemini": os.environ.get("GEMINI_API_KEY", ""),
    "perplexity": os.environ.get("PERPLEXITY_API_KEY", ""),
}

# Una domanda vera, del tipo che farebbe un cliente di quel sito.
DOMANDA = sys.argv[1] if len(sys.argv) > 1 else (
    "Quali sono i migliori produttori italiani di sottosella e accessori "
    "per l'equitazione? Indica i siti dove si possono trovare.")
SITO = sys.argv[2] if len(sys.argv) > 2 else "acavallo.com"

print(f"domanda: {DOMANDA}")
print(f"sito da cercare nelle risposte: {SITO}\n")

fall = []
for provider, chiave in CHIAVI.items():
    nome = ai_monitor.PROVIDER[provider]["nome"]
    if not chiave:
        print(f"  ·   {nome:<12} nessuna chiave: saltato")
        continue

    t0 = time.time()
    try:
        r = ai_monitor.interroga(provider, DOMANDA, chiave)
    except ai_monitor.ErroreProvider as e:
        print(f"  NO  {nome:<12} {e}"[:150])
        fall.append(f"{nome}: {e}"[:200])
        continue

    citazioni = ai_monitor.leggi_citazioni(r, SITO)
    citato = any(c["e_il_cliente"] for c in citazioni)
    durata = time.time() - t0

    print(f"  ok  {nome:<12} {len(r['testo']):>5} caratteri · "
          f"{len(citazioni):>2} citazioni · {durata:>4.0f}s · "
          f"{'CITA il sito' if citato else 'non lo cita'}")
    for c in citazioni[:5]:
        segno = "→" if c["e_il_cliente"] else " "
        print(f"        {segno} {c['dominio']}")
    if not citazioni:
        # ⚠️ Zero citazioni può voler dire due cose: il motore non ha cercato,
        # oppure ha cercato e non ha citato nessuno. La prima è un difetto
        # nostro, la seconda è un dato — e vanno distinte.
        print("        ⚠️ nessuna citazione: il modello ha davvero cercato sul web?")
        fall.append(f"{nome}: zero citazioni, da capire se ha cercato")

print("\n── i modelli disponibili")
for provider, chiave in CHIAVI.items():
    if not chiave:
        continue
    modelli = ai_monitor.elenca_modelli(provider, chiave)
    sanno = [m for m in modelli if m["sa_cercare"]]
    print(f"  {ai_monitor.PROVIDER[provider]['nome']:<12} {len(modelli):>3} modelli, "
          f"{len(sanno):>3} sanno cercare sul web")
    if modelli and not sanno:
        fall.append(f"{provider}: nessun modello risulta capace di cercare")

print("\nESITO:", "TUTTO A POSTO" if not fall else f"DA GUARDARE ({len(fall)})")
for f in fall:
    print("   -", f)
raise SystemExit(1 if fall else 0)
