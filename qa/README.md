# `qa/` — i controlli che si passano sulle pagine

Strumenti da lanciare a mano quando si tocca l'aspetto di qualcosa. Non girano
in automatico: servono a chi sta lavorando, non a un sistema di build.

## `controlla_pagine.py`

Apre ogni pagina pubblica in **due temi × due larghezze** e cerca tre cose:

| Controllo | Perché |
|---|---|
| **contrasto** | il testo si legge davvero sul fondo che ha sotto |
| **sbordamento** | la pagina non scorre lateralmente |
| **errori di console** | niente si rompe in silenzio |

```
# serve il server acceso, perché il CSS va servito davvero
.venv\Scripts\python.exe -m uvicorn server:app --port 8000
.venv\Scripts\python.exe qa\controlla_pagine.py
```

⚠️ **Va lanciato contro il server, mai su un file salvato su disco.** Le pagine
linkano il CSS con un percorso assoluto (`/static/css/...`): da `file://` quel
foglio non si carica, la pagina appare senza stili e ogni controllo perde senso.
È esattamente il motivo per cui la pagina di accesso è rimasta **illeggibile in
tema chiaro** senza che nessuno se ne accorgesse.

### Due cose imparate scrivendo il controllo del contrasto

⚠️ **Il fondo dietro un testo non è quasi mai quello dell'elemento**: è del primo
antenato che ne ha uno davvero. Confrontare il colore del testo con lo sfondo
dell'elemento — che di solito è trasparente — non trova niente.

⚠️ **I gradienti vanno letti, non aggirati.** La prima versione, davanti a un
gradiente, ricadeva sul colore del body: risultato, ogni bottone colorato
risultava illeggibile e le segnalazioni vere sparivano nel rumore. Ora si
leggono i colori del gradiente e si prende il punto peggiore — saltando però
quelli **semitrasparenti**, che lasciano vedere ciò che hanno sotto e quindi non
sono il fondo.

### Provare che il controllo sappia ancora fallire

Dopo ogni ritocco, iniettare in pagina tre elementi deliberatamente illeggibili
(scuro su scuro, bianco su bianco, grigio su grigio) e verificare che li trovi
tutti e tre. Un controllo ammorbidito finché non segnala più niente **sembra**
un prodotto sano: è il modo più facile di illudersi.
