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


# ── Richiesta audit dalla landing page ──────────────────────────────────────

ADMIN_EMAIL = "verticalai00@gmail.com"
AUDIT_FROM  = "geo@verticalai.it"


def _send_audit_request_admin(nome: str, email: str, sito: str) -> None:
    """Notifica interna a verticalai00@gmail.com."""
    if not RESEND_KEY:
        return
    sito_display = sito or "—"
    html = f"""<!doctype html>
<html lang="it">
<head><meta charset="UTF-8"><style>
  body{{font-family:Inter,Arial,sans-serif;background:#F6F4FC;margin:0;padding:32px}}
  .wrap{{max-width:560px;margin:0 auto;background:#fff;border-radius:16px;
         box-shadow:0 4px 24px rgba(90,69,216,.10);overflow:hidden}}
  .top{{background:linear-gradient(135deg,#7C6BEC,#5A45D8);padding:28px 32px}}
  .top h1{{color:#fff;font-size:1.15rem;margin:0;font-weight:700}}
  .body{{padding:28px 32px}}
  .row{{margin-bottom:16px}}
  .label{{font-size:.78rem;font-weight:700;color:#9182F0;text-transform:uppercase;
           letter-spacing:.08em;margin-bottom:4px}}
  .value{{font-size:1rem;color:#15131F;font-weight:500}}
  .footer{{padding:18px 32px;background:#F6F4FC;font-size:.8rem;color:#9C99B5;text-align:center}}
</style></head>
<body>
<div class="wrap">
  <div class="top"><h1>🔔 Nuova richiesta di audit GEO</h1></div>
  <div class="body">
    <div class="row"><div class="label">Nome</div><div class="value">{nome}</div></div>
    <div class="row"><div class="label">Email</div><div class="value">{email}</div></div>
    <div class="row"><div class="label">Sito web</div><div class="value">{sito_display}</div></div>
  </div>
  <div class="footer">Richiesta inviata tramite la landing page di verticalai.it</div>
</div>
</body></html>"""
    req.post(
        "https://api.resend.com/emails",
        json={
            "from": AUDIT_FROM,
            "to": [ADMIN_EMAIL],
            "subject": f"Nuova richiesta di audit GEO – {nome}",
            "html": html,
        },
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
        timeout=10,
    )


def _send_audit_request_user(nome: str, email: str) -> None:
    """Email brandizzata di conferma all'utente."""
    if not RESEND_KEY:
        return
    nome_display = nome.split()[0] if nome else "ciao"
    html = f"""<!doctype html>
<html lang="it">
<head><meta charset="UTF-8"><style>
  body{{font-family:Inter,Arial,sans-serif;background:#F6F4FC;margin:0;padding:32px}}
  .wrap{{max-width:560px;margin:0 auto;background:#fff;border-radius:16px;
         box-shadow:0 4px 24px rgba(90,69,216,.10);overflow:hidden}}
  .top{{background:linear-gradient(135deg,#7C6BEC,#5A45D8);padding:36px 32px;text-align:center}}
  .logo{{font-family:Arial,sans-serif;font-weight:900;font-size:1.5rem;color:#fff;letter-spacing:-.02em}}
  .logo span{{color:#c4b8ff}}
  .top p{{color:rgba(255,255,255,.8);margin:8px 0 0;font-size:.95rem}}
  .body{{padding:32px}}
  .body h2{{color:#15131F;font-size:1.25rem;margin:0 0 16px}}
  .body p{{color:#5C586F;line-height:1.65;margin:0 0 16px}}
  .pill{{display:inline-block;background:#F2F0FE;color:#5A45D8;border-radius:999px;
          padding:.45rem 1.1rem;font-weight:700;font-size:.9rem;margin-bottom:20px}}
  .cta{{display:block;text-align:center;margin:24px 0}}
  .cta a{{background:linear-gradient(135deg,#7C6BEC,#5A45D8);color:#fff;
           padding:14px 32px;border-radius:12px;text-decoration:none;font-weight:700;font-size:1rem}}
  .footer{{padding:20px 32px;background:#F6F4FC;font-size:.8rem;color:#9C99B5;text-align:center}}
  .footer a{{color:#9182F0;text-decoration:none}}
</style></head>
<body>
<div class="wrap">
  <div class="top">
    <div class="logo">vertical<span>ai</span></div>
    <p>Generative Engine Optimization</p>
  </div>
  <div class="body">
    <span class="pill">✅ Richiesta ricevuta</span>
    <h2>Ciao {nome_display}, abbiamo ricevuto la tua richiesta!</h2>
    <p>Grazie per aver richiesto l’<strong>audit GEO gratuito</strong>. Il nostro team ha già preso in carico la tua richiesta e ti contatterà a breve per spiegarti — in parole semplici — come gli assistenti AI vedono oggi la tua attività.</p>
    <p>Nel frattempo, se hai domande puoi rispondere direttamente a questa email.</p>
    <div class="cta"><a href="https://verticalai.it">Scopri di più su verticalai.it</a></div>
    <p style="font-size:.88rem;color:#9C99B5">L’audit è completamente gratuito e senza impegno. Decidi tu se e come proseguire dopo aver visto i risultati.</p>
  </div>
  <div class="footer">
    Vertical AI srl — Società Benefit &amp; Startup Innovativa<br>
    Via Monte Napoleone, 8 – 20121 Milano · P.IVA 13764720960<br>
    <a href="https://verticalai.it">verticalai.it</a>
  </div>
</div>
</body></html>"""
    req.post(
        "https://api.resend.com/emails",
        json={
            "from": AUDIT_FROM,
            "to": [email],
            "reply_to": ADMIN_EMAIL,
            "subject": "Abbiamo ricevuto la tua richiesta di audit GEO ✅",
            "html": html,
        },
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
        timeout=10,
    )


@app.post("/richiedi-audit")
async def richiedi_audit(
    nome: str = Form(...),
    email: str = Form(...),
    sito: str = Form(""),
):
    nome  = (nome or "").strip()
    email = (email or "").strip().lower()
    sito  = (sito or "").strip()

    if not nome or not email:
        return Response(status_code=400)

    try:
        await run_in_threadpool(_send_audit_request_admin, nome, email, sito)
    except Exception:
        pass
    try:
        await run_in_threadpool(_send_audit_request_user, nome, email)
    except Exception:
        pass

    return Response(content='{"ok":true}', media_type="application/json", status_code=200)
