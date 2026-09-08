# -*- coding: utf-8 -*-
"""
Chiedere ai motori AI, e leggere chi citano.

Quattro provider, un'interfaccia sola: si manda una domanda vera — «qual è il
miglior X a Y?» — e si guarda **quali siti l'assistente cita** rispondendo. È la
misura che il prodotto promette: non se il sito è ottimizzato, ma se le AI lo
nominano davvero.

⚠️ Ogni provider restituisce le citazioni in un posto diverso, e nessuno dei
quattro lo documenta allo stesso modo:

    OpenAI      annotazioni `url_citation` dentro il testo della risposta
    Anthropic   blocchi `web_search_result_location`, oppure i risultati grezzi
    Gemini      `groundingMetadata.groundingChunks[].web.uri`
    Perplexity  `search_results[]`, o `citations[]` nelle versioni più vecchie

I quattro adattatori qui sotto nascondono la differenza. Le forme sono quelle
già verificate sul campo dal plugin GEO Suite Pro (`includes/ai/`), che fa la
stessa cosa in PHP: non sono state indovinate dalla documentazione.

⚠️ Gemini avvolge gli URL in un redirect `vertexaisearch.cloud.google.com`:
il dominio vero non si legge dall'indirizzo, va seguito. Vedi `_dominio_vero`.

⚠️ E il grounding di Gemini **è intermittente**: alla stessa domanda posta due
volte può rispondere con ventun fonti o con nessuna. Misurato sul campo — non è
un difetto del codice, è come si comporta. Una domanda che chiede esplicitamente
le fonti («cita le fonti web») le ottiene molto più spesso di una che non lo
chiede: chi genera i prompt monitorati tenga conto che **come è scritta la
domanda cambia il risultato**, e che uno zero di Gemini va guardato due volte
prima di chiamarlo dato.

Modulo foglia: non importa nulla del progetto, come `ai_sources.py`.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests as req

# ── I quattro motori ─────────────────────────────────────────────────────────
#
# I modelli predefiniti sono quelli che GEO Suite usa già in produzione: sono
# quelli economici che sanno cercare sul web. Un modello senza ricerca web
# risponderebbe a memoria — e a memoria non cita nessuno.
PROVIDER = {
    "openai": {
        "nome": "ChatGPT",
        "endpoint": "https://api.openai.com/v1/responses",
        "modelli": "https://api.openai.com/v1/models",
        "modello": "gpt-4o-mini",
    },
    "anthropic": {
        "nome": "Claude",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "modelli": "https://api.anthropic.com/v1/models",
        "modello": "claude-haiku-4-5",
    },
    "gemini": {
        "nome": "Gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/",
        "modelli": "https://generativelanguage.googleapis.com/v1beta/models",
        "modello": "gemini-flash-latest",
    },
    "perplexity": {
        "nome": "Perplexity",
        "endpoint": "https://api.perplexity.ai/chat/completions",
        # ⚠️ `/models` risponde 404: l'elenco sta sotto `/v1/models`, a
        # differenza dell'endpoint delle domande che sta senza `/v1`.
        "modelli": "https://api.perplexity.ai/v1/models",
        "modello": "sonar",
    },
}

_ATTESA = 90            # un giro di ricerca web è lento: non è un errore
_REDIRECT_GOOGLE = "vertexaisearch.cloud.google.com"


class ErroreProvider(Exception):
    """Il provider non ha risposto, o ha risposto in un modo che non si capisce."""


# ── Utilità ──────────────────────────────────────────────────────────────────

def dominio_di(url: str) -> str:
    """Il dominio nudo di un indirizzo, senza `www.` e senza porta."""
    try:
        host = (urlparse(url if "//" in url else "https://" + url).netloc or "").lower()
    except Exception:
        return ""
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _dominio_vero(url: str) -> str:
    """Il dominio dietro un eventuale redirect.

    ⚠️ Gemini non restituisce l'indirizzo della fonte: restituisce un suo
    redirect su `vertexaisearch.cloud.google.com`. Chi lo legge senza seguirlo
    si ritrova un elenco di citazioni che puntano tutte a Google — e conclude
    che nessun sito viene mai citato.
    """
    d = dominio_di(url)
    if _REDIRECT_GOOGLE not in d:
        return d
    try:
        r = req.head(url, allow_redirects=True, timeout=15)
        vero = dominio_di(r.url)
        if vero and _REDIRECT_GOOGLE not in vero:
            return vero
    except Exception:
        pass
    return ""          # meglio niente che attribuire la citazione a Google


def e_lo_stesso_sito(dominio_citato: str, dominio_progetto: str) -> bool:
    """Se la citazione parla del sito che stiamo seguendo.

    ⚠️ Conta anche un sottodominio: `shop.esempio.it` citato per il progetto
    `esempio.it` è il cliente, non un altro. Ma non basta il «contiene»:
    `nonesempio.it` contiene `esempio.it` e non c'entra niente.
    """
    a, b = dominio_di(dominio_citato), dominio_di(dominio_progetto)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _pulisci(citazioni: list) -> list:
    """Un dominio per riga, senza doppioni, nell'ordine in cui è stato citato."""
    viste, fuori = set(), []
    for c in citazioni:
        d = c.get("dominio") or ""
        if not d or d in viste:
            continue
        viste.add(d)
        fuori.append(c)
    return fuori


# ── I quattro adattatori ─────────────────────────────────────────────────────

def _openai(prompt: str, chiave: str, modello: str) -> dict:
    r = req.post(PROVIDER["openai"]["endpoint"], timeout=_ATTESA,
                 headers={"Authorization": f"Bearer {chiave}",
                          "Content-Type": "application/json"},
                 json={"model": modello, "input": prompt,
                       "tools": [{"type": "web_search"}]})
    if r.status_code >= 300:
        raise ErroreProvider(f"OpenAI HTTP {r.status_code}: {r.text[:200]}")
    dati = r.json()

    testo, citazioni = "", []
    for blocco in dati.get("output") or []:
        for pezzo in blocco.get("content") or []:
            testo += pezzo.get("text") or ""
            for nota in pezzo.get("annotations") or []:
                if nota.get("type") == "url_citation" and nota.get("url"):
                    citazioni.append({"url": nota["url"],
                                      "titolo": nota.get("title") or "",
                                      "dominio": dominio_di(nota["url"])})
    return {"testo": testo.strip(), "citazioni": _pulisci(citazioni),
            "modello": dati.get("model") or modello}


def _anthropic(prompt: str, chiave: str, modello: str) -> dict:
    r = req.post(PROVIDER["anthropic"]["endpoint"], timeout=_ATTESA,
                 headers={"x-api-key": chiave, "anthropic-version": "2023-06-01",
                          "Content-Type": "application/json"},
                 json={"model": modello, "max_tokens": 1500,
                       "messages": [{"role": "user", "content": prompt}],
                       "tools": [{"type": "web_search_20250305",
                                  "name": "web_search", "max_uses": 5}]})
    if r.status_code >= 300:
        raise ErroreProvider(f"Anthropic HTTP {r.status_code}: {r.text[:200]}")
    dati = r.json()

    testo, citazioni = "", []
    for blocco in dati.get("content") or []:
        tipo = blocco.get("type")
        if tipo == "text":
            testo += blocco.get("text") or ""
            for c in blocco.get("citations") or []:
                if c.get("type") == "web_search_result_location" and c.get("url"):
                    citazioni.append({"url": c["url"], "titolo": c.get("title") or "",
                                      "dominio": dominio_di(c["url"])})
        elif tipo == "web_search_tool_result":
            # I risultati grezzi della ricerca: servono quando il testo cita
            # senza annotazioni, cosa che capita sulle risposte brevi.
            for c in blocco.get("content") or []:
                if isinstance(c, dict) and c.get("url"):
                    citazioni.append({"url": c["url"], "titolo": c.get("title") or "",
                                      "dominio": dominio_di(c["url"])})
    return {"testo": testo.strip(), "citazioni": _pulisci(citazioni),
            "modello": dati.get("model") or modello}


def _gemini(prompt: str, chiave: str, modello: str) -> dict:
    url = f"{PROVIDER['gemini']['endpoint']}{modello}:generateContent"
    r = req.post(url, timeout=_ATTESA, params={"key": chiave},
                 headers={"Content-Type": "application/json"},
                 json={"contents": [{"parts": [{"text": prompt}]}],
                       "tools": [{"google_search": {}}]})
    if r.status_code >= 300:
        raise ErroreProvider(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
    dati = r.json()

    testo, citazioni = "", []
    for cand in dati.get("candidates") or []:
        for parte in (cand.get("content") or {}).get("parts") or []:
            testo += parte.get("text") or ""
        for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
            web = chunk.get("web") or {}
            if web.get("uri"):
                citazioni.append({"url": web["uri"], "titolo": web.get("title") or "",
                                  "dominio": ""})

    # ⚠️ I redirect si seguono INSIEME, non uno dopo l'altro: sono una ventina
    # per risposta, e in fila costavano quaranta secondi per un singolo prompt —
    # su dieci prompt sarebbero stati sette minuti del solo Gemini.
    if citazioni:
        with ThreadPoolExecutor(max_workers=8) as pool:
            domini = list(pool.map(lambda c: _dominio_vero(c["url"]), citazioni))
        for c, d in zip(citazioni, domini):
            c["dominio"] = d

    return {"testo": testo.strip(), "citazioni": _pulisci(citazioni), "modello": modello}


def _perplexity(prompt: str, chiave: str, modello: str) -> dict:
    r = req.post(PROVIDER["perplexity"]["endpoint"], timeout=_ATTESA,
                 headers={"Authorization": f"Bearer {chiave}",
                          "Content-Type": "application/json"},
                 json={"model": modello,
                       "messages": [{"role": "user", "content": prompt}]})
    if r.status_code >= 300:
        raise ErroreProvider(f"Perplexity HTTP {r.status_code}: {r.text[:200]}")
    dati = r.json()

    testo = ""
    for scelta in dati.get("choices") or []:
        testo += ((scelta.get("message") or {}).get("content")) or ""

    citazioni = []
    for s in dati.get("search_results") or []:
        if s.get("url"):
            citazioni.append({"url": s["url"], "titolo": s.get("title") or "",
                              "dominio": dominio_di(s["url"])})
    if not citazioni:
        # forma più vecchia: un elenco piatto di indirizzi
        for u in dati.get("citations") or []:
            if isinstance(u, str) and u:
                citazioni.append({"url": u, "titolo": "", "dominio": dominio_di(u)})
    return {"testo": testo.strip(), "citazioni": _pulisci(citazioni),
            "modello": dati.get("model") or modello}


_ADATTATORI = {"openai": _openai, "anthropic": _anthropic,
               "gemini": _gemini, "perplexity": _perplexity}


def interroga(provider: str, prompt: str, chiave: str, modello: str = "") -> dict:
    """Fa la domanda a un motore e torna testo e citazioni, in forma uguale per tutti.

    Solleva `ErroreProvider` se il motore non risponde: chi chiama decide se
    riprovare o registrare il fallimento. Non si inventa una risposta vuota,
    perché «nessuna citazione» e «non ha risposto» sono due cose diverse e
    finirebbero per contare allo stesso modo nel punteggio.
    """
    if provider not in _ADATTATORI:
        raise ErroreProvider(f"provider sconosciuto: {provider}")
    if not chiave:
        raise ErroreProvider(f"manca la chiave API per {provider}")
    return _ADATTATORI[provider](prompt, chiave, modello or PROVIDER[provider]["modello"])


# ── Come si legge una risposta ───────────────────────────────────────────────

def leggi_citazioni(risposta: dict, dominio_progetto: str) -> list:
    """Le citazioni della risposta, dicendo quali sono del sito seguito."""
    fuori = []
    for c in risposta.get("citazioni") or []:
        fuori.append({**c, "e_il_cliente": e_lo_stesso_sito(c["dominio"], dominio_progetto)})
    return fuori


def e_citato(risposta: dict, dominio_progetto: str) -> bool:
    """Se in questa risposta il sito del cliente è stato nominato."""
    return any(c["e_il_cliente"] for c in leggi_citazioni(risposta, dominio_progetto))


# ── I modelli disponibili ────────────────────────────────────────────────────

def elenca_modelli(provider: str, chiave: str) -> list:
    """I modelli che l'account può usare. Lista vuota se non si riesce a saperlo.

    ⚠️ Non tutti sanno cercare sul web, e uno che non sa cercare non cita
    nessuno: `sa_cercare` marca quelli usabili per il monitoraggio, così dalla
    console non si sceglie un modello che darà sempre zero.
    """
    if not chiave:
        return []
    try:
        if provider == "gemini":
            r = req.get(PROVIDER["gemini"]["modelli"], params={"key": chiave}, timeout=25)
            nomi = [(m.get("name") or "").split("/")[-1] for m in (r.json().get("models") or [])]
        elif provider == "anthropic":
            r = req.get(PROVIDER["anthropic"]["modelli"], timeout=25,
                        headers={"x-api-key": chiave, "anthropic-version": "2023-06-01"})
            nomi = [m.get("id") for m in (r.json().get("data") or [])]
        else:
            r = req.get(PROVIDER[provider]["modelli"], timeout=25,
                        headers={"Authorization": f"Bearer {chiave}"})
            nomi = [m.get("id") for m in (r.json().get("data") or [])]
    except Exception:
        return []

    fuori = []
    for n in nomi:
        if not n:
            continue
        fuori.append({"id": n, "sa_cercare": _sa_cercare(provider, n)})
    return sorted(fuori, key=lambda m: m["id"])


def _sa_cercare(provider: str, modello: str) -> bool:
    """Se quel modello può usare la ricerca web.

    Regole ricavate dalla pratica, non da un elenco ufficiale: i provider non
    espongono questa informazione nell'elenco dei modelli.
    """
    m = (modello or "").lower()
    if provider == "perplexity":
        return "sonar" in m                     # i Sonar cercano per costruzione
    if provider == "openai":
        return bool(re.match(r"^(gpt-4o|gpt-4\.1|gpt-5|o[34])", m))
    if provider == "anthropic":
        return "claude-3-5" in m or bool(re.match(r"^claude-(haiku|sonnet|opus)-[45]", m))
    if provider == "gemini":
        return "gemini-1.5" in m or "gemini-2" in m or "flash" in m or "pro" in m
    return False


# ── Sentiment ────────────────────────────────────────────────────────────────

def valuta_sentiment(testo: str, dominio: str, provider: str, chiave: str) -> str:
    """Come parla di quel sito la risposta: positivo, neutro o negativo.

    ⚠️ Si usa apposta un modello economico e senza ricerca web: qui non si deve
    cercare niente, solo leggere un testo che si ha già davanti. Il documento lo
    chiede esplicitamente per i compiti accessori.

    Torna stringa vuota se non si riesce a stabilirlo: meglio un campo vuoto che
    un «neutro» inventato, che nelle medie peserebbe come una misura vera.
    """
    if not testo or not chiave:
        return ""
    domanda = (
        "Leggi questo testo e dimmi come parla del sito indicato.\n"
        "Rispondi con UNA parola sola fra: positivo, neutro, negativo.\n"
        "Se il sito non è nominato, rispondi: assente.\n\n"
        f"Sito: {dominio}\n\nTesto:\n{testo[:4000]}")
    try:
        if provider == "anthropic":
            r = req.post(PROVIDER["anthropic"]["endpoint"], timeout=40,
                         headers={"x-api-key": chiave, "anthropic-version": "2023-06-01",
                                  "Content-Type": "application/json"},
                         json={"model": "claude-haiku-4-5", "max_tokens": 12,
                               "messages": [{"role": "user", "content": domanda}]})
            fuori = "".join(b.get("text") or "" for b in (r.json().get("content") or []))
        elif provider == "openai":
            r = req.post("https://api.openai.com/v1/chat/completions", timeout=40,
                         headers={"Authorization": f"Bearer {chiave}",
                                  "Content-Type": "application/json"},
                         json={"model": "gpt-4o-mini", "max_tokens": 12,
                               "messages": [{"role": "user", "content": domanda}]})
            fuori = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        elif provider == "gemini":
            r = req.post(f"{PROVIDER['gemini']['endpoint']}gemini-flash-latest:generateContent",
                         params={"key": chiave}, timeout=40,
                         json={"contents": [{"parts": [{"text": domanda}]}]})
            parti = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            fuori = "".join(p.get("text") or "" for p in parti)
        else:
            return ""
    except Exception:
        return ""

    parola = (fuori or "").strip().lower()
    for valida in ("positivo", "negativo", "neutro", "assente"):
        if valida in parola:
            return "" if valida == "assente" else valida
    return ""
