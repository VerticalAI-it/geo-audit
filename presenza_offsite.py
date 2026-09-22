# -*- coding: utf-8 -*-
"""5.2 · Presenza off-site: l'entità esiste, fuori dal sito?

Gli assistenti non leggono solo la pagina: riconoscono un soggetto quando lo
ritrovano in fonti indipendenti che già conoscono. Wikidata è la più leggibile
da una macchina, ed è interrogabile gratis.

⚠️ **Il blocco 5 del documento chiede anche backlink e SERP.** Quelli costano
per query (Ahrefs / Semrush / Moz), e la decisione presa è di non comprare dati
da nessuno per ora. Qui dentro c'è solo ciò che si verifica gratis, e il
prodotto non deve far credere che la parte a pagamento ci sia.

⚠️ **Non si cerca per nome.** La ricerca testuale su Wikidata è inaffidabile in
un modo che conta: «Vertical AI» restituisce tre articoli scientifici, e un
check costruito così direbbe a mezzo parco clienti «sei su Wikidata» quando non
è vero. Si cerca sul sito ufficiale dichiarato dall'entità (P856): o è quel
dominio, o non è quell'entità.

⚠️ **Non essere su Wikidata non è un difetto.** Un idraulico non ha una voce e
non può averne una — le regole di rilevanza di Wikipedia lo vietano, e
suggerirgli di crearsela sarebbe un consiglio dannoso oltre che inutile. Per
questo l'assenza vale `unknown` e resta fuori dal punteggio: toglie punti solo
ciò su cui il cliente può agire.
"""
from __future__ import annotations

import re
import time

import requests

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "GEO-Audit/1.0 (https://geo.verticalai.it; info@verticalai.it)"
TIMEOUT = 8

# ⚠️ Tetto complessivo per TUTTE le query di un audit, ritentativi e attese
# comprese. Non è una preferenza: il cron di Vercel ha un margine documentato
# di 40 secondi (`_CRON_TIME_BUDGET + 200s <= maxDuration`, vedi server.py), e
# senza questo tetto il caso peggiore — due query con ritentativo più le
# attese dichiarate da Wikidata — ne prendeva oltre centocinquanta, facendo
# scadere la funzione su un sito già lento. Meglio un check `unknown` che un
# audit che non finisce.
BUDGET = 12.0


def _forme(dominio: str) -> list:
    """Le scritture con cui un sito può comparire come sito ufficiale.

    Wikidata conserva l'URL come l'ha scritto chi ha compilato la voce: con o
    senza `www`, con o senza barra finale, e ancora in `http` su voci vecchie.
    Cercare una sola forma vuol dire non trovare entità che esistono.
    """
    d = (dominio or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    d = d[4:] if d.startswith("www.") else d
    if not d or "." not in d:
        return []
    fuori = []
    for host in (d, "www." + d):
        for schema in ("https://", "http://"):
            fuori += [schema + host, schema + host + "/"]
    return fuori


class _Budget:
    """Il tempo che resta a questo audit per le domande a Wikidata."""

    def __init__(self, secondi: float):
        self.scade = time.monotonic() + secondi

    def resta(self) -> float:
        return self.scade - time.monotonic()

    def finito(self) -> bool:
        return self.resta() <= 0.5


def _query(sparql: str, tentativi: int = 2, budget: "_Budget | None" = None):
    """Interroga il servizio, rispettando lo strozzamento.

    ⚠️ Il servizio pubblico di Wikidata limita le query ravvicinate, e con un
    parco di decine di siti ci si finisce dentro davvero: il primo collaudo di
    questi check è tornato «non verificato» su un sito che l'entità ce l'ha,
    solo perché due audit erano partiti di fila. Senza questa attesa il
    prodotto direbbe «non risulta» a clienti che invece risultano.
    """
    for giro in range(tentativi):
        if budget and budget.finito():
            raise TimeoutError("budget off-site esaurito")
        quanto = min(TIMEOUT, budget.resta()) if budget else TIMEOUT
        r = requests.get(ENDPOINT, params={"query": sparql, "format": "json"},
                         headers={"User-Agent": UA,
                                  "Accept": "application/sparql-results+json"},
                         timeout=quanto)
        if r.status_code in (429, 503) and giro + 1 < tentativi:
            attesa = 3.0
            try:
                attesa = min(float(r.headers.get("Retry-After") or attesa), 10.0)
            except ValueError:
                pass
            # ⚠️ Non si aspetta più di quanto resta: l'attesa dichiarata da
            # Wikidata può essere lunghissima, e rispettarla alla lettera
            # significherebbe far scadere la funzione invece del check.
            if budget:
                attesa = min(attesa, max(budget.resta() - 1.0, 0))
                if attesa <= 0:
                    raise TimeoutError("budget off-site esaurito")
            time.sleep(attesa)
            continue
        r.raise_for_status()
        return r.json()["results"]["bindings"]
    return []


def entita_del_dominio(dominio: str, budget: "_Budget | None" = None) -> dict | None:
    """L'entità Wikidata che dichiara questo dominio come sito ufficiale.

    ⚠️ Query per VALORI ESATTI, non per REGEX: una REGEX su `P856` obbliga il
    servizio a scorrere tutti i siti ufficiali del mondo e finisce in timeout,
    mentre l'elenco di valori usa l'indice e torna subito.

    Restituisce `None` se non c'è, e solleva se la rete non risponde — chi
    chiama deve poter distinguere «non c'è» da «non l'ho potuto sapere».
    """
    forme = _forme(dominio)
    if not forme:
        return None
    valori = " ".join("<%s>" % u for u in forme)
    # ⚠️ Il conteggio delle voci di Wikipedia arriva DENTRO questa query, non
    # con una query per candidato. Più entità possono dichiarare lo stesso
    # sito — su deloitte.com ne tornano due, e la prima in ordine naturale è
    # `Monitor-Deloitte`, una controllata — quindi serve sapere quale sia la
    # principale. Chiederlo una riga alla volta costava troppo: col tetto di
    # tempo la disambiguazione veniva interrotta e tornava di nuovo l'entità
    # sbagliata, cioè il difetto si era solo spostato.
    righe = _query(
        "SELECT ?e ?eLabel ?eDescription ?sito (COUNT(DISTINCT ?voce) AS ?voci) WHERE { "
        "VALUES ?sito { %s } ?e wdt:P856 ?sito. "
        "OPTIONAL { ?voce schema:about ?e ; schema:isPartOf ?w. "
        'FILTER(CONTAINS(STR(?w), ".wikipedia.org")) } '
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "it,en". } } '
        "GROUP BY ?e ?eLabel ?eDescription ?sito "
        "ORDER BY DESC(?voci) LIMIT 5" % valori, budget=budget)
    if not righe:
        return None
    r = righe[0]
    qid = r["e"]["value"].rsplit("/", 1)[-1]
    return {"qid": qid,
            "etichetta": (r.get("eLabel") or {}).get("value", ""),
            "descrizione": (r.get("eDescription") or {}).get("value", ""),
            "sito_dichiarato": r["sito"]["value"],
            "voci_wikipedia": int((r.get("voci") or {}).get("value") or 0),
            "url": "https://www.wikidata.org/wiki/" + qid}


def lingue_wikipedia(qid: str, budget: "_Budget | None" = None) -> list:
    """In quante lingue esiste una voce di Wikipedia per questa entità.

    È il segnale che conta più del semplice esistere: una voce in una sola
    lingua e una in venti pesano diversamente per un assistente.
    """
    if not qid or not re.fullmatch(r"Q\d+", qid):
        return []
    righe = _query(
        "SELECT ?s WHERE { ?s schema:about wd:%s ; schema:isPartOf ?w. "
        'FILTER(CONTAINS(STR(?w), ".wikipedia.org")) } LIMIT 300' % qid, budget=budget)
    lingue = []
    for r in righe:
        m = re.match(r"https://([a-z\-]+)\.wikipedia\.org/", r["s"]["value"])
        if m:
            lingue.append(m.group(1))
    return sorted(set(lingue))


def guarda(dominio: str) -> dict:
    """Tutto ciò che si sa off-site di questo dominio, gratis.

    ⚠️ Non solleva mai: un errore di rete diventa `raggiunto: False`, che il
    check traduce in `unknown`. Un audit non deve fallire perché Wikidata è
    lenta, e non deve nemmeno dichiarare assente ciò che non ha potuto vedere.
    """
    esito = {"raggiunto": False, "entita": None, "voci_wikipedia": 0, "errore": ""}
    if not _forme(dominio):
        # ⚠️ Nessuna query è partita: «non l'ho chiesto» non è «non c'è».
        esito["errore"] = "dominio non interpretabile"
        return esito
    budget = _Budget(BUDGET)
    try:
        ent = entita_del_dominio(dominio, budget)
        esito["raggiunto"] = True
        if ent:
            esito["entita"] = ent
            # ⚠️ Niente seconda query: il conteggio delle voci di Wikipedia
            # arriva già dalla prima, e chiederlo di nuovo raddoppiava il
            # tempo dell'audit per un dato che avevamo in mano.
            esito["voci_wikipedia"] = ent.get("voci_wikipedia", 0)
    except Exception as e:
        esito["errore"] = str(e)[:200]
    return esito
