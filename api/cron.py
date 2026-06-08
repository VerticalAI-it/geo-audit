"""
GEO Audit · Fase B — Vercel Cron job worker
Chiamato ogni minuto da Vercel Cron: GET /api/cron
Processa il prossimo job "pending" dalla tabella audits.
"""
import os, sys, json, traceback
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geo_audit
from supabase import create_client

SUPABASE_URL      = os.environ["SUPABASE_URL"]
SUPABASE_SVC_KEY  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
CRON_SECRET       = os.environ.get("CRON_SECRET", "")
RESEND_API_KEY    = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL        = os.environ.get("FROM_EMAIL", "noreply@verticalai.it")
SITE_URL          = os.environ.get("SITE_URL", "").rstrip("/")

sb = create_client(SUPABASE_URL, SUPABASE_SVC_KEY)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _send_report_email(email: str, job_id: str, domain: str, overall: int, grade: str):
    """Invia email 'report pronto' con magic link incorporato via Resend."""
    if not RESEND_API_KEY or not SITE_URL:
        return
    try:
        link_resp = sb.auth.admin.generate_link({
            "type": "magiclink",
            "email": email,
            "options": {"redirect_to": f"{SITE_URL}/r/{job_id}"}
        })
        magic_url = link_resp.properties.action_link
    except Exception:
        magic_url = f"{SITE_URL}/r/{job_id}"

    score_color = "#6C5CE7"
    if overall >= 75:
        score_color = "#00b894"
    elif overall < 45:
        score_color = "#d63031"

    html_body = f"""
<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0B0B16;color:#F2F1F8;font-family:system-ui,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:40px auto;padding:0 16px">
<tr><td>
  <p style="font-size:13px;color:#9C99B5;margin:0 0 24px">
    <b style="color:#9B8CFF">vertical<span style="color:#9C99B5">ai</span></b> · GEO Audit
  </p>
  <h1 style="font-size:24px;font-weight:800;margin:0 0 8px">
    Il tuo report è pronto
  </h1>
  <p style="color:#9C99B5;font-size:15px;margin:0 0 24px">
    Abbiamo analizzato <b style="color:#F2F1F8">{domain}</b> e il report è disponibile.
  </p>
  <div style="background:#17152A;border:1px solid #2A2640;border-radius:16px;padding:24px;margin-bottom:24px;text-align:center">
    <div style="font-size:48px;font-weight:800;color:{score_color};line-height:1">{overall}</div>
    <div style="font-size:14px;color:#9C99B5;margin-top:4px">punteggio su 100 · grado {grade}</div>
  </div>
  <a href="{magic_url}"
     style="display:block;background:#6C5CE7;color:#fff;text-decoration:none;border-radius:10px;
            padding:14px 24px;font-weight:700;font-size:16px;text-align:center">
    Visualizza il report completo →
  </a>
  <p style="font-size:12px;color:#6E6B86;margin-top:24px;line-height:1.6">
    Hai ricevuto questa email perché hai richiesto un'analisi GEO su {domain}.<br>
    Il link è personale e ti autentica automaticamente.
  </p>
</td></tr>
</table>
</body></html>
"""
    payload = json.dumps({
        "from": FROM_EMAIL,
        "to": [email],
        "subject": f"GEO Audit per {domain}: punteggio {overall}/100 ({grade})",
        "html": html_body,
    }).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def _process_next_job() -> dict:
    """Fetches, claims, and processes the oldest pending job. Returns a status dict."""
    # Fetch oldest pending job
    res = (sb.table("audits")
             .select("id,url,pending_email")
             .eq("status", "pending")
             .order("created_at")
             .limit(1)
             .execute())
    if not res.data:
        return {"status": "idle"}

    job = res.data[0]
    job_id = job["id"]

    # Atomic claim: guard against parallel cron invocations
    claim = (sb.table("audits")
               .update({"status": "processing", "started_at": _now()})
               .eq("id", job_id)
               .eq("status", "pending")
               .execute())
    if not claim.data:
        return {"status": "skipped", "reason": "already claimed"}

    url = job["url"]
    pending_email = job.get("pending_email")

    try:
        result = geo_audit.run_audit(url, max_pages=6, render=False, respect_robots=False)
        sb.table("audits").update({
            "status": "done",
            "html": result["html"],
            "overall": result.get("overall"),
            "grade": result.get("grade"),
            "band": result.get("band"),
            "domain": result.get("domain"),
            "pages_count": len(result.get("pages", [])),
            "completed_at": _now(),
        }).eq("id", job_id).execute()

        if pending_email:
            try:
                _send_report_email(
                    pending_email, job_id,
                    result.get("domain", url),
                    result.get("overall", 0),
                    result.get("grade", "?"),
                )
            except Exception:
                pass  # email failure must not roll back the job result

        return {"status": "done", "job_id": job_id}

    except Exception as exc:
        sb.table("audits").update({
            "status": "failed",
            "error": str(exc)[:500],
        }).eq("id", job_id).execute()
        return {"status": "failed", "job_id": job_id, "error": str(exc)[:200]}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Verify CRON_SECRET (Vercel sends it as Authorization: Bearer <secret>)
        auth = self.headers.get("Authorization", "")
        if CRON_SECRET and auth != f"Bearer {CRON_SECRET}":
            self._respond(401, {"error": "unauthorized"})
            return

        try:
            result = _process_next_job()
        except Exception as exc:
            traceback.print_exc()
            result = {"status": "error", "error": str(exc)[:200]}

        self._respond(200, result)

    def _respond(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress access logs
