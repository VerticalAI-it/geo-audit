"""
GEO Audit · Fase B — Vercel Cron job worker
Chiamato ogni minuto da Vercel Cron: GET /api/cron
Processa il prossimo job "pending" dalla tabella audits.
"""
import os, sys, json, time, traceback
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
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


# ── Email helpers ─────────────────────────────────────────────────────────────

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


def _score_band(overall: int) -> tuple:
    if overall >= 75:
        return "Ottimo", "#E7F8F0", "#0E9F6E"
    if overall >= 50:
        return "Buona, migliorabile", "#FCF3E3", "#9a5b00"
    return "Critico", "#FCEBEC", "#D92D34"


def _resend_post(to: list, subject: str, html: str) -> None:
    payload = json.dumps({"from": FROM_EMAIL, "to": to, "subject": subject, "html": html}).encode()
    r = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(r, timeout=10)


def _send_report_email(email: str, job_id: str, domain: str, overall: int, grade: str):
    """Invia email 'report pronto' con magic link via Resend (flusso asincrono cron)."""
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

    band_lbl, band_bg, band_color = _score_band(overall)
    score_pct = min(overall, 100)
    contact_link = f"{SITE_URL}/contact/{job_id}"
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
        <tr><td class="px" style="padding:28px 36px 8px">
          <div class="t-ink h1" style="font-size:22px;font-weight:600;color:#16151E;font-family:'Space Grotesk',Arial,sans-serif">Il tuo report è pronto.</div>
          <p class="t-2" style="font-size:15px;line-height:1.6;color:#4A4A5A;margin:10px 0 0;font-family:'Inter',Arial,sans-serif">Abbiamo letto le pagine di <b>{domain}</b> come farebbe un assistente AI.</p>
        </td></tr>
        <tr><td class="px" style="padding:24px 36px 6px" align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" class="btn" style="width:100%"><tr>
            <td align="center" bgcolor="#5A45D8" style="border-radius:10px">
              <a href="{magic_url}" target="_blank" style="display:inline-block;padding:15px 30px;font-size:15px;font-weight:700;color:#ffffff;border-radius:10px;font-family:'Inter',Arial,sans-serif">Apri il report completo →</a>
            </td>
          </tr></table>
        </td></tr>
        <tr><td class="px" style="padding:18px 36px 0">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-soft brd" style="background:#F6F6FB;border:1px solid #E6E6EF;border-radius:14px">
            <tr><td style="padding:18px 20px">
              <span style="display:inline-block;background:#5A45D8;color:#ffffff;font-size:10px;font-weight:700;letter-spacing:.06em;padding:3px 9px;border-radius:999px;font-family:'JetBrains Mono','Courier New',monospace">ANALISI COMPLETA</span>
              <div class="t-ink" style="font-size:16px;font-weight:600;color:#16151E;margin-top:10px;font-family:'Space Grotesk',Arial,sans-serif">Vuoi capire come alzare il punteggio?</div>
              <p class="t-2" style="font-size:13.5px;line-height:1.6;color:#4A4A5A;margin:6px 0 12px;font-family:'Inter',Arial,sans-serif">L'analisi completa include la lista di tutti i problemi ordinata per impatto, il confronto con i concorrenti e le raccomandazioni passo-passo.</p>
              <a href="{contact_link}" target="_blank" style="font-size:14px;font-weight:600;color:#4A37BE;font-family:'Inter',Arial,sans-serif">Richiedi l'analisi completa →</a>
            </td></tr>
          </table>
        </td></tr>
        <tr><td class="px" style="padding:22px 36px 30px">
          <div class="hairline" style="height:1px;background:#E6E6EF;line-height:1px;font-size:0">&nbsp;</div>
          <p class="t-3" style="font-size:12.5px;line-height:1.6;color:#76768A;margin:16px 0 0;font-family:'Inter',Arial,sans-serif">
            Il link è personale e ti autentica automaticamente.<br>
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
        to=[email],
        subject=f"GEO Audit per {domain}: punteggio {overall}/100 (grado {grade})",
        html=html,
    )


# TODO: Trigger non implementato — chiamare questa funzione subito dopo il
#       claim atomico del job (dopo la update "processing") per confermare
#       all'utente che la sua richiesta di audit è stata ricevuta.
def _send_conferma_audit(email: str, job_id: str, url: str):
    """Invia email di conferma ricezione richiesta di audit."""
    if not RESEND_API_KEY or not SITE_URL:
        return
    gate_link = f"{SITE_URL}/job/{job_id}/gate"
    html = f"""<!doctype html>
<html lang="it" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>{_EMAIL_HEAD}<title>Richiesta ricevuta!</title></head>
<body class="bg-canvas" style="background:#F1F1F6;margin:0;padding:0;width:100%">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#F1F1F6">
  La tua analisi GEO è in coda. Ti avviseremo via email quando il report sarà pronto.&nbsp;&zwnj;&nbsp;&zwnj;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-canvas" style="background:#F1F1F6">
<tr><td align="center" style="padding:28px 12px 40px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" class="container" style="width:600px;max-width:600px">
    {_email_logo_row("GEO Audit")}
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-card brd" style="background:#FFFFFF;border:1px solid #E6E6EF;border-radius:20px;overflow:hidden">
        <tr><td class="px" style="padding:40px 36px 8px;text-align:center">
          <div style="width:56px;height:56px;background:#E7F8F0;border-radius:50%;margin:0 auto 20px;display:flex;align-items:center;justify-content:center">
            <span style="font-size:26px;line-height:56px;display:block;text-align:center">✓</span>
          </div>
          <div class="t-ink h1" style="font-size:24px;font-weight:600;color:#16151E;font-family:'Space Grotesk',Arial,sans-serif">Richiesta ricevuta!</div>
          <p class="t-2" style="font-size:15px;line-height:1.6;color:#4A4A5A;margin:10px 0 24px;font-family:'Inter',Arial,sans-serif">Stiamo analizzando <b>{url}</b>.<br>Ti mandiamo un'email quando il report è pronto.</p>
        </td></tr>
        <tr><td class="px" style="padding:0 36px 28px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-soft brd" style="background:#F6F6FB;border:1px solid #E6E6EF;border-radius:12px">
            <tr><td style="padding:20px 22px">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr><td style="padding:8px 0">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
                    <td style="vertical-align:top;padding-right:12px;width:24px;text-align:center">
                      <span style="display:inline-block;width:22px;height:22px;border-radius:50%;background:#5A45D8;color:#fff;font-size:11px;font-weight:700;text-align:center;line-height:22px;font-family:'Inter',Arial,sans-serif">1</span>
                    </td>
                    <td class="t-ink" style="font-size:14px;color:#16151E;font-family:'Inter',Arial,sans-serif">Scansione delle pagine del sito</td>
                  </tr></table>
                </td></tr>
                <tr><td style="padding:8px 0">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
                    <td style="vertical-align:top;padding-right:12px;width:24px;text-align:center">
                      <span style="display:inline-block;width:22px;height:22px;border-radius:50%;background:#5A45D8;color:#fff;font-size:11px;font-weight:700;text-align:center;line-height:22px;font-family:'Inter',Arial,sans-serif">2</span>
                    </td>
                    <td class="t-ink" style="font-size:14px;color:#16151E;font-family:'Inter',Arial,sans-serif">Analisi dei segnali GEO per ogni pagina</td>
                  </tr></table>
                </td></tr>
                <tr><td style="padding:8px 0">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
                    <td style="vertical-align:top;padding-right:12px;width:24px;text-align:center">
                      <span style="display:inline-block;width:22px;height:22px;border-radius:50%;background:#5A45D8;color:#fff;font-size:11px;font-weight:700;text-align:center;line-height:22px;font-family:'Inter',Arial,sans-serif">3</span>
                    </td>
                    <td class="t-ink" style="font-size:14px;color:#16151E;font-family:'Inter',Arial,sans-serif">Report pronto — ti avvisiamo via email</td>
                  </tr></table>
                </td></tr>
              </table>
            </td></tr>
          </table>
        </td></tr>
        <tr><td class="px" style="padding:0 36px 30px;text-align:center">
          <p class="t-3" style="font-size:12.5px;color:#76768A;margin:0 0 14px;line-height:1.6;font-family:'Inter',Arial,sans-serif">
            Puoi controllare lo stato dell'analisi in qualsiasi momento.
          </p>
          <a href="{gate_link}" target="_blank" style="font-size:13px;font-weight:600;color:#5A45D8;font-family:'Inter',Arial,sans-serif">Controlla lo stato →</a>
        </td></tr>
      </table>
    </td></tr>
    {_email_footer()}
  </table>
</td></tr>
</table>
</body></html>"""
    _resend_post(to=[email], subject="La tua analisi GEO è in coda", html=html)


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


# ── Audit periodico dei progetti (giornaliero / settimanale / mensile) ──────

_SCAN_INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}


def _next_scan_at(frequency: str) -> str:
    delta = _SCAN_INTERVALS.get(frequency, _SCAN_INTERVALS["weekly"])
    return (datetime.now(timezone.utc) + delta).isoformat()


def _sync_project_issues(project_id: str, user_id: str, audit_id: str, checks: list) -> None:
    """Stessa logica di server.py:_sb_issue_sync, duplicata qui perché questo
    worker usa il client supabase-py invece delle chiamate REST dirette usate
    dal processo web (due entry point Vercel separati, nessuno import fra i due)."""
    now = _now()
    existing = {i["fingerprint"]: i
                for i in sb.table("issue").select("*").eq("project_id", project_id).execute().data}
    seen = set()

    for c in checks:
        if c.get("status") not in ("warn", "fail"):
            continue
        url = c.get("url") or None
        fingerprint = f"{c['id']}|{url or ''}"
        seen.add(fingerprint)
        prev = existing.get(fingerprint)
        if prev:
            sb.table("issue").update({
                "status": "open", "last_seen_audit": audit_id, "last_seen_at": now,
                "resolved_at": None, "severity": c.get("severity"), "title": c.get("title"),
            }).eq("id", prev["id"]).execute()
        else:
            sb.table("issue").insert({
                "project_id": project_id, "user_id": user_id,
                "check_id": c["id"], "category": c.get("category"), "url": url,
                "title": c.get("title"), "severity": c.get("severity"),
                "fingerprint": fingerprint, "status": "open",
                "first_seen_audit": audit_id, "last_seen_audit": audit_id,
                "first_seen_at": now, "last_seen_at": now,
            }).execute()

    to_resolve = [i for fp, i in existing.items() if fp not in seen and i["status"] == "open"]
    for i in to_resolve:
        sb.table("issue").update({"status": "resolved", "resolved_at": now}).eq("id", i["id"]).execute()


def _process_one_due_project() -> dict | None:
    """Reclama ed esegue l'audit del prossimo progetto con next_scan_at scaduto.
    Ritorna None se nessun progetto è in scadenza."""
    res = (sb.table("project")
             .select("id,user_id,domain,scan_frequency,next_scan_at")
             .lte("next_scan_at", _now())
             .order("next_scan_at")
             .limit(1)
             .execute())
    if not res.data:
        return None

    project = res.data[0]
    project_id = project["id"]
    frequency = project.get("scan_frequency") or "weekly"

    # Claim atomico: sposta subito next_scan_at in avanti (stesso valore che
    # verrebbe scritto a fine corsa) così un'altra invocazione concorrente del
    # cron non pesca lo stesso progetto mentre questo è in corso.
    claim = (sb.table("project")
               .update({"next_scan_at": _next_scan_at(frequency), "updated_at": _now()})
               .eq("id", project_id)
               .eq("next_scan_at", project["next_scan_at"])
               .execute())
    if not claim.data:
        return {"status": "skipped", "reason": "already claimed", "project_id": project_id}

    domain = project["domain"]
    url = domain if domain.startswith(("http://", "https://")) else "https://" + domain

    try:
        result = geo_audit.run_audit(url, max_pages=6, render=False, respect_robots=False)
        audit_row = sb.table("audits").insert({
            "user_id": project["user_id"], "project_id": project_id, "url": url,
            "status": "done", "domain": result.get("domain"),
            "overall": result.get("overall"), "grade": result.get("grade"), "band": result.get("band"),
            "pages_count": len(result.get("pages", [])), "html": result["html"],
            "engine_version": result.get("engine_version"), "areas": result.get("areas"),
            "site_checks": result.get("site_checks"), "pages_detail": result.get("pages"),
            "actions": result.get("actions"), "issues_count": result.get("issues_count"),
            "critical_count": result.get("critical_count"), "completed_at": _now(),
        }).execute().data[0]

        all_checks = list(result.get("site_checks", []))
        for p in result.get("pages", []):
            for c in p.get("checks", []):
                all_checks.append({**c, "url": p.get("url")})
        _sync_project_issues(project_id, project["user_id"], audit_row["id"], all_checks)

        return {"status": "done", "project_id": project_id, "audit_id": audit_row["id"]}
    except Exception as exc:
        # next_scan_at è già stato spostato in avanti dal claim: il progetto
        # verrà ritentato al prossimo ciclo normale, senza retry aggressivi.
        return {"status": "failed", "project_id": project_id, "error": str(exc)[:200]}


def _process_due_projects(max_projects: int = 5, time_budget_seconds: int = 45) -> dict:
    """Processa più progetti scaduti in una singola invocazione (limitato da
    conteggio e tempo) così anche uno scheduling poco frequente recupera il
    ritardo accumulato nel tempo."""
    started = time.monotonic()
    results = []
    while len(results) < max_projects and (time.monotonic() - started) < time_budget_seconds:
        outcome = _process_one_due_project()
        if outcome is None:
            break
        results.append(outcome)
    return {"processed": len(results), "results": results}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Verify CRON_SECRET (Vercel sends it as Authorization: Bearer <secret>)
        auth = self.headers.get("Authorization", "")
        if CRON_SECRET and auth != f"Bearer {CRON_SECRET}":
            self._respond(401, {"error": "unauthorized"})
            return

        try:
            pending_result = _process_next_job()
        except Exception as exc:
            traceback.print_exc()
            pending_result = {"status": "error", "error": str(exc)[:200]}

        try:
            scan_result = _process_due_projects()
        except Exception as exc:
            traceback.print_exc()
            scan_result = {"status": "error", "error": str(exc)[:200]}

        self._respond(200, {"pending_queue": pending_result, "project_scans": scan_result})

    def _respond(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress access logs
