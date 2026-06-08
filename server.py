"""
GEO Audit — servizio web (Fase B)
Job queue asincrona via Vercel Cron + Supabase storage + Supabase Auth.

Avvio locale (richiede variabili d'ambiente da .env):
    uvicorn server:app --reload
"""
import os, json
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse, JSONResponse
from pydantic import BaseModel
from supabase import create_client, Client

import geo_audit

app = FastAPI(title="GEO Audit · verticalai")

# ──────────────────────────────────────────── Supabase
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_ANON = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SVC  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SITE_URL      = os.environ.get("SITE_URL", "").rstrip("/")

# anon client: rispetta RLS, usato per auth utente
sb_anon: Client = create_client(SUPABASE_URL, SUPABASE_ANON)
# service client: bypassa RLS, usato per operazioni admin
sb_svc: Client  = create_client(SUPABASE_URL, SUPABASE_SVC)

# ──────────────────────────────────────────── Template
_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name: str) -> str:
    return open(os.path.join(_HERE, "templates", name), encoding="utf-8").read()


FORM_HTML      = _load("form.html")
GATE_HTML      = _load("gate.html")
WAITING_HTML   = _load("waiting.html")
DASHBOARD_HTML = _load("dashboard.html")
# Chiavi pubbliche Supabase iniettate a startup (safe da embeddare nell'HTML)
AUTH_CALLBACK_HTML = (
    _load("auth_callback.html")
    .replace("{{SUPABASE_URL}}", SUPABASE_URL)
    .replace("{{SUPABASE_ANON_KEY}}", SUPABASE_ANON)
)


# ──────────────────────────────────────────── Helpers

def _page(title: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="it"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title>"
        f"<style>body{{font-family:system-ui,sans-serif;background:#0B0B16;color:#F2F1F8;"
        f"display:flex;min-height:100vh;align-items:center;justify-content:center;"
        f"margin:0;text-align:center;padding:24px}}a{{color:#9B8CFF}}</style>"
        f"</head><body><div>{body}</div></body></html>"
    )


def _inject_bar(html: str) -> str:
    """Inietta la barra azioni (PDF via window.print + link dashboard) nel report."""
    hide_on_print = "<style>@media print{#geo-bar{display:none}}</style>"
    bar = (
        '<div id="geo-bar" style="position:fixed;top:14px;right:14px;z-index:999;'
        'display:flex;gap:8px;font-family:system-ui,sans-serif">'
        '<a href="#" onclick="window.print();return false;" '
        'style="background:#6C5CE7;color:#fff;text-decoration:none;'
        'font-weight:700;font-size:13px;padding:9px 14px;border-radius:9px">↓ PDF</a>'
        '<a href="/dashboard" style="background:#17152A;color:#F2F1F8;border:1px solid #2A2640;'
        'text-decoration:none;font-size:13px;padding:9px 14px;border-radius:9px">'
        'I miei report</a>'
        '<a href="/" style="background:#17152A;color:#F2F1F8;border:1px solid #2A2640;'
        'text-decoration:none;font-size:13px;padding:9px 14px;border-radius:9px">'
        "Nuova analisi</a></div>"
    )
    return html.replace('<div class="sheet">', hide_on_print + bar + '<div class="sheet">', 1)


def get_current_user(request: Request):
    """Ritorna il Supabase user autenticato, oppure None. Non lancia eccezioni."""
    token = request.cookies.get("sb-access-token")
    if not token:
        return None
    try:
        return sb_anon.auth.get_user(token).user
    except Exception:
        return None


# ──────────────────────────────────────────── Request models

class SessionBody(BaseModel):
    access_token: str
    refresh_token: str = ""
    job_id: str = ""


# ──────────────────────────────────────────── Endpoints
# Tutti gli handler sono sync (`def`, non `async def`) perché supabase-py usa
# httpx in modalità sincrona. FastAPI esegue i handler sync in un threadpool,
# evitando il blocco dell'event loop.

@app.get("/", response_class=HTMLResponse)
def index():
    return FORM_HTML


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scan")
def scan(url: str = Form(...)):
    url = (url or "").strip()
    if not url:
        return RedirectResponse("/", status_code=303)
    if not url.startswith("http"):
        url = "https://" + url

    res = sb_svc.table("audits").insert({"url": url, "status": "pending"}).execute()
    job_id = res.data[0]["id"]
    return RedirectResponse(f"/job/{job_id}/gate", status_code=303)


@app.get("/job/{job_id}/gate", response_class=HTMLResponse)
def gate(job_id: str, request: Request):
    res = (sb_svc.table("audits")
                 .select("id,url,domain,status,user_id")
                 .eq("id", job_id)
                 .execute())
    if not res.data:
        return HTMLResponse(
            _page("Non trovato",
                  "<h2>Job non trovato.</h2><p><a href='/'>← Nuova analisi</a></p>"),
            status_code=404,
        )
    job = res.data[0]

    # Se il report è pronto e l'utente è già autenticato, vai al report
    user = get_current_user(request)
    if job["status"] == "done" and user and job.get("user_id") == str(user.id):
        return RedirectResponse(f"/r/{job_id}", status_code=303)

    domain = job.get("domain") or job.get("url") or "il sito"
    return HTMLResponse(
        GATE_HTML
        .replace("{{JOB_ID}}", job_id)
        .replace("{{DOMAIN}}", geo_audit.esc(domain))
    )


@app.post("/job/{job_id}/request-access")
def request_access(job_id: str, email: str = Form(...)):
    email = (email or "").strip().lower()
    if not email:
        return Response(status_code=400)

    # Salva l'email nel job (usata dal cron per la notifica)
    sb_svc.table("audits").update({"pending_email": email}).eq("id", job_id).execute()

    # Invia magic link — Supabase Auth gestisce il double opt-in nativamente
    redirect_to = f"{SITE_URL}/auth/callback?job_id={job_id}"
    try:
        sb_anon.auth.sign_in_with_otp({
            "email": email,
            "options": {"email_redirect_to": redirect_to},
        })
    except Exception:
        pass  # Supabase non espone se l'email esiste già (anti-enumerazione)

    return Response(status_code=200)


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback():
    # Il job_id è nel query string e viene letto dal JS nella pagina
    return HTMLResponse(AUTH_CALLBACK_HTML)


@app.post("/auth/set-session")
def set_session(body: SessionBody):
    if not body.access_token:
        return JSONResponse({"error": "missing token"}, status_code=400)

    try:
        user = sb_anon.auth.get_user(body.access_token).user
    except Exception:
        return JSONResponse({"error": "invalid token"}, status_code=401)

    # Collega tutti gli audit con pending_email == user.email a questo user_id
    (sb_svc.table("audits")
           .update({"user_id": str(user.id)})
           .eq("pending_email", user.email)
           .is_("user_id", "null")
           .execute())

    redirect_url = f"/r/{body.job_id}" if body.job_id else "/dashboard"
    resp = JSONResponse({"redirect": redirect_url})
    resp.set_cookie("sb-access-token",  body.access_token,
                    httponly=True, secure=True, samesite="lax", max_age=3600)
    resp.set_cookie("sb-refresh-token", body.refresh_token,
                    httponly=True, secure=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@app.get("/r/{job_id}", response_class=HTMLResponse)
def report(job_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/job/{job_id}/gate", status_code=303)

    res = (sb_svc.table("audits")
                 .select("id,url,domain,status,html,error,user_id")
                 .eq("id", job_id)
                 .execute())
    if not res.data:
        return HTMLResponse(
            _page("Non trovato",
                  "<h2>Report non trovato.</h2><p><a href='/dashboard'>← I tuoi report</a></p>"),
            status_code=404,
        )
    job = res.data[0]

    if job.get("user_id") != str(user.id):
        return HTMLResponse(
            _page("Non autorizzato",
                  "<h2>Non hai accesso a questo report.</h2>"
                  "<p><a href='/dashboard'>← I tuoi report</a></p>"),
            status_code=403,
        )

    if job["status"] in ("pending", "processing"):
        return HTMLResponse(
            WAITING_HTML
            .replace("{{JOB_ID}}", job_id)
            .replace("{{URL}}", geo_audit.esc(job.get("url") or ""))
        )

    if job["status"] == "failed":
        return HTMLResponse(
            _page("Errore",
                  f"<h2>Analisi fallita</h2>"
                  f"<p>{geo_audit.esc(job.get('error') or 'Errore sconosciuto')}</p>"
                  f"<p><a href='/'>← Riprova</a></p>"),
            status_code=500,
        )

    return HTMLResponse(_inject_bar(job["html"]))


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    res = (sb_svc.table("audits")
                 .select("id,url,domain,status,overall,grade,band,pages_count,created_at,completed_at")
                 .eq("user_id", str(user.id))
                 .order("created_at", desc=True)
                 .execute())

    return HTMLResponse(
        DASHBOARD_HTML.replace("{{AUDITS_JSON}}", json.dumps(res.data or []))
    )
