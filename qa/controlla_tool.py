# -*- coding: utf-8 -*-
"""Le pagine del tool cliente — quelle dietro l'accesso — in due temi e due larghezze.

⚠️ Questo controllo non esisteva, ed è il motivo per cui il tema chiaro rotto su
«Nuova analisi» è arrivato fino al consulente: `controlla_pagine.py` guarda solo
le pagine pubbliche, e tutto ciò che sta dietro il login non lo vedeva nessuno.
Il difetto era lo stesso già corretto sul login, su altre tre pagine.

Si finge un utente loggato sostituendo `_current_user`: vale solo dentro questo
controllo, il vero accesso resta dov'è.
"""
import asyncio
import os
import sys
import threading
import time

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)
sys.path.insert(0, os.path.join(RADICE, "qa"))

import db
import server
import uvicorn
from controlla_pagine import CONTRASTO
from playwright.async_api import async_playwright

PORTA = 8124
BASE = f"http://127.0.0.1:{PORTA}"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_schermate")
os.makedirs(OUT, exist_ok=True)

prog = next((p for p in db._sb_progetti_tutti()
             if db._sb_audits_by_project(p["id"], limit=1, full=False)), None)
if not prog:
    raise SystemExit("nessun progetto con audit: non c'è niente da guardare")

UTENTE = {"id": prog["user_id"], "email": "qa@verticalai.it", "app_metadata": {}}
server._current_user = lambda req: (UTENTE, None)

PID = prog["id"]
PAGINE = {
    "nuova-analisi": "/audit",
    "dashboard": "/dashboard",
    "progetto-riepilogo": f"/project/{PID}?tab=audit",
    "progetto-pagine": f"/project/{PID}?tab=pages",
    "progetto-technical": f"/project/{PID}?tab=technical",
    "progetto-criticita": f"/project/{PID}?tab=opportunities",
    "progetto-traffico": f"/project/{PID}?tab=traffic",
    "progetto-rapporti": f"/project/{PID}?tab=reports",
    "progetto-impostazioni": f"/project/{PID}?tab=settings",
    "miei-report": "/miei-report",
}


def avvia():
    uvicorn.run(server.app, host="127.0.0.1", port=PORTA, log_level="error")


async def main():
    problemi = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for nome, url in PAGINE.items():
            for tema in ("light", "dark"):
                for larghezza, et in ((1280, "desktop"), (390, "mobile")):
                    pg = await b.new_page(viewport={"width": larghezza, "height": 900})
                    err = []
                    pg.on("pageerror", lambda e: err.append(str(e)))
                    pg.on("console", lambda m: err.append(m.text) if m.type == "error" else None)
                    await pg.add_init_script(
                        f"try{{localStorage.setItem('geo-theme','{tema}')}}catch(e){{}}")
                    try:
                        await pg.goto(BASE + url, timeout=30000)
                    except Exception as e:
                        problemi.append(f"{nome}: non si apre ({e})")
                        await pg.close()
                        continue
                    await pg.wait_for_timeout(600)

                    scarsi = await pg.evaluate(CONTRASTO)
                    if scarsi:
                        problemi.append(f"{nome} · {tema} @{larghezza}: CONTRASTO {scarsi}")
                        await pg.screenshot(
                            path=os.path.join(OUT, f"tool-{nome}-{tema}-{et}.png"), full_page=True)

                    sbordo = await pg.evaluate(
                        "() => document.documentElement.scrollWidth "
                        "- document.documentElement.clientWidth")
                    if sbordo > 2:
                        problemi.append(f"{nome} · {tema} @{larghezza}: sborda di {sbordo}px")

                    reali = [e for e in err if "favicon" not in e.lower()]
                    if reali:
                        problemi.append(f"{nome} · {tema} @{larghezza}: console {reali[:2]}")

                    if larghezza == 1280:
                        await pg.screenshot(
                            path=os.path.join(OUT, f"tool-{nome}-{tema}.png"), full_page=True)
                    await pg.close()

        # ── e le cose nuove funzionano davvero, non solo esistono ──────────
        pg = await b.new_page(viewport={"width": 1280, "height": 900})
        await pg.goto(BASE + f"/project/{PID}?tab=opportunities", timeout=30000)
        await pg.wait_for_timeout(800)

        rimedio = pg.locator("tr.riga-rimedio").first
        if await rimedio.count():
            if not await rimedio.is_hidden():
                problemi.append("la spiegazione è già aperta senza che nessuno l'abbia chiesta")
            await pg.locator("tr.riga-issue").first.click()
            await pg.wait_for_timeout(250)
            if await rimedio.is_hidden():
                problemi.append("la riga non si apre al clic")
            else:
                await pg.screenshot(path=os.path.join(OUT, "tool-riga-aperta.png"))
        else:
            problemi.append("nessuna riga con spiegazione trovata")

        await pg.goto(BASE + f"/project/{PID}?tab=technical", timeout=30000)
        await pg.wait_for_timeout(600)
        kpi = pg.locator(".kpi-filtro").first
        if await kpi.count():
            prima = await pg.locator("tr[data-stato]:visible").count()
            await kpi.click()
            await pg.wait_for_timeout(250)
            dopo = await pg.locator("tr[data-stato]:visible").count()
            if dopo >= prima:
                problemi.append(f"il filtro di Technical non filtra ({prima} → {dopo} righe)")
            else:
                await pg.screenshot(path=os.path.join(OUT, "tool-technical-filtrato.png"))
        else:
            problemi.append("i KPI filtro di Technical non ci sono")
        await pg.close()
        await b.close()

    print(f"\npagine: {len(PAGINE)} × 2 temi × 2 larghezze = {len(PAGINE) * 4} viste")
    if problemi:
        for x in problemi:
            print("  - " + x)
    else:
        print("  nessun problema rilevato")
    print(f"\nschermate in {OUT}")
    return len(problemi)


if __name__ == "__main__":
    threading.Thread(target=avvia, daemon=True).start()
    time.sleep(3)
    sys.exit(0 if asyncio.run(main()) == 0 else 1)
