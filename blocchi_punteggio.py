# -*- coding: utf-8 -*-
"""Il punteggio complessivo, diviso in tre blocchi a quota fissa.

Specifica di Francesco D'Angelo, 24 settembre 2026
(`geo-audit-scoring-implementazione.md` + documento funzionale).

Prima c'era una sola media pesata su tutti i check di tutte le pagine
concatenati. I check di sito si diluivano in un denominatore che cresce col
numero di pagine: un sito che blocca ogni crawler AI arrivava a 98/100.

Ora tre punteggi indipendenti, ognuno calcolato con la stessa logica di
`score_checks`, ognuno con una **quota fissa** sul totale:

    punteggio = 0.30 × blocco1 + 0.52 × blocco2 + 0.18 × blocco3

Il taglio non è tecnico ma **operativo**, ed è il motivo delle quote: il primo
blocco è ciò che si sistema con dei file statici, il secondo ciò che si fa una
volta sul template, il terzo è lavoro editoriale ricorrente. I primi due
valgono l'82%, cioè quanto VerticalAI può spostare da sola.

⚠️ **Nessun cap separato.** Se tutto il blocco 1 fallisce il massimo
raggiungibile è 70, ma esce dalla formula da sé: aggiungere un tetto sopra
sarebbe la stessa regola scritta due volte, e due regole che dicono la stessa
cosa divergono al primo cambio.

⚠️ **I totali nominali NON fanno 100** (18, 52, 56) e non è un errore: ogni
blocco viene prima normalizzato a 0-100 al suo interno, poi pesato per la sua
quota. I pesi dei singoli check contano quindi solo *dentro* il loro blocco.
"""
from __future__ import annotations

QUOTA = {1: 0.30, 2: 0.52, 3: 0.18}


# ── Blocco 1 · Requisiti tecnici di base ────────────────────────────────────
# File statici. Si sistemano senza toccare il CMS del cliente.
BLOCCO_1 = (
    "crawl.ai",          # blocca i crawler AI: il fallimento che azzera il resto
    "crawl.robots",
    "crawl.sitemap",
    "crawl.llms",
    # ⚠️ Aggiunti da noi: NON sono nell'elenco della specifica, che è stata
    # scritta su una lettura del codice precedente ai rilasci del 22-23
    # settembre. Senza assegnarli uscirebbero dal punteggio in silenzio —
    # esattamente il rovescio del problema che questa revisione risolve.
    # Stanno qui perché riguardano robots.txt e sitemap, cioè file statici.
    "crawl.conflict",    # robots.txt e meta robots si contraddicono
    "crawl.coverage",    # la sitemap non copre le pagine che esistono
)

# ── Blocco 2 · Ottimizzazione tecnica ───────────────────────────────────────
# Serve il CMS, ma si fa una volta a livello di template. Nessun lavoro
# editoriale.
BLOCCO_2 = (
    "crawl.https",
    "sd.present", "sd.valid", "sd.highvalue", "sd.completeness", "sd.sameas",
    "meta.og", "meta.canonical", "meta.lang", "meta.twitter",
    "sem.html",
    "trust.social",
    # ⚠️ Aggiunti da noi, stesso motivo del blocco 1. Sono tutti interventi da
    # template: marcatura, canonical, prestazioni del tema.
    "schema.datemodified",
    "sd.person",
    "meta.canonical.consistency",
    "perf.lcp", "perf.cls",
)

# ── Blocco 3 · Contenuto e qualità editoriale ───────────────────────────────
# Lavoro ricorrente, pagina per pagina.
BLOCCO_3 = (
    "content.h1", "content.len", "content.q", "content.struct", "content.hier",
    "content.tldr", "content.fresh", "content.alt",
    "meta.description", "meta.title",
    "page.noindex", "page.status",
    "render.parity",
    "trust.contact", "trust.author",
    # ⚠️ Aggiunti da noi, stesso motivo. Sono giudizi su come è scritto e
    # organizzato il testo, o su cosa esiste del soggetto fuori dal sito.
    "content.atomic", "content.sources", "content.hidden",
    "faq.answerlen",
    "entity.wikidata", "entity.sameas.fonti",
)

DI_BLOCCO = {}
for _n, _elenco in ((1, BLOCCO_1), (2, BLOCCO_2), (3, BLOCCO_3)):
    for _id in _elenco:
        assert _id not in DI_BLOCCO, "check in due blocchi: %s" % _id
        DI_BLOCCO[_id] = _n


def _stato_peso_id(c):
    """Legge un check sia come dataclass che come dizionario."""
    if hasattr(c, "status"):
        return c.status, (c.weight or 1), c.id
    return (c.get("status"), (c.get("weight") or 1),
            c.get("id") or c.get("check_id"))


def _punteggio(checks, frac) -> tuple:
    num = den = 0.0
    for c in checks:
        stato, peso, _ = _stato_peso_id(c)
        if stato in frac:
            den += peso
            num += peso * frac[stato]
    return (round(100 * num / den) if den else 0), den


def per_blocco(site_checks, page_checks) -> dict:
    """Il punteggio di ciascun blocco e quanto peso misurabile contiene.

    Il peso serve a chi chiama per distinguere «blocco a zero perché è andato
    male» da «blocco a zero perché non c'era niente da misurare»: sono due
    fatti diversi e trattarli uguale falsa il punteggio.
    """
    frac = {"ok": 1.0, "warn": 0.5, "fail": 0.0}
    gruppi: dict = {1: [], 2: [], 3: []}
    orfani = []
    for c in list(site_checks) + list(page_checks):
        _, _, cid = _stato_peso_id(c)
        n = DI_BLOCCO.get(cid)
        if n is None:
            orfani.append(cid)
        else:
            gruppi[n].append(c)
    fuori = {}
    for n in (1, 2, 3):
        punti, peso = _punteggio(gruppi[n], frac)
        fuori[n] = {"punteggio": punti, "peso": peso, "quanti": len(gruppi[n])}
    fuori["orfani"] = sorted(set(orfani))
    return fuori


def complessivo(site_checks, page_checks) -> int:
    """Il punteggio del report.

    ⚠️ Un blocco senza niente di misurabile viene ESCLUSO e la sua quota
    ridistribuita fra gli altri, invece di contare come zero. Un sito di cui
    non si è potuta leggere nessuna pagina non deve prendere 82 su 100 solo
    perché il blocco 3 è vuoto: sarebbe un voto su un limite del crawler, non
    sul sito. È la stessa cautela che la formula a due blocchi aveva già.
    """
    b = per_blocco(site_checks, page_checks)
    vivi = [n for n in (1, 2, 3) if b[n]["peso"] > 0]
    if not vivi:
        return 0
    quota_viva = sum(QUOTA[n] for n in vivi)
    return round(sum(QUOTA[n] * b[n]["punteggio"] for n in vivi) / quota_viva)


def orfani_del_catalogo(tutti_gli_id) -> list:
    """Gli id che nessun blocco rivendica.

    ⚠️ Esiste per essere chiamata da un test. Un check aggiunto domani e non
    assegnato qui **non toglie e non aggiunge punti**: spariscono senza errore
    né avviso, ed è il modo più silenzioso che questo file ha di sbagliare.
    """
    return sorted(set(tutti_gli_id) - set(DI_BLOCCO))
