# -*- coding: utf-8 -*-
"""6.3 · Lo stesso audit, pesato come lo peserebbe ciascun assistente.

I quattro motori non cercano le stesse cose. Perplexity guarda le date di
aggiornamento e i titoli descrittivi; Claude premia i testi lunghi e il tono
non iperbolico; ChatGPT si appoggia molto ai dati strutturati; Gemini è quello
che più dipende dall'HTML statico, perché il suo grounding non esegue il
JavaScript.

Da qui quattro sotto-punteggi: gli stessi controlli, pesi diversi.

⚠️ **Sono STIME, e il prodotto deve dirlo.** I moltiplicatori vengono dai
criteri che i quattro dichiarano e da quanto se ne osserva pubblicamente, non
da una misura nostra. Presentarli come misurati sarebbe la stessa bugia del
«ricerche su ChatGPT» quando il dato è un referral.

⚠️ Il modo per smettere di stimare esiste già: il monitoraggio raccoglie chi
cita chi, motore per motore. Con abbastanza giri si può confrontare il
punteggio stimato con la citazione reale e correggere i pesi sui fatti. Finché
quei dati non bastano, questi numeri restano un'ipotesi ragionata.
"""
from __future__ import annotations

MOTORI = ("openai", "anthropic", "gemini", "perplexity")
NOME = {"openai": "ChatGPT", "anthropic": "Claude",
        "gemini": "Gemini", "perplexity": "Perplexity"}

# Quanto ogni motore tiene a ciascun controllo, rispetto al peso di base.
# 1.0 = come nel punteggio generale. Chi non compare resta a 1.0.
MOLTIPLICATORI = {
    "openai": {
        # Si appoggia molto ai dati strutturati per capire di cosa parla una
        # pagina, e alle FAQ per le risposte brevi.
        "sd.present": 1.6, "sd.valid": 1.5, "sd.highvalue": 1.4,
        "faq.answerlen": 1.4, "content.q": 1.3,
        "content.len": 0.8,
    },
    "anthropic": {
        # Premia il testo esteso e argomentato, e la fonte dichiarata; è il
        # meno sensibile agli aspetti di marcatura.
        "content.len": 1.8, "content.sources": 1.6, "content.atomic": 1.4,
        "trust.author": 1.4, "sd.person": 1.3,
        "meta.og": 0.6, "meta.twitter": 0.5,
    },
    "gemini": {
        # Il grounding legge l'HTML che arriva, senza eseguire il JavaScript:
        # qui la parità statica pesa più che altrove.
        "render.parity": 2.0, "crawl.ai": 1.4, "crawl.sitemap": 1.3,
        "content.hidden": 1.5, "sem.html": 1.3,
    },
    "perplexity": {
        # Mostra le fonti con la data: freschezza e titoli descrittivi contano
        # più del resto.
        "content.fresh": 1.8, "schema.datemodified": 1.8, "meta.title": 1.5,
        "content.sources": 1.4, "meta.description": 1.3,
        "sd.person": 0.8,
    },
}


def _punteggio(checks, moltiplicatori, frac) -> int | None:
    num = den = 0.0
    for c in checks:
        st = c.status if hasattr(c, "status") else c.get("status")
        if st not in frac:
            continue
        cid = c.id if hasattr(c, "id") else c.get("id") or c.get("check_id")
        peso = (c.weight if hasattr(c, "weight") else c.get("weight") or 1)
        peso = peso * moltiplicatori.get(cid, 1.0)
        den += peso
        num += peso * frac[st]
    return round(100 * num / den) if den else None


def per_motore(site_checks, page_checks, peso_sito: float = 0.30) -> list:
    """Un sotto-punteggio per ciascuno dei quattro assistenti.

    Usa la stessa struttura del punteggio generale — sito e pagine pesati
    separatamente — così i cinque numeri sono confrontabili fra loro.
    """
    frac = {"ok": 1.0, "warn": 0.5, "fail": 0.0}
    fuori = []
    for m in MOTORI:
        mol = MOLTIPLICATORI[m]
        s = _punteggio(site_checks, mol, frac)
        p = _punteggio(page_checks, mol, frac)
        if s is None and p is None:
            valore = None
        elif p is None:
            valore = s
        elif s is None:
            valore = p
        else:
            valore = round(peso_sito * s + (1 - peso_sito) * p)
        fuori.append({"motore": m, "nome": NOME[m], "punteggio": valore})
    return fuori


def cosa_conta_per(motore: str, limite: int = 3) -> list:
    """I controlli che questo motore pesa più degli altri."""
    mol = MOLTIPLICATORI.get(motore) or {}
    return sorted((k for k, v in mol.items() if v > 1.0), key=lambda k: -mol[k])[:limite]


# ⚠️ MISURATO, non supposto: sui progetti veri i quattro sotto-punteggi cadono
# tutti entro 2-3 punti l'uno dall'altro. È logico — sono gli stessi controlli
# su una base larga, e cambiare il peso di qualcuno non sposta granché una
# media. Quindi mostrare «ChatGPT 79 · Claude 77 · Gemini 76 · Perplexity 78»
# suggerirebbe una differenza che i dati non hanno, e su una funzione a
# pagamento è peggio che non averla.
#
# Ciò che invece è davvero diverso da motore a motore è l'ORDINE DELLE COSE DA
# FARE: per Perplexity la prima è la data di aggiornamento, per Gemini il
# contenuto che arriva solo col JavaScript. Quella è la parte utile, ed è
# quella che il prodotto mostra.
FORBICE_OSSERVATA = 3


def priorita_per_motore(site_checks, page_checks, rimedi=None, limite=3) -> list:
    """Cosa conviene sistemare per primo, assistente per assistente.

    Il peso di un problema per un motore è: peso del check × moltiplicatore di
    quel motore × quante volte compare. Due motori che tengono a cose diverse
    producono elenchi diversi, ed è quello che il cliente può usare.
    """
    rimedi = rimedi or {}
    frac_rotti = ("fail", "warn")

    def leggi(c):
        if hasattr(c, "status"):
            return c.id, c.status, c.weight, c.title
        return (c.get("id") or c.get("check_id"), c.get("status"),
                c.get("weight") or 1, c.get("title") or "")

    conteggio: dict = {}
    for c in list(site_checks) + list(page_checks):
        cid, st, peso, titolo = leggi(c)
        if st not in frac_rotti or not cid:
            continue
        v = conteggio.setdefault(cid, {"check_id": cid, "titolo": titolo,
                                       "peso": peso, "volte": 0, "grave": st})
        v["volte"] += 1
        if st == "fail":
            v["grave"] = "fail"

    fuori = []
    for m in MOTORI:
        mol = MOLTIPLICATORI[m]
        voci = []
        for v in conteggio.values():
            forza = v["peso"] * mol.get(v["check_id"], 1.0) * (1 + 0.1 * (v["volte"] - 1))
            if v["grave"] == "fail":
                forza *= 1.5
            voci.append({**v, "forza": round(forza, 1),
                         "specifico": mol.get(v["check_id"], 1.0) > 1.0,
                         "rimedio": rimedi.get(v["check_id"], "")})
        voci.sort(key=lambda x: -x["forza"])
        fuori.append({"motore": m, "nome": NOME[m], "voci": voci[:limite]})
    return fuori
