# -*- coding: utf-8 -*-
"""Un giro su tutte le pagine pubbliche: contrasto, sbordamento, errori di console.
qualcosa: contrasto vero, sbordamento, errori di console.

Serve il server acceso (il CSS va servito davvero: da `file://` i fogli con
percorso assoluto non si caricano, ed è per questo che il login illeggibile era
rimasto invisibile).
"""
import os, sys, asyncio, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_schermate")
os.makedirs(OUT, exist_ok=True)

PUBBLICHE = {
    "home": "/",
    "login": "/login",
    "richiedi-accesso": "/richiedi-accesso?email=a%40b.it",
    "richiesta-ricevuta": "/richiesta-ricevuta?email=a%40b.it&sito=esempio.it",
    "roadmap": "/roadmap",
    "privacy": "/privacy",
    "cookie": "/cookie-policy",
    "miei-report": "/miei-report",
}

CONTRASTO = """() => {
  const lum = c => {
    const m = c.match(/[\\d.]+/g); if(!m) return null;
    const [r,g,b] = m.slice(0,3).map(Number);
    const f = v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4); };
    return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);
  };
  /* ⚠️ Il fondo dietro un testo non è quasi mai quello dell'elemento: è del
     primo antenato che ne ha uno davvero. E quando quell'antenato ha un
     GRADIENTE bisogna leggere i colori del gradiente, non ricadere sul body —
     altrimenti ogni bottone colorato di questo prodotto risulta illeggibile e
     lo strumento diventa rumore che si impara a ignorare. */
  const fondo = el => {
    for(let n=el; n; n=n.parentElement){
      const s = getComputedStyle(n);
      const m = s.backgroundColor.match(/[\\d.]+/g);
      if(m && (m.length<4 || parseFloat(m[3])>0.5)) return [s.backgroundColor];
      if(s.backgroundImage && s.backgroundImage !== 'none'){
        /* Solo i colori del gradiente che coprono davvero. Un gradiente
           semitrasparente — ce ne sono diversi qui, per velare un pannello —
           lascia vedere quello che ha sotto, quindi non è lui il fondo e si
           continua a risalire. */
        const colori = (s.backgroundImage.match(/rgba?\\([^)]+\\)/g) || []).filter(cc => {
          const m = cc.match(/[\\d.]+/g);
          return m && (m.length < 4 || parseFloat(m[3]) > 0.5);
        });
        if(colori.length) return colori;
      }
    }
    return ['rgb(255,255,255)'];
  };
  const out = [];
  document.querySelectorAll('h1,h2,h3,p,div,span,button,label,a,td,th,li').forEach(el => {
    const t = el.textContent.trim();
    if(!t || el.children.length) return;
    const s = getComputedStyle(el);
    if(s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) < 0.1) return;
    if(!el.offsetParent && s.position !== 'fixed') return;
    const r0 = el.getBoundingClientRect();
    if(r0.width < 2 || r0.height < 2) return;
    const lt = lum(s.color);
    if(lt === null) return;
    /* Col gradiente si prende il punto PEGGIORE: se il testo diventa
       illeggibile su una delle sue estremità, è illeggibile. */
    let peggiore = null;
    for(const f of fondo(el)){
      const lf = lum(f);
      if(lf === null) continue;
      const r = (Math.max(lt,lf)+0.05)/(Math.min(lt,lf)+0.05);
      if(peggiore === null || r < peggiore) peggiore = r;
    }
    if(peggiore !== null && peggiore < 2.2)
      out.push({t: t.slice(0,40), r: +peggiore.toFixed(2), colore: s.color});
  });
  return out.slice(0,5);
}"""


async def main():
    problemi = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for nome, url in PUBBLICHE.items():
            for tema in ("light", "dark"):
                for larghezza, et in ((1280, "desktop"), (390, "mobile")):
                    pg = await b.new_page(viewport={"width": larghezza, "height": 900})
                    err = []
                    pg.on("pageerror", lambda e: err.append(str(e)))
                    pg.on("console", lambda m: err.append(m.text) if m.type == "error" else None)
                    await pg.add_init_script(
                        f"try{{localStorage.setItem('geo-theme','{tema}')}}catch(e){{}}")
                    try:
                        await pg.goto(BASE + url, timeout=20000)
                    except Exception as e:
                        problemi.append(f"{nome}: non si apre ({e})")
                        await pg.close(); continue
                    await pg.wait_for_timeout(500)

                    scarsi = await pg.evaluate(CONTRASTO)
                    if scarsi:
                        problemi.append(f"{nome} · {tema} @{larghezza}: CONTRASTO "
                                        + json.dumps(scarsi, ensure_ascii=False))
                        await pg.screenshot(path=os.path.join(OUT, f"{nome}-{tema}-{et}.png"),
                                            full_page=True)

                    sbordo = await pg.evaluate(
                        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    if sbordo > 2:
                        problemi.append(f"{nome} · {tema} @{larghezza}: sborda di {sbordo}px")

                    reali = [e for e in err if "favicon" not in e.lower()]
                    if reali:
                        problemi.append(f"{nome} · {tema} @{larghezza}: console {reali[:2]}")
                    await pg.close()
        await b.close()

    print(f"pagine controllate: {len(PUBBLICHE)} × 2 temi × 2 larghezze = {len(PUBBLICHE)*4} viste\n")
    if problemi:
        for x in problemi:
            print("  - " + x)
    else:
        print("  nessun problema rilevato")
    return len(problemi)


sys.exit(0 if asyncio.run(main()) == 0 else 1)
