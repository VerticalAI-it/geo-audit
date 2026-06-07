"""
GEO Audit — servizio web (Fase A)
Una pagina con un campo URL → esegue l'audit → mostra il report (HTML) con
pulsante per scaricare il PDF.

Avvio locale:
    uvicorn server:app --reload
"""
import os, time, uuid
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.concurrency import run_in_threadpool

import geo_audit

app = FastAPI(title="GEO Audit · verticalai")

# Cache in memoria dei report (Fase A). In Fase B → Supabase (persistente).
RESULTS: dict[str, dict] = {}
MAX_RESULTS = 200

_HERE = os.path.dirname(os.path.abspath(__file__))
FORM_HTML = open(os.path.join(_HERE, "templates", "form.html"), encoding="utf-8").read()


def _prune():
    if len(RESULTS) > MAX_RESULTS:
        old = sorted(RESULTS, key=lambda k: RESULTS[k]["ts"])[: len(RESULTS) - MAX_RESULTS]
        for k in old:
            RESULTS.pop(k, None)


def _page(title, body):
    return f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;background:#0B0B16;color:#F2F1F8;display:flex;
min-height:100vh;align-items:center;justify-content:center;margin:0;text-align:center;padding:24px}}
a{{color:#9B8CFF}}</style></head><body><div>{body}</div></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return FORM_HTML


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scan")
async def scan(url: str = Form(...), max_pages: int = Form(12)):
    url = (url or "").strip()
    if not url:
        return RedirectResponse("/", status_code=303)
    max_pages = max(1, min(int(max_pages or 12), 40))
    try:
        res = await run_in_threadpool(geo_audit.run_audit, url, max_pages, True, False)
    except Exception as e:
        return HTMLResponse(
            _page("Errore", f"<h2>Non riesco ad analizzare questo sito</h2>"
                  f"<p>{geo_audit.esc(str(e))}</p><p><a href='/'>← Riprova</a></p>"),
            status_code=400)
    rid = uuid.uuid4().hex[:12]
    RESULTS[rid] = {"html": res["html"], "ts": time.time(),
                    "domain": res["domain"], "overall": res["overall"]}
    _prune()
    return RedirectResponse(f"/r/{rid}", status_code=303)


def _inject_bar(html, rid):
    bar = (
        f'<div style="position:fixed;top:14px;right:14px;z-index:999;display:flex;gap:8px;'
        f'font-family:system-ui,sans-serif">'
        f'<a href="/r/{rid}/pdf" style="background:#6C5CE7;color:#fff;text-decoration:none;'
        f'font-weight:700;font-size:13px;padding:9px 14px;border-radius:9px">↓ PDF</a>'
        f'<a href="/" style="background:#17152A;color:#F2F1F8;border:1px solid #2A2640;'
        f'text-decoration:none;font-size:13px;padding:9px 14px;border-radius:9px">Nuova analisi</a>'
        f'</div>'
    )
    return html.replace('<div class="sheet">', bar + '<div class="sheet">', 1)


@app.get("/r/{rid}", response_class=HTMLResponse)
def report(rid: str):
    r = RESULTS.get(rid)
    if not r:
        return HTMLResponse(_page("Non trovato",
            "<h2>Report non disponibile</h2><p>Potrebbe essere scaduto.</p>"
            "<p><a href='/'>← Nuova analisi</a></p>"), status_code=404)
    return _inject_bar(r["html"], rid)


@app.get("/r/{rid}/pdf")
def report_pdf(rid: str):
    r = RESULTS.get(rid)
    if not r:
        return HTMLResponse(_page("Non trovato", "<h2>Report non disponibile</h2>"), status_code=404)
    try:
        pdf = geo_audit.render_pdf(r["html"])
    except Exception as e:
        return HTMLResponse(_page("PDF non disponibile",
            f"<h2>PDF non disponibile</h2><p>{geo_audit.esc(str(e))}</p>"), status_code=500)
    fname = f"geo-audit-{r['domain']}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
