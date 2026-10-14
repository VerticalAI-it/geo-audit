#!/usr/bin/env python3
"""Runner dell'audit GEO per la campagna outreach (Fase B: elenco di domini).

Usa il motore del prodotto SENZA modificarlo e con i parametri del live:
    geo_audit.run_audit(url, 30, False, False)
cioe' 30 pagine, niente rendering JS, robots.txt non rispettato nel crawl.
Per ottenere lo stesso punteggio del live serve anche la stessa
PAGESPEED_API_KEY di produzione, altrimenti i check perf.* escono `unknown`.

Nessuna scrittura su Supabase, nessuna email, nessun contatto: i dati vivono in
`outreach_data/` (ignorata da git).

Uso:
    PAGESPEED_API_KEY=... python scripts/outreach/run_batch.py \
        --domini starhotels.it,cimbali.it,imballaggidaniello.it

Riprendibile: un dominio con meta.json gia' scritto viene saltato, tranne se
l'esito era `errore`/`timeout` e si passa --riprova-falliti. --forza rifa tutto.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import requests                      # noqa: E402
from bs4 import BeautifulSoup        # noqa: E402

import geo_audit                     # noqa: E402

# ── parametri IDENTICI al prodotto (server.py: run_audit(url, MAX_PAGINE, False, False))
MAX_PAGINE = 30
RENDER = False
RISPETTA_ROBOTS = False

OUR_UA_TOKEN = "verticalai-geoaudit"      # dal BROWSER_UA del motore
STATI = ("ok", "sito_non_raggiungibile", "bloccato_bot", "bloccato_robots",
         "redirect_altro_dominio", "contenuto_insufficiente", "timeout", "errore")
RIPROVABILI = ("errore", "timeout")

# Soglie di dist_chart() in geo_audit.py (le stesse, copiate: la funzione non
# espone la tabella e il motore non si tocca). test_soglie() le verifica.
SOGLIE_DISTRIBUZIONE = [
    {"chiave": "ottimo", "nome": "Ottimo", "min": 90, "max": 100},
    {"chiave": "buono", "nome": "Buono", "min": 75, "max": 89},
    {"chiave": "discreto", "nome": "Discreto", "min": 60, "max": 74},
    {"chiave": "debole", "nome": "Debole", "min": 45, "max": 59},
    {"chiave": "critico", "nome": "Critico", "min": 0, "max": 44},
]

# flag_js_possibile: SOLO segnalazione, l'audit non viene scartato.
FLAG_JS_CRITERI = {
    "pagine_minime": 2,                 # meno pagine analizzate -> flag
    "home_parole_max": 150,             # home con meno parole visibili ...
    "home_script_min": 5,               # ... e almeno tanti <script> -> flag
    "home_parole_irrisorie": 50,        # sotto questa soglia, flag a prescindere
}

_log_lock = threading.Lock()
_log_file: Path | None = None


def log(msg: str) -> None:
    riga = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with _log_lock:
        print(riga, flush=True)
        if _log_file:
            with open(_log_file, "a", encoding="utf-8") as f:
                f.write(riga + "\n")


def slug(dominio: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", dominio.lower().replace("https://", "").replace("http://", "")).strip("-")


# ═══════════════════════════════════════════════════════════════ pre-check
def _get(url: str) -> requests.Response:
    return requests.get(url, headers=geo_audit.HEADERS, timeout=geo_audit.TIMEOUT, allow_redirects=True)


def robots_vieta_tutto(body: str) -> bool:
    """True se robots.txt vieta l'intero sito a `User-agent: *` o al nostro UA.

    Vale la regola standard: se esiste un gruppo che nomina il nostro UA, vince
    quello; altrimenti vale il gruppo `*`. «Vieta tutto» = `Disallow: /` senza
    un `Allow: /` che lo annulli.
    """
    gruppi, agenti, regole, in_regole = [], [], [], False
    for raw in body.splitlines():
        riga = raw.split("#", 1)[0].strip()
        if ":" not in riga:
            continue
        k, v = (s.strip() for s in riga.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if in_regole:
                gruppi.append((agenti, regole)); agenti, regole, in_regole = [], [], False
            agenti.append(v.lower())
        elif k in ("disallow", "allow"):
            in_regole = True
            regole.append((k, v))
    if agenti:
        gruppi.append((agenti, regole))

    def vieta(regole):
        dis = any(k == "disallow" and v == "/" for k, v in regole)
        allow = any(k == "allow" and v in ("/", "/$") for k, v in regole)
        return dis and not allow

    specifici = [r for a, r in gruppi if any(OUR_UA_TOKEN in x or "geoaudit" in x for x in a)]
    if specifici:
        return any(vieta(r) for r in specifici)
    return any(vieta(r) for a, r in gruppi if "*" in a)


def parole_visibili(html: str) -> tuple[int, int]:
    """(parole del testo visibile, numero di <script>) della home statica."""
    soup = BeautifulSoup(html, "lxml")
    n_script = len(soup.find_all("script"))
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    return len(soup.get_text(" ", strip=True).split()), n_script


def precheck(dominio: str) -> dict:
    """DNS + HTTP con redirect. Prova https://dominio poi https://www.dominio.

    Ritorna un dict con `status` (None se si puo' procedere all'audit),
    `url_finale`, `http_status`, `errore`, e i dati della home statica.
    """
    esito = {"status": None, "url_finale": None, "http_status": None, "errore": "",
             "robots": None, "home_parole": None, "home_script": None, "home_html": ""}
    if dominio.startswith("http"):
        candidati = [dominio]
        host = urlparse(dominio).hostname
    else:
        host = dominio
        candidati = [f"https://{dominio}", f"https://www.{dominio}"]
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        esito.update(status="sito_non_raggiungibile", errore=f"DNS: {e}")
        return esito

    ultimo = None
    for url in candidati:
        try:
            r = _get(url)
        except requests.RequestException as e:
            ultimo = f"{type(e).__name__}: {str(e)[:200]}"
            continue
        esito.update(url_finale=str(r.url), http_status=r.status_code)
        ultimo = None
        if r.status_code in (403, 429):
            esito.update(status="bloccato_bot", errore=f"HTTP {r.status_code}")
            return esito
        if r.status_code != 200:
            esito.update(errore=f"HTTP {r.status_code}")
            ultimo = esito["errore"]
            continue
        break
    else:
        esito.update(status="sito_non_raggiungibile", errore=ultimo or "nessuna risposta")
        return esito

    if not geo_audit.same_domain(esito["url_finale"], candidati[0]) and not dominio.startswith("http"):
        if not geo_audit.same_domain(esito["url_finale"], f"https://{dominio}"):
            esito.update(status="redirect_altro_dominio",
                         errore=f"redirect verso {urlparse(esito['url_finale']).netloc}")
            return esito
    ct = r.headers.get("Content-Type", "")
    if "html" not in ct and ct != "":
        esito.update(status="contenuto_insufficiente", errore=f"la home non e' HTML ({ct})")
        return esito

    esito["home_html"] = r.text
    esito["home_parole"], esito["home_script"] = parole_visibili(r.text)

    p = urlparse(esito["url_finale"])
    try:
        rb = _get(f"{p.scheme}://{p.netloc}/robots.txt")
        if rb.status_code == 200 and robots_vieta_tutto(rb.text):
            esito.update(status="bloccato_robots", robots="vieta_tutto",
                         errore="robots.txt: Disallow: / per * o per il nostro UA")
        else:
            esito["robots"] = "ok" if rb.status_code == 200 else f"assente({rb.status_code})"
    except requests.RequestException as e:
        esito["robots"] = f"non_letto({type(e).__name__})"
    return esito


# ═══════════════════════════════════════════════════════════════ audit
def lancia_audit(url: str, timeout: int) -> dict:
    """Esegue run_audit in un processo figlio: e' l'unico modo per avere un
    timeout vero (il motore non ne ha uno complessivo) senza toccarlo."""
    tmp = ROOT / "outreach_data" / f".tmp_{slug(url)}_{os.getpid()}_{threading.get_ident()}.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", url, str(tmp)],
                       timeout=timeout, check=False, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        return {"esito": "timeout", "errore": f"oltre {timeout}s"}
    try:
        dati = json.loads(tmp.read_text(encoding="utf-8"))
    except Exception as e:
        return {"esito": "errore", "errore": f"worker senza output ({e!r})"}
    finally:
        tmp.unlink(missing_ok=True)
    return dati


def worker(url: str, out: str) -> None:
    try:
        res = geo_audit.run_audit(url, MAX_PAGINE, RENDER, RISPETTA_ROBOTS)
        dati = {"esito": "ok", "res": res}
    except Exception as e:
        dati = {"esito": "eccezione", "tipo": type(e).__name__, "errore": str(e)}
    Path(out).write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")


def classifica_eccezione(msg: str) -> tuple[str, bool]:
    """(status, transitorio?) a partire dal messaggio di run_audit."""
    m = re.search(r"HTTP (\d+|None)", msg)
    cod = m.group(1) if m else None
    if cod in ("403", "429"):
        return "bloccato_bot", False
    if cod == "None" or (cod and cod.startswith("5")):
        return "sito_non_raggiungibile", True
    if cod and cod != "200":
        return "sito_non_raggiungibile", False
    if "HTML" in msg or cod == "200":
        return "contenuto_insufficiente", False
    return "errore", True


# ═══════════════════════════════════════════════════════════════ costruzione JSON
def _act_aggrega(site_checks, pages):
    """Stessa aggregazione di geo_audit.derive_actions (ordine del report),
    lavorando sui dict: severita' = la piu' alta incontrata, ordine
    (severita', -occorrenze), a parita' ordine di inserimento."""
    ordine = geo_audit.SEV_ORDER
    agg: dict[str, dict] = {}

    def add(c, url=None):
        if c["status"] not in ("warn", "fail") or not c["recommendation"]:
            return
        a = agg.setdefault(c["id"], {"check_id": c["id"], "titolo": c["title"],
                                     "categoria": c["category"], "raccomandazione": c["recommendation"],
                                     "severita": c["severity"], "n_pagine": 0, "urls": []})
        a["n_pagine"] += 1
        if ordine[c["severity"]] < ordine[a["severita"]]:
            a["severita"] = c["severity"]
        if url and url not in a["urls"]:
            a["urls"].append(url)

    for c in site_checks:
        add(c)
    for p in pages:
        for c in p["checks"]:
            add(c, p["url"])
    return sorted(agg.values(), key=lambda a: (ordine[a["severita"]], -a["n_pagine"]))


def costruisci_audit(dominio_in: str, pre: dict, res: dict) -> dict:
    site, pages = res["site_checks"], res["pages"]
    tutti = list(site) + [c for p in pages for c in p["checks"]]
    n = lambda st: sum(1 for c in tutti if c["status"] == st)
    ok, warn, fail, unk = n("ok"), n("warn"), n("fail"), n("unknown")
    misurati = ok + warn + fail

    acts = _act_aggrega(site, pages)
    # il report mostra le prime 8 azioni (derive_actions limit=8); le vittorie
    # rapide sono scelte dentro quelle 8
    top8 = acts[:8]
    vinc = [a for a in top8 if a["n_pagine"] > 1][:3] or top8[:3]
    desc = lambda a: a["raccomandazione"] + (f" (su {a['n_pagine']} pagine)" if a["n_pagine"] > 1 else "")

    dist = {}
    for s in SOGLIE_DISTRIBUZIONE:
        dist[s["chiave"]] = sum(1 for p in pages if s["min"] <= p["score"] <= s["max"])

    parole, script = pre.get("home_parole"), pre.get("home_script")
    c = FLAG_JS_CRITERI
    flag_js = (len(pages) < c["pagine_minime"]
               or (parole is not None and (parole < c["home_parole_irrisorie"]
                   or (parole < c["home_parole_max"] and (script or 0) >= c["home_script_min"]))))

    return {
        "dominio": res["domain"],
        "dominio_richiesto": dominio_in,
        "data": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url_finale": pre.get("url_finale"),
        "n_pagine": len(pages),
        "engine_version": res["engine_version"],
        "rendering_js": res["render"],
        "robots_superato": not res["respect_robots"],
        "score": res["overall"], "grade": res["grade"], "label": res["band"],
        "n_problemi": res["issues_count"], "n_critici": res["critical_count"],
        "controlli": {"totale": len(tutti), "misurati": misurati, "ok": ok,
                      "da_migliorare": warn, "critici": fail, "non_verificati": unk,
                      "pct_ok": round(100 * ok / (misurati or 1))},
        "aree": [{"nome": a["key"], "score": a["score"]} for a in res["areas"]],
        "distribuzione_pagine": dist,
        "soglie_distribuzione": SOGLIE_DISTRIBUZIONE,
        "controlli_sito": [{"nome": s["title"], "esito": s["status"], "dettaglio": s["detail"]} for s in site],
        "vittorie_rapide": [{"titolo": a["titolo"], "descrizione": a["raccomandazione"],
                             "n_modifiche": 1, "n_pagine": a["n_pagine"]} for a in vinc],
        "interventi_prioritari": [{"rank": i, "titolo": a["titolo"], "severita": a["severita"],
                                   "descrizione": desc(a), "n_pagine": a["n_pagine"],
                                   "check_id": a["check_id"], "categoria": a["categoria"],
                                   "urls": a["urls"]} for i, a in enumerate(acts, 1)],
        "pagine": [{"url": p["url"], "tipo": p["type"], "score": p["score"],
                    "problemi": [{"titolo": k["title"], "dettaglio": k["detail"],
                                  "suggerimento": k["recommendation"], "esito": k["status"],
                                  "severita": k["severity"], "check_id": k["id"]}
                                 for k in p["checks"] if k["status"] in ("warn", "fail")]}
                   for p in pages],
        "flag_js_possibile": bool(flag_js),
        "flag_js_criteri": FLAG_JS_CRITERI,
        "home_parole": parole, "home_script": script,
        "report_url": None,
        # ── completo, come lo restituisce il motore
        "site_checks": site, "pages": pages, "actions": res["actions"],
        "areas": res["areas"], "html": res["html"],
    }


# ═══════════════════════════════════════════════════════════════ per dominio
def lavora(dominio: str, out_root: Path, timeout: int, pausa: float, args) -> dict:
    id_ = slug(dominio)
    cartella = out_root / id_
    meta_p = cartella / "meta.json"
    if meta_p.exists() and not args.forza:
        vecchio = json.loads(meta_p.read_text(encoding="utf-8"))
        if not (args.riprova_falliti and vecchio.get("status") in RIPROVABILI):
            log(f"[{id_}] gia' fatto ({vecchio.get('status')}), salto")
            return vecchio
    cartella.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    meta = {"id": id_, "dominio": dominio, "status": "errore", "errore": "", "url_finale": None,
            "http_status": None, "durata_s": None, "engine_version": geo_audit.ENGINE_VERSION,
            "data": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tentativi": 0, "pagespeed_key": bool(os.environ.get("PAGESPEED_API_KEY")),
            "parametri": {"max_pagine": MAX_PAGINE, "render": RENDER, "respect_robots": RISPETTA_ROBOTS}}
    try:
        log(f"[{id_}] pre-check")
        pre = precheck(dominio)
        meta.update(url_finale=pre["url_finale"], http_status=pre["http_status"],
                    robots=pre["robots"], home_parole=pre["home_parole"], home_script=pre["home_script"])
        if pre["status"]:
            meta.update(status=pre["status"], errore=pre["errore"])
        else:
            url = pre["url_finale"]
            for tentativo in (1, 2):
                meta["tentativi"] = tentativo
                log(f"[{id_}] audit {url} (tentativo {tentativo})")
                r = lancia_audit(url, timeout)
                if r["esito"] == "ok":
                    audit = costruisci_audit(dominio, pre, r["res"])
                    (cartella / "audit.json").write_text(
                        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
                    meta.update(status="ok", errore="", engine_version=audit["engine_version"],
                                score=audit["score"], n_pagine=audit["n_pagine"],
                                flag_js_possibile=audit["flag_js_possibile"])
                    break
                if r["esito"] == "timeout":
                    meta.update(status="timeout", errore=r["errore"]); break
                if r["esito"] == "eccezione":
                    st, transitorio = classifica_eccezione(r["errore"])
                    meta.update(status=st, errore=r["errore"][:500])
                    if transitorio and tentativo == 1:
                        log(f"[{id_}] errore transitorio, 1 retry fra 10s: {r['errore'][:120]}")
                        time.sleep(10); continue
                    break
                meta.update(status="errore", errore=r["errore"]); break
    except Exception as e:  # il runner non deve morire per un dominio
        meta.update(status="errore", errore=f"{type(e).__name__}: {e}"[:500])
    meta["durata_s"] = round(time.monotonic() - t0, 1)
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[{id_}] -> {meta['status']}" + (f" score={meta.get('score')}" if meta["status"] == "ok" else f" ({meta['errore']})")
        + f" in {meta['durata_s']}s")
    time.sleep(pausa)
    return meta


def test_soglie() -> None:
    """Le soglie copiate devono coincidere con dist_chart del motore."""
    import inspect
    src = inspect.getsource(geo_audit.dist_chart)
    for s in SOGLIE_DISTRIBUZIONE:
        assert f'("{s["nome"]}",{s["min"]},{s["max"]}' in src.replace(" ", ""), s


def main() -> None:
    global _log_file
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", nargs=2, metavar=("URL", "OUT"), help=argparse.SUPPRESS)
    ap.add_argument("--domini", help="elenco separato da virgole")
    ap.add_argument("--dati", default=str(ROOT / "outreach_data"))
    ap.add_argument("--concorrenza", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=300, help="secondi per audit")
    ap.add_argument("--pausa", type=float, default=5.0, help="secondi di pausa dopo ogni dominio")
    ap.add_argument("--forza", action="store_true")
    ap.add_argument("--riprova-falliti", action="store_true")
    args = ap.parse_args()
    if args.worker:
        return worker(*args.worker)
    if not args.domini:
        ap.error("serve --domini")
    test_soglie()
    dati = Path(args.dati)
    (dati / "out").mkdir(parents=True, exist_ok=True)
    _log_file = dati / "run.log"
    if not os.environ.get("PAGESPEED_API_KEY"):
        log("ATTENZIONE: PAGESPEED_API_KEY non impostata -> i check perf.* saranno `unknown` "
            "e il punteggio puo' differire dal live.")
    domini = list(dict.fromkeys(d.strip() for d in args.domini.split(",") if d.strip()))
    log(f"Inizio: {len(domini)} domini, concorrenza {args.concorrenza}, engine {geo_audit.ENGINE_VERSION}")
    with ThreadPoolExecutor(max_workers=max(1, args.concorrenza)) as ex:
        metas = list(ex.map(lambda d: lavora(d, dati / "out", args.timeout, args.pausa, args), domini))
    log("Riepilogo: " + ", ".join(f"{m['id']}={m['status']}" for m in metas))


if __name__ == "__main__":
    main()
