# -*- coding: utf-8 -*-
"""I numeri delle schermate del monitoraggio AI, calcolati dai dati salvati.

Le quattro schede cliente (AI Visibility, Prompts & Queries, Competitors,
Citations) e la scheda admin per progetto leggono tutte da qui. Le funzioni
tornano dizionari gia' pronti da rendere: le schermate non fanno conti.

⚠️ Tutto si calcola sulle risposte **riuscite** (`status = completed`): un
motore che non ha risposto non e' un motore che non ha citato. E' la stessa
regola di `ai_giro.aggrega`, ripetuta qui perche' vale per ogni numero.
"""
from __future__ import annotations

from collections import defaultdict

from db import (_sb_ai_argomenti, _sb_ai_citazioni, _sb_ai_concorrenti, _sb_ai_domande,
                _sb_ai_esecuzioni, _sb_ai_ha_dati, _sb_ai_impostazioni, _sb_ai_snapshot)

PROVIDER_NOME = {"openai": "ChatGPT", "anthropic": "Claude",
                 "gemini": "Gemini", "perplexity": "Perplexity"}
PROVIDER_COLORE = {"openai": "#10A37F", "anthropic": "#D97757",
                   "gemini": "#4285F4", "perplexity": "#20808D"}
_ORDINE_PROVIDER = ("openai", "gemini", "perplexity", "anthropic")


# ── Lo stato della scheda ───────────────────────────────────────────────────

def stato(project_id: str) -> str:
    """`non_attivo` · `in_attesa` · `dati`.

    Sono i tre stati del documento (§4.1). La condizione fra «in attesa» e
    «dati» era da confermare col team: e' **almeno una risposta completata**,
    non semplicemente tentata — un giro fallito per intero lascia il cliente
    in attesa, non davanti a una dashboard vuota.
    """
    imp = _sb_ai_impostazioni(project_id)
    if imp and imp.get("is_active") is False:
        return "non_attivo"
    return "dati" if _sb_ai_ha_dati(project_id) else "in_attesa"


# ── La base comune a tutte le schede ────────────────────────────────────────

def _base(project_id: str, giorni: int = 30) -> dict:
    """Carica una volta sola cio' che serve a ogni scheda."""
    esecuzioni = [e for e in _sb_ai_esecuzioni(project_id, giorni=giorni)
                  if e.get("status") == "completed"]
    citazioni = _sb_ai_citazioni(project_id, giorni=giorni)
    domande = _sb_ai_domande(project_id, solo_attive=False)
    argomenti = {a["id"]: a["name"] for a in _sb_ai_argomenti(project_id)}
    per_run = {e["id"]: e for e in esecuzioni}
    domanda_di = {d["id"]: d for d in domande}
    run_citati = {c["prompt_run_id"] for c in citazioni if c.get("is_target")}
    return {"esecuzioni": esecuzioni, "citazioni": citazioni, "domande": domande,
            "argomenti": argomenti, "per_run": per_run, "domanda_di": domanda_di,
            "run_citati": run_citati}


def _pct(n: int, d: int) -> int:
    return round(n * 100 / d) if d else 0


# ── AI Visibility ───────────────────────────────────────────────────────────

def visibilita(project_id: str, giorni: int = 30) -> dict:
    b = _base(project_id, giorni)
    foto = _sb_ai_snapshot(project_id, limit=8)

    # Il punteggio e' quello dell'ultima fotografia (Decisione 5: mai calcolo
    # live). Se non c'e' ancora nessuna fotografia ma ci sono risposte, si
    # calcola una volta e la si salva, cosi' dalla prossima visita c'e'.
    punteggio = None
    if foto and foto[0].get("visibility_score") is not None:
        punteggio = round(float(foto[0]["visibility_score"]))
    elif b["esecuzioni"]:
        from ai_giro import aggrega
        ris = aggrega(project_id, giorni=giorni)
        if ris.get("punteggio") is not None:
            punteggio = round(ris["punteggio"])
            foto = _sb_ai_snapshot(project_id, limit=8)

    # per motore: percentuale di risposte in cui il sito compare
    per_provider = {}
    for e in b["esecuzioni"]:
        p = e.get("provider") or "?"
        c = per_provider.setdefault(p, {"risposte": 0, "citati": 0})
        c["risposte"] += 1
        c["citati"] += 1 if e["id"] in b["run_citati"] else 0
    motori = []
    for p in _ORDINE_PROVIDER:
        c = per_provider.get(p, {"risposte": 0, "citati": 0})
        motori.append({"provider": p, "nome": PROVIDER_NOME[p], "colore": PROVIDER_COLORE[p],
                       "percentuale": _pct(c["citati"], c["risposte"]),
                       "risposte": c["risposte"], "citati": c["citati"]})

    # per argomento
    per_topic = defaultdict(lambda: {"risposte": 0, "citati": 0})
    for e in b["esecuzioni"]:
        d = b["domanda_di"].get(e.get("prompt_id"))
        if not d:
            continue
        t = per_topic[d.get("topic_id")]
        t["risposte"] += 1
        t["citati"] += 1 if e["id"] in b["run_citati"] else 0
    argomenti = sorted(
        ({"nome": b["argomenti"].get(tid, "?"), "percentuale": _pct(c["citati"], c["risposte"]),
          "risposte": c["risposte"]} for tid, c in per_topic.items()),
        key=lambda x: -x["percentuale"])

    # il trend: dalle fotografie, dalla piu' vecchia alla piu' recente
    trend = [{"quando": (f.get("period_end") or "")[:10],
              "valore": round(float(f["visibility_score"]))}
             for f in reversed(foto) if f.get("visibility_score") is not None]
    delta = None
    if foto and foto[0].get("delta_vs_previous") is not None:
        delta = round(float(foto[0]["delta_vs_previous"]), 1)

    return {"punteggio": punteggio, "delta": delta, "trend": trend, "motori": motori,
            "argomenti": argomenti, "risposte": len(b["esecuzioni"]),
            "domande_contate": (foto[0].get("prompts_counted") if foto else None)}


def fascia(punteggio: int | None) -> tuple[str, str]:
    """Etichetta e classe di colore del punteggio, con le soglie del design system."""
    if punteggio is None:
        return "Nessun dato", "neutral"
    if punteggio >= 75:
        return "Visibilità alta", "good"
    if punteggio >= 50:
        return "Visibilità media", "warn"
    return "Visibilità bassa", "critical"


# ── Prompts & Queries ───────────────────────────────────────────────────────

def prompt_e_argomenti(project_id: str, giorni: int = 30) -> dict:
    b = _base(project_id, giorni)

    # citazioni del sito per risposta
    citati_per_run = defaultdict(int)
    for c in b["citazioni"]:
        if c.get("is_target"):
            citati_per_run[c["prompt_run_id"]] += 1

    per_domanda = defaultdict(lambda: {"risposte": 0, "citati": 0, "menzioni": 0,
                                       "esempio": None})
    for e in b["esecuzioni"]:
        pid = e.get("prompt_id")
        if not pid:
            continue
        r = per_domanda[pid]
        r["risposte"] += 1
        if e["id"] in b["run_citati"]:
            r["citati"] += 1
            r["menzioni"] += citati_per_run.get(e["id"], 0)
            # l'esempio mostrato e' una risposta in cui il sito COMPARE, se
            # ce n'e' una: e' quella che dice qualcosa al cliente
            if r["esempio"] is None or not r["esempio"].get("citato"):
                r["esempio"] = {"provider": e.get("provider"), "citato": True,
                                "testo": (e.get("response_text") or "")[:900]}
        elif r["esempio"] is None:
            r["esempio"] = {"provider": e.get("provider"), "citato": False,
                            "testo": (e.get("response_text") or "")[:900]}

    righe_prompt = []
    for d in b["domande"]:
        # ⚠️ Le domande disattivate restano nel database per lo storico, ma
        # per il cliente non esistono: contarle gonfiava il numero dei prompt
        # e faceva comparire argomenti vuoti (trovato con le domande di prova
        # del collaudo, che erano state tolte ma comparivano lo stesso).
        if d.get("active") is False:
            continue
        r = per_domanda.get(d["id"], {"risposte": 0, "citati": 0, "menzioni": 0, "esempio": None})
        righe_prompt.append({
            "id": d["id"], "testo": d["prompt_text"], "intent": d.get("intent") or "",
            "argomento": b["argomenti"].get(d.get("topic_id"), ""),
            "topic_id": d.get("topic_id"), "fonte": d.get("source") or "auto_generated",
            "approvata": d.get("approved"), "attiva": d.get("active", True),
            "percentuale": _pct(r["citati"], r["risposte"]),
            # «Volume AI» = quante risposte sono state analizzate su questa
            # domanda nel periodo. Francesco (8/9): il KPI va ponderato per il
            # numero di domande fatte, e questo e' il denominatore reso visibile.
            "volume": r["risposte"], "menzioni": r["menzioni"], "esempio": r["esempio"],
        })

    # per argomento
    per_topic = defaultdict(lambda: {"risposte": 0, "citati": 0, "menzioni": 0,
                                     "intent": defaultdict(int), "domande": 0})
    for rp in righe_prompt:
        t = per_topic[rp["topic_id"]]
        t["domande"] += 1
        t["risposte"] += rp["volume"]
        t["menzioni"] += rp["menzioni"]
        t["intent"][rp["intent"] or "?"] += 1
    for d in b["domande"]:
        pass
    # i citati per topic si contano sulle esecuzioni, non sommando percentuali
    citati_topic = defaultdict(int)
    for e in b["esecuzioni"]:
        d = b["domanda_di"].get(e.get("prompt_id"))
        if d and e["id"] in b["run_citati"]:
            citati_topic[d.get("topic_id")] += 1

    righe_argomenti = sorted(
        ({"topic_id": tid, "nome": b["argomenti"].get(tid, "?"), "domande": t["domande"],
          "percentuale": _pct(citati_topic.get(tid, 0), t["risposte"]),
          "menzioni": t["menzioni"], "volume": t["risposte"],
          "intent": dict(t["intent"])}
         for tid, t in per_topic.items()),
        key=lambda x: -x["percentuale"])

    return {"argomenti": righe_argomenti, "prompt": righe_prompt,
            "n_argomenti": len(righe_argomenti), "n_prompt": len(righe_prompt),
            "da_approvare": len([p for p in righe_prompt if p["approvata"] is False])}


# ── Competitors ─────────────────────────────────────────────────────────────

def concorrenti(project_id: str, dominio: str, giorni: int = 30) -> dict:
    b = _base(project_id, giorni)
    lista = _sb_ai_concorrenti(project_id)
    domini = {c["domain"]: c for c in lista}
    n_risposte = len(b["esecuzioni"]) or 1

    # in quante risposte DIVERSE compare ogni dominio (non quante volte)
    risposte_per_dominio = defaultdict(set)
    sentiment_per_dominio = defaultdict(list)
    for c in b["citazioni"]:
        d = (c.get("cited_domain") or "").lower()
        if c["prompt_run_id"] not in b["per_run"]:
            continue
        risposte_per_dominio[d].add(c["prompt_run_id"])
        if c.get("sentiment"):
            sentiment_per_dominio[d].append(c["sentiment"])

    def _sent(d):
        v = sentiment_per_dominio.get(d) or []
        if not v:
            return ""
        pos = v.count("positive") + v.count("positivo")
        neg = v.count("negative") + v.count("negativo")
        return "positivo" if pos > neg else ("negativo" if neg > pos else "neutro")

    # Share of voice: risposte in cui compare / risposte totali. Il sito del
    # cliente e' la prima riga, sempre, cosi' si legge il confronto.
    righe = [{"dominio": dominio, "tuo": True, "fonte": "",
              "sov": _pct(len(b["run_citati"]), n_risposte),
              "menzioni": len(b["run_citati"]), "sentiment": _sent(dominio.lower())}]
    for c in lista:
        d = c["domain"]
        n = len(risposte_per_dominio.get(d, ()))
        righe.append({"dominio": d, "tuo": False, "fonte": c.get("source") or "",
                      "sov": _pct(n, n_risposte), "menzioni": n, "sentiment": _sent(d)})
    righe[1:] = sorted(righe[1:], key=lambda r: -r["sov"])

    # l'insight: chi e' davanti e di quanto
    insight = []
    davanti = [r for r in righe[1:] if r["sov"] > righe[0]["sov"]]
    if davanti:
        primo = davanti[0]
        volte = round(primo["sov"] / righe[0]["sov"], 1) if righe[0]["sov"] else None
        insight.append(
            f"{primo['dominio']} viene citato "
            + (f"{volte} volte più spesso" if volte and volte > 1 else "più spesso")
            + f" di {dominio} sulle stesse domande.")
    dietro = [r for r in righe[1:] if r["sov"] < righe[0]["sov"]]
    if dietro:
        insight.append(f"{dominio} è davanti a {len(dietro)} concorrenti su "
                       f"{len(righe) - 1} monitorati.")
    if not righe[1:]:
        insight.append("Nessun concorrente in elenco: si popola da solo al primo giro, "
                       "e si può integrare a mano.")

    return {"righe": righe, "insight": insight, "risposte": len(b["esecuzioni"]),
            "n_concorrenti": len(lista)}


# ── Citations ───────────────────────────────────────────────────────────────

def citazioni(project_id: str, giorni: int = 30) -> dict:
    b = _base(project_id, giorni)
    dirette = [c for c in b["citazioni"]
               if c.get("is_target") and c["prompt_run_id"] in b["per_run"]]

    # per pagina: quante volte e da quali motori
    per_url = defaultdict(lambda: {"n": 0, "motori": set()})
    for c in dirette:
        url = c.get("cited_url") or ""
        # il percorso, non l'intero indirizzo: e' quello che il cliente riconosce
        from urllib.parse import urlsplit
        try:
            p = urlsplit(url).path or "/"
        except Exception:
            p = url
        r = per_url[p]
        r["n"] += 1
        e = b["per_run"].get(c["prompt_run_id"]) or {}
        if e.get("provider"):
            r["motori"].add(PROVIDER_NOME.get(e["provider"], e["provider"]))
    pagine = sorted(({"pagina": u, "n": r["n"], "motori": sorted(r["motori"])}
                     for u, r in per_url.items()), key=lambda x: -x["n"])

    # sentiment medio sulle citazioni del sito
    voti = [c.get("sentiment") for c in dirette if c.get("sentiment")]
    pos = sum(1 for v in voti if v in ("positive", "positivo"))
    neg = sum(1 for v in voti if v in ("negative", "negativo"))
    sentiment = ("positivo" if pos > neg else "negativo" if neg > pos else "neutro") if voti else ""

    # Gli argomenti di discussione al posto delle «fonti terze»: e' la
    # richiesta di Francesco dell'8 settembre — in questa fase non si
    # distingue chi parla del brand da chi parla del tema, si riportano i
    # temi su cui il sito viene citato e quelli su cui non compare mai.
    per_topic = defaultdict(lambda: {"risposte": 0, "citati": 0})
    for e in b["esecuzioni"]:
        d = b["domanda_di"].get(e.get("prompt_id"))
        if not d:
            continue
        t = per_topic[d.get("topic_id")]
        t["risposte"] += 1
        t["citati"] += 1 if e["id"] in b["run_citati"] else 0
    argomenti = sorted(
        ({"nome": b["argomenti"].get(tid, "?"), "citati": t["citati"],
          "risposte": t["risposte"], "percentuale": _pct(t["citati"], t["risposte"])}
         for tid, t in per_topic.items()),
        key=lambda x: (-x["citati"], -x["percentuale"]))

    return {"dirette": len(dirette), "pagine": pagine, "n_pagine": len(pagine),
            "risposte": len(b["esecuzioni"]), "sentiment": sentiment, "voti": len(voti),
            "argomenti": argomenti,
            "citate_in": len({c["prompt_run_id"] for c in dirette})}
