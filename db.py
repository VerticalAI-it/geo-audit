"""
GEO Audit — accesso ai dati (Supabase via REST diretta).

Non si usa supabase-py: il suo client sincrono bloccava l'event loop e la sua
dipendenza httpx risulto' incompatibile col runtime Vercel. Vedi
docs/02-architettura.md.

ATTENZIONE: la service role key BYPASSA le RLS. L'autorizzazione e' nel codice
applicativo, non nel database: ogni route che legge dati di progetto deve
verificare project["user_id"] == user["id"].
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import requests as req

from config import SUPABASE_URL, SUPABASE_SVC, SUPABASE_ANON
from ai_sources import detect_ai_referral, detect_ai_crawler


_SB_H = {
    "apikey": SUPABASE_SVC,
    "Authorization": f"Bearer {SUPABASE_SVC}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _sb_insert(data: dict) -> dict:
    r = req.post(f"{SUPABASE_URL}/rest/v1/audits",
                 json=data, headers=_SB_H, timeout=10)
    r.raise_for_status()
    return r.json()[0]


def _sb_patch(job_id: str, data: dict):
    req.patch(f"{SUPABASE_URL}/rest/v1/audits",
              json=data, headers=_SB_H,
              params={"id": f"eq.{job_id}"}, timeout=10)


def _sb_get(job_id: str) -> dict | None:
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits",
                headers=_SB_H,
                params={"id": f"eq.{job_id}", "select": "*"}, timeout=10)
    d = r.json()
    return d[0] if d else None


def _sb_insert_contact(data: dict) -> dict | None:
    r = req.post(f"{SUPABASE_URL}/rest/v1/contact_requests",
                 json=data, headers=_SB_H, timeout=10)
    r.raise_for_status()
    righe = r.json()
    return righe[0] if righe else None


# ─────────────────────────────────────────────────────────────────────────────
# I lead: chi ha chiesto l'accesso e aspetta
#
# Stanno in `contact_requests`, che nasce proprio come raccolta lead e ha gia'
# tutti i campi che servono — `email`, `phone`, `domain` (il sito da analizzare),
# `audit_id` piu' lo snapshot di `overall`/`grade`, cioe' il collegamento
# all'audit preliminare e il suo esito.
#
# ⚠️ Perche' NON una tabella nuova, che pure il documento propone: crearla vuole
# un DDL, e le chiavi di servizio non fanno DDL — servirebbe qualcuno che apre il
# pannello Supabase, e la funzionalita' resterebbe ferma li'. Il prezzo di
# riusare questa tabella e' che le due sorgenti (il form del report esterno e il
# form di richiesta accesso) vanno distinte: si distinguono dal `source`
# dell'audit collegato, che per i lead vale `lead`.
# ⚠️ **Lo stato del lead non e' una colonna, e' un fatto**: se l'email ha un
# account, il lead e' stato approvato; se non ce l'ha, sta ancora aspettando.
# Cosi' non esistono due verita' da tenere allineate.
# ─────────────────────────────────────────────────────────────────────────────

_LEAD_SOURCE = "lead"


def _sb_lead_insert(email: str, phone: str, sito: str) -> dict | None:
    """Registra la richiesta di accesso. L'audit arriva dopo, e la aggiorna."""
    return _sb_insert_contact({
        "email": (email or "").strip().lower(),
        "phone": (phone or "").strip() or None,
        "domain": sito,
        "preference": "email",
    })


_ADMIN_AZIONE = "admin_action"


def _sb_admin_traccia(attore: str, azione: str, bersaglio: str = "") -> bool:
    """Registra un'azione del pannello: chi, cosa, su chi, quando.

    ⚠️ Sta in `tracking_event` e non in una tabella sua perche' crearla vuole un
    DDL, che le chiavi di servizio non fanno. E' lo stesso compromesso gia' preso
    per i voti della roadmap, con lo stesso limite: `tracking_event` sta
    diventando un registro eventi generico, e quando queste righe conteranno
    davvero — un audit di sicurezza, una contestazione — vorranno una tabella
    con i vincoli giusti. **Il punto da cui migrare sono queste tre funzioni.**
    """
    r = req.post(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                 json={"event_name": _ADMIN_AZIONE,
                       "properties": {"attore": attore, "azione": azione,
                                      "bersaglio": bersaglio}})
    return r.status_code < 300


def _sb_admin_azioni(limit: int = 200) -> list:
    """Lo storico delle azioni del pannello, le piu' recenti per prime."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=15,
                params={"event_name": f"eq.{_ADMIN_AZIONE}",
                        "select": "properties,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


def _sb_contact_requests(limit: int = 300) -> list:
    """Tutte le richieste, le piu' recenti per prime. Solo per il pannello del team."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/contact_requests", headers=_SB_H, timeout=15,
                params={"select": "id,email,phone,domain,audit_id,overall,grade,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


def _sb_audits_recenti(limit: int = 500) -> list:
    """Audit di tutti, per il pannello. `site_checks` serve all'anteprima delle
    criticita' nella coda lead; l'HTML no, e pesa decine di KB per riga."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits", headers=_SB_H, timeout=20,
                params={"select": "id,user_id,project_id,domain,url,status,overall,grade,"
                                  "source,site_checks,error,created_at,completed_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


def _sb_progetti_tutti(limit: int = 1000) -> list:
    """Tutti i progetti, di tutti gli utenti. Solo per il pannello del team."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/project", headers=_SB_H, timeout=15,
                params={"select": "id,user_id,name,domain,scan_frequency,next_scan_at,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


def _sb_lead_attach_audit(lead_id: str, audit_id: str, overall, grade) -> None:
    """Aggancia al lead l'audit preliminare appena finito, col suo punteggio.

    E' quello che permette al team di richiamare avendo gia' il risultato in
    mano invece di una telefonata a freddo — cioe' il senso della funzionalita'.
    """
    req.patch(f"{SUPABASE_URL}/rest/v1/contact_requests", headers=_SB_H, timeout=10,
              json={"audit_id": audit_id, "overall": overall, "grade": grade},
              params={"id": f"eq.{lead_id}"})


def _sb_get_by_email(email: str) -> list:
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits",
                headers=_SB_H,
                params={"pending_email": f"eq.{email}",
                        "select": "id,domain,overall,grade,created_at",
                        "order": "created_at.desc"},
                timeout=10)
    return r.json() if r.ok else []


def _sb_get_by_user(user_id: str) -> list:
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits",
                headers=_SB_H,
                params={"user_id": f"eq.{user_id}",
                        "select": "id,url,domain,overall,grade,status,pages_count,created_at",
                        "order": "domain.asc,created_at.desc"},
                timeout=10)
    return r.json() if r.ok else []


_SCAN_INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}


def _next_scan_at(frequency: str) -> str:
    delta = _SCAN_INTERVALS.get(frequency, _SCAN_INTERVALS["weekly"])
    return (datetime.now(timezone.utc) + delta).isoformat()


def _sb_project_find(user_id: str, domain: str) -> dict | None:
    r = req.get(f"{SUPABASE_URL}/rest/v1/project",
                headers=_SB_H,
                params={"user_id": f"eq.{user_id}", "domain": f"eq.{domain}", "select": "*"},
                timeout=10)
    d = r.json() if r.ok else []
    return d[0] if d else None


def _sb_project_upsert(user_id: str, domain: str) -> dict:
    """Trova il project per (user_id, domain), altrimenti lo crea (nome default = dominio)."""
    existing = _sb_project_find(user_id, domain)
    if existing:
        return existing
    r = req.post(f"{SUPABASE_URL}/rest/v1/project",
                 json={"user_id": user_id, "domain": domain, "name": domain,
                       "next_scan_at": _next_scan_at("weekly")},
                 headers=_SB_H, timeout=10)
    if r.status_code == 409:  # race: creato nel frattempo da un'altra richiesta concorrente
        return _sb_project_find(user_id, domain)
    r.raise_for_status()
    return r.json()[0]


def _sb_projects_by_user(user_id: str) -> list:
    r = req.get(f"{SUPABASE_URL}/rest/v1/project",
                headers=_SB_H,
                params={"user_id": f"eq.{user_id}", "select": "*", "order": "updated_at.desc"},
                timeout=10)
    return r.json() if r.ok else []


def _sb_project_get(project_id: str) -> dict | None:
    r = req.get(f"{SUPABASE_URL}/rest/v1/project",
                headers=_SB_H,
                params={"id": f"eq.{project_id}", "select": "*"},
                timeout=10)
    d = r.json() if r.ok else []
    return d[0] if d else None


def _sb_project_patch(project_id: str, data: dict) -> None:
    data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    req.patch(f"{SUPABASE_URL}/rest/v1/project",
              json=data, headers=_SB_H,
              params={"id": f"eq.{project_id}"}, timeout=10)


def _sb_project_bump_scan(project_id: str, frequency: str) -> None:
    """Da chiamare dopo ogni audit completato (manuale o da /scan): sposta in
    avanti la prossima esecuzione automatica in base alla cadenza del progetto."""
    _sb_project_patch(project_id, {"next_scan_at": _next_scan_at(frequency)})


_AUDIT_LIGHT_FIELDS = "id,overall,grade,band,pages_count,issues_count,critical_count,status,created_at"
_AUDIT_FULL_FIELDS = ("id,url,domain,status,overall,grade,band,pages_count,engine_version,"
                       "areas,site_checks,pages_detail,actions,issues_count,critical_count,"
                       "created_at,completed_at")


def _sb_audits_by_project(project_id: str, limit: int = 50, full: bool = False) -> list:
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits",
                headers=_SB_H,
                params={"project_id": f"eq.{project_id}",
                        "select": _AUDIT_FULL_FIELDS if full else _AUDIT_LIGHT_FIELDS,
                        "order": "created_at.desc", "limit": str(limit)},
                timeout=10)
    return r.json() if r.ok else []


def _sb_audits_without_project(user_id: str) -> list:
    """Righe audits dell'utente non ancora agganciate a un project (backfill lazy)."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits",
                headers=_SB_H,
                params={"user_id": f"eq.{user_id}", "project_id": "is.null",
                        "select": "id,domain", "order": "created_at.asc"},
                timeout=10)
    return r.json() if r.ok else []


def _sb_recent_audits_by_user(user_id: str, limit: int = 10) -> list:
    """Ultimi run dell'utente, di qualsiasi progetto, manuali e automatici.
    Il filtro su user_id è l'autorizzazione: la service role key bypassa le RLS."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits",
                headers=_SB_H,
                params={"user_id": f"eq.{user_id}",
                        "select": "id,domain,url,overall,grade,status,source,created_at",
                        "order": "created_at.desc", "limit": str(limit)},
                timeout=10)
    return r.json() if r.ok else []


def _sb_issues_by_project(project_id: str, status: str | None = None) -> list:
    params = {"project_id": f"eq.{project_id}", "select": "*", "order": "severity.asc,last_seen_at.desc"}
    if status:
        params["status"] = f"eq.{status}"
    r = req.get(f"{SUPABASE_URL}/rest/v1/issue", headers=_SB_H, params=params, timeout=10)
    return r.json() if r.ok else []


def _sb_issue_sync(project_id: str, user_id: str, audit_id: str, checks: list) -> None:
    """Ciclo di vita delle issue del progetto: apre/aggiorna quelle presenti nei
    check warn/fail dell'audit appena completato, marca risolte quelle aperte in
    precedenza e non più viste in questo run.

    Tre stati possibili in `status`:
      open               criticità aperta
      resolved           chiusa dall'audit, che non l'ha più rilevata
      resolved_manually  chiusa a mano dall'utente da Opportunities

    **L'audit vince sullo stato manuale**: se un check torna a fallire sulla
    stessa pagina, la riga torna `open` qualunque fosse il suo stato — è il
    ramo `if prev` qui sotto, che non guarda lo stato precedente apposta.

    All'opposto, la chiusura automatica in fondo tocca **solo** le `open`: una
    riga chiusa a mano resta chiusa finché l'audit non la ritrova, altrimenti si
    perderebbe l'informazione che qualcuno l'aveva già gestita.

    Nessuna migrazione è stata necessaria: `issue.status` è una colonna TEXT
    senza vincolo CHECK — il commento `-- open | resolved` nello schema è solo
    una nota, non una regola imposta dal database."""
    now = datetime.now(timezone.utc).isoformat()
    existing = {i["fingerprint"]: i for i in _sb_issues_by_project(project_id)}
    seen = set()

    for c in checks:
        if c.get("status") not in ("warn", "fail"):
            continue
        url = c.get("url") or None
        fingerprint = f"{c['id']}|{url or ''}"
        seen.add(fingerprint)
        prev = existing.get(fingerprint)
        if prev:
            req.patch(f"{SUPABASE_URL}/rest/v1/issue",
                      json={"status": "open", "last_seen_audit": audit_id, "last_seen_at": now,
                            "resolved_at": None, "severity": c.get("severity"), "title": c.get("title")},
                      headers=_SB_H, params={"id": f"eq.{prev['id']}"}, timeout=10)
        else:
            req.post(f"{SUPABASE_URL}/rest/v1/issue",
                     json={"project_id": project_id, "user_id": user_id,
                           "check_id": c["id"], "category": c.get("category"), "url": url,
                           "title": c.get("title"), "severity": c.get("severity"),
                           "fingerprint": fingerprint, "status": "open",
                           "first_seen_audit": audit_id, "last_seen_audit": audit_id,
                           "first_seen_at": now, "last_seen_at": now},
                     headers=_SB_H, timeout=10)

    to_resolve = [i for fp, i in existing.items() if fp not in seen and i["status"] == "open"]
    for i in to_resolve:
        req.patch(f"{SUPABASE_URL}/rest/v1/issue",
                  json={"status": "resolved", "resolved_at": now},
                  headers=_SB_H, params={"id": f"eq.{i['id']}"}, timeout=10)


_SCAN_LEASE = timedelta(minutes=20)


def _sb_project_claim_due() -> dict | None:
    """Rivendica il prossimo progetto con next_scan_at scaduto scrivendoci una
    lease breve. Ritorna None se non c'è nulla da fare o se un'altra invocazione
    concorrente ha vinto la corsa."""
    now = datetime.now(timezone.utc).isoformat()
    r = req.get(f"{SUPABASE_URL}/rest/v1/project", headers=_SB_H, timeout=10,
                params={"next_scan_at": f"lte.{now}",
                        "select": "id,user_id,domain,scan_frequency,next_scan_at",
                        "order": "next_scan_at.asc", "limit": "1"})
    rows = r.json() if r.ok else []
    if not rows:
        return None

    project = rows[0]
    lease = (datetime.now(timezone.utc) + _SCAN_LEASE).isoformat()
    # Il predicato del claim è `next_scan_at <= now`, non l'uguaglianza col
    # valore appena letto: Postgres rivaluta la WHERE sulla riga bloccata, quindi
    # la seconda invocazione concorrente non trova più nulla da aggiornare (il
    # primo claim ha già spostato next_scan_at nel futuro) e riceve [].
    # Rispetto al compare-and-swap sul valore esatto non dipende dalla fedeltà
    # del round-trip del timestamp attraverso PostgREST.
    claim = req.patch(f"{SUPABASE_URL}/rest/v1/project", headers=_SB_H, timeout=10,
                      json={"next_scan_at": lease},
                      params={"id": f"eq.{project['id']}",
                              "next_scan_at": f"lte.{now}"})
    if not claim.ok or not claim.json():
        return None
    return project


def _detect_ai_source(referrer: str, page_url: str = "") -> str | None:
    """Assistente AI da cui arriva la visita. Le regole stanno in `ai_sources`,
    portate dal plugin GEO Suite dove sono in esercizio da mesi.

    Il secondo parametro e' facoltativo per retrocompatibilita', ma passarlo
    conviene: senza `page_url` si perde `utm_source`, e con lui tutti i referral
    che arrivano senza `Referer` (link copiato a mano, app mobile, https->http).
    """
    return detect_ai_referral(referrer, page_url)


def _sb_insert_tracking_event(data: dict) -> None:
    req.post(f"{SUPABASE_URL}/rest/v1/tracking_event", json=data, headers=_SB_H, timeout=5)


# PostgREST non restituisce piu' di 1000 righe per richiesta, qualunque `limit`
# si chieda: oltre, si pagina con l'header Range.
_PAGINA_PG = 1000

# ⚠️ Tetto agli eventi letti per una scheda. Serve perche' un sito con molti
# crawler puo' produrre decine di migliaia di righe al mese, e scaricarle tutte a
# ogni apertura della scheda costerebbe secondi. Chi chiama riceve anche il
# numero totale, cosi' puo' dire che sta mostrando una parte invece di far
# passare un dato parziale per completo.
_TETTO_EVENTI = 12000

_TRACKING_FIELDS = "event_name,session_id,page_url,ai_source,properties,created_at"


def _sb_tracking_events_conta(project_id: str, days: int = 30) -> int:
    """Quanti eventi ci sono nel periodo, senza scaricarli."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event",
                headers={**_SB_H, "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"},
                params={"project_id": f"eq.{project_id}", "created_at": f"gte.{since}",
                        "select": "id"}, timeout=10)
    intervallo = r.headers.get("content-range", "")
    try:
        return int(intervallo.split("/")[-1])
    except (ValueError, IndexError):
        return 0


def _sb_tracking_events(project_id: str, days: int = 30, limit: int = _TETTO_EVENTI) -> list:
    """Eventi di tracking del periodo, paginati.

    ⚠️ Qui c'era una richiesta sola con `limit=5000`, e **PostgREST ne restituisce
    al massimo 1000**: su un progetto con 4.089 eventi in 30 giorni la scheda ne
    leggeva un quarto e presentava quel quarto come il totale. Il difetto era
    silenzioso — nessun errore, solo numeri piu' bassi del vero — e sarebbe
    peggiorato con l'arrivo dei passaggi dei crawler, che si sommano alle visite.

    Ordini di grandezza misurati su un sito vero (fratellipalomba.it, 41 giorni):
    3.671 visite, 1.178 passaggi di crawler, 29 referral da AI. I crawler non sono
    piu' delle visite — sono quaranta volte i referral, che e' il confronto giusto:
    sono le due cose che questa scheda mette una accanto all'altra.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    params = {"project_id": f"eq.{project_id}", "created_at": f"gte.{since}",
              # `properties` porta la categoria del crawler (training / search /
              # user), che e' cio che rende leggibile il dato.
              "select": _TRACKING_FIELDS, "order": "created_at.desc"}

    def pagina(inizio: int) -> list:
        r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event",
                    headers={**_SB_H, "Range-Unit": "items",
                             "Range": f"{inizio}-{inizio + _PAGINA_PG - 1}"},
                    params=params, timeout=10)
        return r.json() if r.ok else []

    prima = pagina(0)
    if len(prima) < _PAGINA_PG:
        return prima

    # Ci sono altre pagine: si scaricano in parallelo, non una dopo l'altra.
    totale = min(_sb_tracking_events_conta(project_id, days) or len(prima), limit)
    inizi = list(range(_PAGINA_PG, totale, _PAGINA_PG))
    if not inizi:
        return prima
    with ThreadPoolExecutor(max_workers=min(6, len(inizi))) as pool:
        for blocco in pool.map(pagina, inizi):
            prima.extend(blocco)
    return prima[:limit]


def _sb_has_tracking(project_id: str) -> bool:
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event",
                headers=_SB_H,
                params={"project_id": f"eq.{project_id}", "select": "id", "limit": "1"},
                timeout=10)
    return bool(r.json()) if r.ok else False


def _sb_auth_user(access_token: str) -> dict | None:
    r = req.get(f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_ANON, "Authorization": f"Bearer {access_token}"},
                timeout=10)
    return r.json() if r.ok else None


# ─────────────────────────────────────────────────────────────────────────────
# Chi puo' entrare
#
# ⭐ L'invariante, e vale la pena dirla in un posto solo: **essere in
# `auth.users` E' essere approvati.** Non c'e' un secondo stato da tenere
# allineato — chi ha un account entra, chi non ce l'ha e' un lead. Un solo
# concetto invece di due che possono divergere.
#
# Ne discende che la migrazione degli utenti attuali **non serve**: i sei
# account che esistono oggi sono approvati per costruzione.
# ─────────────────────────────────────────────────────────────────────────────


def _sb_auth_find_by_email(email: str) -> dict | None:
    """L'utente con questa email, o None se non ha un account.

    ⚠️ Il filtro dell'admin API di GoTrue cerca «contiene», non «uguale»: senza
    il confronto esatto qui sotto, `mario@x.it` verrebbe trovato da una ricerca
    per `ario@x.it` e a quel punto chiunque scelga un'email che contiene quella
    di un cliente riceverebbe un link di accesso.
    """
    email = (email or "").strip().lower()
    if not email:
        return None
    r = req.get(f"{SUPABASE_URL}/auth/v1/admin/users", headers=_SB_H, timeout=10,
                params={"filter": email, "per_page": "50"})
    if not r.ok:
        return None
    for u in (r.json().get("users") or []):
        if (u.get("email") or "").strip().lower() == email:
            return u
    return None


def _sb_auth_magiclink(email: str, redirect_to: str) -> str | None:
    """Genera il link di accesso **senza far mandare l'email a Supabase**.

    ⚠️ Due motivi, e il secondo e' il piu' importante:
      1. il contenuto della mail resta nostro (lingua, design, mittente);
      2. **la posta predefinita di Supabase non consegna** — e' il difetto per
         cui da giorni nessuno riesce ad accedere: la chiamata risponde 200 e la
         mail non arriva mai. Generando il link qui e spedendolo con Resend, che
         gia' funziona per tutte le altre email del prodotto, il problema sparisce
         senza dover configurare l'SMTP nel pannello Supabase.

    ⚠️⚠️ **`generate_link` con `type=magiclink` CREA L'ACCOUNT se non esiste.**
    Non fallisce: risponde 200, restituisce un link valido, e da quel momento
    l'indirizzo e' un utente a tutti gli effetti — cioe' esattamente cio' che
    questo controllo deve impedire. Verificato sul campo il 03/09/2026: una
    chiamata con un indirizzo inventato ha creato l'utente, che e' stato poi
    cancellato a mano. Per questo il controllo di esistenza sta **dentro** questa
    funzione e non solo in chi la chiama: una difesa che dipende dal fatto che
    tutti si ricordino di controllare prima, prima o poi cede.
    """
    utente = _sb_auth_find_by_email(email)
    if not utente:
        return None
    # Un cliente disabilitato ha un account, quindi supererebbe il controllo di
    # esistenza: il divieto va applicato qui, dove il link nasce, altrimenti
    # «disabilita» sarebbe solo una spunta che non impedisce niente.
    if not _e_attivo(utente):
        return None

    r = req.post(f"{SUPABASE_URL}/auth/v1/admin/generate_link", headers=_SB_H, timeout=15,
                 # `redirect_to` va al primo livello: dentro `options` viene
                 # ignorato in silenzio e il link porta all'indirizzo predefinito
                 # del progetto invece che al nostro callback.
                 json={"type": "magiclink", "email": email, "redirect_to": redirect_to})
    if not r.ok:
        return None
    d = r.json()
    return d.get("action_link") or (d.get("properties") or {}).get("action_link")


def _e_admin(user: dict | None) -> bool:
    """Questo utente fa parte del team?

    ⚠️ **Il ruolo si legge da `app_metadata`, mai da `user_metadata`.** Sono due
    campi che si somigliano e fanno cose opposte: `user_metadata` lo puo'
    riscrivere l'utente stesso con la sua chiave (e' li' che sta il tema), mentre
    `app_metadata` lo tocca solo chi ha la service role. Metterci il ruolo nel
    campo sbagliato vorrebbe dire lasciare che chiunque si promuova admin da solo.

    Non serve una tabella `team_members`: crearla vuole un DDL, che le chiavi di
    servizio non fanno. `app_metadata` e' il posto che Supabase prevede per
    l'autorizzazione, ed e' gia' li'.
    """
    if not user:
        return False
    meta = user.get("app_metadata") or {}
    return meta.get("role") == "admin" or bool(meta.get("is_admin"))


def _sb_auth_set_admin(user_id: str, admin: bool = True) -> bool:
    """Promuove (o rimuove) un membro del team. Solo con la service role."""
    r = req.put(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_SB_H, timeout=15,
                json={"app_metadata": {"role": "admin" if admin else None}})
    return r.ok


def _sb_auth_users(limit: int = 200) -> list:
    """Tutti gli account. E' l'elenco clienti: essere qui significa essere approvati."""
    r = req.get(f"{SUPABASE_URL}/auth/v1/admin/users", headers=_SB_H, timeout=15,
                params={"per_page": str(limit)})
    return (r.json().get("users") or []) if r.ok else []


def _sb_auth_set_attivo(user_id: str, attivo: bool) -> bool:
    """Abilita o disabilita l'accesso di un cliente.

    ⚠️ Deve **impedire davvero il login**, non solo nascondere il cliente da un
    elenco: sta in `app_metadata`, e chi genera il magic link lo legge.
    """
    r = req.put(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_SB_H, timeout=15,
                json={"app_metadata": {"disabled": (not attivo) or None}})
    return r.ok


def _e_attivo(user: dict | None) -> bool:
    """L'accesso di questo cliente e' abilitato?"""
    if not user:
        return False
    return not (user.get("app_metadata") or {}).get("disabled")


def _sb_auth_create_user(email: str) -> dict | None:
    """Crea l'account: e' l'atto con cui un lead diventa cliente.

    `email_confirm=True` perche' l'indirizzo lo abbiamo gia' verificato noi
    parlandoci: senza, Supabase manderebbe una sua mail di conferma.
    """
    r = req.post(f"{SUPABASE_URL}/auth/v1/admin/users", headers=_SB_H, timeout=15,
                 json={"email": (email or "").strip().lower(), "email_confirm": True})
    return r.json() if r.ok else None


def _sb_auth_refresh(refresh_token: str) -> dict | None:
    r = req.post(f"{SUPABASE_URL}/auth/v1/token",
                 params={"grant_type": "refresh_token"},
                 json={"refresh_token": refresh_token},
                 headers={"apikey": SUPABASE_ANON, "Content-Type": "application/json"},
                 timeout=10)
    return r.json() if r.ok else None


def _sb_issue_resolve_manually(issue_id: str, user_id: str) -> dict | None:
    """Chiude a mano una criticità. Ritorna la riga aggiornata, None se non
    esiste o non appartiene all'utente.

    Il filtro su user_id NON è un di più: la service role key scavalca le
    politiche di sicurezza del database, quindi senza questo vincolo chiunque
    conoscesse un id potrebbe chiudere le criticità altrui.
    """
    now = datetime.now(timezone.utc).isoformat()
    r = req.patch(f"{SUPABASE_URL}/rest/v1/issue", headers=_SB_H, timeout=10,
                  params={"id": f"eq.{issue_id}", "user_id": f"eq.{user_id}"},
                  json={"status": "resolved_manually", "resolved_at": now})
    r.raise_for_status()
    righe = r.json()
    return righe[0] if righe else None


def _sb_user_theme(user: dict | None) -> str | None:
    """Tema salvato sul profilo, se c'è. Torna 'light', 'dark' o None."""
    if not user:
        return None
    t = (user.get("user_metadata") or {}).get("theme")
    return t if t in ("light", "dark") else None


def _sb_user_theme_set(user_id: str, tema: str) -> bool:
    """Salva il tema nei metadati dell'account.

    I metadati utente di Supabase Auth esistono già e reggono un oggetto
    libero: usarli evita una tabella di preferenze per un solo campo. Se un
    domani le preferenze diventeranno molte (notifiche, lingua, fuso) allora
    varrà la pena di una tabella dedicata.
    """
    if tema not in ("light", "dark"):
        return False
    r = req.put(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_SB_H,
                json={"user_metadata": {"theme": tema}}, timeout=10)
    return r.status_code < 300


# ── Roadmap pubblica: voti e iscrizioni ─────────────────────────────────────
#
# Niente tabelle nuove: si usa `tracking_event`, che ha gia' un campo libero
# (`properties`) e non pretende un progetto. I voti restano fuori dalle
# statistiche di AI Traffic perche' quelle filtrano sempre per project_id, che
# qui e' vuoto.
#
# Se un domani i voti diventeranno tanti o serviranno query aggregate, una
# tabella dedicata avra' senso: il punto di innesto sono queste tre funzioni.

_ROADMAP_VOTO = "roadmap_vote"
_ROADMAP_ISCRIZIONE = "roadmap_signup"


def _sb_roadmap_voti() -> dict:
    """Conteggio dei voti per funzionalita'."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                params={"event_name": f"eq.{_ROADMAP_VOTO}",
                        "select": "properties", "limit": "5000"})
    if r.status_code >= 300:
        return {}
    conteggio: dict = {}
    for riga in r.json():
        f = (riga.get("properties") or {}).get("feature")
        if f:
            conteggio[f] = conteggio.get(f, 0) + 1
    return conteggio


def _sb_roadmap_ha_votato(votante: str, feature: str) -> bool:
    """Vero se questo votante ha gia' votato questa funzionalita'."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                params={"event_name": f"eq.{_ROADMAP_VOTO}",
                        "properties->>votante": f"eq.{votante}",
                        "properties->>feature": f"eq.{feature}",
                        "select": "id", "limit": "1"})
    return r.status_code < 300 and bool(r.json())


def _sb_roadmap_vota(votante: str, feature: str) -> bool:
    """Registra un voto. Falso se era gia' stato espresso."""
    if _sb_roadmap_ha_votato(votante, feature):
        return False
    r = req.post(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                 json={"event_name": _ROADMAP_VOTO,
                       "properties": {"feature": feature, "votante": votante}})
    return r.status_code < 300


def _sb_roadmap_iscrivi(email: str, feature: str | None = None) -> bool:
    """Registra chi vuole essere avvisato quando una funzionalita' arriva."""
    r = req.post(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                 json={"event_name": _ROADMAP_ISCRIZIONE,
                       "properties": {"email": email, "feature": feature}})
    return r.status_code < 300


# ── Dashboard: letture in blocco ────────────────────────────────────────────
#
# La dashboard costruiva le card ciclando sui progetti e chiedendo al database
# gli audit e lo stato del tracking di ognuno: con 18 progetti erano 38 viaggi
# in fila, e la pagina ci metteva quasi 6 secondi. Queste due funzioni fanno
# lo stesso lavoro in 2 viaggi.

def _sb_audits_by_user_grouped(user_id: str, per_progetto: int = 8) -> dict:
    """Ultimi N audit di OGNI progetto dell'utente, con una sola richiesta.

    Gli audit sono poche decine in tutto: si prendono ordinati dal più recente
    e si raggruppano qui. Il tetto di 1000 righe è quello di PostgREST; se un
    giorno lo si sfiorasse, questa funzione è il punto da cui paginare.
    """
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits", headers=_SB_H, timeout=10,
                params={"user_id": f"eq.{user_id}",
                        # project_id NON è in _AUDIT_LIGHT_FIELDS: senza, il
                        # raggruppamento qui sotto non saprebbe a quale progetto
                        # appartiene ogni audit e tornerebbe sempre vuoto
                        "select": _AUDIT_LIGHT_FIELDS + ",project_id,source",
                        "order": "created_at.desc", "limit": "1000"})
    if r.status_code >= 300:
        return {}
    per_id: dict = {}
    for riga in r.json():
        pid = riga.get("project_id")
        if not pid:
            continue
        elenco = per_id.setdefault(pid, [])
        if len(elenco) < per_progetto:
            elenco.append(riga)
    return per_id


def _sb_projects_with_tracking(project_ids: list) -> set:
    """Quali progetti hanno almeno un evento di tracking.

    Qui una richiesta sola non basta: gli eventi sono migliaia e PostgREST ne
    restituisce al massimo 1000, quindi un progetto con solo eventi vecchi
    sfuggirebbe. Si fanno tante richieste quanti i progetti, ma **in
    parallelo**: ognuna chiede una riga sola, e il tempo totale è quello della
    più lenta invece della somma.
    """
    if not project_ids:
        return set()

    def ha_eventi(pid):
        try:
            r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                        params={"project_id": f"eq.{pid}", "select": "id", "limit": "1"})
            return pid if r.status_code < 300 and r.json() else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(12, len(project_ids))) as pool:
        return {pid for pid in pool.map(ha_eventi, project_ids) if pid}
