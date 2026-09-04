# -*- coding: utf-8 -*-
"""Le otto schermate del pannello, viste davvero: contrasto, sbordamento, errori.

Avvia il server con la sessione gia' da team — il pannello e' dietro un
controllo di ruolo, e da sloggati si vedrebbe solo la pagina di accesso.

⚠️ Il server va servito per davvero: da `file://` il CSS con percorso assoluto
non si carica, la pagina appare senza stili e ogni controllo perde senso.
"""
import asyncio
import os
import sys
import threading
import time

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)
sys.path.insert(0, os.path.join(RADICE, "qa"))

import server
import uvicorn
from playwright.async_api import async_playwright

TEAM = {"id": "u-qa", "email": "qa@verticalai.it", "app_metadata": {"role": "admin"}}
server._current_user = lambda req: (TEAM, None)

PORTA = 8123
BASE = f"http://127.0.0.1:{PORTA}"
PAGINE = {
    "overview": "/admin",
    "overview-7": "/admin?giorni=7",
    "lead": "/admin/lead",
    "clienti": "/admin/clienti",
    "job-log": "/admin/job-log",
    "tracking": "/admin/tracking",
    "interesse": "/admin/interesse",
    "log": "/admin/log",
}

# lo stesso controllo di contrasto usato sulle pagine pubbliche
from controlla_pagine import CONTRASTO  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_schermate")
os.makedirs(OUT, exist_ok=True)


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
                    await pg.wait_for_timeout(500)

                    scarsi = await pg.evaluate(CONTRASTO)
                    if scarsi:
                        problemi.append(f"{nome} · {tema} @{larghezza}: CONTRASTO {scarsi}")

                    sbordo = await pg.evaluate(
                        "() => document.documentElement.scrollWidth "
                        "- document.documentElement.clientWidth")
                    if sbordo > 2:
                        problemi.append(f"{nome} · {tema} @{larghezza}: sborda di {sbordo}px")

                    reali = [e for e in err if "favicon" not in e.lower()]
                    if reali:
                        problemi.append(f"{nome} · {tema} @{larghezza}: console {reali[:2]}")

                    if larghezza == 1280 and tema == "light":
                        await pg.screenshot(path=os.path.join(OUT, f"{nome}.png"),
                                            full_page=True)
                    await pg.close()

        # ── la finestra a comparsa si apre e si chiude ──────────────────────
        pg = await b.new_page(viewport={"width": 1280, "height": 900})
        await pg.goto(BASE + "/admin/clienti", timeout=30000)
        visibile = await pg.evaluate("() => !document.getElementById('agg-cliente').hidden")
        if visibile:
            problemi.append("il modulo «Aggiungi cliente» è aperto senza che nessuno lo chieda")
        await pg.click('[data-apri="agg-cliente"]')
        await pg.wait_for_timeout(200)
        aperto = await pg.evaluate("() => !document.getElementById('agg-cliente').hidden")
        if not aperto:
            problemi.append("il modulo «Aggiungi cliente» non si apre")
        else:
            await pg.screenshot(path=os.path.join(OUT, "modale-aggiungi.png"))
            # e il campo email deve avere il fuoco: chi lo apre vuole scrivere
            focus = await pg.evaluate("() => document.activeElement.name")
            if focus != "email":
                problemi.append(f"aperto il modulo, il fuoco è su {focus!r} invece che sull'email")
            await pg.keyboard.press("Escape")
            await pg.wait_for_timeout(200)
            chiuso = await pg.evaluate("() => document.getElementById('agg-cliente').hidden")
            if not chiuso:
                problemi.append("Esc non chiude il modulo")
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


t = threading.Thread(target=avvia, daemon=True)
t.start()
time.sleep(3)
raise SystemExit(0 if asyncio.run(main()) == 0 else 1)
