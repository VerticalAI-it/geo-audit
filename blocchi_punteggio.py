# -*- coding: utf-8 -*-
"""Il punteggio complessivo, diviso in tre blocchi a quota fissa.

Specifica di Francesco D'Angelo, 24 settembre 2026
(`geo-audit-scoring-implementazione.md` + documento funzionale).

Prima c'era una sola media pesata su tutti i check di tutte le pagine
concatenati. I check di sito si diluivano in un denominatore che cresce col
numero di pagine: un sito che blocca ogni crawler AI arrivava a 98/100.

Ora tre punteggi indipendenti, ognuno calcolato con la stessa logica di
`score_checks`, ognuno con una **quota fissa** sul totale:

    punteggio = 0.40 × blocco1 + 0.45 × blocco2 + 0.15 × blocco3

Il taglio non è tecnico ma **operativo**: il primo blocco è ciò che si
sistema con dei file statici, il secondo ciò che si fa una volta sul
template, il terzo è lavoro editoriale ricorrente.

**Revisione del 16 ottobre 2026** (task «GEO Score: rivedere i pesi»). Il
punteggio dice quanto il sito è pronto per le AI, e usciva 83/100 su siti
senza llms.txt. Due cambi:
- le quote passano da 30/52/18 a 40/45/15, e dentro il blocco 1 i file per
  le AI pesano molto di più (vedi i pesi in `geo_audit.build_site_checks`);
- **tetto**: se manca anche uno solo dei requisiti per le AI
  (`REQUISITI_AI`), il punteggio non va oltre `TETTO_SENZA_REQUISITI`, cioè
  niente sufficienza. Appena il requisito c'è, il tetto sparisce e il sito
  fa il salto: è voluto.

Il tetto è una regola di prodotto, non un effetto della formula: le quote da
sole non bastano, perché un sito ottimo in tutto il resto supererebbe 60
anche senza llms.txt.

⚠️ **I totali nominali NON fanno 100** e non è un errore: ogni blocco viene
prima normalizzato a 0-100 al suo interno, poi pesato per la sua quota. I
pesi dei singoli check contano quindi solo *dentro* il loro blocco.
"""
from __future__ import annotations

QUOTA = {1: 0.40, 2: 0.45, 3: 0.15}

# Sotto la sufficienza: chi non ha i requisiti per le AI non arriva a 60.
TETTO_SENZA_REQUISITI = 59

# I requisiti senza i quali un sito non è pronto per le AI. Un `warn` o un
# `fail` su uno qualsiasi fa scattare il tetto; un `unknown` no, perché è un
# limite della misura e non un difetto del sito.
REQUISITI_AI = ("crawl.ai", "crawl.robots", "crawl.sitemap", "crawl.llms", "crawl.llms_full")

# Il JSON-LD si misura pagina per pagina: manca se manca su più di metà delle
# pagine lette. Una pagina sola senza dati strutturati non rende il sito
# illeggibile, la maggioranza sì.
REQUISITO_DI_PAGINA = "sd.present"


# ── Blocco 1 · Requisiti tecnici di base ────────────────────────────────────
# File statici. Si sistemano senza toccare il CMS del cliente.
BLOCCO_1 = (
    "crawl.ai",          # blocca i crawler AI: il fallimento che azzera il resto
    "crawl.robots",
    "crawl.sitemap",
    "crawl.llms",
    "crawl.llms_full",   # 16/10/2026
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


def requisiti_mancanti(site_checks, page_checks) -> list:
    """Gli id dei requisiti per le AI che il sito non soddisfa, in ordine."""
    mancano = []
    stati = {}
    for c in site_checks:
        stato, _, cid = _stato_peso_id(c)
        stati[cid] = stato
    for cid in REQUISITI_AI:
        if stati.get(cid) in ("warn", "fail"):
            mancano.append(cid)
    misurate = senza = 0
    for c in page_checks:
        stato, _, cid = _stato_peso_id(c)
        if cid == REQUISITO_DI_PAGINA and stato in ("ok", "warn", "fail"):
            misurate += 1
            senza += stato == "fail"
    if misurate and senza * 2 > misurate:
        mancano.append(REQUISITO_DI_PAGINA)
    return mancano


def complessivo(site_checks, page_checks) -> int:
    """Il punteggio del report.

    ⚠️ Un blocco senza niente di misurabile viene ESCLUSO e la sua quota
    ridistribuita fra gli altri, invece di contare come zero. Un sito di cui
    non si è potuta leggere nessuna pagina non deve prendere 82 su 100 solo
    perché il blocco 3 è vuoto: sarebbe un voto su un limite del crawler, non
    sul sito. È la stessa cautela che la formula a due blocchi aveva già.

    Poi il tetto: senza tutti i requisiti per le AI, al massimo
    `TETTO_SENZA_REQUISITI`.
    """
    b = per_blocco(site_checks, page_checks)
    vivi = [n for n in (1, 2, 3) if b[n]["peso"] > 0]
    if not vivi:
        return 0
    quota_viva = sum(QUOTA[n] for n in vivi)
    punti = round(sum(QUOTA[n] * b[n]["punteggio"] for n in vivi) / quota_viva)
    if requisiti_mancanti(site_checks, page_checks):
        punti = min(punti, TETTO_SENZA_REQUISITI)
    return punti


def orfani_del_catalogo(tutti_gli_id) -> list:
    """Gli id che nessun blocco rivendica.

    ⚠️ Esiste per essere chiamata da un test. Un check aggiunto domani e non
    assegnato qui **non toglie e non aggiunge punti**: spariscono senza errore
    né avviso, ed è il modo più silenzioso che questo file ha di sbagliare.
    """
    return sorted(set(tutti_gli_id) - set(DI_BLOCCO))
