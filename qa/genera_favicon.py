# -*- coding: utf-8 -*-
"""Genera i file della favicon da zero, con la sola libreria standard.

Si lancia a mano quando il marchio cambia:

    python qa/genera_favicon.py

⚠️ Perche' uno script e non un'immagine disegnata una volta: non c'e' Pillow
nelle dipendenze e non vale aggiungerne una per una favicon. Qui il marchio e'
descritto in venti righe di geometria, quindi si rigenera invece di essere un
binario che nessuno sa piu' come rifare.

⚠️ Perche' non il logo di verticalai.it: quello e' un lettering 273x111 in
nero. A 16 pixel diventa una macchia, e su una scheda in tema scuro sparisce.
Il marchio quadrato con la V su gradiente viola e' quello che il prodotto
mostra gia' nel suo header (`.brand-mark` in admin.html), quindi non e' un
marchio inventato per l'occasione.
"""
import os
import struct
import zlib

QUI = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(QUI), "static")

# gli stessi due colori del gradiente di .brand-mark
C1 = (0x6C, 0x5C, 0xE7)
C2 = (0x5B, 0x4F, 0xE8)
BIANCO = (0xFF, 0xFF, 0xFF)

SUPER = 4          # campionamento 4x4 per bordi non scalettati
RAGGIO = 0.22      # raggio degli angoli, in frazione del lato


def _dentro_quadrato_stondato(x, y, lato):
    r = RAGGIO * lato
    if r <= 0:
        return True
    cx = min(max(x, r), lato - r)
    cy = min(max(y, r), lato - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _dentro_la_v(x, y, lato):
    """La V: due bracci che scendono verso un vertice in basso al centro."""
    u, v = x / lato, y / lato
    if not (0.26 <= v <= 0.76):
        return False
    spessore = 0.085
    # i due bracci, come distanza dalla retta che ognuno descrive
    for verso in (1, -1):
        # retta dal punto alto esterno al vertice basso centrale
        x0, y0 = 0.5 - verso * 0.215, 0.26
        x1, y1 = 0.5, 0.735
        dx, dy = x1 - x0, y1 - y0
        lung = (dx * dx + dy * dy) ** 0.5
        t = ((u - x0) * dx + (v - y0) * dy) / (lung * lung)
        if not (0.0 <= t <= 1.0):
            continue
        dist = abs((u - x0) * dy - (v - y0) * dx) / lung
        if dist <= spessore / 2:
            return True
    return False


def _pixel(lato):
    """Le righe RGBA dell'icona, con i bordi ammorbiditi."""
    righe = []
    passo = 1.0 / SUPER
    for py in range(lato):
        riga = bytearray()
        for px in range(lato):
            dentro = 0
            su_v = 0
            for sy in range(SUPER):
                for sx in range(SUPER):
                    x = px + (sx + 0.5) * passo
                    y = py + (sy + 0.5) * passo
                    if _dentro_quadrato_stondato(x, y, lato):
                        dentro += 1
                        if _dentro_la_v(x, y, lato):
                            su_v += 1
            tot = SUPER * SUPER
            if not dentro:
                riga += bytes((0, 0, 0, 0))
                continue
            # gradiente in diagonale, come il CSS
            k = (px + py) / (2.0 * lato)
            sfondo = tuple(round(C1[i] + (C2[i] - C1[i]) * k) for i in range(3))
            quota = su_v / float(dentro)
            colore = tuple(round(sfondo[i] + (BIANCO[i] - sfondo[i]) * quota)
                           for i in range(3))
            riga += bytes((colore[0], colore[1], colore[2],
                           round(255 * dentro / tot)))
        righe.append(bytes(riga))
    return righe


def _png(lato):
    righe = _pixel(lato)
    grezzo = b"".join(b"\x00" + r for r in righe)

    def chunk(tipo, dati):
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", lato, lato, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(grezzo, 9))
            + chunk(b"IEND", b""))


def _ico(lati):
    """Un .ico che contiene i PNG: lo chiedono i client vecchi e i crawler, che
    domandano /favicon.ico senza guardare l'HTML. Senza, e' un 404 nei log."""
    immagini = [_png(l) for l in lati]
    testa = struct.pack("<HHH", 0, 1, len(immagini))
    offset = 6 + 16 * len(immagini)
    voci = b""
    for lato, dati in zip(lati, immagini):
        voci += struct.pack("<BBBBHHII", lato if lato < 256 else 0,
                            lato if lato < 256 else 0, 0, 0, 1, 32,
                            len(dati), offset)
        offset += len(dati)
    return testa + voci + b"".join(immagini)


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6C5CE7"/>
      <stop offset="1" stop-color="#5B4FE8"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="url(#g)"/>
  <path d="M18.2 18.5 L32 44.5 L45.8 18.5" fill="none" stroke="#fff"
        stroke-width="7.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
'''


def main():
    with open(os.path.join(STATIC, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write(SVG)
    with open(os.path.join(STATIC, "favicon.ico"), "wb") as f:
        f.write(_ico([16, 32, 48]))
    with open(os.path.join(STATIC, "favicon-180.png"), "wb") as f:
        f.write(_png(180))
    for nome in ("favicon.svg", "favicon.ico", "favicon-180.png"):
        p = os.path.join(STATIC, nome)
        print("%-18s %6d byte" % (nome, os.path.getsize(p)))


if __name__ == "__main__":
    main()
