"""
GEO Audit — servizio web
Scan sincrono → salva su Supabase via REST → report oscurato → sblocco via email.
"""
import os, hmac, hashlib, json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import requests as req
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

import geo_audit

app = FastAPI(title="GEO Audit · verticalai")

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ── Config ──────────────────────────────────────────────────────────────────
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_SVC  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPABASE_ANON = os.environ.get("SUPABASE_ANON_KEY", "")
RESEND_KEY   = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL   = os.environ.get("FROM_EMAIL", "")
SITE_URL     = os.environ.get("SITE_URL", "").rstrip("/")
_SECRET      = os.environ.get("CRON_SECRET", "fallback-secret").encode()

_HERE = os.path.dirname(os.path.abspath(__file__))
FORM_HTML     = open(os.path.join(_HERE, "templates", "form.html"),          encoding="utf-8").read()
HOME_HTML     = open(os.path.join(_HERE, "templates", "home.html"),          encoding="utf-8").read()
PRIVACY_HTML  = open(os.path.join(_HERE, "templates", "privacy.html"),       encoding="utf-8").read()
COOKIE_HTML   = open(os.path.join(_HERE, "templates", "cookie.html"),        encoding="utf-8").read()
ROADMAP_HTML  = open(os.path.join(_HERE, "templates", "roadmap.html"),       encoding="utf-8").read()
LOGIN_HTML    = open(os.path.join(_HERE, "templates", "login.html"),         encoding="utf-8").read()
AUTH_CB_HTML  = open(os.path.join(_HERE, "templates", "auth_callback.html"), encoding="utf-8").read()
DASHBOARD_HTML = open(os.path.join(_HERE, "templates", "dashboard.html"),    encoding="utf-8").read()
PROJECT_HTML   = open(os.path.join(_HERE, "templates", "project.html"),      encoding="utf-8").read()


def _render(tpl: str, **kv) -> str:
    """Sostituisce i placeholder {{CHIAVE}} nel template."""
    for k, v in kv.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    return tpl

# Supabase REST headers (service role bypassa RLS)
_SB_H = {
    "apikey": SUPABASE_SVC,
    "Authorization": f"Bearer {SUPABASE_SVC}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# ── Supabase helpers (usa requests, non supabase-py) ────────────────────────

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


def _sb_insert_contact(data: dict):
    r = req.post(f"{SUPABASE_URL}/rest/v1/contact_requests",
                 json=data, headers=_SB_H, timeout=10)
    r.raise_for_status()


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


# ── Project helpers ───────────────────────────────────────────────────────────

_SCAN_INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}
_SCAN_FREQUENCY_LABELS = {"daily": "Giornaliero", "weekly": "Settimanale", "monthly": "Mensile"}


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


# ── Issue lifecycle helpers ───────────────────────────────────────────────────

def _sb_issues_by_project(project_id: str, status: str | None = None) -> list:
    params = {"project_id": f"eq.{project_id}", "select": "*", "order": "severity.asc,last_seen_at.desc"}
    if status:
        params["status"] = f"eq.{status}"
    r = req.get(f"{SUPABASE_URL}/rest/v1/issue", headers=_SB_H, params=params, timeout=10)
    return r.json() if r.ok else []


def _sb_issue_sync(project_id: str, user_id: str, audit_id: str, checks: list) -> None:
    """Ciclo di vita delle issue del progetto: apre/aggiorna quelle presenti nei
    check warn/fail dell'audit appena completato, marca risolte quelle aperte in
    precedenza e non più viste in questo run."""
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


# ── Tracking first-party (v1.3 · AI Traffic) ─────────────────────────────────

_AI_REFERRER_DOMAINS = {
    "chat.openai.com": "ChatGPT",
    "chatgpt.com": "ChatGPT",
    "perplexity.ai": "Perplexity",
    "www.perplexity.ai": "Perplexity",
    "gemini.google.com": "Gemini",
    "bard.google.com": "Gemini",
    "claude.ai": "Claude",
    "copilot.microsoft.com": "Copilot",
    "you.com": "You.com",
    "meta.ai": "Meta AI",
}


def _detect_ai_source(referrer: str) -> str | None:
    if not referrer:
        return None
    try:
        host = urlparse(referrer).netloc.lower()
    except Exception:
        return None
    return _AI_REFERRER_DOMAINS.get(host)


def _sb_insert_tracking_event(data: dict) -> None:
    req.post(f"{SUPABASE_URL}/rest/v1/tracking_event", json=data, headers=_SB_H, timeout=5)


def _sb_tracking_events(project_id: str, days: int = 30, limit: int = 5000) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event",
                headers=_SB_H,
                params={"project_id": f"eq.{project_id}", "created_at": f"gte.{since}",
                        "select": "event_name,session_id,page_url,ai_source,created_at",
                        "order": "created_at.desc", "limit": str(limit)},
                timeout=10)
    return r.json() if r.ok else []


def _sb_has_tracking(project_id: str) -> bool:
    r = req.get(f"{SUPABASE_URL}/rest/v1/tracking_event",
                headers=_SB_H,
                params={"project_id": f"eq.{project_id}", "select": "id", "limit": "1"},
                timeout=10)
    return bool(r.json()) if r.ok else False


# ── Token helpers ────────────────────────────────────────────────────────────

def _make_token(job_id: str) -> str:
    """Token HMAC deterministico: non serve salvarlo nel DB."""
    return hmac.new(_SECRET, job_id.encode(), hashlib.sha256).hexdigest()


def _valid_token(job_id: str, token: str) -> bool:
    return hmac.compare_digest(_make_token(job_id), token)


def _has_access(request: Request, job_id: str) -> bool:
    """True se l'utente ha già un cookie di accesso valido per questo report."""
    cookie = request.cookies.get(f"geo-access-{job_id}", "")
    return _valid_token(job_id, cookie)


# ── Auth helpers (Supabase Auth · magic link) ────────────────────────────────

_AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 giorni (rinnovato ad ogni refresh)


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie("sb-access-token", access_token,
                         httponly=True, secure=True, samesite="lax",
                         max_age=_AUTH_COOKIE_MAX_AGE)
    response.set_cookie("sb-refresh-token", refresh_token,
                         httponly=True, secure=True, samesite="lax",
                         max_age=_AUTH_COOKIE_MAX_AGE)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("sb-access-token")
    response.delete_cookie("sb-refresh-token")


def _sb_auth_user(access_token: str) -> dict | None:
    r = req.get(f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_ANON, "Authorization": f"Bearer {access_token}"},
                timeout=10)
    return r.json() if r.ok else None


def _sb_auth_refresh(refresh_token: str) -> dict | None:
    r = req.post(f"{SUPABASE_URL}/auth/v1/token",
                 params={"grant_type": "refresh_token"},
                 json={"refresh_token": refresh_token},
                 headers={"apikey": SUPABASE_ANON, "Content-Type": "application/json"},
                 timeout=10)
    return r.json() if r.ok else None


def _current_user(request: Request) -> tuple[dict | None, dict | None]:
    """Utente loggato (via cookie sb-access-token), con refresh trasparente.
    Ritorna (user, refreshed_tokens): refreshed_tokens è {access_token,
    refresh_token} da riscrivere nei cookie della risposta se non None
    (i cookie iniettati via Response non sopravvivono se la route ritorna
    direttamente un altro oggetto Response, quindi il refresh va applicato
    esplicitamente da chi chiama)."""
    access = request.cookies.get("sb-access-token", "")
    if access:
        user = _sb_auth_user(access)
        if user:
            return user, None

    refresh = request.cookies.get("sb-refresh-token", "")
    if not refresh:
        return None, None

    session = _sb_auth_refresh(refresh)
    if not session or not session.get("access_token"):
        return None, None

    user = _sb_auth_user(session["access_token"])
    if not user:
        return None, None
    return user, {"access_token": session["access_token"], "refresh_token": session["refresh_token"]}


def _apply_refresh(response: Response, refreshed: dict | None) -> Response:
    if refreshed:
        _set_auth_cookies(response, refreshed["access_token"], refreshed["refresh_token"])
    return response


# ── Email helpers ─────────────────────────────────────────────────────────────

_NOTIFY_TO = ["geo@verticalai.it", "info@verticalai.it"]

_EMAIL_FONTS = (
    'https://fonts.googleapis.com/css2?'
    'family=Space+Grotesk:wght@500;600;700'
    '&family=Inter:wght@400;500;600;700'
    '&family=JetBrains+Mono:wght@500;600&display=swap'
)

_EMAIL_HEAD = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<link href="{fonts}" rel="stylesheet">
<style>
  :root{{color-scheme:light dark;supported-color-schemes:light dark}}
  body,table,td{{margin:0;padding:0}}
  img{{border:0;line-height:100%;-ms-interpolation-mode:bicubic}}
  table{{border-collapse:collapse!important}}
  a{{text-decoration:none}}
  @media only screen and (max-width:600px){{
    .container{{width:100%!important}}
    .px{{padding-left:22px!important;padding-right:22px!important}}
    .stack{{display:block!important;width:100%!important;padding-bottom:14px!important}}
    .btn a{{display:block!important}}
    .h1{{font-size:21px!important}}
    .scorebig{{font-size:52px!important}}
  }}
  @media (prefers-color-scheme:dark){{
    .bg-canvas{{background:#0B0A12!important}}
    .bg-card{{background:#131220!important}}
    .bg-soft{{background:#1A1925!important}}
    .t-ink{{color:#F4F3F8!important}}
    .t-2{{color:#BCBBCB!important}}
    .t-3{{color:#8A8A9E!important}}
    .brd{{border-color:#272636!important}}
    .hairline{{background:#272636!important}}
  }}
</style>
""".format(fonts=_EMAIL_FONTS)


def _email_logo_row(right_text: str = "GEO Audit") -> str:
    return (
        '<tr><td class="px" style="padding:4px 8px 18px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td align="left">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="width:30px;height:30px;background:#5A45D8;border-radius:9px;'
        'text-align:center;vertical-align:middle">'
        '<span style="color:#fff;font-size:15px;font-weight:600;'
        "font-family:'JetBrains Mono','Courier New',monospace\">V</span>"
        '</td>'
        '<td style="padding-left:10px">'
        '<span class="t-ink" style="font-size:15px;font-weight:600;color:#16151E;'
        "font-family:'Space Grotesk',Arial,sans-serif\">"
        '<span style="color:#5A45D8">vertical</span>ai</span>'
        '</td>'
        '</tr></table>'
        '</td>'
        f'<td align="right" class="t-3" style="font-size:11px;letter-spacing:.12em;'
        f'text-transform:uppercase;color:#76768A;'
        f"font-family:'JetBrains Mono','Courier New',monospace\">{right_text}</td>"
        '</tr></table>'
        '</td></tr>'
    )


def _email_footer() -> str:
    return (
        '<tr><td class="px" style="padding:24px 28px">'
        '<p class="t-3" style="font-size:12px;line-height:1.7;color:#76768A;margin:0;'
        "text-align:center;font-family:'Inter',Arial,sans-serif\">"
        '<b style="color:#4A4A5A">Vertical AI</b> · Rendiamo la tua attività consigliabile dagli assistenti AI<br>'
        'verticalai.it · '
        '<a href="#" style="color:#76768A;text-decoration:underline">Preferenze email</a>'
        ' · '
        '<a href="#" style="color:#76768A;text-decoration:underline">Disiscriviti</a>'
        '</p>'
        '</td></tr>'
    )


def _score_band(overall: int) -> tuple[str, str, str]:
    """Restituisce (etichetta, bg, color) in base alle soglie del design system."""
    if overall >= 75:
        return "Ottimo", "#E7F8F0", "#0E9F6E"
    if overall >= 50:
        return "Buona, migliorabile", "#FCF3E3", "#9a5b00"
    return "Critico", "#FCEBEC", "#D92D34"


def _resend_post(to: list, subject: str, html: str) -> None:
    req.post(
        "https://api.resend.com/emails",
        json={"from": FROM_EMAIL, "to": to, "subject": subject, "html": html},
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
        timeout=10,
    )


def _send_contact_notif(job_id: str, domain: str, overall: int, grade: str,
                         email: str, phone: str, preference: str):
    if not RESEND_KEY or not FROM_EMAIL:
        return
    pref_label = "Telefono" if preference == "phone" else "Email"
    report_link = f"{SITE_URL}/r/{job_id}?token={_make_token(job_id)}"
    band_lbl, band_bg, band_color = _score_band(overall)
    html = f"""<!doctype html>
<html lang="it" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>{_EMAIL_HEAD}<title>Nuova richiesta di contatto</title></head>
<body class="bg-canvas" style="background:#F1F1F6;margin:0;padding:0;width:100%">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#F1F1F6">
  Richiesta di contatto da {email} per {domain} — punteggio {overall}/100.&nbsp;&zwnj;&nbsp;&zwnj;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-canvas" style="background:#F1F1F6">
<tr><td align="center" style="padding:28px 12px 40px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" class="container" style="width:600px;max-width:600px">
    {_email_logo_row("GEO Audit")}
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-card brd" style="background:#FFFFFF;border:1px solid #E6E6EF;border-radius:20px;overflow:hidden">
        <tr><td class="px" style="padding:32px 36px 8px">
          <div class="t-ink h1" style="font-size:22px;font-weight:600;color:#16151E;font-family:'Space Grotesk',Arial,sans-serif">Nuova richiesta di contatto</div>
        </td></tr>
        <tr><td class="px" style="padding:16px 36px 4px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-soft brd" style="background:#F6F6FB;border:1px solid #E6E6EF;border-radius:12px">
            <tr><td style="padding:16px 18px">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="padding:6px 0;font-size:13px;color:#76768A;width:130px;font-family:'Inter',Arial,sans-serif">Email</td>
                  <td style="padding:6px 0;font-size:13px;color:#16151E;font-family:'Inter',Arial,sans-serif"><b>{email}</b></td>
                </tr>
                <tr>
                  <td style="padding:6px 0;font-size:13px;color:#76768A;font-family:'Inter',Arial,sans-serif">Telefono</td>
                  <td style="padding:6px 0;font-size:13px;color:#16151E;font-family:'Inter',Arial,sans-serif">{phone or "—"}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0;font-size:13px;color:#76768A;font-family:'Inter',Arial,sans-serif">Preferenza</td>
                  <td style="padding:6px 0;font-size:13px;color:#16151E;font-family:'Inter',Arial,sans-serif">{pref_label}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0;font-size:13px;color:#76768A;font-family:'Inter',Arial,sans-serif">Sito</td>
                  <td style="padding:6px 0;font-size:13px;color:#16151E;font-family:'Inter',Arial,sans-serif">{domain}</td>
                </tr>
                <tr>
                  <td style="padding:6px 0;font-size:13px;color:#76768A;font-family:'Inter',Arial,sans-serif">Punteggio GEO</td>
                  <td style="padding:6px 0;font-size:13px;font-weight:700;color:{band_color};font-family:'Inter',Arial,sans-serif">{overall}/100 · {band_lbl}</td>
                </tr>
              </table>
            </td></tr>
          </table>
        </td></tr>
        <tr><td class="px" style="padding:22px 36px 32px" align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" class="btn" style="width:100%"><tr>
            <td align="center" bgcolor="#5A45D8" style="border-radius:10px">
              <a href="{report_link}" target="_blank" style="display:inline-block;padding:14px 28px;font-size:14px;font-weight:700;color:#ffffff;border-radius:10px;font-family:'Inter',Arial,sans-serif">Apri il report →</a>
            </td>
          </tr></table>
        </td></tr>
      </table>
    </td></tr>
    {_email_footer()}
  </table>
</td></tr>
</table>
</body></html>"""
    r = req.post("https://api.resend.com/emails",
                 json={"from": FROM_EMAIL,
                       "to": _NOTIFY_TO,
                       "subject": f"GEO: richiesta di contatto — {domain}",
                       "html": html},
                 headers={"Authorization": f"Bearer {RESEND_KEY}",
                          "Content-Type": "application/json"},
                 timeout=10)
    r.raise_for_status()


def _send_unlock_email(to: str, job_id: str, domain: str, overall: int, grade: str):
    if not RESEND_KEY or not FROM_EMAIL:
        return
    token = _make_token(job_id)
    link  = f"{SITE_URL}/r/{job_id}?token={token}"
    band_lbl, band_bg, band_color = _score_band(overall)
    score_pct = min(overall, 100)
    html = f"""<!doctype html>
<html lang="it" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>{_EMAIL_HEAD}<title>Il tuo report è pronto</title></head>
<body class="bg-canvas" style="background:#F1F1F6;margin:0;padding:0;width:100%">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#F1F1F6">
  Leggibilità AI di {domain}: {overall}/100. Ecco cosa va già bene e cosa conviene sistemare.&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-canvas" style="background:#F1F1F6">
<tr><td align="center" style="padding:28px 12px 40px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" class="container" style="width:600px;max-width:600px">
    {_email_logo_row("GEO Audit")}
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-card brd" style="background:#FFFFFF;border:1px solid #E6E6EF;border-radius:20px;overflow:hidden">

        <!-- score band -->
        <tr><td style="background:#5A45D8;background:linear-gradient(135deg,#5A45D8,#3D2F9B);padding:32px 36px" class="px">
          <div style="color:#D0C9FB;font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-family:'JetBrains Mono','Courier New',monospace">Report leggibilità AI</div>
          <div style="color:#ffffff;font-size:22px;font-weight:600;margin-top:6px;font-family:'Space Grotesk',Arial,sans-serif">{domain}</div>
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:20px"><tr>
            <td style="vertical-align:bottom">
              <span class="scorebig" style="color:#ffffff;font-size:64px;font-weight:700;line-height:1;font-family:'Space Grotesk',Arial,sans-serif">{overall}</span>
              <span style="color:#B3A8F7;font-size:16px;font-family:'JetBrains Mono','Courier New',monospace">/100</span>
            </td>
            <td style="padding-left:16px;vertical-align:bottom">
              <span style="display:inline-block;background:{band_bg};color:{band_color};font-size:12px;font-weight:700;padding:5px 11px;border-radius:999px;font-family:'Inter',Arial,sans-serif">{band_lbl}</span>
            </td>
          </tr></table>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px"><tr>
            <td style="background:#2B2160;border-radius:999px;height:8px;line-height:8px;font-size:0">
              <table role="presentation" width="{score_pct}%" cellpadding="0" cellspacing="0" border="0"><tr><td style="background:#2DD4DC;border-radius:999px;height:8px;line-height:8px;font-size:0">&nbsp;</td></tr></table>
            </td>
          </tr></table>
        </td></tr>

        <!-- intro -->
        <tr><td class="px" style="padding:28px 36px 8px">
          <div class="t-ink h1" style="font-size:22px;font-weight:600;color:#16151E;font-family:'Space Grotesk',Arial,sans-serif">Il tuo report è pronto.</div>
          <p class="t-2" style="font-size:15px;line-height:1.6;color:#4A4A5A;margin:10px 0 0;font-family:'Inter',Arial,sans-serif">Abbiamo letto le pagine di <b>{domain}</b> come farebbe un assistente AI.</p>
        </td></tr>

        <!-- CTA -->
        <tr><td class="px" style="padding:24px 36px 6px" align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" class="btn" style="width:100%"><tr>
            <td align="center" bgcolor="#5A45D8" style="border-radius:10px">
              <a href="{link}" target="_blank" style="display:inline-block;padding:15px 30px;font-size:15px;font-weight:700;color:#ffffff;border-radius:10px;font-family:'Inter',Arial,sans-serif">Apri il report completo →</a>
            </td>
          </tr></table>
        </td></tr>

        <!-- teaser analisi completa -->
        <tr><td class="px" style="padding:18px 36px 0">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-soft brd" style="background:#F6F6FB;border:1px solid #E6E6EF;border-radius:14px">
            <tr><td style="padding:18px 20px">
              <span style="display:inline-block;background:#5A45D8;color:#ffffff;font-size:10px;font-weight:700;letter-spacing:.06em;padding:3px 9px;border-radius:999px;font-family:'JetBrains Mono','Courier New',monospace">ANALISI COMPLETA</span>
              <div class="t-ink" style="font-size:16px;font-weight:600;color:#16151E;margin-top:10px;font-family:'Space Grotesk',Arial,sans-serif">Vuoi capire come alzare il punteggio?</div>
              <p class="t-2" style="font-size:13.5px;line-height:1.6;color:#4A4A5A;margin:6px 0 12px;font-family:'Inter',Arial,sans-serif">L'analisi completa include la lista di tutti i problemi ordinata per impatto, il confronto con i concorrenti e le raccomandazioni passo-passo.</p>
              <a href="{SITE_URL}/contact/{job_id}" target="_blank" style="font-size:14px;font-weight:600;color:#4A37BE;font-family:'Inter',Arial,sans-serif">Richiedi l'analisi completa →</a>
            </td></tr>
          </table>
        </td></tr>

        <tr><td class="px" style="padding:22px 36px 30px">
          <div class="hairline" style="height:1px;background:#E6E6EF;line-height:1px;font-size:0">&nbsp;</div>
          <p class="t-3" style="font-size:12.5px;line-height:1.6;color:#76768A;margin:16px 0 0;font-family:'Inter',Arial,sans-serif">
            Il link è personale e ti dà accesso diretto al report.<br>
            Hai ricevuto questa email perché hai richiesto un'analisi GEO per {domain}.
          </p>
        </td></tr>
      </table>
    </td></tr>
    {_email_footer()}
  </table>
</td></tr>
</table>
</body></html>"""
    _resend_post(
        to=[to],
        subject=f"GEO Audit per {domain}: punteggio {overall}/100 (grado {grade})",
        html=html,
    )


# ── HTML helpers ──────────────────────────────────────────────────────────────

_DS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="/static/css/design-system.css">'
)


def _page(title, body):
    return (
        f'<!doctype html><html lang="it" data-theme="dark"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title>"
        f"{_DS_LINK}"
        f"<style>"
        f"body{{min-height:100vh;display:flex;align-items:center;justify-content:center;"
        f"margin:0;text-align:center;padding:24px}}"
        f"a{{color:var(--brand-text)}}"
        f"</style>"
        f"</head><body><div>{body}</div></body></html>"
    )


def _inject_bar(html: str, job_id: str = "", email: str = "", dashboard_link: bool = False) -> str:
    """Barra azioni per report sbloccato. Sostituisce il placeholder __JOB_ID__ e pre-compila la mail nel form CTA."""
    reports_href, reports_label = ("/dashboard", "I tuoi report") if dashboard_link else ("/miei-report", "I miei report")
    bar_css = (
        "<style>"
        "@media print{#geo-bar{display:none!important}}"
        "#geo-bar{position:fixed;top:12px;right:12px;z-index:9999;"
        "display:flex;gap:8px;font-family:'Inter',system-ui,sans-serif}"
        "#geo-bar a{text-decoration:none;font-size:13px;font-weight:600;"
        "padding:9px 14px;border-radius:10px;display:inline-flex;align-items:center;"
        "gap:6px;transition:opacity .15s}"
        "#geo-bar a:hover{opacity:.88}"
        "#geo-bar .bar-primary{background:#5A45D8;color:#fff}"
        "#geo-bar .bar-secondary{background:#131220;color:#F4F3F8;border:1px solid #272636}"
        "</style>"
    )
    bar = (
        '<div id="geo-bar">'
        '<a href="#" class="bar-primary" onclick="window.print();return false;"'
        ' aria-label="Scarica PDF">↓ PDF</a>'
        f'<a href="{reports_href}" class="bar-secondary">{reports_label}</a>'
        '<a href="/audit" class="bar-secondary">Nuova analisi</a>'
        '</div>'
    )
    if job_id:
        html = html.replace("__JOB_ID__", job_id)
    if email:
        prefill = (
            f'<script>var _e=document.getElementById("cta-email");'
            f'if(_e)_e.value={json.dumps(email)};</script>'
        )
        html = html.replace("</body>", prefill + "</body>", 1)
    return html.replace('<div class="sheet">', bar_css + bar + '<div class="sheet">', 1)


def _inject_gate(html: str, job_id: str) -> str:
    """Oscura il report e inietta il form email di sblocco."""
    gate = f"""
<style>
@media print{{.geo-gate-blur,.geo-gate-overlay{{display:none!important}}}}
html,body{{overflow:hidden!important;height:100vh!important}}
.geo-gate-blur{{
  position:fixed;inset:480px 0 0 0;
  backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
  background:linear-gradient(to bottom,transparent 0,rgba(11,10,18,.98) 140px);
  z-index:200;pointer-events:none
}}
.geo-gate-overlay{{
  position:fixed;bottom:0;left:0;right:0;z-index:201;
  padding:0 16px 36px;display:flex;justify-content:center
}}
.geo-gate-card{{
  background:#131220;border:1px solid #272636;border-radius:20px;
  padding:28px 28px 24px;width:100%;max-width:460px;text-align:center;
  box-shadow:0 16px 40px -12px rgba(0,0,0,.7);
  font-family:'Inter',system-ui,sans-serif
}}
.geo-gate-card h2{{
  font-family:'Space Grotesk','Inter',sans-serif;font-weight:600;font-size:20px;
  color:#F4F3F8;margin:0 0 8px;letter-spacing:-.01em
}}
.geo-gate-card p{{color:#BCBBCB;font-size:14px;margin:0 0 18px;line-height:1.55}}
.geo-gate-card input{{
  width:100%;background:#0B0A12;border:1.5px solid #3A3950;border-radius:10px;
  color:#F4F3F8;font-size:15px;padding:12px 14px;
  font-family:inherit;outline:none;box-sizing:border-box;
  transition:border-color .12s
}}
.geo-gate-card input:focus{{border-color:#7C6BEC;box-shadow:0 0 0 3px rgba(124,107,236,.2)}}
.geo-gate-card button{{
  width:100%;margin-top:10px;background:#5A45D8;color:#fff;border:none;
  border-radius:10px;font-family:'Inter',system-ui,sans-serif;font-weight:600;
  font-size:15px;padding:13px;cursor:pointer;min-height:44px;
  transition:background .12s
}}
.geo-gate-card button:hover{{background:#4A37BE}}
.geo-gate-card button:focus-visible{{outline:2px solid #9182F0;outline-offset:2px}}
.geo-gate-note{{color:#8A8A9E;font-size:12px;margin-top:12px;line-height:1.5}}
.geo-gate-ok{{display:none;color:#3DDC97;font-size:14px;margin-top:10px;font-weight:600}}
</style>
<div class="geo-gate-blur" aria-hidden="true"></div>
<div class="geo-gate-overlay" role="dialog" aria-modal="true" aria-label="Sblocca report">
  <div class="geo-gate-card">
    <h2>Sblocca il report completo</h2>
    <p>Inserisci la tua email: ti inviamo il link al report completo.</p>
    <form id="geo-gate-form" novalidate>
      <input type="email" id="geo-gate-email" placeholder="nome@esempio.it"
             required autofocus autocomplete="email"
             aria-label="La tua email">
      <button type="submit" id="geo-gate-btn">Inviami il report →</button>
    </form>
    <p class="geo-gate-ok" id="geo-gate-ok" role="status">✓ Email inviata! Controlla la casella.</p>
    <p class="geo-gate-note">Nessuna password. Riceverai solo il link al tuo report.</p>
  </div>
</div>
<script>
document.getElementById('geo-gate-form').addEventListener('submit', async function(e) {{
  e.preventDefault();
  var btn = document.getElementById('geo-gate-btn');
  btn.disabled = true; btn.textContent = 'Invio…';
  var email = document.getElementById('geo-gate-email').value;
  var fd = new FormData(); fd.append('email', email);
  try {{
    await fetch('/unlock/{job_id}', {{method:'POST', body:fd}});
    document.getElementById('geo-gate-ok').style.display = 'block';
    btn.textContent = 'Email inviata ✓';
  }} catch(err) {{
    btn.disabled = false; btn.textContent = 'Inviami il report →';
  }}
}});
</script>
"""
    return html.replace("</body>", gate + "</body>", 1)


def _with_topbar(html: str, email: str) -> str:
    """Inietta una barra in alto con toggle tema, email dell'utente loggato e logout."""
    topbar = (
        '<div id="auth-topbar" style="position:fixed;top:0;left:0;right:0;height:48px;'
        'display:flex;align-items:center;justify-content:flex-end;gap:14px;padding:0 22px;'
        'font-family:var(--font-mono);font-size:12px;color:var(--text-3);'
        'background:var(--canvas);border-bottom:1px solid var(--border);z-index:60;box-sizing:border-box">'
        '<button type="button" class="theme-toggle" id="theme-toggle" aria-label="Cambia tema">'
        '<svg class="i-sun" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
        '<svg class="i-moon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>'
        '</button>'
        '<a href="/dashboard" style="color:var(--text-2);text-decoration:none">I tuoi report</a>'
        f'<span>{geo_audit.esc(email)}</span>'
        '<a href="/auth/logout" style="color:var(--text-2);text-decoration:none">Esci</a>'
        '</div>'
        '<style>body{padding-top:70px!important}</style>'
        '<script>document.getElementById("theme-toggle").addEventListener("click",function(){'
        'var cur=document.documentElement.getAttribute("data-theme")==="dark"?"dark":"light";'
        'var next=cur==="dark"?"light":"dark";'
        'document.documentElement.setAttribute("data-theme",next);'
        'try{localStorage.setItem("geo-theme",next);}catch(e){}});</script>'
    )
    return html.replace("<body>", "<body>" + topbar, 1)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return HOME_HTML


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/audit"):
    # Se sei già loggato, salta il form e vai dritto alla destinazione
    user, refreshed = _current_user(request)
    if user:
        target = next if next.startswith("/") else "/audit"
        return _apply_refresh(RedirectResponse(target, status_code=303), refreshed)
    return _render(LOGIN_HTML, SUPABASE_URL=SUPABASE_URL, SUPABASE_ANON_KEY=SUPABASE_ANON)


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback_page():
    return _render(AUTH_CB_HTML, SUPABASE_URL=SUPABASE_URL, SUPABASE_ANON_KEY=SUPABASE_ANON)


@app.post("/auth/set-session")
async def auth_set_session(request: Request, response: Response):
    body = await request.json()
    access_token  = (body.get("access_token")  or "").strip()
    refresh_token = (body.get("refresh_token") or "").strip()
    next_path     = body.get("next") or "/audit"
    if not next_path.startswith("/"):
        next_path = "/audit"
    if not access_token or not refresh_token:
        return Response(status_code=400)

    user = _sb_auth_user(access_token)
    if not user:
        return Response(status_code=401)

    _set_auth_cookies(response, access_token, refresh_token)
    return {"redirect": next_path}


@app.get("/auth/logout")
def auth_logout():
    resp = RedirectResponse("/", status_code=303)
    _clear_auth_cookies(resp)
    return resp


@app.get("/audit", response_class=HTMLResponse)
def audit_form(request: Request):
    user, refreshed = _current_user(request)
    if not user:
        return RedirectResponse("/login?next=/audit", status_code=303)
    resp = HTMLResponse(_with_topbar(FORM_HTML, user.get("email", "")))
    return _apply_refresh(resp, refreshed)


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return PRIVACY_HTML


@app.get("/cookie-policy", response_class=HTMLResponse)
def cookie_policy():
    return COOKIE_HTML


@app.get("/roadmap", response_class=HTMLResponse)
def roadmap():
    return ROADMAP_HTML


_SITEMAP_PATHS = ["/", "/roadmap", "/privacy", "/cookie-policy"]


@app.get("/robots.txt", response_class=Response)
def robots_txt():
    body = f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n"
    return Response(content=body, media_type="text/plain")


@app.get("/sitemap.xml", response_class=Response)
def sitemap_xml():
    urls = "".join(f"<url><loc>{SITE_URL}{p}</loc></url>" for p in _SITEMAP_PATHS)
    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'{urls}</urlset>')
    return Response(content=body, media_type="application/xml")


_LLMS_TXT = f"""# GEO Audit — Vertical AI

> Strumento gratuito di Vertical AI che analizza quanto un sito è leggibile e consigliabile dagli assistenti AI (ChatGPT, Gemini, Claude, Perplexity) e indica cosa correggere: dati strutturati, accesso crawler, contenuti, rendering.

## Pagine

- [Home e report gratuito]({SITE_URL}/): richiedi un'analisi GEO gratuita del tuo sito.
- [Roadmap]({SITE_URL}/roadmap): cosa è già costruito e cosa arriva dopo nella piattaforma.
- [Privacy Policy]({SITE_URL}/privacy)
- [Cookie Policy]({SITE_URL}/cookie-policy)

## Su Vertical AI

Vertical AI srl (verticalai.it) rende i siti web delle PMI leggibili e consigliabili dagli assistenti AI (GEO — Generative Engine Optimization).
"""


@app.get("/llms.txt", response_class=Response)
def llms_txt():
    return Response(content=_LLMS_TXT, media_type="text/plain")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/t")
async def track(request: Request):
    """Endpoint pubblico di ingestion per lo snippet static/js/geo-track.js.
    Nessuna autenticazione (gira su siti di terzi): validazione minima,
    fallisce silenziosamente per non rompere mai il sito del cliente."""
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=204)

    project_id = (body.get("pid") or "").strip()
    if not project_id:
        return Response(status_code=204)

    event_name = (body.get("event") or "pageview").strip()[:64]
    page_url = (body.get("url") or "")[:2048]
    referrer = (body.get("ref") or "")[:2048]
    session_id = (body.get("sid") or "")[:128]
    properties = body.get("props") if isinstance(body.get("props"), dict) else None

    try:
        _sb_insert_tracking_event({
            "project_id": project_id,
            "event_name": event_name,
            "session_id": session_id,
            "page_url": page_url,
            "referrer": referrer,
            "ai_source": _detect_ai_source(referrer),
            "properties": properties,
        })
    except Exception:
        pass

    return Response(status_code=204)


@app.post("/scan")
async def scan(request: Request, url: str = Form(...)):
    user, refreshed = _current_user(request)
    if not user:
        return RedirectResponse("/login?next=/audit", status_code=303)

    url = (url or "").strip()
    if not url:
        return _apply_refresh(RedirectResponse("/audit", status_code=303), refreshed)
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        res = await run_in_threadpool(geo_audit.run_audit, url, 6, False, False)
    except Exception as e:
        resp = HTMLResponse(
            _page("Errore",
                  f"<h2>Non riesco ad analizzare questo sito</h2>"
                  f"<p>{geo_audit.esc(str(e))}</p><p><a href='/audit'>← Riprova</a></p>"),
            status_code=400,
        )
        return _apply_refresh(resp, refreshed)

    # Salva su Supabase, associato al progetto dell'utente loggato (non bloccante se fallisce)
    job_id = None
    try:
        project = _sb_project_upsert(user["id"], res.get("domain") or url)
        row = _sb_insert({
            "user_id":    user["id"],
            "project_id": project["id"],
            "url":        url,
            "status":     "done",
            "domain":     res.get("domain"),
            "overall":    res.get("overall"),
            "grade":      res.get("grade"),
            "band":       res.get("band"),
            "pages_count": len(res.get("pages", [])),
            "html":       res["html"],
            "engine_version": res.get("engine_version"),
            "areas":       res.get("areas"),
            "site_checks": res.get("site_checks"),
            "pages_detail": res.get("pages"),
            "actions":      res.get("actions"),
            "issues_count":    res.get("issues_count"),
            "critical_count":  res.get("critical_count"),
        })
        job_id = row.get("id")

        all_checks = list(res.get("site_checks", []))
        for p in res.get("pages", []):
            for c in p.get("checks", []):
                all_checks.append({**c, "url": p.get("url")})
        _sb_issue_sync(project["id"], user["id"], job_id, all_checks)
        _sb_project_bump_scan(project["id"], project.get("scan_frequency") or "weekly")
    except Exception as e:
        # Non blocca la visualizzazione, ma va loggato: altrimenti un salvataggio
        # rotto è invisibile e l'utente ricade silenziosamente sul gate legacy.
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[/scan] salvataggio Supabase fallito: {e!r} {body}".strip())

    if job_id:
        return _apply_refresh(RedirectResponse(f"/r/{job_id}", status_code=303), refreshed)
    # Fallback se Supabase non disponibile: mostra comunque il gate inline
    # (il link email non funzionerà, ma il gate appare)
    resp = HTMLResponse(_inject_gate(res["html"], "offline"))
    return _apply_refresh(resp, refreshed)


@app.get("/r/{job_id}", response_class=HTMLResponse)
def report(job_id: str, request: Request, token: str = ""):
    # Valida token da query string → imposta cookie → redirect pulito
    if token and _valid_token(job_id, token):
        resp = RedirectResponse(f"/r/{job_id}", status_code=303)
        resp.set_cookie(f"geo-access-{job_id}", token,
                        httponly=True, secure=True, samesite="lax",
                        max_age=60 * 60 * 24 * 90)
        return resp

    job = _sb_get(job_id)
    if not job or not job.get("html"):
        return HTMLResponse(
            _page("Non trovato", "<h2>Report non trovato.</h2><p><a href='/audit'>← Nuova analisi</a></p>"),
            status_code=404,
        )

    # Report associato a un account: richiede login come proprietario, niente più gate email
    if job.get("user_id"):
        user, refreshed = _current_user(request)
        if not user or user["id"] != job["user_id"]:
            return RedirectResponse(f"/login?next=/r/{job_id}", status_code=303)
        resp = HTMLResponse(_inject_bar(job["html"], job_id, user.get("email", ""), dashboard_link=True))
        return _apply_refresh(resp, refreshed)

    # Report legacy anonimo: flusso invariato (gate email + cookie HMAC)
    if _has_access(request, job_id):
        return HTMLResponse(_inject_bar(job["html"], job_id, job.get("pending_email", "")))

    return HTMLResponse(_inject_gate(job["html"], job_id))


def _project_status(latest: dict | None) -> str:
    """Healthy / Needs attention / Critical / Audit required, calcolato
    dall'ultimo audit_run del progetto (nessuno stato persistito a mano)."""
    if not latest or latest.get("overall") is None:
        return "Audit required"
    try:
        created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).days
    except Exception:
        age_days = 0
    if age_days > 30:
        return "Audit required"
    if (latest.get("critical_count") or 0) > 0:
        return "Critical"
    overall = latest.get("overall") or 0
    if overall < 50:
        return "Critical"
    if overall < 75:
        return "Needs attention"
    return "Healthy"


def _backfill_projects(user_id: str) -> None:
    """Aggancia a un project le righe audits create prima che il modello
    project esistesse (idempotente: gira ad ogni /dashboard finché serve)."""
    orphans = _sb_audits_without_project(user_id)
    if not orphans:
        return
    domains = sorted({o["domain"] for o in orphans if o.get("domain")})
    for domain in domains:
        project = _sb_project_upsert(user_id, domain)
        for o in orphans:
            if o.get("domain") == domain:
                _sb_patch(o["id"], {"project_id": project["id"]})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user, refreshed = _current_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard", status_code=303)

    _backfill_projects(user["id"])

    cards = []
    for p in _sb_projects_by_user(user["id"]):
        runs = _sb_audits_by_project(p["id"], limit=2, full=False)
        latest = runs[0] if runs else None
        previous = runs[1] if len(runs) > 1 else None
        delta = None
        if latest and previous and latest.get("overall") is not None and previous.get("overall") is not None:
            delta = latest["overall"] - previous["overall"]

        tracking_on = _sb_has_tracking(p["id"])
        cards.append({
            "id": p["id"], "name": p["name"], "domain": p["domain"],
            "overall": latest.get("overall") if latest else None,
            "grade": latest.get("grade") if latest else None,
            "delta": delta,
            "critical_count": latest.get("critical_count") if latest else None,
            "pages_count": latest.get("pages_count") if latest else None,
            "last_scan": latest.get("created_at") if latest else None,
            "status": _project_status(latest),
            "tracking": "Tracking attivo" if tracking_on else "Tracking not installed",
            "tracking_active": tracking_on,
        })
    cards.sort(key=lambda c: c["last_scan"] or "", reverse=True)

    summary = {
        "total": len(cards),
        "critical": len([c for c in cards if c["status"] == "Critical"]),
        "audits_due": len([c for c in cards if c["status"] == "Audit required"]),
        "tracking_active": len([c for c in cards if c["tracking_active"]]),
    }

    html = _render(DASHBOARD_HTML,
                    PROJECTS_JSON=json.dumps(cards),
                    SUMMARY_JSON=json.dumps(summary),
                    USER_EMAIL=json.dumps(user.get("email", "")))
    resp = HTMLResponse(html)
    return _apply_refresh(resp, refreshed)


# ── Project detail: IA definitiva a 12 tab (dati reali dove disponibili) ────

_TAB_CATEGORIES = [
    ("overview", "Overview", None),
    ("audit", "Audit", [
        ("audit", "Riepilogo"), ("pages", "Pages"),
        ("technical", "Technical GEO"), ("opportunities", "Opportunities"),
    ]),
    ("ai", "AI Intelligence", [
        ("ai-visibility", "AI Visibility"), ("prompts", "Prompts & Queries"),
        ("competitors", "Competitors"), ("citations", "Citations"),
    ]),
    ("growth", "Traffic & Reports", [
        ("traffic", "AI Traffic"), ("reports", "Reports"),
    ]),
    ("settings", "Settings", None),
]

_ALL_TAB_KEYS = []
for _cat_key, _cat_label, _children in _TAB_CATEGORIES:
    _ALL_TAB_KEYS.extend([_cat_key] if _children is None else [k for k, _ in _children])

_COMING_SOON_TABS = {
    "ai-visibility": ("AI Visibility",
        "Richiede un panel di monitoraggio prompt sui provider AI (ChatGPT, Gemini, Perplexity). "
        "Non ancora configurato per questo progetto."),
    "prompts": ("Prompts & Queries",
        "Richiede il monitoraggio prompt attivo per esplorare cluster, risposte e storico. Non ancora configurato."),
    "competitors": ("Competitors",
        "Richiede lo stesso panel di monitoraggio prompt per calcolare Share of Voice e gap competitivi. "
        "Non ancora configurato."),
    "citations": ("Citations",
        "Richiede l'osservazione delle citazioni nelle risposte AI. Non ancora configurato."),
    "reports": ("Reports",
        "Richiede almeno un modulo di monitoraggio attivo per generare variazioni e alert. Non ancora disponibile."),
}

_STATUS_BADGE_CLS = {"ok": "badge--success", "warn": "badge--warning", "fail": "badge--danger", "unknown": "badge--neutral"}
_STATUS_LABEL     = {"ok": "OK", "warn": "Migliorabile", "fail": "Critico", "unknown": "N/D"}
_SEV_BADGE_CLS    = {"critical": "badge--danger", "high": "badge--danger", "medium": "badge--warning",
                      "low": "badge--neutral", "info": "badge--neutral"}


def _category_for_tab(tab: str) -> str:
    for cat_key, _, children in _TAB_CATEGORIES:
        if children is None:
            if cat_key == tab:
                return cat_key
        elif any(k == tab for k, _ in children):
            return cat_key
    return "overview"


def _tab_nav(project_id: str, active_tab: str) -> str:
    active_cat = _category_for_tab(active_tab)

    top = []
    for cat_key, cat_label, children in _TAB_CATEGORIES:
        target = cat_key if children is None else children[0][0]
        soon = children is not None and all(k in _COMING_SOON_TABS for k, _ in children)
        cls = "tab" + (" active" if cat_key == active_cat else "") + (" soon" if soon else "")
        badge = ' <span class="tab-soon">soon</span>' if soon else ""
        top.append(f'<a href="/project/{project_id}?tab={target}" class="{cls}">{geo_audit.esc(cat_label)}{badge}</a>')
    html = '<div class="tabs">' + "".join(top) + '</div>'

    active_children = next((c for k, _, c in _TAB_CATEGORIES if k == active_cat), None)
    if active_children:
        subs = []
        for key, label in active_children:
            soon = key in _COMING_SOON_TABS
            cls = "subtab" + (" active" if key == active_tab else "") + (" soon" if soon else "")
            badge = ' <span class="tab-soon">soon</span>' if soon else ""
            subs.append(f'<a href="/project/{project_id}?tab={key}" class="{cls}">{geo_audit.esc(label)}{badge}</a>')
        html += '<div class="subtabs">' + "".join(subs) + '</div>'
    return html


def _coming_soon_tab(title: str, description: str) -> str:
    return (
        '<div class="card coming-soon-card">'
        '<span class="badge badge--neutral"><span class="dot"></span>Coming soon</span>'
        f'<h2 class="card-title" style="margin-top:12px">{geo_audit.esc(title)}</h2>'
        f'<p class="card-sub">{geo_audit.esc(description)}</p>'
        '</div>'
    )


def _status_badge(status: str) -> str:
    cls = _STATUS_BADGE_CLS.get(status, "badge--neutral")
    label = _STATUS_LABEL.get(status, status or "—")
    return f'<span class="badge {cls}"><span class="dot"></span>{geo_audit.esc(label)}</span>'


def _sev_badge(sev: str) -> str:
    cls = _SEV_BADGE_CLS.get(sev, "badge--neutral")
    return f'<span class="badge {cls}">{geo_audit.esc(sev or "—")}</span>'


def _score_class(overall) -> str:
    if overall is None:
        return "score-unknown"
    if overall >= 75:
        return "score-ottimo"
    if overall >= 50:
        return "score-migliorabile"
    return "score-critico"


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%d %b %Y")
    except Exception:
        return iso


def _checks_table(rows: list) -> str:
    """rows: [{'title','status','detail','recommendation'}]"""
    if not rows:
        return '<p class="card-sub">Nessun dato disponibile.</p>'
    body = "".join(
        f'<tr><td data-label="Check"><b>{geo_audit.esc(r["title"])}</b></td>'
        f'<td data-label="Stato">{_status_badge(r["status"])}</td>'
        f'<td data-label="Dettaglio">{geo_audit.esc(r.get("detail") or "—")}</td>'
        f'<td data-label="Raccomandazione">{geo_audit.esc(r.get("recommendation") or "—")}</td></tr>'
        for r in rows
    )
    return (
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr>'
        '<th>Check</th><th>Stato</th><th>Dettaglio</th><th>Raccomandazione</th>'
        '</tr></thead><tbody>' + body + '</tbody></table></div>'
    )


def _aggregate_page_check(pages_detail: list, check_id: str) -> dict:
    """Aggrega lo stato di un check page-level su tutte le pagine dell'audit."""
    matches = [c for p in (pages_detail or []) for c in (p.get("checks") or []) if c.get("id") == check_id]
    if not matches:
        return {"total": 0}
    ok = len([c for c in matches if c["status"] == "ok"])
    warn = len([c for c in matches if c["status"] == "warn"])
    fail = len([c for c in matches if c["status"] == "fail"])
    worst = matches[0]
    for c in matches:
        if c["status"] == "fail":
            worst = c
            break
        if c["status"] == "warn" and worst["status"] != "fail":
            worst = c
    return {"title": worst["title"], "status": worst["status"], "recommendation": worst.get("recommendation"),
            "ok": ok, "warn": warn, "fail": fail, "total": len(matches)}


def _section_card(project_id: str, tab_key: str, label: str, stat_num: str, stat_label: str,
                   summary: str, soon: bool) -> str:
    badge = '<span class="badge badge--neutral">Coming soon</span>' if soon else ''
    cls = "card section-card" + (" coming-soon-card" if soon else "")
    return (
        f'<a href="/project/{project_id}?tab={tab_key}" class="{cls}">'
        f'{badge}'
        f'<div class="section-card-stat"><span class="section-stat-num">{geo_audit.esc(stat_num)}</span>'
        f'<span class="section-stat-label">{geo_audit.esc(stat_label)}</span></div>'
        f'<div class="card-title">{geo_audit.esc(label)}</div>'
        f'<p class="card-sub">{summary}</p>'
        '<span class="section-card-link">Apri dettaglio →</span>'
        '</a>'
    )


def _overview_sections_grid(project_id: str, latest: dict | None, open_issues: int, resolved_recent: int) -> str:
    if latest:
        pages = latest.get("pages_detail") or []
        pages_with_issues = len([p for p in pages if any(c.get("status") in ("warn", "fail") for c in (p.get("checks") or []))])
        site_checks = latest.get("site_checks") or []
        site_ok = len([c for c in site_checks if c.get("status") == "ok"])

        pages_stat = str(len(pages)) if pages else "—"
        pages_summary = f'{len(pages)} pagine analizzate, {pages_with_issues} con almeno un problema.' if pages else "Nessuna pagina analizzata."

        tech_stat = f'{round(100 * site_ok / len(site_checks))}%' if site_checks else "—"
        technical_summary = f'{site_ok}/{len(site_checks)} check di accesso e infrastruttura superati.' if site_checks else "Nessun dato tecnico disponibile."

        areas = latest.get("areas") or []
        audit_stat = str(latest.get("overall")) if latest.get("overall") is not None else "—"
        audit_summary = (f'Punteggio {latest.get("overall", "—")}/100 su {len(areas)} aree, '
                          f'area migliore «{geo_audit.esc(areas[-1]["key"])}».') if areas else "Nessun audit ancora eseguito."
    else:
        pages_stat = tech_stat = audit_stat = "—"
        pages_summary = technical_summary = audit_summary = "Nessun audit ancora eseguito."

    opportunities_summary = f'{open_issues} issue aperte' + (f', {resolved_recent} risolte di recente.' if resolved_recent else '.')

    tracking_events = _sb_tracking_events(project_id, days=30, limit=5000)
    if tracking_events:
        ai_sessions = len({e.get("session_id") for e in tracking_events if e.get("ai_source")})
        traffic_stat = str(ai_sessions)
        traffic_summary = f'{ai_sessions} sessioni da assistenti AI negli ultimi 30 giorni.'
    else:
        traffic_stat = "—"
        traffic_summary = "Nessun evento ricevuto: installa lo snippet di tracking per attivare questa sezione."

    cards = [
        _section_card(project_id, "audit", "Audit", audit_stat, "Punteggio GEO", audit_summary, False),
        _section_card(project_id, "pages", "Pages", pages_stat, "pagine analizzate", pages_summary, False),
        _section_card(project_id, "technical", "Technical GEO", tech_stat, "check superati", technical_summary, False),
        _section_card(project_id, "opportunities", "Opportunities", str(open_issues), "issue aperte", opportunities_summary, False),
        _section_card(project_id, "traffic", "AI Traffic", traffic_stat, "sessioni AI (30gg)", traffic_summary, False),
    ]
    for tab_key, (label, desc) in _COMING_SOON_TABS.items():
        cards.append(_section_card(project_id, tab_key, label, "—", "non configurato", desc, True))

    return f'<div class="card-title" style="margin:24px 0 12px">Tutte le sezioni</div><div class="section-grid">{"".join(cards)}</div>'


def _tab_overview(project_id: str, latest: dict | None, previous: dict | None,
                   open_issues: int, resolved_recent: int) -> str:
    sections_html = _overview_sections_grid(project_id, latest, open_issues, resolved_recent)

    if not latest:
        return (
            '<div class="alert alert--info"><div class="ic">i</div>'
            '<div>Nessun audit ancora eseguito per questo progetto. '
            '<a href="/audit">Avvia la prima analisi →</a></div></div>'
            + sections_html
        )

    overall = latest.get("overall")
    delta = None
    if previous and previous.get("overall") is not None and overall is not None:
        delta = overall - previous["overall"]
    delta_html = ""
    if delta is not None:
        cls = "delta-up" if delta > 0 else ("delta-down" if delta < 0 else "delta-flat")
        sign = "+" if delta > 0 else ""
        delta_html = (
            f'<div class="delta-block"><span class="delta-pill {cls}">{sign}{delta}</span>'
            '<span class="delta-text">vs audit precedente</span></div>'
        )

    areas = latest.get("areas") or []
    worst = areas[0] if areas else None
    best = areas[-1] if areas else None
    best_cls = _score_class(best["score"]).replace("score-", "txt-") if best else "txt-unknown"
    worst_cls = _score_class(worst["score"]).replace("score-", "txt-") if worst else "txt-unknown"
    best_txt = (f'<b>{geo_audit.esc(best["key"])}</b> <span class="{best_cls}">({best["score"]}/100)</span>'
                if best else "—")
    worst_txt = (f'<b>{geo_audit.esc(worst["key"])}</b> <span class="{worst_cls}">({worst["score"]}/100)</span>'
                 if worst else "—")

    issues_count = latest.get("issues_count")
    critical_count = latest.get("critical_count")
    variazione = (f'Punteggio passato da {previous["overall"]} a {overall} rispetto '
                  f'all\'audit del {_fmt_date(previous.get("created_at"))}.'
                  if previous and previous.get("overall") is not None
                  else "Ancora nessun audit precedente per calcolare una variazione.")

    def _count_cls(value, critical):
        if value is None:
            return "stat-neutral"
        if critical:
            return "stat-good" if value == 0 else "stat-bad"
        if value == 0:
            return "stat-good"
        return "stat-warn" if value <= 10 else "stat-bad"

    sc = _score_class(overall)
    return (
        '<div class="ov-grid">'
        '<div class="card"><div class="card-sub">GEO Score</div>'
        f'<div class="ov-score-row"><div class="score-block {sc}" style="width:72px;height:72px">'
        f'<span class="num" style="font-size:24px">{overall if overall is not None else "—"}</span>'
        f'<span class="grd">{geo_audit.esc(latest.get("grade") or "—")}</span></div>{delta_html}</div>'
        f'<p class="card-sub" style="margin-top:10px">Ultimo audit: {_fmt_date(latest.get("created_at"))}</p></div>'

        '<div class="card"><div class="card-sub">Salute issue</div>'
        '<div class="mini-stat-row">'
        f'<div class="mini-stat {_count_cls(issues_count, False)}"><span class="mini-stat-num">{issues_count if issues_count is not None else "—"}</span>'
        '<span class="mini-stat-label">problemi totali</span></div>'
        f'<div class="mini-stat {_count_cls(critical_count, True)}"><span class="mini-stat-num">{critical_count if critical_count is not None else "—"}</span>'
        '<span class="mini-stat-label">critici</span></div>'
        '</div>'
        f'<p style="margin:10px 0 0"><b>{open_issues}</b> issue aperte in Opportunities</p></div>'

        '<div class="card"><div class="card-sub">Area migliore / peggiore</div>'
        f'<p style="margin:6px 0">✓ {best_txt}</p>'
        f'<p style="margin:6px 0">⚠ {worst_txt}</p></div>'

        f'<div class="card"><div class="card-sub">Tracking</div>'
        f'<p style="margin:6px 0">{_tracking_badge(project_id)}</p>'
        '<p class="card-sub" style="margin-top:8px">Vedi la tab AI Traffic per sessioni, provider e landing page.</p></div>'
        '</div>'

        f'<div class="card" style="margin-top:16px"><div class="card-title">Ultime variazioni</div>'
        f'<p class="card-sub">{variazione}</p></div>'
        + sections_html
    )


def _tab_audit(latest: dict | None, history: list) -> str:
    if not latest:
        return ('<div class="alert alert--info"><div class="ic">i</div>'
                '<div>Nessun audit ancora eseguito. <a href="/audit">Avvia la prima analisi →</a></div></div>')

    areas = latest.get("areas") or []
    area_rows = "".join(
        f'<div class="area-row"><span class="area-label">{geo_audit.esc(a["key"])}</span>'
        f'<div class="area-bar-track"><div class="area-bar-fill {_score_class(a["score"])}" '
        f'style="width:{a["score"]}%"></div></div><span class="area-score">{a["score"]}</span></div>'
        for a in areas
    )

    issues_count = latest.get("issues_count")
    critical_count = latest.get("critical_count")
    total_checks = len(latest.get("site_checks") or []) + sum(
        len(p.get("checks") or []) for p in (latest.get("pages_detail") or []))
    pct_ok = round(100 * (total_checks - (issues_count or 0)) / total_checks) if total_checks else None

    actions = (latest.get("actions") or [])[:8]
    actions_html = "".join(
        f'<li class="action-row">{_sev_badge(a["severity"])} <b>{geo_audit.esc(a["title"])}</b>'
        f'<p class="card-sub" style="margin:4px 0 0">{geo_audit.esc(a["recommendation"])} — '
        f'{a["count"]} pagin{"a" if a["count"] == 1 else "e"} interessate</p></li>'
        for a in actions
    ) or '<li class="card-sub">Nessun intervento prioritario: tutti i check principali sono superati.</li>'

    history_html = "".join(
        f'<tr><td data-label="Data">{_fmt_date(h.get("created_at"))}</td>'
        f'<td data-label="Score"><b>{h.get("overall") if h.get("overall") is not None else "—"}</b></td>'
        f'<td data-label="Grade">{geo_audit.esc(h.get("grade") or "—")}</td>'
        f'<td data-label="Critici">{h.get("critical_count") if h.get("critical_count") is not None else "—"}</td></tr>'
        for h in history
    )

    sc = _score_class(latest.get("overall"))
    return (
        '<div class="card"><div class="audit-head-row">'
        f'<div class="score-block {sc}" style="width:72px;height:72px">'
        f'<span class="num" style="font-size:24px">{latest.get("overall") if latest.get("overall") is not None else "—"}</span>'
        f'<span class="grd">{geo_audit.esc(latest.get("grade") or "—")}</span></div>'
        f'<div><p style="margin:0"><b>{issues_count if issues_count is not None else "—"}</b> problemi · '
        f'<b>{critical_count if critical_count is not None else "—"}</b> critici · '
        f'<b>{pct_ok if pct_ok is not None else "—"}%</b> controlli superati</p>'
        f'<a href="/r/{latest.get("id", "")}" class="btn btn--sm" style="margin-top:8px">Apri report completo →</a>'
        '</div></div></div>'

        f'<div class="card" style="margin-top:16px"><div class="card-title">Punteggio per area</div>{area_rows}</div>'
        f'<div class="card" style="margin-top:16px"><div class="card-title">Interventi prioritari</div>'
        f'<ul class="action-list">{actions_html}</ul></div>'
        '<div class="card" style="margin-top:16px"><div class="card-title">Storico audit</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr>'
        f'<th>Data</th><th>Score</th><th>Grade</th><th>Critici</th></tr></thead>'
        f'<tbody>{history_html}</tbody></table></div></div>'
    )


def _tab_pages(latest: dict | None) -> str:
    if not latest:
        return '<p class="card-sub">Nessun audit ancora eseguito.</p>'
    pages = latest.get("pages_detail") or []
    rows_html = "".join(
        f'<tr><td data-label="URL"><a href="{geo_audit.esc(p.get("url", ""))}" target="_blank" '
        f'rel="noopener">{geo_audit.esc(p.get("url", ""))}</a></td>'
        f'<td data-label="Tipo">{geo_audit.esc(p.get("type") or "—")}</td>'
        f'<td data-label="Score"><b>{p.get("score") if p.get("score") is not None else "—"}</b></td>'
        f'<td data-label="Issue">{len([c for c in (p.get("checks") or []) if c.get("status") in ("warn", "fail")])}</td>'
        f'<td data-label="Critici">{len([c for c in (p.get("checks") or []) if c.get("status") == "fail"])}</td></tr>'
        for p in pages
    )
    return (
        '<div class="card" style="margin-bottom:16px">'
        f'<a href="/r/{latest.get("id", "")}" class="btn btn--sm">Apri report completo per il dettaglio pagina-per-pagina →</a>'
        '</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr>'
        '<th>URL</th><th>Tipo</th><th>Score</th><th>Issue</th><th>Critici</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table></div>'
    )


def _tab_technical(latest: dict | None) -> str:
    if not latest:
        return '<p class="card-sub">Nessun audit ancora eseguito.</p>'

    site_checks = [c for c in (latest.get("site_checks") or []) if c.get("id", "").startswith("crawl.")]
    rows_access = [{"title": c["title"], "status": c["status"], "detail": c.get("detail"),
                     "recommendation": c.get("recommendation")} for c in site_checks]

    pages_detail = latest.get("pages_detail") or []
    for check_id in ("meta.canonical", "render.parity"):
        agg = _aggregate_page_check(pages_detail, check_id)
        if agg.get("total"):
            rows_access.append({"title": agg["title"], "status": agg["status"],
                                 "detail": f'{agg["ok"]}/{agg["total"]} pagine OK',
                                 "recommendation": agg.get("recommendation")})

    rows_structured = []
    for check_id in ("sd.present", "sd.valid", "sd.highvalue", "sd.completeness", "sd.sameas",
                      "trust.contact", "trust.social", "trust.author", "sem.html"):
        agg = _aggregate_page_check(pages_detail, check_id)
        if agg.get("total"):
            rows_structured.append({"title": agg["title"], "status": agg["status"],
                                     "detail": f'{agg["ok"]}/{agg["total"]} pagine OK',
                                     "recommendation": agg.get("recommendation")})

    return (
        f'<div class="card-title" style="margin-bottom:10px">Accesso crawler e infrastruttura</div>{_checks_table(rows_access)}'
        f'<div class="card-title" style="margin:20px 0 10px">Dati strutturati ed entity signals</div>{_checks_table(rows_structured)}'
    )


def _tab_opportunities(project_id: str) -> str:
    issues = _sb_issues_by_project(project_id)
    if not issues:
        return '<p class="card-sub">Nessuna issue registrata: esegui un audit per popolare questa sezione.</p>'

    open_issues = [i for i in issues if i["status"] == "open"]
    resolved_issues = [i for i in issues if i["status"] != "open"]

    def row(i):
        return (f'<tr><td data-label="Check"><b>{geo_audit.esc(i.get("title") or i.get("check_id"))}</b></td>'
                f'<td data-label="Severità">{_sev_badge(i.get("severity"))}</td>'
                f'<td data-label="URL">{geo_audit.esc(i.get("url") or "sito")}</td>'
                f'<td data-label="Prima vista">{_fmt_date(i.get("first_seen_at"))}</td>'
                f'<td data-label="Ultima vista">{_fmt_date(i.get("last_seen_at"))}</td>'
                f'<td data-label="Stato">{_status_badge("fail" if i["status"] == "open" else "ok")}</td></tr>')

    thead = '<thead><tr><th>Check</th><th>Severità</th><th>URL</th><th>Prima vista</th><th>Ultima vista</th><th>Stato</th></tr></thead>'
    open_html = "".join(row(i) for i in open_issues) or '<tr><td colspan="6" class="card-sub">Nessuna issue aperta 🎉</td></tr>'
    out = (f'<div class="card-title" style="margin-bottom:10px">Issue aperte ({len(open_issues)})</div>'
           f'<div class="tbl-wrap"><table class="tbl tbl-responsive">{thead}<tbody>{open_html}</tbody></table></div>')

    if resolved_issues:
        resolved_html = "".join(row(i) for i in resolved_issues[:20])
        out += (f'<div class="card-title" style="margin:20px 0 10px">Risolte di recente ({len(resolved_issues)})</div>'
                f'<div class="tbl-wrap"><table class="tbl tbl-responsive">{thead}<tbody>{resolved_html}</tbody></table></div>')
    return out


def _tracking_badge(project_id: str) -> str:
    return ('<span class="badge badge--success"><span class="dot"></span>Tracking attivo</span>'
            if _sb_has_tracking(project_id) else
            '<span class="badge badge--neutral">Tracking not installed</span>')


def _tracking_snippet_html(project_id: str) -> str:
    tag = (f'&lt;script src="{SITE_URL}/static/js/geo-track.js" '
           f'data-project="{project_id}" async&gt;&lt;/script&gt;')
    return (
        '<div class="card-title" style="margin-bottom:8px">Snippet di tracking</div>'
        '<p class="card-sub" style="margin-bottom:10px">Incolla questo tag prima della chiusura di '
        '<code>&lt;/head&gt;</code> sul tuo sito. Gli eventi compaiono qui entro pochi minuti dalla prima visita.</p>'
        '<pre style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);'
        f'padding:12px 14px;overflow-x:auto;font-family:var(--font-mono);font-size:12.5px;color:var(--text-2);'
        f'margin:0">{tag}</pre>'
        '<p class="card-sub" style="margin-top:10px">Per registrare una conversione (es. invio form, prenotazione): '
        '<code>window.geoTrack("nome_evento")</code>.</p>'
    )


def _tab_traffic(project: dict) -> str:
    events = _sb_tracking_events(project["id"], days=30, limit=5000)
    if not events:
        return (
            '<div class="alert alert--info"><div class="ic">i</div>'
            '<div>Nessun evento di tracking ancora ricevuto per questo progetto. '
            'Installa lo snippet qui sotto per iniziare a raccogliere le sessioni.</div></div>'
            f'<div class="card" style="margin-top:16px">{_tracking_snippet_html(project["id"])}</div>'
        )

    sessions = {}
    for e in events:
        sid = e.get("session_id") or e.get("created_at")
        row = sessions.setdefault(sid, {"ai_source": None, "landing": e.get("page_url"), "first_at": e.get("created_at")})
        if e.get("ai_source"):
            row["ai_source"] = e["ai_source"]
        created = e.get("created_at") or ""
        if created and created < (row["first_at"] or ""):
            row["landing"] = e.get("page_url")
            row["first_at"] = created

    total_sessions = len(sessions)
    ai_sessions = [s for s in sessions.values() if s["ai_source"]]
    ai_count = len(ai_sessions)
    ai_pct = round(100 * ai_count / total_sessions) if total_sessions else 0

    by_source: dict = {}
    for s in ai_sessions:
        by_source[s["ai_source"]] = by_source.get(s["ai_source"], 0) + 1
    source_rows = "".join(
        f'<tr><td data-label="Provider"><b>{geo_audit.esc(k)}</b></td><td data-label="Sessioni">{v}</td></tr>'
        for k, v in sorted(by_source.items(), key=lambda x: -x[1])
    ) or '<tr><td colspan="2" class="card-sub">Nessuna sessione da AI nel periodo.</td></tr>'

    by_landing: dict = {}
    for s in ai_sessions:
        url = s["landing"] or "—"
        by_landing[url] = by_landing.get(url, 0) + 1
    landing_rows = "".join(
        f'<tr><td data-label="Pagina">{geo_audit.esc(k)}</td><td data-label="Sessioni">{v}</td></tr>'
        for k, v in sorted(by_landing.items(), key=lambda x: -x[1])[:10]
    ) or '<tr><td colspan="2" class="card-sub">Nessuna landing page da AI nel periodo.</td></tr>'

    daily: dict = {}
    for e in events:
        if not e.get("ai_source"):
            continue
        day = (e.get("created_at") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + 1
    trend_rows = "".join(
        f'<tr><td data-label="Data">{_fmt_date(day)}</td><td data-label="Eventi AI">{count}</td></tr>'
        for day, count in sorted(daily.items(), reverse=True)[:14]
    ) or '<tr><td colspan="2" class="card-sub">Nessun evento AI negli ultimi 14 giorni.</td></tr>'

    return (
        '<div class="mini-stat-row">'
        f'<div class="mini-stat"><span class="mini-stat-num">{total_sessions}</span><span class="mini-stat-label">sessioni (30gg)</span></div>'
        f'<div class="mini-stat stat-good"><span class="mini-stat-num">{ai_count}</span><span class="mini-stat-label">sessioni da AI</span></div>'
        f'<div class="mini-stat"><span class="mini-stat-num">{ai_pct}%</span><span class="mini-stat-label">quota AI</span></div>'
        '</div>'

        '<div class="card-title" style="margin:20px 0 10px">Per provider</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr><th>Provider</th><th>Sessioni</th></tr></thead>'
        f'<tbody>{source_rows}</tbody></table></div>'

        '<div class="card-title" style="margin:20px 0 10px">Landing page più visitate da AI</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr><th>Pagina</th><th>Sessioni</th></tr></thead>'
        f'<tbody>{landing_rows}</tbody></table></div>'

        '<div class="card-title" style="margin:20px 0 10px">Andamento (ultimi 14 giorni)</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr><th>Data</th><th>Eventi AI</th></tr></thead>'
        f'<tbody>{trend_rows}</tbody></table></div>'

        f'<div class="card" style="margin-top:20px">{_tracking_snippet_html(project["id"])}</div>'
    )


def _tab_settings(project: dict) -> str:
    freq = project.get("scan_frequency") or "weekly"
    freq_options = "".join(
        f'<option value="{key}"{" selected" if key == freq else ""}>{label}</option>'
        for key, label in _SCAN_FREQUENCY_LABELS.items()
    )
    tracking_installed = _sb_has_tracking(project["id"])
    tracking_status = ('<span class="badge badge--success"><span class="dot"></span>Installato</span>'
                        if tracking_installed else
                        '<span class="badge badge--neutral">Non ancora rilevato</span>')
    return (
        '<div class="card"><div class="card-title">Informazioni progetto</div>'
        f'<form method="post" action="/project/{project["id"]}/settings" class="settings-form">'
        '<div class="field"><label for="name">Nome progetto</label>'
        f'<input class="input" id="name" name="name" value="{geo_audit.esc(project.get("name") or "")}" required></div>'
        '<div class="field"><label for="sector">Settore (opzionale)</label>'
        f'<input class="input" id="sector" name="sector" value="{geo_audit.esc(project.get("sector") or "")}" '
        'placeholder="es. Hospitality, Retail…"></div>'
        '<div class="field"><label>Dominio</label>'
        f'<input class="input" value="{geo_audit.esc(project.get("domain") or "")}" disabled></div>'
        '<div class="field"><label for="scan_frequency">Audit automatico</label>'
        f'<select class="input" id="scan_frequency" name="scan_frequency">{freq_options}</select>'
        f'<span class="hint">Prossimo audit automatico: {geo_audit.esc(_fmt_date(project.get("next_scan_at")))}</span></div>'
        '<button type="submit" class="btn btn--primary" style="margin-top:8px">Salva</button>'
        '</form></div>'

        f'<div class="card" style="margin-top:16px">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">'
        f'<span class="card-title" style="margin:0">Tracking</span>{tracking_status}</div>'
        f'{_tracking_snippet_html(project["id"])}</div>'

        '<div class="card coming-soon-card" style="margin-top:16px">'
        '<span class="badge badge--neutral"><span class="dot"></span>Coming soon</span>'
        '<h2 class="card-title" style="margin-top:12px">Conversion event personalizzati</h2>'
        '<p class="card-sub">Configurazione guidata degli eventi di conversione (oggi disponibile solo via '
        '<code>window.geoTrack()</code> lato codice) non ancora disponibile da qui.</p></div>'
    )


def _project_actions(project: dict) -> str:
    freq = project.get("scan_frequency") or "weekly"
    freq_label = _SCAN_FREQUENCY_LABELS.get(freq, "Settimanale")
    next_scan = project.get("next_scan_at")
    next_txt = (f'Prossimo audit automatico: {_fmt_date(next_scan)} · {freq_label}'
                if next_scan else f'Audit automatico: {freq_label}')
    return (
        '<div class="project-actions">'
        f'<form method="post" action="/project/{project["id"]}/rerun" class="rerun-form" '
        'onsubmit="var b=this.querySelector(\'button\');b.disabled=true;'
        'b.textContent=\'Analisi in corso…\';">'
        '<button type="submit" class="btn btn--secondary btn--sm">↻ Rifai audit</button>'
        '</form>'
        f'<p class="next-scan-note">{geo_audit.esc(next_txt)}</p>'
        '</div>'
    )


@app.get("/project/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: str, request: Request, tab: str = "overview", rerun_error: str = ""):
    user, refreshed = _current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/project/{project_id}", status_code=303)

    project = _sb_project_get(project_id)
    if not project or project.get("user_id") != user["id"]:
        return HTMLResponse(
            _page("Non trovato", "<h2>Progetto non trovato.</h2><p><a href='/dashboard'>← I tuoi progetti</a></p>"),
            status_code=404,
        )

    valid_tabs = set(_ALL_TAB_KEYS)
    if tab not in valid_tabs:
        tab = "overview"

    if tab in _COMING_SOON_TABS:
        title, desc = _COMING_SOON_TABS[tab]
        body = _coming_soon_tab(title, desc)
    elif tab == "overview":
        runs = _sb_audits_by_project(project_id, limit=2, full=True)
        latest = runs[0] if runs else None
        previous = runs[1] if len(runs) > 1 else None
        all_issues = _sb_issues_by_project(project_id)
        open_issues = len([i for i in all_issues if i["status"] == "open"])
        resolved_recent = len([i for i in all_issues if i["status"] == "resolved"])
        body = _tab_overview(project_id, latest, previous, open_issues, resolved_recent)
    elif tab == "audit":
        history = _sb_audits_by_project(project_id, limit=50, full=False)
        latest_full = _sb_audits_by_project(project_id, limit=1, full=True)
        body = _tab_audit(latest_full[0] if latest_full else None, history)
        if rerun_error:
            body = ('<div class="alert alert--danger"><div class="ic">!</div>'
                     '<div>Non siamo riusciti a rifare l\'audit. Riprova tra qualche minuto.</div></div>') + body
    elif tab == "pages":
        latest_full = _sb_audits_by_project(project_id, limit=1, full=True)
        body = _tab_pages(latest_full[0] if latest_full else None)
    elif tab == "technical":
        latest_full = _sb_audits_by_project(project_id, limit=1, full=True)
        body = _tab_technical(latest_full[0] if latest_full else None)
    elif tab == "opportunities":
        body = _tab_opportunities(project_id)
    elif tab == "traffic":
        body = _tab_traffic(project)
    elif tab == "settings":
        body = _tab_settings(project)
    else:
        body = ""

    html = _render(PROJECT_HTML,
                    PROJECT_NAME=geo_audit.esc(project.get("name") or project.get("domain")),
                    PROJECT_DOMAIN=geo_audit.esc(project.get("domain") or ""),
                    PROJECT_ACTIONS=_project_actions(project),
                    TABS_NAV=_tab_nav(project_id, tab),
                    TAB_BODY=body,
                    USER_EMAIL=json.dumps(user.get("email", "")))
    resp = HTMLResponse(html)
    return _apply_refresh(resp, refreshed)


@app.post("/project/{project_id}/settings")
def project_settings(project_id: str, request: Request, name: str = Form(...), sector: str = Form(""),
                      scan_frequency: str = Form("weekly")):
    user, refreshed = _current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/project/{project_id}", status_code=303)

    project = _sb_project_get(project_id)
    if not project or project.get("user_id") != user["id"]:
        return HTMLResponse(status_code=404, content="Non trovato")

    name = (name or "").strip() or project["domain"]
    sector = (sector or "").strip() or None
    scan_frequency = scan_frequency if scan_frequency in _SCAN_INTERVALS else "weekly"

    patch = {"name": name, "sector": sector, "scan_frequency": scan_frequency}
    if scan_frequency != (project.get("scan_frequency") or "weekly"):
        patch["next_scan_at"] = _next_scan_at(scan_frequency)
    _sb_project_patch(project_id, patch)

    resp = RedirectResponse(f"/project/{project_id}?tab=settings", status_code=303)
    return _apply_refresh(resp, refreshed)


@app.post("/project/{project_id}/rerun")
async def project_rerun(project_id: str, request: Request):
    user, refreshed = _current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/project/{project_id}", status_code=303)

    project = _sb_project_get(project_id)
    if not project or project.get("user_id") != user["id"]:
        return HTMLResponse(status_code=404, content="Non trovato")

    domain = project["domain"]
    url = domain if domain.startswith(("http://", "https://")) else "https://" + domain

    try:
        res = await run_in_threadpool(geo_audit.run_audit, url, 6, False, False)

        row = _sb_insert({
            "user_id":    user["id"],
            "project_id": project["id"],
            "url":        url,
            "status":     "done",
            "domain":     res.get("domain"),
            "overall":    res.get("overall"),
            "grade":      res.get("grade"),
            "band":       res.get("band"),
            "pages_count": len(res.get("pages", [])),
            "html":       res["html"],
            "engine_version": res.get("engine_version"),
            "areas":       res.get("areas"),
            "site_checks": res.get("site_checks"),
            "pages_detail": res.get("pages"),
            "actions":      res.get("actions"),
            "issues_count":    res.get("issues_count"),
            "critical_count":  res.get("critical_count"),
        })
        job_id = row.get("id")

        all_checks = list(res.get("site_checks", []))
        for p in res.get("pages", []):
            for c in p.get("checks", []):
                all_checks.append({**c, "url": p.get("url")})
        _sb_issue_sync(project["id"], user["id"], job_id, all_checks)
        _sb_project_bump_scan(project["id"], project.get("scan_frequency") or "weekly")
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[/project/{project_id}/rerun] audit fallito: {e!r} {body}".strip())
        resp = RedirectResponse(f"/project/{project_id}?tab=audit&rerun_error=1", status_code=303)
        return _apply_refresh(resp, refreshed)

    resp = RedirectResponse(f"/project/{project_id}?tab=audit", status_code=303)
    return _apply_refresh(resp, refreshed)


@app.post("/unlock/{job_id}")
def unlock(job_id: str, email: str = Form(...)):
    email = (email or "").strip().lower()
    if not email:
        return Response(status_code=400)

    try:
        _sb_patch(job_id, {"pending_email": email})
    except Exception:
        pass

    try:
        job = _sb_get(job_id)
        domain  = job.get("domain") or job.get("url") or "il sito"
        overall = job.get("overall") or 0
        grade   = job.get("grade") or "?"
    except Exception:
        domain, overall, grade = "il sito", 0, "?"

    try:
        _send_unlock_email(email, job_id, domain, overall, grade)
    except Exception:
        pass

    return Response(status_code=200)


_SHARED_HEAD = (
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    + _DS_LINK +
    "<style>"
    "body{min-height:100vh;"
    "background:radial-gradient(140% 100% at 70% -5%,#1E1A38 0%,#0B0A12 60%);"
    "display:flex;align-items:center;justify-content:center;padding:24px}"
    ".wrap{width:100%;max-width:540px}"
    ".logo-row{display:flex;align-items:center;gap:10px;font-family:var(--font-display);"
    "font-size:18px;font-weight:600;color:var(--text);margin-bottom:32px;text-decoration:none}"
    ".logo-mark{width:32px;height:32px;background:var(--brand);border-radius:9px;"
    "display:grid;place-items:center;box-shadow:var(--sh-brand)}"
    ".logo-mark span{color:#fff;font-family:var(--font-mono);font-weight:600;font-size:16px}"
    ".logo-ai{color:var(--brand-text)}"
    ".eyebrow-lbl{font-family:var(--font-mono);font-size:11px;letter-spacing:.14em;"
    "color:var(--brand-text);text-transform:uppercase;margin-bottom:12px}"
    "h1{font-size:28px;letter-spacing:-.02em;margin:0 0 10px;color:var(--ink)}"
    "p.sub{color:var(--text-2);font-size:15px;margin:0 0 26px;line-height:1.6}"
    ".form-card{background:var(--surface);border:1px solid var(--border);"
    "border-radius:20px;padding:22px;box-shadow:var(--sh-md)}"
    ".form-card label{display:block;font-family:var(--font-mono);font-size:11px;"
    "color:var(--text-3);text-transform:uppercase;letter-spacing:.1em;"
    "font-weight:500;margin-bottom:8px}"
    "input[type=email]{width:100%;background:var(--canvas);border:1.5px solid var(--border-strong);"
    "border-radius:10px;color:var(--text);font-size:15px;padding:12px 14px;"
    "font-family:inherit;outline:none;min-height:46px;box-sizing:border-box;"
    "transition:border-color .12s,box-shadow .12s}"
    "input[type=email]:focus{border-color:var(--brand);"
    "box-shadow:0 0 0 4px color-mix(in srgb,var(--brand) 18%,transparent)}"
    ".submit-btn{display:flex;width:100%;margin-top:16px;background:var(--brand);"
    "color:#fff;border:none;border-radius:10px;font-family:var(--font-sans);"
    "font-weight:600;font-size:15px;padding:14px;cursor:pointer;"
    "align-items:center;justify-content:center;min-height:44px;"
    "box-shadow:var(--sh-brand);transition:background .12s}"
    ".submit-btn:hover{background:var(--brand-hover)}"
    ".submit-btn:focus-visible{outline:2px solid var(--focus);outline-offset:2px}"
    ".foot{margin-top:22px;font-family:var(--font-mono);font-size:11px;"
    "color:var(--text-3);text-align:center}"
    "a.back{display:block;margin-top:4px;font-size:13px;color:var(--text-2);"
    "text-decoration:none;text-align:center}"
    "a.back:hover{color:var(--text)}"
    ".check-icon{font-size:40px;margin-bottom:16px;color:var(--success)}"
    "</style>"
)

_MIEI_REPORT_PAGE = f"""<!doctype html>
<html lang="it" data-theme="dark">
<head>
{_SHARED_HEAD}
<title>I miei report · GEO Audit</title>
</head>
<body>
<div class="wrap">
  <a href="/" class="logo-row" aria-label="verticalai — home">
    <div class="logo-mark" aria-hidden="true"><span>V</span></div>
    <span><span class="logo-ai">vertical</span>ai</span>
  </a>
  <div class="eyebrow-lbl" aria-label="sezione">GEO Audit</div>
  <h1>I miei report</h1>
  <p class="sub">Inserisci l'email con cui hai richiesto i report: ti inviamo tutti i link.</p>
  <div class="form-card">
    <form method="post" action="/miei-report">
      <label for="email">La tua email</label>
      <input id="email" name="email" type="email" placeholder="nome@esempio.it"
             required autofocus autocomplete="email"
             aria-describedby="email-note">
      <button type="submit" class="submit-btn">Inviami i link →</button>
    </form>
  </div>
  <p id="email-note" style="font-size:12px;color:var(--text-3);margin-top:12px;text-align:center;line-height:1.5">
    Riceverai un'email con i link diretti a tutti i report.
  </p>
  <a class="back" href="/audit">← Nuova analisi</a>
  <div class="foot">verticalai.it · GEO Audit</div>
</div>
</body>
</html>"""

_MIEI_REPORT_SENT = f"""<!doctype html>
<html lang="it" data-theme="dark">
<head>
{_SHARED_HEAD}
<title>Email inviata · GEO Audit</title>
</head>
<body>
<div class="wrap" style="text-align:center">
  <a href="/" class="logo-row" style="justify-content:center" aria-label="verticalai — home">
    <div class="logo-mark" aria-hidden="true"><span>V</span></div>
    <span><span class="logo-ai">vertical</span>ai</span>
  </a>
  <div class="check-icon" role="img" aria-label="Fatto">✓</div>
  <h1>Email inviata</h1>
  <p class="sub">Controlla la tua casella: troverai i link a tutti i report associati a quell'indirizzo.</p>
  <a class="back" href="/audit">← Nuova analisi</a>
</div>
</body>
</html>"""


def _send_my_reports_email(to: str, jobs: list):
    if not RESEND_KEY or not FROM_EMAIL:
        return
    _months = ["gen","feb","mar","apr","mag","giu","lug","ago","set","ott","nov","dic"]
    if jobs:
        rows = ""
        for j in jobs:
            token = _make_token(j["id"])
            link  = f"{SITE_URL}/r/{j['id']}?token={token}"
            overall = j.get("overall") or 0
            band_lbl, band_bg, band_color = _score_band(overall)
            raw_date = j.get("created_at", "")
            try:
                y, m, d = raw_date[:10].split("-")
                date_fmt = f"{d} {_months[int(m)-1]} {y}"
            except Exception:
                date_fmt = raw_date[:10] if raw_date else "—"
            rows += (
                f'<tr><td style="padding:14px 0;border-bottom:1px solid #EBEBF5">'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
                f'<td style="vertical-align:middle">'
                f'<div style="font-size:15px;font-weight:600;color:#16151E;font-family:\'Space Grotesk\',Arial,sans-serif">{j.get("domain","?")}</div>'
                f'<div style="font-size:12px;color:#76768A;margin-top:3px;font-family:\'Inter\',Arial,sans-serif">{date_fmt}</div>'
                f'</td>'
                f'<td style="text-align:right;vertical-align:middle;white-space:nowrap;padding-left:12px">'
                f'<span style="display:inline-block;background:{band_bg};color:{band_color};font-size:13px;font-weight:700;padding:4px 10px;border-radius:999px;font-family:\'Inter\',Arial,sans-serif">{overall}/100</span>'
                f'&nbsp;&nbsp;'
                f'<a href="{link}" target="_blank" style="font-size:13px;font-weight:600;color:#5A45D8;font-family:\'Inter\',Arial,sans-serif;text-decoration:none">Apri →</a>'
                f'</td>'
                f'</tr></table>'
                f'</td></tr>'
            )
        subject = "I tuoi report GEO Audit"
        card_content = (
            f'<tr><td class="px" style="padding:28px 36px 8px">'
            f'<div class="t-ink h1" style="font-size:22px;font-weight:600;color:#16151E;font-family:\'Space Grotesk\',Arial,sans-serif">I tuoi report GEO</div>'
            f'<p class="t-2" style="font-size:15px;color:#4A4A5A;margin:8px 0 20px;font-family:\'Inter\',Arial,sans-serif">Tutti i report associati a <b>{to}</b>.</p>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>'
            f'<p class="t-3" style="font-size:12.5px;color:#76768A;margin-top:20px;line-height:1.6;font-family:\'Inter\',Arial,sans-serif">'
            f'I link sono personali e danno accesso diretto al report completo.</p>'
            f'</td></tr>'
        )
    else:
        subject = "GEO Audit — nessun report trovato"
        card_content = (
            f'<tr><td class="px" style="padding:36px 36px 28px;text-align:center">'
            f'<div class="t-ink h1" style="font-size:22px;font-weight:600;color:#16151E;font-family:\'Space Grotesk\',Arial,sans-serif">Nessun report trovato</div>'
            f'<p class="t-2" style="font-size:15px;color:#4A4A5A;margin:10px 0 24px;font-family:\'Inter\',Arial,sans-serif">'
            f'Non abbiamo trovato report associati a <b>{to}</b>.<br>Prova con un\'altra email o avvia una nuova analisi.</p>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 auto"><tr>'
            f'<td align="center" bgcolor="#5A45D8" style="border-radius:10px">'
            f'<a href="{SITE_URL}/audit" target="_blank" style="display:inline-block;padding:13px 26px;font-size:14px;font-weight:700;color:#ffffff;border-radius:10px;font-family:\'Inter\',Arial,sans-serif">Avvia un\'analisi →</a>'
            f'</td></tr></table>'
            f'</td></tr>'
        )
    preheader = "I link ai tuoi report GEO Audit." if jobs else "Nessun report trovato per questa email."
    html = f"""<!doctype html>
<html lang="it" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>{_EMAIL_HEAD}<title>{subject}</title></head>
<body class="bg-canvas" style="background:#F1F1F6;margin:0;padding:0;width:100%">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#F1F1F6">
  {preheader}&nbsp;&zwnj;&nbsp;&zwnj;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-canvas" style="background:#F1F1F6">
<tr><td align="center" style="padding:28px 12px 40px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" class="container" style="width:600px;max-width:600px">
    {_email_logo_row("GEO Audit")}
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-card brd" style="background:#FFFFFF;border:1px solid #E6E6EF;border-radius:20px;overflow:hidden">
        {card_content}
      </table>
    </td></tr>
    {_email_footer()}
  </table>
</td></tr>
</table>
</body></html>"""
    _resend_post(to=[to], subject=subject, html=html)


# TODO: Trigger non implementato — chiamare questa funzione da un follow-up
#       scheduler (es. N giorni dopo il report) per invitare l'utente che
#       ha un punteggio basso/medio a richiedere l'analisi completa.
def _send_analisi_completa(to: str, job_id: str, domain: str, overall: int, grade: str):
    if not RESEND_KEY or not FROM_EMAIL:
        return
    contact_link = f"{SITE_URL}/contact/{job_id}"
    band_lbl, band_bg, band_color = _score_band(overall)
    html = f"""<!doctype html>
<html lang="it" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>{_EMAIL_HEAD}<title>Approfondisci l'analisi GEO di {domain}</title></head>
<body class="bg-canvas" style="background:#F1F1F6;margin:0;padding:0;width:100%">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#F1F1F6">
  Abbiamo individuato i punti chiave da migliorare per {domain}. Scopri di più.&nbsp;&zwnj;&nbsp;&zwnj;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-canvas" style="background:#F1F1F6">
<tr><td align="center" style="padding:28px 12px 40px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" class="container" style="width:600px;max-width:600px">
    {_email_logo_row("GEO Audit")}
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-card brd" style="background:#FFFFFF;border:1px solid #E6E6EF;border-radius:20px;overflow:hidden">
        <tr><td style="background:#5A45D8;background:linear-gradient(135deg,#5A45D8,#3D2F9B);padding:32px 36px" class="px">
          <span style="display:inline-block;background:rgba(255,255,255,.18);color:#fff;font-size:10px;font-weight:700;letter-spacing:.08em;padding:4px 11px;border-radius:999px;font-family:'JetBrains Mono','Courier New',monospace">ANALISI COMPLETA</span>
          <div style="color:#ffffff;font-size:22px;font-weight:600;margin-top:12px;font-family:'Space Grotesk',Arial,sans-serif">Vuoi capire come alzare il punteggio?</div>
          <div style="color:#B3A8F7;font-size:14px;margin-top:6px;font-family:'Inter',Arial,sans-serif">{domain} · <span style="font-weight:700;color:{band_color}">{overall}/100</span></div>
        </td></tr>
        <tr><td class="px" style="padding:28px 36px 8px">
          <p class="t-2" style="font-size:15px;line-height:1.6;color:#4A4A5A;margin:0 0 18px;font-family:'Inter',Arial,sans-serif">Il report automatico mostra il punteggio e le aree principali. Con l'analisi completa andiamo a fondo:</p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr><td style="padding:7px 0"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="vertical-align:top;padding-right:10px;color:#0E9F6E;font-size:18px;line-height:1.2">✓</td><td class="t-ink" style="font-size:14px;color:#16151E;font-family:'Inter',Arial,sans-serif">Lista completa dei problemi ordinata per impatto</td></tr></table></td></tr>
            <tr><td style="padding:7px 0"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="vertical-align:top;padding-right:10px;color:#0E9F6E;font-size:18px;line-height:1.2">✓</td><td class="t-ink" style="font-size:14px;color:#16151E;font-family:'Inter',Arial,sans-serif">Confronto con i concorrenti diretti</td></tr></table></td></tr>
            <tr><td style="padding:7px 0"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="vertical-align:top;padding-right:10px;color:#0E9F6E;font-size:18px;line-height:1.2">✓</td><td class="t-ink" style="font-size:14px;color:#16151E;font-family:'Inter',Arial,sans-serif">Raccomandazioni passo-passo pronte da implementare</td></tr></table></td></tr>
            <tr><td style="padding:7px 0"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="vertical-align:top;padding-right:10px;color:#0E9F6E;font-size:18px;line-height:1.2">✓</td><td class="t-ink" style="font-size:14px;color:#16151E;font-family:'Inter',Arial,sans-serif">Sessione di confronto con il nostro team</td></tr></table></td></tr>
          </table>
        </td></tr>
        <tr><td class="px" style="padding:24px 36px 30px" align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" class="btn" style="width:100%"><tr>
            <td align="center" bgcolor="#5A45D8" style="border-radius:10px">
              <a href="{contact_link}" target="_blank" style="display:inline-block;padding:15px 30px;font-size:15px;font-weight:700;color:#ffffff;border-radius:10px;font-family:'Inter',Arial,sans-serif">Richiedi l'analisi completa →</a>
            </td>
          </tr></table>
          <p class="t-3" style="font-size:12px;color:#76768A;margin:12px 0 0;font-family:'Inter',Arial,sans-serif">Nessun acquisto immediato — ti contatteremo per capire le tue esigenze.</p>
        </td></tr>
      </table>
    </td></tr>
    {_email_footer()}
  </table>
</td></tr>
</table>
</body></html>"""
    _resend_post(
        to=[to],
        subject=f"Vuoi alzare il punteggio GEO di {domain}?",
        html=html,
    )


# TODO: Scheduler non implementato — questa funzione va chiamata da un job
#       pianificato (es. cron mensile) per inviare il report di monitoraggio
#       periodico ai siti già analizzati.
def _send_report_mensile(to: str, job_id: str, domain: str, overall: int, grade: str,
                          delta: int = 0):
    if not RESEND_KEY or not FROM_EMAIL:
        return
    link = f"{SITE_URL}/r/{job_id}?token={_make_token(job_id)}"
    contact_link = f"{SITE_URL}/contact/{job_id}"
    band_lbl, band_bg, band_color = _score_band(overall)
    score_pct = min(overall, 100)
    if delta > 0:
        delta_str = f"+{delta}"
        delta_color = "#0E9F6E"
    elif delta < 0:
        delta_str = str(delta)
        delta_color = "#D92D34"
    else:
        delta_str = "±0"
        delta_color = "#76768A"
    html = f"""<!doctype html>
<html lang="it" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>{_EMAIL_HEAD}<title>Report mensile GEO — {domain}</title></head>
<body class="bg-canvas" style="background:#F1F1F6;margin:0;padding:0;width:100%">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#F1F1F6">
  Il tuo punteggio GEO mensile per {domain}: {overall}/100. {delta_str} rispetto al mese scorso.&nbsp;&zwnj;&nbsp;&zwnj;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-canvas" style="background:#F1F1F6">
<tr><td align="center" style="padding:28px 12px 40px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" class="container" style="width:600px;max-width:600px">
    {_email_logo_row("Report mensile")}
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-card brd" style="background:#FFFFFF;border:1px solid #E6E6EF;border-radius:20px;overflow:hidden">
        <tr><td style="background:#5A45D8;background:linear-gradient(135deg,#5A45D8,#3D2F9B);padding:32px 36px" class="px">
          <div style="color:#D0C9FB;font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-family:'JetBrains Mono','Courier New',monospace">Monitoraggio GEO</div>
          <div style="color:#ffffff;font-size:22px;font-weight:600;margin-top:6px;font-family:'Space Grotesk',Arial,sans-serif">{domain}</div>
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:20px"><tr>
            <td style="vertical-align:bottom">
              <span class="scorebig" style="color:#ffffff;font-size:64px;font-weight:700;line-height:1;font-family:'Space Grotesk',Arial,sans-serif">{overall}</span>
              <span style="color:#B3A8F7;font-size:16px;font-family:'JetBrains Mono','Courier New',monospace">/100</span>
            </td>
            <td style="padding-left:16px;vertical-align:bottom">
              <span style="display:inline-block;background:{band_bg};color:{band_color};font-size:12px;font-weight:700;padding:5px 11px;border-radius:999px;font-family:'Inter',Arial,sans-serif">{band_lbl}</span><br>
              <span style="display:inline-block;margin-top:8px;font-size:14px;font-weight:700;color:{delta_color};font-family:'JetBrains Mono','Courier New',monospace">{delta_str} vs mese scorso</span>
            </td>
          </tr></table>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px"><tr>
            <td style="background:#2B2160;border-radius:999px;height:8px;line-height:8px;font-size:0">
              <table role="presentation" width="{score_pct}%" cellpadding="0" cellspacing="0" border="0"><tr><td style="background:#2DD4DC;border-radius:999px;height:8px;line-height:8px;font-size:0">&nbsp;</td></tr></table>
            </td>
          </tr></table>
        </td></tr>
        <tr><td class="px" style="padding:28px 36px 30px" align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" class="btn" style="width:100%"><tr>
            <td align="center" bgcolor="#5A45D8" style="border-radius:10px">
              <a href="{link}" target="_blank" style="display:inline-block;padding:15px 30px;font-size:15px;font-weight:700;color:#ffffff;border-radius:10px;font-family:'Inter',Arial,sans-serif">Apri il report completo →</a>
            </td>
          </tr></table>
          <p class="t-3" style="font-size:12px;color:#76768A;margin:16px 0 0;line-height:1.6;font-family:'Inter',Arial,sans-serif">
            Vuoi un'analisi più approfondita? <a href="{contact_link}" style="color:#5A45D8;font-weight:600;text-decoration:none">Richiedi l'analisi completa →</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
    {_email_footer()}
  </table>
</td></tr>
</table>
</body></html>"""
    _resend_post(
        to=[to],
        subject=f"Report mensile GEO di {domain}: {overall}/100 ({delta_str})",
        html=html,
    )


@app.get("/miei-report", response_class=HTMLResponse)
def miei_report_form():
    return HTMLResponse(_MIEI_REPORT_PAGE)


@app.post("/miei-report", response_class=HTMLResponse)
def miei_report_send(email: str = Form(...)):
    email = (email or "").strip().lower()
    if not email:
        return RedirectResponse("/miei-report", status_code=303)

    try:
        jobs = _sb_get_by_email(email)
    except Exception:
        jobs = []

    try:
        _send_my_reports_email(email, jobs)
    except Exception:
        pass

    return HTMLResponse(_MIEI_REPORT_SENT)


@app.post("/contact/{job_id}")
def contact(job_id: str,
            email: str = Form(...),
            phone: str = Form(""),
            preference: str = Form("email")):
    email = (email or "").strip().lower()
    if not email:
        return Response(status_code=400)
    phone = (phone or "").strip()
    preference = preference if preference in ("email", "phone") else "email"

    job = None
    try:
        job = _sb_get(job_id)
    except Exception:
        pass

    domain  = (job or {}).get("domain") or "—"
    overall = int((job or {}).get("overall") or 0)
    grade   = (job or {}).get("grade") or "?"

    try:
        _sb_insert_contact({
            "audit_id":   job_id,
            "email":      email,
            "phone":      phone or None,
            "preference": preference,
            "domain":     domain,
            "overall":    overall,
            "grade":      grade,
        })
    except Exception:
        pass

    try:
        _send_contact_notif(job_id, domain, overall, grade, email, phone, preference)
    except Exception:
        pass

    return Response(status_code=200)


# ── Richiesta report dalla landing page ─────────────────────────────────────

_ADMIN_REPORT_EMAIL = "verticalai00@gmail.com"
_REPORT_FROM        = "geo@verticalai.it"


def _send_report_request_admin(nome: str, email: str, sito: str) -> None:
    if not RESEND_KEY:
        return
    html = f"""<!doctype html><html lang="it"><head><meta charset="UTF-8"><style>
body{{font-family:Inter,Arial,sans-serif;background:#F6F4FC;margin:0;padding:32px}}
.wrap{{max-width:560px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(90,69,216,.10);overflow:hidden}}
.top{{background:linear-gradient(135deg,#7C6BEC,#5A45D8);padding:28px 32px}}
.top h1{{color:#fff;font-size:1.1rem;margin:0;font-weight:700}}
.body{{padding:28px 32px}}
.row{{margin-bottom:16px}}
.label{{font-size:.78rem;font-weight:700;color:#9182F0;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}}
.value{{font-size:1rem;color:#15131F;font-weight:500}}
.foot{{padding:18px 32px;background:#F6F4FC;font-size:.8rem;color:#9C99B5;text-align:center}}
</style></head><body>
<div class="wrap">
  <div class="top"><h1>🔔 Nuova richiesta di report GEO</h1></div>
  <div class="body">
    <div class="row"><div class="label">Nome</div><div class="value">{nome}</div></div>
    <div class="row"><div class="label">Email</div><div class="value">{email}</div></div>
    <div class="row"><div class="label">Sito web</div><div class="value">{sito or "—"}</div></div>
  </div>
  <div class="foot">Richiesta dalla landing page di verticalai.it</div>
</div></body></html>"""
    req.post("https://api.resend.com/emails",
             json={"from": _REPORT_FROM, "to": [_ADMIN_REPORT_EMAIL],
                   "subject": f"Nuova richiesta di report GEO – {nome}", "html": html},
             headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
             timeout=10)


def _send_report_request_user(nome: str, email: str) -> None:
    if not RESEND_KEY:
        return
    first = nome.split()[0] if nome else "ciao"
    html = f"""<!doctype html><html lang="it"><head><meta charset="UTF-8"><style>
body{{font-family:Inter,Arial,sans-serif;background:#F6F4FC;margin:0;padding:32px}}
.wrap{{max-width:560px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(90,69,216,.10);overflow:hidden}}
.top{{background:linear-gradient(135deg,#7C6BEC,#5A45D8);padding:36px 32px;text-align:center}}
.logo{{font-family:Arial,sans-serif;font-weight:900;font-size:1.5rem;color:#fff;letter-spacing:-.02em}}
.logo span{{color:#c4b8ff}}
.top p{{color:rgba(255,255,255,.8);margin:8px 0 0;font-size:.95rem}}
.body{{padding:32px}}
.body h2{{color:#15131F;font-size:1.2rem;margin:0 0 16px}}
.body p{{color:#5C586F;line-height:1.65;margin:0 0 16px}}
.pill{{display:inline-block;background:#F2F0FE;color:#5A45D8;border-radius:999px;padding:.45rem 1.1rem;font-weight:700;font-size:.9rem;margin-bottom:20px}}
.cta{{text-align:center;margin:24px 0}}
.cta a{{background:linear-gradient(135deg,#7C6BEC,#5A45D8);color:#fff;padding:14px 32px;border-radius:12px;text-decoration:none;font-weight:700;font-size:1rem}}
.foot{{padding:20px 32px;background:#F6F4FC;font-size:.8rem;color:#9C99B5;text-align:center}}
.foot a{{color:#9182F0;text-decoration:none}}
</style></head><body>
<div class="wrap">
  <div class="top">
    <div class="logo">vertical<span>ai</span></div>
    <p>Generative Engine Optimization</p>
  </div>
  <div class="body">
    <span class="pill">✅ Richiesta ricevuta</span>
    <h2>Ciao {first}, abbiamo ricevuto la tua richiesta!</h2>
    <p>Grazie per aver richiesto il <strong>report GEO gratuito</strong>. Il nostro team ha già preso in carico la tua richiesta e ti contatterà a breve per spiegarti — in parole semplici — come gli assistenti AI vedono oggi la tua attività.</p>
    <p>Nel frattempo, se hai domande puoi rispondere direttamente a questa email.</p>
    <div class="cta"><a href="https://verticalai.it">Scopri di più su verticalai.it</a></div>
    <p style="font-size:.85rem;color:#9C99B5">Il report è completamente gratuito e senza impegno.</p>
  </div>
  <div class="foot">
    Vertical AI srl — Società Benefit &amp; Startup Innovativa<br>
    Via Monte Napoleone, 8 – 20121 Milano · P.IVA 13764720960<br>
    <a href="https://verticalai.it">verticalai.it</a>
  </div>
</div></body></html>"""
    req.post("https://api.resend.com/emails",
             json={"from": _REPORT_FROM, "to": [email], "reply_to": _ADMIN_REPORT_EMAIL,
                   "subject": "Abbiamo ricevuto la tua richiesta di report GEO ✅", "html": html},
             headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
             timeout=10)


@app.post("/richiedi-audit")
async def richiedi_audit(
    nome:  str = Form(...),
    email: str = Form(...),
    sito:  str = Form(""),
):
    nome  = (nome  or "").strip()
    email = (email or "").strip().lower()
    sito  = (sito  or "").strip()
    if sito and not sito.startswith(("http://", "https://")):
        sito = "https://" + sito
    if not nome or not email:
        return Response(status_code=400)
    try:
        await run_in_threadpool(_send_report_request_admin, nome, email, sito)
    except Exception:
        pass
    try:
        await run_in_threadpool(_send_report_request_user, nome, email)
    except Exception:
        pass
    return Response(content='{"ok":true}', media_type="application/json", status_code=200)
