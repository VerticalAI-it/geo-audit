# -*- coding: utf-8 -*-
"""Il giro di monitoraggio: si generano le domande, si chiede alle AI, si conta.

Quattro passaggi, ognuno separabile perché costano tempo diverso:

    1. `genera_domande`   una volta sola, all'attivazione  (una chiamata LLM)
    2. `esegui_giro`      periodico                        (domande × 4 motori)
    3. `classifica`       dentro il giro                   (nessuna chiamata)
    4. `aggrega`          dopo il giro                     (nessuna chiamata)

⚠️ Il passaggio 2 è lento e costa: 36 secondi a domanda sui quattro motori,
misurati. Dieci domande sono sei minuti per un progetto solo — troppo per stare
dentro una singola invocazione con ventisette progetti. Per questo `esegui_giro`
accetta un budget di tempo e si ferma quando è finito, lasciando il resto al
giro dopo: la stessa cosa che fa il cron con gli audit.

Direzione degli import: `server.py` → `ai_giro.py` → `db.py` / `ai_monitor.py`.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta, timezone

import ai_monitor
from db import (_sb_ai_argomento_crea, _sb_ai_citazioni, _sb_ai_citazioni_scrivi,
                _sb_ai_snapshot_ultimo,
                _sb_ai_citazioni_categoria, _sb_ai_concorrente_aggiungi,
                _sb_ai_concorrenti, _sb_ai_domanda_crea, _sb_ai_domande,
                _sb_ai_esecuzione_scrivi, _sb_ai_impostazioni,
                _sb_ai_impostazioni_salva, _sb_ai_snapshot_scrivi, _sb_audits_by_project)

# Quante domande si propongono all'attivazione. Il documento dice «almeno 10».
QUANTE_DOMANDE = 10

# I motori interrogati a ogni giro.
MOTORI = ("openai", "anthropic", "gemini", "perplexity")


# ── 1. Le domande da monitorare ─────────────────────────────────────────────

def com_e_fatto_il_sito(project_id: str) -> str:
    """Cosa sappiamo del sito, dall'ultimo audit: i titoli delle sue pagine.

    ⚠️ Serve a non far indovinare il settore dal nome del dominio. Per
    `amahorse.com` il nome suggerisce «cavalli» e il generatore aveva scritto
    dieci domande su dove comprare articoli equestri — ma i titoli delle pagine
    dicono «Amahorse Corporate» e «Amahorse Group S.p.a.»: è un gruppo
    industriale, non un negozio. Le domande misuravano un mercato in cui quel
    sito non gioca, e la visibilità risultava zero per costruzione.

    È un dato che abbiamo già e non costa niente: l'audit legge quelle pagine
    comunque.
    """
    try:
        ultimi = _sb_audits_by_project(project_id, limit=1, full=True)
    except Exception:
        return ""
    if not ultimi:
        return ""

    righe = []
    for p in (ultimi[0].get("pages_detail") or [])[:14]:
        titolo = (p.get("title") or "").strip()
        if titolo and titolo not in righe:
            righe.append(titolo)
    return " · ".join(righe[:12])


def genera_domande(dominio: str, settore: str, chiave: str,
                   provider: str = "anthropic", com_e_fatto: str = "") -> list:
    """Propone le domande su cui misurare la visibilità del sito.

    ⚠️ Le domande devono essere quelle che farebbe **un cliente che cerca**, non
    quelle su di lui: «qual è il miglior X in Y» misura qualcosa, «parlami di
    esempio.it» no — l'assistente citerebbe il sito per forza, e la visibilità
    risulterebbe sempre del cento per cento.

    ⚠️ E devono chiedere le fonti: senza, il grounding di Gemini parte molto
    meno spesso (vedi `ai_monitor`), e uno zero diventa impossibile da leggere.

    ⚠️ `com_e_fatto` sono i titoli delle pagine vere, presi dall'ultimo audit.
    Senza, il modello indovina il settore dal nome del dominio e può sbagliare
    mercato — vedi `com_e_fatto_il_sito`. Un giro di domande sul mercato
    sbagliato dà zero, e quello zero sembra un dato.

    Usa il modello economico del provider, non quello con la ricerca web: qui
    non si cerca niente, si scrive.
    """
    richiesta = (
        f"Sto misurando quanto gli assistenti AI citano il sito {dominio}"
        + (f", che si occupa di: {settore}." if settore else ".")
        + (f"\n\nQueste sono le pagine vere del sito, guardale per capire cosa fa"
           f" davvero prima di scrivere le domande:\n{com_e_fatto}\n"
           if com_e_fatto else "")
        + f"\n\nScrivi {QUANTE_DOMANDE} domande in italiano che una persona"
        " potrebbe fare a ChatGPT quando cerca prodotti o servizi come quelli di"
        " quel sito.\n\nRegole:\n"
        "- domande di chi CERCA, non domande sul sito. Il nome del sito o"
        " dell'azienda NON deve comparire in nessuna domanda.\n"
        "- devono riguardare il mercato in cui quel sito lavora DAVVERO,"
        " ricavato dalle pagine qui sopra: se e' un produttore non scrivere"
        " domande da negozio online, se e' un gruppo industriale non scrivere"
        " domande da e-commerce\n"
        "- ogni domanda deve chiedere esplicitamente di citare le fonti o i siti\n"
        "- varia il tipo: chi confronta, chi vuole comprare, chi si informa\n\n"
        'Rispondi SOLO con un elenco JSON di oggetti {"domanda": "...",'
        ' "argomento": "...", "intento": "informativo|commerciale|comparativo"}.'
        " Niente altro testo.")

    try:
        risposta = _chiedi_senza_cercare(provider, richiesta, chiave)
    except Exception:
        return []

    grezzo = (risposta or "").strip()
    m = re.search(r"\[.*\]", grezzo, re.S)
    if not m:
        return []
    try:
        voci = json.loads(m.group(0))
    except Exception:
        return []

    fuori = []
    for v in voci:
        testo = (v.get("domanda") or "").strip()
        if not testo:
            continue
        # ⚠️ Se il nome del sito è finito nella domanda, quella domanda non
        # misura niente: si scarta invece di tenerla e falsare la media.
        radice = ai_monitor.dominio_di(dominio).split(".")[0]
        if radice and radice.lower() in testo.lower():
            continue
        fuori.append({"domanda": testo,
                      "argomento": (v.get("argomento") or "Generale").strip(),
                      "intento": (v.get("intento") or "").strip()})
    return fuori[:QUANTE_DOMANDE]


def _chiedi_senza_cercare(provider: str, richiesta: str, chiave: str) -> str:
    """Una domanda semplice al modello economico, senza ricerca web."""
    import requests as req
    if provider == "anthropic":
        r = req.post("https://api.anthropic.com/v1/messages", timeout=60,
                     headers={"x-api-key": chiave, "anthropic-version": "2023-06-01",
                              "Content-Type": "application/json"},
                     json={"model": "claude-haiku-4-5", "max_tokens": 2000,
                           "messages": [{"role": "user", "content": richiesta}]})
        return "".join(b.get("text") or "" for b in (r.json().get("content") or []))
    if provider == "openai":
        r = req.post("https://api.openai.com/v1/chat/completions", timeout=60,
                     headers={"Authorization": f"Bearer {chiave}",
                              "Content-Type": "application/json"},
                     json={"model": "gpt-4o-mini", "max_tokens": 2000,
                           "messages": [{"role": "user", "content": richiesta}]})
        return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if provider == "gemini":
        r = req.post("https://generativelanguage.googleapis.com/v1beta/models/"
                     "gemini-flash-latest:generateContent",
                     params={"key": chiave}, timeout=60,
                     json={"contents": [{"parts": [{"text": richiesta}]}]})
        parti = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text") or "" for p in parti)
    return ""


def prepara_progetto(project_id: str, dominio: str, settore: str, chiavi: dict) -> int:
    """Crea le domande di un progetto che non ne ha. Torna quante ne ha create."""
    if _sb_ai_domande(project_id):
        return 0                       # ce le ha già: non si sovrascrive niente

    chiave = chiavi.get("anthropic") or chiavi.get("openai") or chiavi.get("gemini")
    provider = ("anthropic" if chiavi.get("anthropic") else
                "openai" if chiavi.get("openai") else "gemini")
    if not chiave:
        return 0

    fatte = 0
    com_e = com_e_fatto_il_sito(project_id)
    for v in genera_domande(dominio, settore, chiave, provider, com_e):
        topic_id = _sb_ai_argomento_crea(project_id, v["argomento"])
        if topic_id and _sb_ai_domanda_crea(topic_id, v["domanda"], v["intento"]):
            fatte += 1
    return fatte


# ── 2. Il giro sui motori ───────────────────────────────────────────────────

def esegui_giro(project_id: str, dominio: str, chiavi: dict,
                budget_secondi: float = 240, sentiment: bool = True) -> dict:
    """Chiede a tutti i motori tutte le domande, e salva cosa hanno risposto.

    Si ferma quando il budget di tempo è finito: quello che resta lo farà il
    giro successivo. ⚠️ Fermarsi a metà **non è un fallimento** — le risposte
    già salvate valgono, e il punteggio si calcola su quelle che ci sono.
    """
    partito = time.monotonic()
    domande = _sb_ai_domande(project_id)
    if not domande:
        return {"esito": "nessuna_domanda", "eseguite": 0}

    # ⚠️ Nessuna domanda entra in un giro finche' un umano non l'ha guardata.
    # Il documento dell'8 settembre lo chiede, e il motivo si e' visto sul
    # primo giro vero: il generatore aveva scritto dieci domande sul mercato
    # sbagliato e la visibilita' era risultata 0% — uno zero che il cliente
    # avrebbe letto come un giudizio sul suo sito.
    #
    # Prima della migrazione della fase G la colonna non esiste e il campo
    # arriva assente: in quel caso si passa, altrimenti il monitoraggio si
    # fermerebbe ovunque fino a quando Silvio non esegue lo script.
    in_attesa = [d for d in domande if d.get("approved") is False]
    domande = [d for d in domande if d.get("approved") is not False]
    if not domande:
        return {"esito": "da_approvare", "eseguite": 0,
                "da_approvare": len(in_attesa)}

    concorrenti = {c["domain"] for c in _sb_ai_concorrenti(project_id)}
    eseguite = falliti = citazioni_salvate = 0
    finito = True

    for d in domande:
        if (time.monotonic() - partito) >= budget_secondi:
            finito = False
            break
        for provider in MOTORI:
            chiave = chiavi.get(provider)
            if not chiave:
                continue
            if (time.monotonic() - partito) >= budget_secondi:
                finito = False
                break
            try:
                r = ai_monitor.interroga(provider, d["prompt_text"], chiave)
            except ai_monitor.ErroreProvider as e:
                # ⚠️ Si registra anche il fallimento: «non ha risposto» e «ha
                # risposto senza citare» sono due cose diverse, e confonderle
                # abbasserebbe il punteggio per un guasto nostro.
                _sb_ai_esecuzione_scrivi(d["id"], project_id, provider,
                                         ai_monitor.PROVIDER[provider]["modello"],
                                         "", stato="failed", errore=str(e))
                falliti += 1
                continue

            run_id = _sb_ai_esecuzione_scrivi(
                d["id"], project_id, provider, r.get("modello", ""), r.get("testo", ""))
            eseguite += 1

            citazioni = ai_monitor.leggi_citazioni(r, dominio)
            for c in citazioni:
                c["categoria"] = classifica(c, dominio, concorrenti)
            if sentiment and any(c["e_il_cliente"] for c in citazioni):
                voto = ai_monitor.valuta_sentiment(
                    r.get("testo", ""), dominio, provider, chiave)
                for c in citazioni:
                    if c["e_il_cliente"]:
                        c["sentiment"] = voto
            citazioni_salvate += _sb_ai_citazioni_scrivi(run_id, project_id, citazioni)

    _sb_ai_impostazioni_salva(
        project_id, {"last_run_at": datetime.now(timezone.utc).isoformat()})

    # Chi ricorre nelle risposte appena raccolte viene proposto come
    # concorrente, e le citazioni gia' scritte si adeguano. Deve stare qui e
    # non in una schermata: al primo giro l'elenco e' vuoto per forza, e senza
    # questo passaggio ogni concorrente resterebbe «terza parte» fino a quando
    # qualcuno non lo scrivesse a mano — cioe' quasi sempre mai.
    nuovi = []
    try:
        nuovi = scopri_concorrenti(project_id, dominio)
        if nuovi:
            riclassifica_citazioni(project_id, dominio)
    except Exception:
        # ⚠️ un problema qui non deve far risultare fallito un giro riuscito:
        # le risposte sono gia' salvate, i concorrenti si riproporranno al giro
        # dopo.
        pass

    return {"esito": "completato" if finito else "parziale",
            "eseguite": eseguite, "falliti": falliti,
            "citazioni": citazioni_salvate,
            "concorrenti_nuovi": nuovi,
            # ⚠️ va detto: un giro «completato» che ha saltato meta' delle
            # domande perche' erano da approvare non e' un giro completo.
            "da_approvare": len(in_attesa),
            "secondi": round(time.monotonic() - partito)}


# ── 3. Chi è il dominio citato ──────────────────────────────────────────────

def classifica(citazione: dict, dominio_progetto: str, concorrenti: set) -> str:
    """Se una citazione è del cliente, di un concorrente, di terzi o rumore.

    ⚠️ Era un punto aperto del documento (§8): «un dominio non-target potrebbe
    essere un competitor, una fonte terza sul brand, o rumore». La regola qui è
    volutamente prudente — si dice «concorrente» solo di chi è **nell'elenco dei
    concorrenti seguiti**, e «rumore» di ciò che è chiaramente un contenitore
    generico. Tutto il resto resta `third_party_about_brand`, che è il modo
    onesto di dire «un altro sito che parla dell'argomento».

    Una classificazione più fine — capire se quel sito parla DEL BRAND o solo
    del tema — vorrebbe una lettura del testo, cioè un'altra chiamata a
    pagamento per ogni citazione. Vale la pena solo se qualcuno userà davvero
    quella distinzione.
    """
    if citazione.get("e_il_cliente"):
        return "target"
    d = (citazione.get("dominio") or "").lower()
    if not d:
        return "noise"
    if any(d == c or d.endswith("." + c) for c in concorrenti):
        return "competitor"
    if any(x in d for x in _CONTENITORI):
        return "noise"
    return "third_party_about_brand"


# Piattaforme dove chiunque pubblica: una citazione qui non dice niente sul
# posizionamento del sito, e contarla come «fonte che parla del brand»
# gonfierebbe un numero che qualcuno leggerà come un risultato.
_CONTENITORI = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "tiktok.com", "pinterest.com", "reddit.com", "quora.com",
    "wikipedia.org", "amazon.", "ebay.", "aliexpress.", "tripadvisor.",
    "google.com", "bing.com", "yahoo.", "medium.com", "blogspot.", "wordpress.com",
)


# Elenchi, portali e marketplace: compaiono in massa nelle risposte «chi sono i
# principali X» ma non sono concorrenti — sono il posto dove i concorrenti stanno.
# Proporli come tali riempirebbe la scheda Competitors di rumore.
_ELENCHI = (
    "europages.", "kompass.", "paginegialle.", "yelp.", "trustpilot.",
    "glassdoor.", "indeed.", "subito.it", "shopify.com", "etsy.com",
    "alibaba.", "made-in-china.", "chatgpt.com", "openai.com",
)

# Quante risposte DIVERSE deve toccare un dominio per essere proposto. Contare
# le citazioni grezze non andrebbe: un sito linkato dodici volte dentro la
# stessa risposta è un segnale solo, non dodici.
_SOGLIA_RISPOSTE = 3


def scopri_concorrenti(project_id: str, dominio_progetto: str,
                       giorni: int = 30, quanti: int = 10) -> list:
    """Propone come concorrenti i domini che ricorrono nelle risposte.

    Il documento prevede tre fonti per l'elenco (`ai_suggested`, `admin_added`,
    `client_added`): questa è la prima. Le domande del monitoraggio sono già
    formulate come «quali sono i principali X» — chi torna spesso in quelle
    risposte occupa il posto che il cliente vorrebbe, ed è la definizione
    operativa di concorrente che il prodotto può permettersi senza una lettura
    a pagamento di ogni risposta.

    ⚠️ Propone, non decide: salva con `source='ai_suggested'` perché la scheda
    li mostri come suggerimenti da confermare o togliere. Un elenco automatico
    presentato come certo sarebbe peggio di un elenco vuoto — nessuno andrebbe
    a controllarlo.

    ⚠️ Non ripropone chi è stato **escluso**: legge la tabella con
    `solo_attivi=False` apposta. `_sb_ai_concorrente_aggiungi` fonde sui
    duplicati riportando lo stato ad `active`, quindi senza questo controllo
    ogni giro riporterebbe indietro i domini che il cliente aveva tolto, e
    l'esclusione non varrebbe niente.

    Torna i domini proposti in questo giro (solo i nuovi).
    """
    proprio = (dominio_progetto or "").lower().replace("www.", "")
    # anche gli esclusi: sono una decisione già presa, non si ridiscute
    gia_noti = {c["domain"].lower()
                for c in _sb_ai_concorrenti(project_id, solo_attivi=False)}

    risposte_per_dominio: dict = {}
    for c in _sb_ai_citazioni(project_id, giorni=giorni):
        if c.get("is_target"):
            continue
        d = (c.get("cited_domain") or "").lower()
        run = c.get("prompt_run_id")
        if not d or not run:
            continue
        if d == proprio or d.endswith("." + proprio):
            continue
        if any(x in d for x in _CONTENITORI) or any(x in d for x in _ELENCHI):
            continue
        risposte_per_dominio.setdefault(d, set()).add(run)

    classifica_domini = sorted(risposte_per_dominio.items(),
                               key=lambda kv: -len(kv[1]))
    proposti = []
    for d, run_ids in classifica_domini:
        if len(run_ids) < _SOGLIA_RISPOSTE or len(proposti) >= quanti:
            break
        if d in gia_noti:
            continue
        if _sb_ai_concorrente_aggiungi(project_id, d, "ai_suggested"):
            proposti.append(d)
    return proposti


def riclassifica_citazioni(project_id: str, dominio_progetto: str,
                           giorni: int = 30) -> int:
    """Rimette a posto le citazioni già salvate quando l'elenco concorrenti cambia.

    ⚠️ La categoria viene scritta **al momento del salvataggio**: le citazioni
    del primo giro portano per sempre la classificazione fatta quando l'elenco
    era vuoto. Senza questa passata, la scheda mostrerebbe come «terze parti»
    dei concorrenti riconosciuti un minuto dopo, e i numeri storici non
    tornerebbero con quelli nuovi.

    Torna quanti domini ha corretto.
    """
    concorrenti = {c["domain"] for c in _sb_ai_concorrenti(project_id)}
    if not concorrenti:
        return 0
    da_correggere = set()
    for c in _sb_ai_citazioni(project_id, giorni=giorni):
        if c.get("is_target") or c.get("citation_category") == "competitor":
            continue
        d = (c.get("cited_domain") or "").lower()
        if d and any(d == x or d.endswith("." + x) for x in concorrenti):
            da_correggere.add(d)
    fatti = 0
    for d in da_correggere:
        if _sb_ai_citazioni_categoria(project_id, d, "competitor", giorni):
            fatti += 1
    return fatti


# ── 4. Il punteggio ─────────────────────────────────────────────────────────

def aggrega(project_id: str, giorni: int = 30, batch_id: str = "") -> dict:
    """Calcola la visibilità e la salva, su una base uguale per tutti i motori.

    ⚠️ Si contano solo le risposte **riuscite**: un motore che non ha risposto
    non è un motore che non ha citato, e confondere le due cose farebbe
    scendere il punteggio per un guasto nostro.

    ⚠️ E si contano sulle **domande fatte a tutti** — l'intersezione, non
    l'unione. Il documento lo chiede («il numero di domande deve essere sempre
    al minimo tra tutti, il KPI ponderato per il numero di domande») e il
    motivo si è visto al primo giro vero: finito il tempo, OpenAI aveva
    risposto a 8 domande e Gemini a 7. Contando tutto in un mucchio, chi ha
    risposto di più pesa di più, e fra un giro e l'altro il punteggio si muove
    anche solo perché il giro è stato più corto. Su una base comune, invece,
    due giri si possono confrontare.

    Il punteggio complessivo è la **media delle percentuali dei motori**, non
    la percentuale del mucchio: così ogni motore pesa uguale anche se ha
    risposto a un numero diverso di domande.
    """
    from db import _sb_ai_esecuzioni

    esecuzioni = _sb_ai_esecuzioni(project_id, giorni=giorni)
    if batch_id:
        esecuzioni = [e for e in esecuzioni if e.get("batch_id") == batch_id]
    riuscite = [e for e in esecuzioni if e.get("status") == "completed"]
    if not riuscite:
        return {"punteggio": None, "risposte": 0}

    citazioni = _sb_ai_citazioni(project_id, giorni=giorni)
    con_noi = {c["prompt_run_id"] for c in citazioni if c.get("is_target")}

    # Le domande a cui ogni motore ha effettivamente risposto.
    domande_per_provider: dict = {}
    for e in riuscite:
        if e.get("prompt_id"):
            domande_per_provider.setdefault(e.get("provider") or "?", set()).add(e["prompt_id"])

    base = set()
    if domande_per_provider:
        base = set.intersection(*domande_per_provider.values())

    # ⚠️ Se un motore è andato giù del tutto, l'intersezione può svuotarsi. Un
    # punteggio calcolato su zero domande non è «zero visibilità», è nessuna
    # misura: si ripiega sull'unione e lo si dichiara, invece di restituire un
    # numero che sembra un risultato.
    base_comune = True
    if not base:
        base_comune = False
        base = set().union(*domande_per_provider.values()) if domande_per_provider else set()

    per_provider = {}
    for e in riuscite:
        if e.get("prompt_id") not in base:
            continue
        p = e.get("provider") or "?"
        conto = per_provider.setdefault(p, {"risposte": 0, "citati": 0})
        conto["risposte"] += 1
        if e["id"] in con_noi:
            conto["citati"] += 1
    for c in per_provider.values():
        c["percentuale"] = round(c["citati"] * 100 / c["risposte"]) if c["risposte"] else 0

    if not per_provider:
        return {"punteggio": None, "risposte": 0}

    # Media fra i motori: ognuno pesa uguale, a prescindere da quante domande
    # ha alle spalle.
    punteggio = round(
        sum(c["percentuale"] for c in per_provider.values()) / len(per_provider), 1)

    contate = sum(c["risposte"] for c in per_provider.values())
    citati = sum(c["citati"] for c in per_provider.values())

    # ── l'andamento rispetto al giro precedente ────────────────────────────
    delta = None
    try:
        precedente = _sb_ai_snapshot_ultimo(project_id, escludi_batch=batch_id)
        if precedente and precedente.get("visibility_score") is not None:
            delta = round(punteggio - float(precedente["visibility_score"]), 1)
    except Exception:
        delta = None

    fine = date.today()
    inizio = fine - timedelta(days=giorni)
    _sb_ai_snapshot_scrivi(project_id, inizio.isoformat(), fine.isoformat(),
                           punteggio, per_provider, batch_id=batch_id,
                           domande=len(base), delta=delta)

    return {"punteggio": punteggio, "risposte": contate, "citati": citati,
            "domande": len(base), "base_comune": base_comune,
            "delta": delta,
            "per_provider": per_provider,
            "falliti": len(esecuzioni) - len(riuscite)}
