"""
GEO Audit — servizio web
Scan sincrono → salva su Supabase via REST → report oscurato → sblocco via email.
"""
import os, hmac, hashlib, json
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
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SVC = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
RESEND_KEY   = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL   = os.environ.get("FROM_EMAIL", "")
SITE_URL     = os.environ.get("SITE_URL", "").rstrip("/")
_SECRET      = os.environ.get("CRON_SECRET", "fallback-secret").encode()

_HERE = os.path.dirname(os.path.abspath(__file__))
FORM_HTML = open(os.path.join(_HERE, "templates", "form.html"), encoding="utf-8").read()
HOME_HTML = open(os.path.join(_HERE, "templates", "home.html"), encoding="utf-8").read()

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


# ── Email helpers ─────────────────────────────────────────────────────────────

_NOTIFY_TO = ["geo@verticalai.it", "info@verticalai.it"]


def _send_contact_notif(job_id: str, domain: str, overall: int, grade: str,
                         email: str, phone: str, preference: str):
    if not RESEND_KEY or not FROM_EMAIL:
        return
    pref_label = "Telefono" if preference == "phone" else "Email"
    report_link = f"{SITE_URL}/r/{job_id}?token={_make_token(job_id)}"
    sc = "#00b894" if overall >= 75 else ("#fdcb6e" if overall >= 45 else "#d63031")
    html = (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:0;background:#0B0B16;color:#F2F1F8;font-family:system-ui,sans-serif">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:40px auto;padding:0 16px">'
        '<tr><td>'
        '<p style="font-size:13px;color:#9C99B5;margin:0 0 24px">'
        '<b style="color:#9B8CFF">vertical</b><span style="color:#9C99B5">ai</span> · GEO Audit</p>'
        '<h1 style="font-size:22px;font-weight:800;margin:0 0 20px">Nuova richiesta di contatto</h1>'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="background:#17152A;border:1px solid #2A2640;border-radius:12px;padding:20px;margin-bottom:20px">'
        f'<tr><td style="padding:6px 0;font-size:13px;color:#9C99B5;width:140px">Email</td>'
        f'<td style="padding:6px 0;font-size:13px;color:#F2F1F8"><b>{email}</b></td></tr>'
        f'<tr><td style="padding:6px 0;font-size:13px;color:#9C99B5">Telefono</td>'
        f'<td style="padding:6px 0;font-size:13px;color:#F2F1F8">{phone or "—"}</td></tr>'
        f'<tr><td style="padding:6px 0;font-size:13px;color:#9C99B5">Preferenza</td>'
        f'<td style="padding:6px 0;font-size:13px;color:#F2F1F8">{pref_label}</td></tr>'
        f'<tr><td style="padding:6px 0;font-size:13px;color:#9C99B5">Sito analizzato</td>'
        f'<td style="padding:6px 0;font-size:13px;color:#F2F1F8">{domain}</td></tr>'
        f'<tr><td style="padding:6px 0;font-size:13px;color:#9C99B5">Punteggio GEO</td>'
        f'<td style="padding:6px 0;font-size:13px;font-weight:700;color:{sc}">{overall}/100 (grado {grade})</td></tr>'
        '</table>'
        f'<a href="{report_link}" style="display:block;background:#6C5CE7;color:#fff;text-decoration:none;'
        'border-radius:10px;padding:13px 20px;font-weight:700;font-size:14px;text-align:center">'
        'Apri il report →</a>'
        '</td></tr></table></body></html>'
    )
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
    score_color = "#00b894" if overall >= 75 else ("#fdcb6e" if overall >= 45 else "#d63031")
    html = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0B0B16;color:#F2F1F8;font-family:system-ui,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:40px auto;padding:0 16px">
<tr><td>
  <p style="font-size:13px;color:#9C99B5;margin:0 0 24px">
    <b style="color:#9B8CFF">vertical</b><span style="color:#9C99B5">ai</span> · GEO Audit
  </p>
  <h1 style="font-size:22px;font-weight:800;margin:0 0 8px">Il tuo report GEO è pronto</h1>
  <p style="color:#9C99B5;font-size:15px;margin:0 0 20px">
    Abbiamo analizzato <b style="color:#F2F1F8">{domain}</b>.
  </p>
  <div style="background:#17152A;border:1px solid #2A2640;border-radius:16px;
              padding:24px;margin-bottom:24px;text-align:center">
    <div style="font-size:52px;font-weight:800;color:{score_color};line-height:1">{overall}</div>
    <div style="font-size:14px;color:#9C99B5;margin-top:4px">punteggio su 100 · grado {grade}</div>
  </div>
  <a href="{link}" style="display:block;background:#6C5CE7;color:#fff;text-decoration:none;
     border-radius:10px;padding:14px 24px;font-weight:700;font-size:16px;text-align:center">
    Visualizza il report completo →
  </a>
  <p style="font-size:12px;color:#6E6B86;margin-top:20px;line-height:1.6">
    Il link è personale e ti dà accesso al report completo.<br>
    Hai ricevuto questa email perché hai richiesto un'analisi GEO per {domain}.
  </p>
</td></tr>
</table>
</body></html>"""
    req.post("https://api.resend.com/emails",
             json={"from": FROM_EMAIL, "to": [to],
                   "subject": f"GEO Audit per {domain}: punteggio {overall}/100 (grado {grade})",
                   "html": html},
             headers={"Authorization": f"Bearer {RESEND_KEY}",
                      "Content-Type": "application/json"},
             timeout=10)


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


def _inject_bar(html: str, job_id: str = "", email: str = "") -> str:
    """Barra azioni per report sbloccato. Sostituisce il placeholder __JOB_ID__ e pre-compila la mail nel form CTA."""
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
        '<a href="/miei-report" class="bar-secondary">I miei report</a>'
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return HOME_HTML


@app.get("/audit", response_class=HTMLResponse)
def audit_form():
    return FORM_HTML


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scan")
async def scan(url: str = Form(...)):
    url = (url or "").strip()
    if not url:
        return RedirectResponse("/audit", status_code=303)
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        res = await run_in_threadpool(geo_audit.run_audit, url, 6, False, False)
    except Exception as e:
        return HTMLResponse(
            _page("Errore",
                  f"<h2>Non riesco ad analizzare questo sito</h2>"
                  f"<p>{geo_audit.esc(str(e))}</p><p><a href='/audit'>← Riprova</a></p>"),
            status_code=400,
        )

    # Salva su Supabase (non bloccante se fallisce)
    job_id = None
    try:
        row = _sb_insert({
            "url":        url,
            "status":     "done",
            "domain":     res.get("domain"),
            "overall":    res.get("overall"),
            "grade":      res.get("grade"),
            "band":       res.get("band"),
            "pages_count": len(res.get("pages", [])),
            "html":       res["html"],
        })
        job_id = row.get("id")
    except Exception:
        pass  # Supabase non critico per la visualizzazione

    if job_id:
        return RedirectResponse(f"/r/{job_id}", status_code=303)
    # Fallback se Supabase non disponibile: mostra comunque il gate inline
    # (il link email non funzionerà, ma il gate appare)
    return HTMLResponse(_inject_gate(res["html"], "offline"))


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

    if _has_access(request, job_id):
        return HTMLResponse(_inject_bar(job["html"], job_id, job.get("pending_email", "")))

    return HTMLResponse(_inject_gate(job["html"], job_id))


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
    if jobs:
        rows = ""
        for j in jobs:
            token = _make_token(j["id"])
            link  = f"{SITE_URL}/r/{j['id']}?token={token}"
            sc = "#00b894" if (j.get("overall") or 0) >= 75 else ("#fdcb6e" if (j.get("overall") or 0) >= 45 else "#d63031")
            raw_date = j.get("created_at", "")
            try:
                date_str = raw_date[:10]  # "2026-06-09" from ISO timestamp
                d, m, y = date_str.split("-")
                date_fmt = f"{d}/{m}/{y}"
            except Exception:
                date_fmt = raw_date[:10] if raw_date else "—"
            rows += (
                f'<tr><td style="padding:12px 0;border-bottom:1px solid #2A2640">'
                f'<div><b style="color:#F2F1F8">{j.get("domain","?")}</b>'
                f'<span style="color:{sc};font-weight:700;margin-left:10px">{j.get("overall","?")}/100</span>'
                f'<span style="color:#9C99B5;margin-left:6px">({j.get("grade","?")})</span></div>'
                f'<div style="color:#6E6B86;font-size:12px;margin-top:3px">{date_fmt}</div></td>'
                f'<td style="padding:12px 0 12px 16px;border-bottom:1px solid #2A2640;text-align:right;vertical-align:middle">'
                f'<a href="{link}" style="color:#9B8CFF;text-decoration:none;font-size:13px">Apri →</a>'
                f'</td></tr>'
            )
        body = (
            f'<h1 style="font-size:22px;font-weight:800;margin:0 0 8px">I tuoi report GEO</h1>'
            f'<p style="color:#9C99B5;font-size:14px;margin:0 0 20px">Ecco tutti i report associati a {to}.</p>'
            f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
            f'<p style="font-size:12px;color:#6E6B86;margin-top:24px;line-height:1.6">'
            f'I link sono personali e danno accesso diretto al report completo.</p>'
        )
        subject = "I tuoi report GEO Audit"
    else:
        body = (
            f'<h1 style="font-size:22px;font-weight:800;margin:0 0 8px">Nessun report trovato</h1>'
            f'<p style="color:#9C99B5;font-size:14px;margin:0">Non abbiamo trovato report associati a {to}.<br>'
            f'Prova con un\'altra email o <a href="{SITE_URL}/audit" style="color:#9B8CFF">avvia una nuova analisi</a>.</p>'
        )
        subject = "GEO Audit — nessun report trovato"
    html = (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:0;background:#0B0B16;color:#F2F1F8;font-family:system-ui,sans-serif">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:40px auto;padding:0 16px">'
        '<tr><td>'
        '<p style="font-size:13px;color:#9C99B5;margin:0 0 24px">'
        '<b style="color:#9B8CFF">vertical</b><span style="color:#9C99B5">ai</span> · GEO Audit</p>'
        + body +
        '</td></tr></table></body></html>'
    )
    r = req.post("https://api.resend.com/emails",
                 json={"from": FROM_EMAIL, "to": [to],
                       "subject": subject, "html": html},
                 headers={"Authorization": f"Bearer {RESEND_KEY}",
                          "Content-Type": "application/json"},
                 timeout=10)
    r.raise_for_status()


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
