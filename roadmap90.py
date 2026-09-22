# -*- coding: utf-8 -*-
"""7.2 · La roadmap a 90 giorni, ricavata dalle criticità aperte.

Tre fasi da trenta giorni, come chiede il piano:

  1. **Fondamenta** — accesso e infrastruttura: se un assistente non riesce a
     leggere il sito, tutto il resto non serve a niente.
  2. **Contenuto e autorevolezza** — quello che fa citare una pagina invece di
     un'altra, una volta che il sito è leggibile.
  3. **Rifinitura** — i segnali specifici degli assistenti e la misurazione.

⚠️ **L'ordine non è una gerarchia di gravità, è una gerarchia di dipendenze.**
Sistemare le FAQ su un sito che blocca GPTBot è lavoro sprecato: nessuno le
leggerà. Per questo `crawl.ai`, che è il check più grave del catalogo, sta in
fase 1 insieme a cose molto meno gravi ma altrettanto bloccanti.

⚠️ Non è un elenco ordinato per severità con sopra tre titoli: quella sarebbe
la scheda Criticità con un vestito diverso. Qui le voci si spostano di fase in
base a cosa sblocca cosa.
"""
from __future__ import annotations

# A quale fase appartiene ogni controllo. Chi non compare qui finisce in
# fase 2, che è il posto ragionevole per un problema di contenuto.
#
# ⚠️ Si ragiona per PREFISSO quando il check è nuovo e non ancora mappato:
# meglio una collocazione approssimata che lasciarlo fuori dalla roadmap.
_FASE = {
    # ── 1 · senza questo, il resto non viene letto ────────────────────────
    "crawl.ai": 1, "crawl.robots": 1, "crawl.https": 1, "crawl.sitemap": 1,
    "crawl.conflict": 1, "crawl.coverage": 1, "render.parity": 1,
    "page.status": 1, "page.noindex": 1, "meta.canonical": 1,
    "meta.canonical.consistency": 1,

    # ── 2 · cosa fa citare una pagina invece di un'altra ──────────────────
    "content.atomic": 2, "content.len": 2, "content.struct": 2, "content.q": 2,
    "content.hier": 2, "content.h1": 2, "content.tldr": 2, "content.hidden": 2,
    "content.sources": 2, "trust.author": 2, "trust.contact": 2,
    "sd.present": 2, "sd.valid": 2, "sd.highvalue": 2,

    # ── 3 · rifinitura e misurazione ──────────────────────────────────────
    "sd.sameas": 3, "sd.person": 3, "schema.datemodified": 3, "faq.answerlen": 3,
    "content.fresh": 3, "crawl.llms": 3, "meta.title": 3, "meta.description": 3,
    "meta.og": 3, "meta.twitter": 3, "meta.lang": 3, "trust.social": 3,
    "sem.html": 3, "perf.lcp": 3, "perf.cls": 3,
}

_PREFISSO = {"crawl": 1, "page": 1, "render": 1,
             "content": 2, "trust": 2, "sd": 2,
             "meta": 3, "perf": 3, "sem": 3, "schema": 3, "faq": 3}

FASI = (
    (1, "Giorni 1-30 · Fondamenta",
     "Rendere il sito leggibile dagli assistenti. Finché qui resta qualcosa "
     "aperto, il lavoro sul contenuto non produce effetti."),
    (2, "Giorni 31-60 · Contenuto e autorevolezza",
     "Rendere le pagine citabili: risposte autosufficienti, dati attribuiti, "
     "struttura estraibile."),
    (3, "Giorni 61-90 · Rifinitura e misurazione",
     "I segnali specifici degli assistenti, e mettersi in condizione di "
     "vedere se sta funzionando."),
)

_ORDINE_GRAVITA = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _fase_di(check_id: str) -> int:
    if check_id in _FASE:
        return _FASE[check_id]
    return _PREFISSO.get((check_id or "").split(".")[0], 2)


def costruisci(issues: list, rimedi: dict | None = None) -> list:
    """Le tre fasi, ognuna con le sue voci. Le criticità già risolte non
    entrano: la roadmap dice cosa fare, non cosa è stato fatto.

    `rimedi` mappa check_id -> testo del rimedio (da `_rimedi_per_check`).
    """
    rimedi = rimedi or {}
    aperte = [i for i in (issues or []) if i.get("status") == "open"]

    # Una voce per CHECK, non per occorrenza: «aggiungi la meta description»
    # ripetuto quattordici volte è un elenco, non un piano.
    per_check: dict = {}
    for i in aperte:
        cid = i.get("check_id") or "?"
        v = per_check.setdefault(cid, {
            "check_id": cid, "titolo": i.get("title") or cid,
            "categoria": i.get("category") or "", "gravita": i.get("severity") or "medium",
            "pagine": 0, "url": []})
        v["pagine"] += 1
        if i.get("url") and len(v["url"]) < 5:
            v["url"].append(i["url"])
        if _ORDINE_GRAVITA.get(i.get("severity"), 9) < _ORDINE_GRAVITA.get(v["gravita"], 9):
            v["gravita"] = i["severity"]

    for v in per_check.values():
        v["rimedio"] = rimedi.get(v["check_id"], "")
        v["fase"] = _fase_di(v["check_id"])

    fuori = []
    for numero, titolo, sottotitolo in FASI:
        voci = [v for v in per_check.values() if v["fase"] == numero]
        voci.sort(key=lambda v: (_ORDINE_GRAVITA.get(v["gravita"], 9), -v["pagine"]))
        fuori.append({"numero": numero, "titolo": titolo, "sottotitolo": sottotitolo,
                      "voci": voci,
                      "pagine_toccate": sum(v["pagine"] for v in voci)})
    return fuori


def quante_voci(fasi: list) -> int:
    return sum(len(f["voci"]) for f in fasi)
