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
from urllib.parse import urlparse
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


_LINK_RICHIESTO = "link_richiesto"

# Quante richieste di link accettare per la stessa email, e in quanti minuti.
# Non e' una difesa contro un attacco vero — chi vuole cambia email a ogni giro —
# ma contro il caso normale e piu' probabile: qualcuno che non vede arrivare la
# mail e preme «invia di nuovo» dieci volte, riempiendo la sua casella e la
# nostra quota di invii.
_LINK_MAX = 4
_LINK_FINESTRA_MIN = 15


def _sb_login_evento(email: str, tipo: str, client_id: str | None = None) -> None:
    """Segna un momento del percorso di accesso.

    Due tipi, e insieme dicono una cosa che nessuno dei due direbbe da solo:
      `link_richiesto`   — e' partito un link
      `accesso_riuscito` — la sessione si e' davvero aperta
    Il divario fra i due sono i link che non vengono mai cliccati: mail che non
    arrivano, o gente che ci ripensa. Supabase espone solo `last_sign_in_at`,
    cioe' l'ultima volta e basta.
    """
    try:
        req.post(f"{SUPABASE_URL}/rest/v1/login_events", headers=_SB_H, timeout=6,
                 json={"email": (email or "").strip().lower() or None,
                       "event_type": tipo, "client_id": client_id})
    except Exception:
        pass


def _sb_link_richiesto(email: str) -> None:
    """Un link e' partito per questa email."""
    _sb_login_evento(email, "link_richiesto")


def _sb_login_riuscito(email: str, client_id: str | None = None) -> None:
    """La sessione si e' aperta davvero."""
    _sb_login_evento(email, "accesso_riuscito", client_id)


def _sb_accessi_cliente(client_id: str, email: str = "", limit: int = 40) -> list:
    """Lo storico accessi di un cliente, per la sua scheda nel pannello.

    Si cerca per `client_id` **o** per email: i primi eventi di un cliente
    nascono prima che l'account esista — quando chiede il link non sappiamo
    ancora se lo diventera' — quindi li' c'e' solo l'indirizzo.
    """
    filtri = []
    if client_id:
        filtri.append(f"client_id.eq.{client_id}")
    if email:
        filtri.append(f"email.eq.{(email or '').strip().lower()}")
    if not filtri:
        return []
    r = req.get(f"{SUPABASE_URL}/rest/v1/login_events", headers=_SB_H, timeout=15,
                params={"or": f"({','.join(filtri)})", "select": "event_type,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


def _sb_link_troppo_spesso(email: str) -> bool:
    """Questa email ha gia' chiesto troppi link di recente?

    ⚠️ Il conteggio sta nel database e non in memoria di proposito: l'app gira su
    piu' istanze serverless, e un contatore in memoria verrebbe azzerato a ogni
    avvio a freddo — cioe' non limiterebbe niente proprio quando serve.
    """
    email = (email or "").strip().lower()
    if not email:
        return False
    da = (datetime.now(timezone.utc) - timedelta(minutes=_LINK_FINESTRA_MIN)).isoformat()
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/login_events",
                    headers={**_SB_H, "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"},
                    params={"event_type": "eq.link_richiesto", "created_at": f"gte.{da}",
                            "email": f"eq.{email}", "select": "id"}, timeout=8)
        quante = int((r.headers.get("content-range") or "*/0").split("/")[-1])
    except Exception:
        # Se il conteggio non riesce non si blocca l'accesso: un limite che si
        # rompe non deve trasformarsi in una porta chiusa in faccia a un cliente.
        return False
    return quante >= _LINK_MAX


# ── Note interne su un cliente ──────────────────────────────────────────────

def _sb_note_cliente(client_id: str, limit: int = 50) -> list:
    r = req.get(f"{SUPABASE_URL}/rest/v1/client_notes", headers=_SB_H, timeout=15,
                params={"client_id": f"eq.{client_id}",
                        "select": "id,text,author_email,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


def _sb_nota_aggiungi(client_id: str, testo: str, autore_id: str, autore_email: str) -> bool:
    """Aggiunge una nota. Non si modifica e non si cancella: una nota
    commerciale che qualcuno puo' riscrivere dopo non e' piu' una traccia."""
    r = req.post(f"{SUPABASE_URL}/rest/v1/client_notes", headers=_SB_H, timeout=10,
                 json={"client_id": client_id, "text": (testo or "").strip()[:4000],
                       "author_id": autore_id, "author_email": autore_email})
    return r.status_code < 300


# ── Promemoria «installa il tracking» ───────────────────────────────────────

def _sb_promemoria_inviati(project_ids: list) -> dict:
    """Ultimo promemoria mandato, per progetto. Serve a non riscrivere a raffica."""
    if not project_ids:
        return {}
    elenco = ",".join(project_ids[:200])
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_reminders", headers=_SB_H, timeout=15,
                params={"project_id": f"in.({elenco})", "select": "project_id,sent_at,sent_to",
                        "order": "sent_at.desc", "limit": "500"})
    out: dict = {}
    for riga in (r.json() if r.ok else []):
        out.setdefault(riga["project_id"], riga)      # il primo e' il piu' recente
    return out


def _sb_promemoria_registra(project_id: str, chi: str, a_chi: str) -> bool:
    r = req.post(f"{SUPABASE_URL}/rest/v1/tracking_reminders", headers=_SB_H, timeout=10,
                 json={"project_id": project_id, "sent_by": chi, "sent_to": a_chi})
    return r.status_code < 300


# ── Lo stato di una richiesta ───────────────────────────────────────────────

def _sb_lead_stato(lead_id: str, stato: str) -> bool:
    """`nuova` | `contattata` | `ignorata`. E' lo stato intermedio che non
    corrisponde a nessun fatto osservabile — «l'ho chiamato, non ho ancora
    deciso» — e per questo, a differenza degli altri, ha bisogno di una colonna."""
    r = req.patch(f"{SUPABASE_URL}/rest/v1/contact_requests", headers=_SB_H, timeout=10,
                  json={"status": stato}, params={"id": f"eq.{lead_id}"})
    return r.status_code < 300


_ADMIN_AZIONE = "admin_action"


def _sb_admin_traccia(attore: str, azione: str, bersaglio: str = "") -> bool:
    """Registra un'azione del pannello: chi, cosa, su chi, quando.

    Stava in `tracking_event` finche' `admin_audit_log` non esisteva — quella
    tabella e' nata per il traffico di un sito e stava diventando un registro
    eventi generico. Ora ha la sua casa, con le colonne giuste al posto di un
    JSON libero: `actor_email` e `action_type` sono `NOT NULL`, quindi una riga
    monca non ci entra.
    """
    r = req.post(f"{SUPABASE_URL}/rest/v1/admin_audit_log", headers=_SB_H, timeout=10,
                 json={"actor_email": attore or "?", "action_type": azione,
                       "target": bersaglio or None})
    return r.status_code < 300


def _sb_admin_azioni(limit: int = 200) -> list:
    """Lo storico delle azioni del pannello, le piu' recenti per prime."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/admin_audit_log", headers=_SB_H, timeout=15,
                params={"select": "actor_email,action_type,target,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


def _sb_contact_requests(limit: int = 300) -> list:
    """Tutte le richieste, le piu' recenti per prime. Solo per il pannello del team."""
    r = req.get(f"{SUPABASE_URL}/rest/v1/contact_requests", headers=_SB_H, timeout=15,
                params={"select": "id,email,phone,domain,audit_id,overall,grade,status,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    return r.json() if r.ok else []


_TRAFFIC_DAILY = None


def _traffic_daily_c_e() -> bool:
    """Se la tabella di riepilogo giornaliero esiste gia' (fase H).

    ⚠️ Come per la fase G: il codice esce prima della migrazione, e nel
    frattempo la scheda deve continuare a funzionare contando gli eventi in
    Python. Si prova a leggere la tabella: se PostgREST non la conosce
    risponde con un errore invece che con dei dati.
    """
    global _TRAFFIC_DAILY
    if _TRAFFIC_DAILY is None:
        try:
            r = req.get(f"{SUPABASE_URL}/rest/v1/traffic_daily", headers=_SB_H,
                        timeout=10, params={"select": "id", "limit": "1"})
            _TRAFFIC_DAILY = r.ok
        except Exception:
            return False          # guasto di rete, non risposta sullo schema
    return bool(_TRAFFIC_DAILY)


def _sb_traffic_riepilogo(project_id: str, days: int = 30) -> list:
    """Il traffico del periodo, gia' contato per giorno.

    Trenta righe invece di dodicimila eventi. Torna lista vuota se la tabella
    non c'e' ancora: chi chiama ripiega sul conteggio in Python.
    """
    if not _traffic_daily_c_e():
        return []
    da = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/traffic_daily", headers=_SB_H, timeout=15,
                    params={"project_id": f"eq.{project_id}", "giorno": f"gte.{da}",
                            "select": "giorno,tipo,sorgente,categoria,eventi,sessioni",
                            "order": "giorno.desc", "limit": "2000"})
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_traffic_ricalcola(giorni: int = 2) -> int:
    """Rifa' il conteggio degli ultimi giorni. La chiama il cron.

    ⚠️ Ricalcola invece di sommare: sommare vuol dire sapere cosa si e' gia'
    contato, e al primo passaggio andato storto i numeri divergono per sempre
    senza che nulla lo segnali.
    """
    if not _traffic_daily_c_e():
        return 0
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/rpc/ricalcola_traffic_daily",
                     headers=_SB_H, timeout=60, json={"giorni": giorni})
        return int(r.json()) if r.ok else 0
    except Exception:
        return 0


def _sb_peso_archivio(campione: int = 60) -> dict:
    """Quanto pesa l'HTML dei report conservato, e quanto pesera'.

    ⚠️ Serve a decidere QUANDO fare la retention, non a farla. Al 22/09/2026
    sono 204 report per ~7 MB in tutto: costruire ora lo spostamento su
    Storage sarebbe macchinario per un problema che non c'e'. E cancellarli
    non sarebbe gratis — gli indirizzi `/r/{id}` stanno nelle email gia'
    mandate ai clienti, quindi buttare un HTML vecchio rompe un link che
    qualcuno puo' aver salvato.

    Si misura su un campione: scaricare l'HTML di tutti i report per pesarli
    costerebbe piu' di quanto valga la risposta.
    """
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/audits",
                    headers={**_SB_H, "Prefer": "count=exact", "Range": "0-0"},
                    timeout=15, params={"select": "id"})
        totale = int((r.headers.get("content-range") or "/0").split("/")[-1])
        r = req.get(f"{SUPABASE_URL}/rest/v1/audits", headers=_SB_H, timeout=30,
                    params={"select": "html", "order": "created_at.desc",
                            "limit": str(campione)})
        pesi = [len(x.get("html") or "") for x in (r.json() or []) if x.get("html")]
    except Exception:
        return {}
    if not pesi:
        return {"report": totale, "mb": 0.0, "kb_medi": 0}
    medio = sum(pesi) / len(pesi)
    return {"report": totale, "kb_medi": round(medio / 1024),
            "mb": round(totale * medio / 1024 / 1024, 1)}


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


_PIANO_C_E = None


def _piano_c_e() -> bool:
    """Se la colonna `plan` esiste gia' (fase I).

    ⚠️ Stessa ragione delle fasi G e H: il codice esce prima della migrazione,
    e nel frattempo il prodotto deve continuare a funzionare. Senza la colonna
    ogni progetto risulta «completo», che e' il comportamento di oggi.
    """
    global _PIANO_C_E
    if _PIANO_C_E is None:
        try:
            r = req.get(f"{SUPABASE_URL}/rest/v1/project", headers=_SB_H, timeout=10,
                        params={"select": "plan", "limit": "1"})
            _PIANO_C_E = r.ok
        except Exception:
            return False
    return bool(_PIANO_C_E)


def _sb_project_piano(project_id: str, piano: str, chi: str = "") -> bool:
    """Assegna il piano a un progetto. Torna False se la colonna non c'e'."""
    if not _piano_c_e() or piano not in ("free", "paid"):
        return False
    try:
        r = req.patch(f"{SUPABASE_URL}/rest/v1/project", headers=_SB_H, timeout=15,
                      params={"id": f"eq.{project_id}"},
                      json={"plan": piano,
                            "plan_updated_at": datetime.now(timezone.utc).isoformat(),
                            "plan_updated_by": chi or None})
        return r.status_code < 300
    except Exception:
        return False


def _sb_project_patch(project_id: str, data: dict) -> None:
    data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    req.patch(f"{SUPABASE_URL}/rest/v1/project",
              json=data, headers=_SB_H,
              params={"id": f"eq.{project_id}"}, timeout=10)


def _sb_project_bump_scan(project_id: str, frequency: str) -> None:
    """Da chiamare dopo ogni audit completato (manuale o da /scan): sposta in
    avanti la prossima esecuzione automatica in base alla cadenza del progetto."""
    _sb_project_patch(project_id, {"next_scan_at": _next_scan_at(frequency)})


# ⚠️ `engine_version` serve al grafico storico: quando il motore cambia, il
# punteggio fa un gradino che NON e' il sito a essere cambiato, ed e' l'unico
# modo che ha la pagina per dirlo invece di lasciarlo interpretare.
_AUDIT_LIGHT_FIELDS = ("id,overall,grade,band,pages_count,issues_count,critical_count,"
                       "status,engine_version,created_at")
_AUDIT_FULL_FIELDS = ("id,url,domain,status,overall,grade,band,pages_count,engine_version,"
                       "areas,site_checks,pages_detail,actions,issues_count,critical_count,"
                       "created_at,completed_at")


def _sb_audits_by_project(project_id: str, limit: int = 50, full: bool = False,
                          solo_riusciti: bool = True) -> list:
    """Gli audit del progetto, dal piu' recente.

    ⚠️ **Di default esclude quelli falliti**, e non e' un dettaglio: da settembre
    2026 un audit che fallisce lascia una riga (prima spariva in un `print`).
    Senza questo filtro «l'ultimo audit» del progetto diventerebbe il fallimento,
    e la dashboard mostrerebbe un punteggio vuoto su un progetto che sta
    benissimo — cioe' la correzione avrebbe rotto la schermata principale.

    Chi vuole vedere anche i fallimenti — il Job log del pannello — passa
    `solo_riusciti=False`.
    """
    params = {"project_id": f"eq.{project_id}",
              "select": _AUDIT_FULL_FIELDS if full else _AUDIT_LIGHT_FIELDS,
              "order": "created_at.desc", "limit": str(limit)}
    if solo_riusciti:
        params["status"] = "neq.failed"
    r = req.get(f"{SUPABASE_URL}/rest/v1/audits", headers=_SB_H, params=params, timeout=10)
    return r.json() if r.ok else []


def _sb_audit_fallito(url: str, errore: str, project_id: str | None = None,
                      user_id: str | None = None, origine: str = "auto",
                      iniziato: str | None = None) -> None:
    """Lascia traccia di un audit che non e' riuscito.

    ⚠️ Prima non la lasciava: l'errore finiva in un `print`, cioe' nei log della
    function su Vercel — che nessuno guarda e che scadono. Il risultato era che
    **se il monitoraggio automatico falliva su un cliente, non lo sapeva
    nessuno**, e il pannello non poteva mostrarlo perche' non c'era niente da
    mostrare.

    Non solleva mai: sta nel ramo di errore di qualcos'altro, e un registro che
    fa fallire cio' che stava gia' fallendo peggiora le cose e basta.

    ⚠️ `iniziato` e' l'istante in cui l'audit e' PARTITO, non quello in cui e'
    fallito. Senza, inizio e fine coincidono e il pannello mostra «0s» per un
    audit che magari ha girato due minuti prima di andare in timeout — cioe'
    proprio il numero che serviva a distinguere un timeout da un DNS che non
    risolve. Chi puo' passarlo lo passa.
    """
    try:
        ora = datetime.now(timezone.utc).isoformat()
        dominio = ""
        try:
            dominio = (urlparse(url).netloc or "").lower()
        except Exception:
            pass
        req.post(f"{SUPABASE_URL}/rest/v1/audits", headers=_SB_H, timeout=8,
                 json={"url": url, "domain": dominio or None, "status": "failed",
                       "source": origine if origine in ("manual", "auto") else "auto",
                       "project_id": project_id, "user_id": user_id,
                       "error": (errore or "")[:500],
                       "created_at": iniziato or ora, "completed_at": ora})
    except Exception:
        pass


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


def _sb_auth_get_user(user_id: str) -> dict | None:
    """Un account dal suo id. Serve a sapere a chi mandare le email di un progetto."""
    if not user_id:
        return None
    try:
        r = req.get(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_SB_H, timeout=10)
        return r.json() if r.ok else None
    except Exception:
        return None


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


def _sb_roadmap_iscrizioni(limit: int = 500) -> list:
    """Chi ha lasciato l'email per essere avvisato, dalla roadmap pubblica.

    Sono segnali commerciali quanto una richiesta di contatto: qualcuno che non
    e' ancora cliente ha detto che una cosa gli interessa, e ha lasciato un
    recapito. Il pannello li mostra accanto alle richieste dal report.
    """
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=15,
                params={"event_name": f"eq.{_ROADMAP_ISCRIZIONE}",
                        "select": "properties,created_at",
                        "order": "created_at.desc", "limit": str(limit)})
    if r.status_code >= 300:
        return []
    out = []
    for riga in r.json():
        p = riga.get("properties") or {}
        if p.get("email"):
            out.append({"email": p["email"], "feature": p.get("feature"),
                        "created_at": riga.get("created_at")})
    return out


# ── Rapporti: preferenze di invio e registro ────────────────────────────────
#
# ⚠️ Le tabelle `report_preferences` e `report_log` del documento funzionale
# NON esistono ancora: crearle vuole un DDL, e la service role key scrive righe
# ma non crea tabelle. L'SQL e' pronto in `supabase_setup.sql` (Fase E) e va
# eseguito dal pannello Supabase.
#
# Finche' non ci sono, questi dati vivono in `tracking_event`, che il prodotto
# usa gia' come registro generico. **Il codice non cambia quando le tabelle
# arriveranno**: si accorge da solo di averle e ci si sposta, perche' la scelta
# sta tutta qui dentro — `_report_tabella_c_e()` — e non nelle schermate.
#
# Il compromesso ha un costo da conoscere: su `tracking_event` una preferenza e'
# «l'ultimo evento scritto», quindi non c'e' un vincolo che impedisca due righe
# per lo stesso progetto, e la lettura deve ordinare per data. Con 27 progetti
# regge; e' il genere di cosa che smette di reggere in silenzio.

_REPORT_PREF_EVENTO = "report_pref"
_REPORT_LOG_EVENTO = "report_inviato"

# Cosa vale se nessuno ha ancora scelto niente. ⚠️ Gli alert nascono ACCESI
# perche' servono ad avvisare di un peggioramento: uno spento di default
# starebbe zitto proprio quando c'e' qualcosa da dire. Il digest al cliente
# nasce mensile — la frequenza piu' prudente da mandare a qualcuno che non l'ha
# chiesta — e quello al team settimanale.
_REPORT_PREF_DEFAULT = {
    "client_digest_frequency": "monthly",
    "team_digest_frequency": "weekly",
    "alert_score_drop": True,
    "alert_new_critical": True,
    # Resta spento e non si accende: dipende da Competitors, che non esiste.
    "alert_competitor_overtake": False,
    # Acceso per tutti su decisione di Francesco (24/09). Nasceva SPENTO per
    # una ragione che resta valida — gli altri avvisi scattano dopo un audit,
    # che e' un evento voluto e raro, mentre il traffico oscilla da solo, e
    # dopo tre email inutili non si legge piu' nemmeno quella che conta.
    #
    # Cio' che rende accettabile accenderlo sono le due condizioni sotto, non
    # il fatto che sia acceso: serve un RADDOPPIO (o un dimezzamento) E almeno
    # 20 passaggi nella settimana. Senza il minimo, «da 3 visite a 6» sarebbe
    # un +100% e partirebbe un allarme su niente. Chi alza il default senza
    # guardare quelle due soglie riapre esattamente il problema di prima.
    "alert_traffico_ai": True,
    # ⚠️ La volonta' del cliente, e sta APPOSTA in un campo suo invece che nella
    # frequenza. Se il «disiscriviti» dell'email scrivesse `frequency = off`,
    # basterebbe che qualcuno dal pannello rimettesse «Mensile» — in buona fede,
    # senza saperlo — e le email ripartirebbero verso chi aveva chiesto di non
    # riceverle piu'. Qui invece la frequenza resta quella che era, e questo
    # campo la scavalca: si spegne dal link, si riaccende solo di proposito.
    "client_unsubscribed": False,
    "client_unsubscribed_at": None,
}

_report_tabelle: dict = {}


def _report_tabella_c_e(nome: str) -> bool:
    """Vero se la tabella esiste davvero. Si chiede una volta sola per processo."""
    if nome in _report_tabelle:
        return _report_tabelle[nome]
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/{nome}", headers=_SB_H, timeout=8,
                    params={"select": "project_id", "limit": "1"})
        _report_tabelle[nome] = r.status_code < 300
    except Exception:
        _report_tabelle[nome] = False
    return _report_tabelle[nome]


def _sb_report_prefs(project_id: str) -> dict:
    """Le preferenze di un progetto, coi valori predefiniti dove manca la scelta."""
    fuori = dict(_REPORT_PREF_DEFAULT)
    try:
        if _report_tabella_c_e("report_preferences"):
            r = req.get(f"{SUPABASE_URL}/rest/v1/report_preferences", headers=_SB_H,
                        timeout=10, params={"project_id": f"eq.{project_id}", "limit": "1"})
            righe = r.json() if r.ok else []
            if righe:
                for k in fuori:
                    if righe[0].get(k) is not None:
                        fuori[k] = righe[0][k]
                # `client_unsubscribed` e' un booleano: un falso e' un valore,
                # non un'assenza, e va letto anche quando vale False.
                if "client_unsubscribed" in righe[0]:
                    fuori["client_unsubscribed"] = bool(righe[0]["client_unsubscribed"])
            return fuori

        r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                    params={"event_name": f"eq.{_REPORT_PREF_EVENTO}",
                            "project_id": f"eq.{project_id}",
                            "select": "properties,created_at",
                            "order": "created_at.desc", "limit": "1"})
        righe = r.json() if r.ok else []
        if righe:
            p = righe[0].get("properties") or {}
            for k in fuori:
                if p.get(k) is not None:
                    fuori[k] = p[k]
            if "client_unsubscribed" in p:
                fuori["client_unsubscribed"] = bool(p["client_unsubscribed"])
    except Exception:
        pass
    # ⚠️ L'avviso sul sorpasso competitor non si accende, qualunque cosa dica il
    # dato salvato: la funzionalita' che lo alimenta non esiste, e un avviso che
    # non puo' scattare e' peggio di un avviso spento — chi lo vede acceso
    # smette di controllare a mano.
    fuori["alert_competitor_overtake"] = False
    return fuori


def _sb_report_prefs_salva(project_id: str, campi: dict) -> bool:
    """Salva le preferenze cambiate. Torna falso se il salvataggio non riesce."""
    permessi = set(_REPORT_PREF_DEFAULT)
    dati = {k: v for k, v in campi.items() if k in permessi}
    # Chi si disiscrive lascia anche la data: serve a poterlo raccontare — a lui
    # o a chi chiede perche' non riceve piu' niente.
    if dati.get("client_unsubscribed") is True and "client_unsubscribed_at" not in dati:
        dati["client_unsubscribed_at"] = datetime.now(timezone.utc).isoformat()
    if dati.get("client_unsubscribed") is False:
        dati["client_unsubscribed_at"] = None
    if not dati:
        return False
    dati["alert_competitor_overtake"] = False
    try:
        if _report_tabella_c_e("report_preferences"):
            r = req.post(f"{SUPABASE_URL}/rest/v1/report_preferences", timeout=15,
                         headers={**_SB_H, "Prefer": "resolution=merge-duplicates"},
                         json={**dati, "project_id": project_id,
                               "updated_at": datetime.now(timezone.utc).isoformat()})
            return r.status_code < 300

        vecchie = _sb_report_prefs(project_id)
        r = req.post(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=15,
                     json={"event_name": _REPORT_PREF_EVENTO, "project_id": project_id,
                           "properties": {**vecchie, **dati}})
        return r.status_code < 300
    except Exception:
        return False


def _sb_report_log_scrivi(project_id: str, tipo: str, destinatario: str) -> None:
    """Traccia un invio. Non solleva: un registro che fa fallire l'invio che sta
    registrando peggiora le cose e basta."""
    try:
        if _report_tabella_c_e("report_log"):
            req.post(f"{SUPABASE_URL}/rest/v1/report_log", headers=_SB_H, timeout=10,
                     json={"project_id": project_id, "report_type": tipo,
                           "sent_to": destinatario})
            return
        req.post(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                 json={"event_name": _REPORT_LOG_EVENTO, "project_id": project_id,
                       "properties": {"report_type": tipo, "sent_to": destinatario}})
    except Exception:
        pass


def _sb_log_globale_scrivi(tipo: str, a_chi: str) -> None:
    """Registra un invio che NON riguarda un progetto solo.

    ⚠️ Esiste perché `_sb_report_log_scrivi` vuole un `project_id`, e il
    riepilogo delle approvazioni è uno per tutti. Passandogli stringa vuota la
    guardia anti-doppione rispondeva `400 invalid input syntax for type uuid`,
    quindi non funzionava mai e l'email poteva ripartire a ogni invocazione —
    difetto trovato collaudando, non in teoria. La colonna accetta NULL.
    """
    try:
        if _report_tabella_c_e("report_log"):
            req.post(f"{SUPABASE_URL}/rest/v1/report_log", headers=_SB_H, timeout=10,
                     json={"project_id": None, "report_type": tipo, "sent_to": a_chi})
    except Exception:
        pass


def _sb_log_globale_ultimo(tipo: str) -> str | None:
    """Quando è partito l'ultimo invio globale di questo tipo."""
    try:
        if not _report_tabella_c_e("report_log"):
            return None
        r = req.get(f"{SUPABASE_URL}/rest/v1/report_log", headers=_SB_H, timeout=10,
                    params={"project_id": "is.null", "report_type": f"eq.{tipo}",
                            "select": "sent_at", "order": "sent_at.desc", "limit": "1"})
        righe = r.json() if r.ok else []
        return righe[0].get("sent_at") if righe else None
    except Exception:
        return None


def _sb_report_log_ultimo(project_id: str, tipo: str) -> str | None:
    """Quando e' partito l'ultimo invio di questo tipo. None se non e' mai partito.

    ⚠️ E' il dato che impedisce di rimandare lo stesso digest ogni volta che il
    cron passa: senza, un digest «settimanale» partirebbe a ogni giro dell'ora.
    """
    try:
        if _report_tabella_c_e("report_log"):
            r = req.get(f"{SUPABASE_URL}/rest/v1/report_log", headers=_SB_H, timeout=10,
                        params={"project_id": f"eq.{project_id}",
                                "report_type": f"eq.{tipo}", "select": "sent_at",
                                "order": "sent_at.desc", "limit": "1"})
            righe = r.json() if r.ok else []
            return righe[0].get("sent_at") if righe else None

        r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                    params={"event_name": f"eq.{_REPORT_LOG_EVENTO}",
                            "project_id": f"eq.{project_id}",
                            "properties->>report_type": f"eq.{tipo}",
                            "select": "created_at", "order": "created_at.desc",
                            "limit": "1"})
        righe = r.json() if r.ok else []
        return righe[0].get("created_at") if righe else None
    except Exception:
        return None


def _sb_report_invii(project_id: str, limit: int = 20) -> list:
    """Gli ultimi invii di un progetto, per mostrarli in pagina."""
    try:
        if _report_tabella_c_e("report_log"):
            r = req.get(f"{SUPABASE_URL}/rest/v1/report_log", headers=_SB_H, timeout=10,
                        params={"project_id": f"eq.{project_id}",
                                "select": "report_type,sent_to,sent_at",
                                "order": "sent_at.desc", "limit": str(limit)})
            return r.json() if r.ok else []
        r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event", headers=_SB_H, timeout=10,
                    params={"event_name": f"eq.{_REPORT_LOG_EVENTO}",
                            "project_id": f"eq.{project_id}",
                            "select": "properties,created_at",
                            "order": "created_at.desc", "limit": str(limit)})
        out = []
        for riga in (r.json() if r.ok else []):
            p = riga.get("properties") or {}
            out.append({"report_type": p.get("report_type"), "sent_to": p.get("sent_to"),
                        "sent_at": riga.get("created_at")})
        return out
    except Exception:
        return []


# ── Monitoraggio AI ─────────────────────────────────────────────────────────
#
# Le tabelle esistono dall'8 settembre 2026 (Fase F). A differenza dei rapporti
# qui non c'e' ripiego: senza le tabelle queste funzioni tornano vuoto, e le
# schermate mostrano «in attesa dei primi dati» invece di inventarne.

def _sb_ai_progetti_da_girare(frequenza_giorni: dict) -> list:
    """I progetti attivi il cui ultimo giro e' piu' vecchio della loro frequenza.

    `frequenza_giorni` traduce `schedule_frequency` in giorni, es.
    {"weekly": 7, "monthly": 30, "custom": 7}. Un progetto mai girato viene
    per primo.
    """
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/ai_monitoring_settings", headers=_SB_H,
                    timeout=15, params={"is_active": "eq.true",
                                        "select": "project_id,schedule_frequency,"
                                                  "last_run_at,sentiment_enabled",
                                        "order": "last_run_at.asc.nullsfirst"})
        if not r.ok:
            return []
        adesso = datetime.now(timezone.utc)
        pronti = []
        for s_ in r.json() or []:
            giorni = frequenza_giorni.get(s_.get("schedule_frequency") or "weekly", 7)
            ultimo = s_.get("last_run_at")
            if not ultimo:
                pronti.append(s_); continue
            try:
                t = datetime.fromisoformat(ultimo.replace("Z", "+00:00"))
            except Exception:
                pronti.append(s_); continue
            if (adesso - t) >= timedelta(days=giorni):
                pronti.append(s_)
        return pronti
    except Exception:
        return []


def _sb_ai_impostazioni(project_id: str) -> dict:
    """Se e ogni quanto si interrogano le AI per questo progetto."""
    vuoto = {"is_active": True, "schedule_frequency": "weekly",
             "sentiment_enabled": True, "last_run_at": None}
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/ai_monitoring_settings", headers=_SB_H,
                    timeout=10, params={"project_id": f"eq.{project_id}", "limit": "1"})
        righe = r.json() if r.ok else []
        return {**vuoto, **righe[0]} if righe else vuoto
    except Exception:
        return vuoto


def _sb_ai_impostazioni_salva(project_id: str, campi: dict, chi: str = "") -> bool:
    permessi = {"is_active", "schedule_frequency", "sentiment_enabled", "last_run_at"}
    dati = {k: v for k, v in campi.items() if k in permessi}
    if not dati:
        return False
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/ai_monitoring_settings", timeout=15,
                     headers={**_SB_H, "Prefer": "resolution=merge-duplicates"},
                     json={**dati, "project_id": project_id, "updated_by": chi or None,
                           "updated_at": datetime.now(timezone.utc).isoformat()})
        return r.status_code < 300
    except Exception:
        return False


def _sb_ai_argomenti(project_id: str) -> list:
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/monitored_topics", headers=_SB_H, timeout=15,
                    params={"project_id": f"eq.{project_id}", "select": "id,name,created_at",
                            "order": "created_at"})
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_ai_domande(project_id: str, solo_attive: bool = True) -> list:
    """Le domande monitorate, con l'argomento di ognuna.

    ⚠️ Le domande appartengono a un argomento, e l'argomento a un progetto: non
    c'e' `project_id` sulla domanda. Si passa dagli argomenti, altrimenti si
    leggerebbero le domande di tutti.
    """
    argomenti = _sb_ai_argomenti(project_id)
    if not argomenti:
        return []
    per_id = {a["id"]: a["name"] for a in argomenti}
    try:
        p = {"topic_id": f"in.({','.join(per_id)})",
             # ⚠️ `approved` si chiede solo se la colonna c'e': prima della
             # migrazione PostgREST rifiuterebbe l'intera query, e il
             # monitoraggio si fermerebbe su tutti i progetti.
             "select": "id,topic_id,prompt_text,intent,source,active,created_at"
                       + (",approved" if _fase_g_c_e() else ""),
             "order": "created_at"}
        if solo_attive:
            p["active"] = "is.true"
        r = req.get(f"{SUPABASE_URL}/rest/v1/monitored_prompts", headers=_SB_H,
                    timeout=15, params=p)
        return [{**d, "argomento": per_id.get(d.get("topic_id"), "")}
                for d in (r.json() if r.ok else [])]
    except Exception:
        return []


def _sb_ai_argomento_crea(project_id: str, nome: str) -> str:
    """Crea un argomento e ne torna l'id. Se c'e' gia', torna quello esistente."""
    for a in _sb_ai_argomenti(project_id):
        if (a.get("name") or "").strip().lower() == (nome or "").strip().lower():
            return a["id"]
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/monitored_topics", timeout=15,
                     headers={**_SB_H, "Prefer": "return=representation"},
                     json={"project_id": project_id, "name": nome})
        return (r.json() or [{}])[0].get("id", "") if r.status_code < 300 else ""
    except Exception:
        return ""


def _sb_ai_domanda_crea(topic_id: str, testo: str, intent: str = "",
                        origine: str = "auto_generated") -> str:
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/monitored_prompts", timeout=15,
                     headers={**_SB_H, "Prefer": "return=representation"},
                     json={"topic_id": topic_id, "prompt_text": testo,
                           "intent": intent or None, "source": origine})
        return (r.json() or [{}])[0].get("id", "") if r.status_code < 300 else ""
    except Exception:
        return ""


def _sb_ai_domanda_modifica(prompt_id: str, testo: str) -> bool:
    """Cambia il testo di una domanda. ⚠️ Una domanda riscritta a mano NON
    resta «generata»: la fonte passa a `manual`, e se era da approvare resta
    da approvare — chi la modifica non e' detto sia chi la approva."""
    try:
        r = req.patch(f"{SUPABASE_URL}/rest/v1/monitored_prompts", headers=_SB_H,
                      timeout=15, params={"id": f"eq.{prompt_id}"},
                      json={"prompt_text": testo.strip()[:500], "source": "manual"})
        return r.status_code < 300
    except Exception:
        return False


def _sb_ai_domanda_elimina(prompt_id: str) -> bool:
    """Toglie una domanda dal monitoraggio.

    ⚠️ Non e' una DELETE: la si disattiva. La tabella delle risposte punta
    alla domanda con ON DELETE CASCADE, quindi cancellarla porterebbe via
    tutte le risposte e le citazioni raccolte su di essa — e il punteggio dei
    periodi passati cambierebbe retroattivamente. Una domanda disattivata non
    entra piu' nei giri (`_sb_ai_domande` legge solo le attive) ma lo storico
    resta quello misurato allora.
    """
    try:
        r = req.patch(f"{SUPABASE_URL}/rest/v1/monitored_prompts", headers=_SB_H,
                      timeout=15, params={"id": f"eq.{prompt_id}"},
                      json={"active": False})
        return r.status_code < 300
    except Exception:
        return False


def _sb_ai_esecuzione_scrivi(prompt_id: str, project_id: str, provider: str,
                             modello: str, testo: str, stato: str = "completed",
                             errore: str = "", batch_id: str = "") -> str:
    """Registra una risposta di un motore. Torna l'id della riga.

    ⚠️ Si registra anche quando FALLISCE: un motore che non risponde e un motore
    che risponde senza citare nessuno sono due cose diverse, e confonderle in
    uno zero falserebbe il punteggio di visibilita'.
    """
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/prompt_runs", timeout=20,
                     headers={**_SB_H, "Prefer": "return=representation"},
                     json={"prompt_id": prompt_id, "project_id": project_id,
                           "provider": provider, "model_used": modello,
                           "response_text": (testo or "")[:20000],
                           "status": stato, "error": (errore or "")[:500] or None,
                           # ⚠️ solo dopo la fase G: prima la colonna non c'e' e
                           # PostgREST rifiuterebbe l'intera riga
                           **({"batch_id": batch_id} if batch_id and _fase_g_c_e() else {})})
        return (r.json() or [{}])[0].get("id", "") if r.status_code < 300 else ""
    except Exception:
        return ""


def _sb_ai_citazioni_scrivi(run_id: str, project_id: str, citazioni: list) -> int:
    """Salva in blocco le citazioni di una risposta. Torna quante ne ha scritte."""
    if not run_id or not citazioni:
        return 0
    righe = [{"prompt_run_id": run_id, "project_id": project_id,
              "cited_domain": c.get("dominio") or "", "cited_url": c.get("url"),
              "is_target": bool(c.get("e_il_cliente")),
              "citation_category": c.get("categoria"),
              "sentiment": c.get("sentiment") or None,
              "context_snippet": (c.get("titolo") or "")[:500] or None}
             for c in citazioni if c.get("dominio")]
    if not righe:
        return 0
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/extracted_citations", headers=_SB_H,
                     timeout=25, json=righe)
        return len(righe) if r.status_code < 300 else 0
    except Exception:
        return 0


def _sb_ai_esecuzioni(project_id: str, giorni: int = 30, limit: int = 2000) -> list:
    da = (datetime.now(timezone.utc) - timedelta(days=giorni)).isoformat()
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/prompt_runs", headers=_SB_H, timeout=20,
                    params={"project_id": f"eq.{project_id}", "run_at": f"gte.{da}",
                            "select": "id,prompt_id,provider,model_used,run_at,status,"
                                      "response_text"
                                      + (",batch_id" if _fase_g_c_e() else ""),
                            "order": "run_at.desc", "limit": str(limit)})
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_ai_citazioni(project_id: str, giorni: int = 30, limit: int = 5000) -> list:
    da = (datetime.now(timezone.utc) - timedelta(days=giorni)).isoformat()
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/extracted_citations", headers=_SB_H,
                    timeout=25,
                    params={"project_id": f"eq.{project_id}", "created_at": f"gte.{da}",
                            "select": "prompt_run_id,cited_domain,cited_url,is_target,"
                                      "citation_category,sentiment,created_at",
                            "order": "created_at.desc", "limit": str(limit)})
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_ai_citazioni_categoria(project_id: str, dominio: str, categoria: str,
                               giorni: int = 30) -> bool:
    """Riscrive la categoria di tutte le citazioni di un dominio.

    ⚠️ La categoria si decide al salvataggio, quando l'elenco dei concorrenti
    e' quello di allora. Se un dominio viene riconosciuto come concorrente
    dopo, le righe gia' scritte restano indietro: serve poterle correggere,
    o lo storico e il presente raccontano due cose diverse.
    """
    da = (datetime.now(timezone.utc) - timedelta(days=giorni)).isoformat()
    try:
        r = req.patch(f"{SUPABASE_URL}/rest/v1/extracted_citations", headers=_SB_H,
                      timeout=20,
                      params={"project_id": f"eq.{project_id}",
                              "cited_domain": f"eq.{dominio.lower()}",
                              "created_at": f"gte.{da}"},
                      json={"citation_category": categoria})
        return r.status_code < 300
    except Exception:
        return False


def _sb_ai_citazione_url(citazione_id: str, url: str) -> bool:
    try:
        r = req.patch(f"{SUPABASE_URL}/rest/v1/extracted_citations", headers=_SB_H,
                      timeout=15, params={"id": f"eq.{citazione_id}"}, json={"cited_url": url})
        return r.status_code < 300
    except Exception:
        return False


def _sb_ai_citazioni_con_redirect(limit: int = 500) -> list:
    """Le citazioni salvate con l'URL di redirect di Google al posto della
    pagina vera. Sono quelle dei giri fatti prima del 15/09; si risolvono una
    volta e non tornano piu'."""
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/extracted_citations", headers=_SB_H,
                    timeout=20, params={"cited_url": "like.*vertexaisearch.cloud.google.com*",
                                        "select": "id,cited_url", "limit": str(limit)})
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_ai_ha_dati(project_id: str) -> bool:
    """Se almeno un giro e' andato a buon fine.

    ⚠️ E' la condizione che distingue «in attesa dei primi dati» da «ecco i
    dati»: il documento la lasciava da confermare, e questa e' la risposta —
    almeno una esecuzione COMPLETATA, non semplicemente tentata.
    """
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/prompt_runs", headers=_SB_H, timeout=10,
                    params={"project_id": f"eq.{project_id}", "status": "eq.completed",
                            "select": "id", "limit": "1"})
        return bool(r.json()) if r.ok else False
    except Exception:
        return False


def _sb_ai_concorrenti(project_id: str, solo_attivi: bool = True) -> list:
    try:
        p = {"project_id": f"eq.{project_id}",
             "select": "id,domain,source,added_by,status,created_at", "order": "created_at"}
        if solo_attivi:
            p["status"] = "eq.active"
        r = req.get(f"{SUPABASE_URL}/rest/v1/project_competitors", headers=_SB_H,
                    timeout=15, params=p)
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_ai_concorrente_aggiungi(project_id: str, dominio: str, origine: str,
                                chi: str = "") -> bool:
    """⚠️ Se il dominio c'era ed era stato escluso, si RIATTIVA invece di
    creare un doppione: la tabella ha un vincolo di unicita' e un insert
    fallirebbe, lasciando l'utente col dubbio di aver sbagliato qualcosa.

    ⚠️ `on_conflict` non e' facoltativo. PostgREST fonde sulla CHIAVE PRIMARIA
    se non gli si dice altro, e qui la primaria e' un uuid generato: non va mai
    in conflitto, quindi l'upsert diventava un insert e sbatteva sul vincolo
    (project_id, domain) con un 409. La funzione tornava False in silenzio e
    nessun concorrente gia' presente poteva piu' essere riaggiunto.
    """
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/project_competitors", timeout=15,
                     headers={**_SB_H, "Prefer": "resolution=merge-duplicates"},
                     params={"on_conflict": "project_id,domain"},
                     json={"project_id": project_id, "domain": dominio.lower(),
                           "source": origine, "added_by": chi or None,
                           "status": "active"})
        return r.status_code < 300
    except Exception:
        return False


def _sb_ai_concorrente_escludi(project_id: str, dominio: str) -> bool:
    """Non cancella: segna «escluso», cosi' al prossimo giro di suggerimenti il
    motore non lo ripropone. Era un punto aperto del documento (§3.3)."""
    try:
        r = req.patch(f"{SUPABASE_URL}/rest/v1/project_competitors", headers=_SB_H,
                      timeout=15,
                      params={"project_id": f"eq.{project_id}",
                              "domain": f"eq.{dominio.lower()}"},
                      json={"status": "excluded"})
        return r.status_code < 300
    except Exception:
        return False


_FASE_G = None


def _fase_g_c_e() -> bool:
    """Se la migrazione della fase G e' gia' stata eseguita sul database.

    ⚠️ Serve perche' il codice esce prima della migrazione: Silvio esegue lo
    script quando puo', e nel frattempo il monitoraggio non deve fermarsi.
    Si prova a leggere una colonna nuova: se PostgREST non la conosce risponde
    con un errore invece che con dei dati.

    Il risultato si tiene in memoria: e' una domanda la cui risposta cambia
    una volta sola nella vita del prodotto.
    """
    global _FASE_G
    if _FASE_G is None:
        try:
            r = req.get(f"{SUPABASE_URL}/rest/v1/prompt_runs", headers=_SB_H, timeout=10,
                        params={"select": "batch_id", "limit": "1"})
            _FASE_G = r.ok
        except Exception:
            return False          # ⚠️ non si memorizza: e' un guasto di rete,
                                  # non una risposta sullo schema
    return bool(_FASE_G)


def _sb_ai_snapshot_ultimo(project_id: str, escludi_batch: str = "") -> dict:
    """L'ultima fotografia salvata, per calcolare l'andamento del giro nuovo.

    ⚠️ `escludi_batch` toglie dal confronto la fotografia del giro corrente,
    se ne e' gia' stata scritta una: senza, un ricalcolo confronterebbe il giro
    con se stesso e l'andamento risulterebbe sempre zero.
    """
    try:
        p = {"project_id": f"eq.{project_id}",
             "select": "visibility_score,period_end,created_at",
             "order": "created_at.desc", "limit": "2"}
        r = req.get(f"{SUPABASE_URL}/rest/v1/ai_visibility_snapshots",
                    headers=_SB_H, timeout=15, params=p)
        if not r.ok:
            return {}
        righe = r.json() or []
        if escludi_batch and _fase_g_c_e():
            q = dict(p, select="visibility_score,batch_id,created_at")
            r2 = req.get(f"{SUPABASE_URL}/rest/v1/ai_visibility_snapshots",
                         headers=_SB_H, timeout=15, params=q)
            if r2.ok:
                righe = [x for x in (r2.json() or [])
                         if x.get("batch_id") != escludi_batch]
        return righe[0] if righe else {}
    except Exception:
        return {}


def _sb_ai_domande_da_approvare(project_id: str) -> list:
    """Le domande generate che aspettano il via libera dell'admin.

    Prima della migrazione non esiste il concetto di approvazione: torna una
    lista vuota, che e' la risposta onesta — non «non ce ne sono», ma «qui non
    si approva ancora niente». Chi chiama distingue i due casi con
    `_fase_g_c_e()`.
    """
    if not _fase_g_c_e():
        return []
    argomenti = _sb_ai_argomenti(project_id)
    if not argomenti:
        return []
    ids = ",".join(a["id"] for a in argomenti)
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/monitored_prompts", headers=_SB_H,
                    timeout=15,
                    params={"topic_id": f"in.({ids})", "approved": "is.false",
                            "select": "id,topic_id,prompt_text,intent,source,created_at",
                            "order": "created_at"})
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_ai_da_approvare_per_progetto() -> list:
    """Quante domande aspettano il via libera, progetto per progetto.

    Serve al riepilogo settimanale chiesto da Francesco (24/09). Torna solo i
    progetti che ne hanno almeno una, con dominio e conteggio, ordinati dal
    più arretrato.

    ⚠️ Tre query in tutto, non una per progetto. Con trenta progetti la
    versione ingenua ne farebbe sessanta e il cron di Vercel non ci sta
    dentro; e il numero di query non deve crescere col parco, altrimenti
    funziona adesso e smette di funzionare quando i clienti aumentano.
    """
    if not _fase_g_c_e():
        return []
    try:
        arg = req.get(f"{SUPABASE_URL}/rest/v1/monitored_topics", headers=_SB_H,
                      timeout=20, params={"select": "id,project_id", "limit": "2000"})
        if not arg.ok:
            return []
        di_chi = {a["id"]: a.get("project_id") for a in arg.json()}
        if not di_chi:
            return []

        dom = req.get(f"{SUPABASE_URL}/rest/v1/monitored_prompts", headers=_SB_H,
                      timeout=20,
                      params={"select": "id,topic_id,created_at",
                              "approved": "is.false", "active": "is.true",
                              "limit": "5000"})
        if not dom.ok:
            return []
        conteggio: dict = {}
        for d in dom.json():
            pid = di_chi.get(d.get("topic_id"))
            if not pid:
                continue
            v = conteggio.setdefault(pid, {"project_id": pid, "quante": 0,
                                           "piu_vecchia": d.get("created_at") or ""})
            v["quante"] += 1
            se = d.get("created_at") or ""
            if se and (not v["piu_vecchia"] or se < v["piu_vecchia"]):
                v["piu_vecchia"] = se
        if not conteggio:
            return []

        pr = req.get(f"{SUPABASE_URL}/rest/v1/project", headers=_SB_H, timeout=20,
                     params={"select": "id,domain,name",
                             "id": f"in.({','.join(conteggio)})"})
        nomi = {p["id"]: (p.get("domain") or p.get("name") or "")
                for p in (pr.json() if pr.ok else [])}
        fuori = []
        for pid, v in conteggio.items():
            fuori.append({**v, "dominio": nomi.get(pid, "")})
        fuori.sort(key=lambda x: (x["piu_vecchia"] or "9999"))
        return fuori
    except Exception:
        return []


def _sb_ai_domanda_approva(prompt_ids: list, chi: str = "") -> int:
    """Segna approvate le domande indicate. Torna quante ne ha aggiornate."""
    if not prompt_ids or not _fase_g_c_e():
        return 0
    try:
        r = req.patch(f"{SUPABASE_URL}/rest/v1/monitored_prompts", timeout=20,
                      headers={**_SB_H, "Prefer": "return=representation"},
                      params={"id": f"in.({','.join(prompt_ids)})"},
                      json={"approved": True,
                            "approved_at": datetime.now(timezone.utc).isoformat(),
                            "approved_by": chi or None})
        return len(r.json() or []) if r.ok else 0
    except Exception:
        return 0


def _sb_ai_snapshot_scrivi(project_id: str, inizio: str, fine: str,
                           punteggio: float, per_provider: dict,
                           batch_id: str = "", domande: int = 0,
                           delta: float = None) -> bool:
    """⚠️ I campi del giro (batch_id, domande contate, andamento) si scrivono
    solo se la migrazione della fase G c'e' gia': prima, quelle colonne non
    esistono e PostgREST rifiuterebbe l'intera riga — perdendo anche il
    punteggio, che invece si puo' salvare benissimo."""
    extra, params, testate = {}, {}, {**_SB_H}
    if _fase_g_c_e():
        # Dopo la migrazione ogni giro ha la sua fotografia: inserimento
        # normale, nessuna fusione. E' il senso di «una per giro».
        extra = {"batch_id": batch_id or None,
                 "prompts_counted": domande or None,
                 "delta_vs_previous": delta}
    else:
        # ⚠️ Prima della migrazione vale ancora il vincolo vecchio, uno per
        # periodo di date: due giri lo stesso giorno collidono. Si sovrascrive
        # la riga del periodo, indicando SU COSA fondere.
        #
        # `on_conflict` non e' facoltativo: senza, PostgREST fonde sulla chiave
        # primaria, che qui e' un uuid generato e non collide mai — l'upsert
        # diventa un insert, sbatte sul vincolo e torna 409. E' successo
        # davvero: di tre fotografie ne era rimasta salvata solo la prima,
        # quella del giro con le domande sbagliate, e l'andamento si sarebbe
        # calcolato contro quella per sempre.
        testate["Prefer"] = "resolution=merge-duplicates"
        params = {"on_conflict": "project_id,period_start,period_end"}
    try:
        r = req.post(f"{SUPABASE_URL}/rest/v1/ai_visibility_snapshots", timeout=15,
                     headers=testate, params=params,
                     json={**extra,
                           "project_id": project_id, "period_start": inizio,
                           "period_end": fine, "visibility_score": punteggio,
                           "breakdown_by_provider": per_provider})
        return r.status_code < 300
    except Exception:
        return False


def _sb_ai_snapshot(project_id: str, limit: int = 6) -> list:
    """Gli ultimi periodi misurati, dal piu' recente. Serve al grafico del trend."""
    try:
        r = req.get(f"{SUPABASE_URL}/rest/v1/ai_visibility_snapshots", headers=_SB_H,
                    timeout=15,
                    params={"project_id": f"eq.{project_id}",
                            "select": "period_start,period_end,visibility_score,"
                                      "breakdown_by_provider,created_at"
                                      + (",batch_id,prompts_counted,delta_vs_previous"
                                         if _fase_g_c_e() else ""),
                            "order": "created_at.desc", "limit": str(limit)})
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_llm_config(provider: str = "") -> list:
    """La configurazione dei provider. ⚠️ La chiave torna CIFRATA: chi legge
    questa funzione non ha in mano niente di utilizzabile finche' non la
    decifra, e la decifratura sta in un punto solo (`ai_chiavi.py`)."""
    try:
        p = {"select": "provider,api_key_encrypted,default_model,updated_at,updated_by"}
        if provider:
            p["provider"] = f"eq.{provider}"
        r = req.get(f"{SUPABASE_URL}/rest/v1/llm_provider_config", headers=_SB_H,
                    timeout=10, params=p)
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_llm_config_salva(provider: str, chiave_cifrata: str = "",
                         modello: str = "", chi: str = "") -> bool:
    dati = {"provider": provider,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": chi or None}
    if chiave_cifrata:
        dati["api_key_encrypted"] = chiave_cifrata
    if modello:
        dati["default_model"] = modello
    try:
        if not chiave_cifrata:
            # ⚠️ Senza la chiave non si puo' fare upsert: la colonna e' NOT
            # NULL e l'INSERT dell'upsert la vuole anche quando poi si limita
            # ad aggiornare. Si aggiorna la riga che c'e' — e se non c'e', la
            # risposta e' «no»: un modello senza chiave non ha senso.
            r = req.patch(f"{SUPABASE_URL}/rest/v1/llm_provider_config", timeout=15,
                          headers={**_SB_H, "Prefer": "return=representation"},
                          params={"provider": f"eq.{provider}"}, json=dati)
            return r.ok and bool(r.json())
        r = req.post(f"{SUPABASE_URL}/rest/v1/llm_provider_config", timeout=15,
                     headers={**_SB_H, "Prefer": "resolution=merge-duplicates"},
                     json=dati)
        return r.status_code < 300
    except Exception:
        return False


def _sb_llm_modelli(provider: str = "") -> list:
    try:
        p = {"select": "provider,model_id,supports_web_search,fetched_at",
             "order": "model_id"}
        if provider:
            p["provider"] = f"eq.{provider}"
        r = req.get(f"{SUPABASE_URL}/rest/v1/llm_available_models", headers=_SB_H,
                    timeout=15, params=p)
        return r.json() if r.ok else []
    except Exception:
        return []


def _sb_llm_modelli_salva(provider: str, modelli: list) -> int:
    """Sostituisce l'elenco dei modelli di un provider con quello appena letto."""
    try:
        req.delete(f"{SUPABASE_URL}/rest/v1/llm_available_models", headers=_SB_H,
                   timeout=15, params={"provider": f"eq.{provider}"})
        if not modelli:
            return 0
        righe = [{"provider": provider, "model_id": m["id"],
                  "supports_web_search": bool(m.get("sa_cercare"))} for m in modelli]
        r = req.post(f"{SUPABASE_URL}/rest/v1/llm_available_models", headers=_SB_H,
                     timeout=25, json=righe)
        return len(righe) if r.status_code < 300 else 0
    except Exception:
        return 0


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
