# -*- coding: utf-8 -*-
"""Un giro di monitoraggio vero, per sapere quanto costa prima di costruirci sopra.

⚠️ SPENDE: N prompt × 4 provider chiamate a pagamento con ricerca web. Serve a
rispondere alle due domande che decidono se la funzionalità è sostenibile —
**quanto tempo ci mette** e **quanto costa** un giro su un progetto — prima di
scrivere il resto del sistema che li farà girare tutti a settimana.

Non scrive niente: le tabelle non esistono ancora (Fase F).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_monitor

CHIAVI = {p: os.environ.get(v, "") for p, v in (
    ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"),
    ("gemini", "GEMINI_API_KEY"), ("perplexity", "PERPLEXITY_API_KEY"))}

SITO = sys.argv[1] if len(sys.argv) > 1 else "amahorse.com"

# Il tipo di domande che il generatore automatico dovrà produrre: domande vere,
# di chi cerca — non «parlami di amahorse», che citerebbe il sito per forza.
PROMPT = [
    "Quali sono i migliori produttori italiani di sottosella e accessori "
    "per l'equitazione? Cita le fonti web.",
    "Dove posso comprare online sottosella di qualità per cavalli in Italia? "
    "Indica i siti.",
    "Che differenza c'è fra un sottosella in gel e uno in memory foam per "
    "l'equitazione? Cita le fonti.",
]

print(f"sito seguito: {SITO}")
print(f"{len(PROMPT)} domande × {len([c for c in CHIAVI.values() if c])} motori\n")

t_inizio = time.time()
righe, falliti = [], []
for i, prompt in enumerate(PROMPT, 1):
    print(f"[{i}/{len(PROMPT)}] {prompt[:64]}…")
    for provider, chiave in CHIAVI.items():
        if not chiave:
            continue
        nome = ai_monitor.PROVIDER[provider]["nome"]
        t0 = time.time()
        try:
            r = ai_monitor.interroga(provider, prompt, chiave)
        except ai_monitor.ErroreProvider as e:
            print(f"     NO  {nome:<11} {str(e)[:70]}")
            falliti.append(f"{nome} su «{prompt[:30]}…»")
            continue
        cit = ai_monitor.leggi_citazioni(r, SITO)
        citato = any(c["e_il_cliente"] for c in cit)
        righe.append({"provider": provider, "citazioni": len(cit), "citato": citato,
                      "secondi": time.time() - t0, "caratteri": len(r["testo"])})
        print(f"     ok  {nome:<11} {len(cit):>2} citazioni · "
              f"{time.time()-t0:>4.0f}s · {'CITATO' if citato else '—'}")

durata = time.time() - t_inizio
print(f"\n── il giro è costato {durata:.0f} secondi ({durata/60:.1f} minuti)")

if righe:
    visti = len([r for r in righe if r["citato"]])
    print(f"   il sito è stato citato in {visti} risposte su {len(righe)} "
          f"→ visibilità {visti * 100 // len(righe)}%")
    per_prov = {}
    for r in righe:
        per_prov.setdefault(r["provider"], []).append(r)
    print("\n   per motore:")
    for p, gruppo in per_prov.items():
        v = len([r for r in gruppo if r["citato"]])
        medio = sum(r["secondi"] for r in gruppo) / len(gruppo)
        print(f"      {ai_monitor.PROVIDER[p]['nome']:<12} citato {v}/{len(gruppo)} · "
              f"{medio:>4.0f}s a domanda")

    # ⚠️ Il conto che serve a Michele prima di dire sì: questo giro moltiplicato
    # per i prompt veri (almeno 10, dice il documento) e per i progetti.
    per_prompt = durata / len(PROMPT)
    print(f"\n   proiezione: {per_prompt:.0f}s a domanda su 4 motori")
    print(f"      10 domande su 1 progetto  → {per_prompt * 10 / 60:>5.1f} minuti")
    print(f"      10 domande su 27 progetti → {per_prompt * 10 * 27 / 3600:>5.1f} ore")
    print("      ⚠️ oltre il limite di durata di una function: il giro va spezzato,")
    print("         come già si fa per gli audit nel cron.")

if falliti:
    print(f"\n   non hanno risposto: {len(falliti)}")
    for f in falliti[:5]:
        print("      -", f)
