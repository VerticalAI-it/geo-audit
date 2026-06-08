"""
GEO Audit — servizio web
Analisi sincrona: il form invia l'URL, il report viene restituito direttamente.
"""
import os
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool

import geo_audit

app = FastAPI(title="GEO Audit · verticalai")

_HERE = os.path.dirname(os.path.abspath(__file__))
FORM_HTML = open(os.path.join(_HERE, "templates", "form.html"), encoding="utf-8").read()


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


def _inject_bar(html):
    hide = "<style>@media print{#geo-bar{display:none}}</style>"
    bar = (
        '<div id="geo-bar" style="position:fixed;top:14px;right:14px;z-index:999;'
        'display:flex;gap:8px;font-family:system-ui,sans-serif">'
        '<a href="#" onclick="window.print();return false;" '
        'style="background:#6C5CE7;color:#fff;text-decoration:none;'
        'font-weight:700;font-size:13px;padding:9px 14px;border-radius:9px">↓ PDF</a>'
        '<a href="/" style="background:#17152A;color:#F2F1F8;border:1px solid #2A2640;'
        'text-decoration:none;font-size:13px;padding:9px 14px;border-radius:9px">'
        "Nuova analisi</a></div>"
    )
    return html.replace('<div class="sheet">', hide + bar + '<div class="sheet">', 1)


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

    return HTMLResponse(_inject_bar(res["html"]))
