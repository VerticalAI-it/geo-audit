"""
GEO Audit — servizio web
Scan sincrono → salva su Supabase via REST → report oscurato → sblocco via email.
"""
import os, hmac, hashlib
import requests as req
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.concurrency import run_in_threadpool

import geo_audit

app = FastAPI(title="GEO Audit · verticalai")

# ── Config ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SVC = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
RESEND_KEY   = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL   = os.environ.get("FROM_EMAIL", "")
SITE_URL     = os.environ.get("SITE_URL", "").rstrip("/")
_SECRET      = os.environ.get("CRON_SECRET", "fallback-secret").encode()

_HERE = os.path.dirname(os.path.abspath(__file__))
FORM_HTML = open(os.path.join(_HERE, "templates", "form.html"), encoding="utf-8").read()

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

def _page(title, body):
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
    """Barra azioni per report sbloccato."""
    hide = "<style>@media print{#geo-bar{display:none}}</style>"
    bar = (
        '<div id="geo-bar" style="position:fixed;top:14px;right:14px;z-index:9999;'
        'display:flex;gap:8px;font-family:system-ui,sans-serif">'
        '<a href="#" onclick="window.print();return false;" '
        'style="background:#6C5CE7;color:#fff;text-decoration:none;'
        'font-weight:700;font-size:13px;padding:9px 14px;border-radius:9px">↓ PDF</a>'
        '<a href="/" style="background:#17152A;color:#F2F1F8;border:1px solid #2A2640;'
        'text-decoration:none;font-size:13px;padding:9px 14px;border-radius:9px">'
        "Nuova analisi</a></div>"
    )
    return html.replace('<div class="sheet">', hide + bar + '<div class="sheet">', 1)


def _inject_gate(html: str, job_id: str) -> str:
    """Oscura il report e inietta il form email di sblocco."""
    gate = f"""
<style>
@media print{{.geo-gate-blur,.geo-gate-overlay{{display:none!important}}}}
.geo-gate-blur{{
  position:fixed;inset:360px 0 0 0;
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);
  background:linear-gradient(to bottom,transparent,rgba(11,11,22,.97) 100px);
  z-index:200;pointer-events:none
}}
.geo-gate-overlay{{
  position:fixed;bottom:0;left:0;right:0;z-index:201;
  padding:0 16px 36px;display:flex;justify-content:center
}}
.geo-gate-card{{
  background:#17152A;border:1px solid #2A2640;border-radius:18px;
  padding:28px 28px 24px;width:100%;max-width:460px;text-align:center;
  font-family:system-ui,sans-serif
}}
.geo-gate-card h2{{
  font-family:Archivo,sans-serif;font-weight:800;font-size:19px;
  color:#F2F1F8;margin:0 0 7px
}}
.geo-gate-card p{{color:#9C99B5;font-size:14px;margin:0 0 18px;line-height:1.5}}
.geo-gate-card input{{
  width:100%;background:#0B0B16;border:1px solid #2A2640;border-radius:10px;
  color:#F2F1F8;font-size:15px;padding:12px 14px;
  font-family:inherit;outline:none;box-sizing:border-box
}}
.geo-gate-card input:focus{{border-color:#6C5CE7}}
.geo-gate-card button{{
  width:100%;margin-top:10px;background:#6C5CE7;color:#fff;border:none;
  border-radius:10px;font-family:Archivo,sans-serif;font-weight:700;
  font-size:15px;padding:13px;cursor:pointer
}}
.geo-gate-card button:hover{{background:#5b4bd8}}
.geo-gate-note{{color:#6E6B86;font-size:12px;margin-top:12px;line-height:1.5}}
.geo-gate-ok{{display:none;color:#00b894;font-size:14px;margin-top:10px;font-weight:600}}
</style>
<div class="geo-gate-blur"></div>
<div class="geo-gate-overlay">
  <div class="geo-gate-card">
    <h2>Sblocca il report completo</h2>
    <p>Inserisci la tua email: ti inviamo il link al report completo.</p>
    <form id="geo-gate-form">
      <input type="email" id="geo-gate-email" placeholder="nome@esempio.it" required autofocus>
      <button type="submit" id="geo-gate-btn">Inviami il report →</button>
    </form>
    <p class="geo-gate-ok" id="geo-gate-ok">✓ Email inviata! Controlla la casella.</p>
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
    return FORM_HTML


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scan")
async def scan(url: str = Form(...)):
    url = (url or "").strip()
    if not url:
        return RedirectResponse("/", status_code=303)
    if not url.startswith("http"):
        url = "https://" + url

    try:
        res = await run_in_threadpool(geo_audit.run_audit, url, 6, False, False)
    except Exception as e:
        return HTMLResponse(
            _page("Errore",
                  f"<h2>Non riesco ad analizzare questo sito</h2>"
                  f"<p>{geo_audit.esc(str(e))}</p><p><a href='/'>← Riprova</a></p>"),
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
    # Fallback se Supabase non disponibile: mostra il report direttamente
    return HTMLResponse(_inject_bar(res["html"]))


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
            _page("Non trovato", "<h2>Report non trovato.</h2><p><a href='/'>← Nuova analisi</a></p>"),
            status_code=404,
        )

    if _has_access(request, job_id):
        return HTMLResponse(_inject_bar(job["html"]))

    return HTMLResponse(_inject_gate(job["html"], job_id))


@app.post("/unlock/{job_id}")
def unlock(job_id: str, email: str = Form(...)):
    email = (email or "").strip().lower()
    if not email:
        return Response(status_code=400)

    # Salva email su Supabase
    try:
        _sb_patch(job_id, {"pending_email": email})
    except Exception:
        pass

    # Recupera dati per l'email
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
