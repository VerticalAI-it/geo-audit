# `qa/` — i controlli che si passano prima di consegnare

Strumenti da lanciare a mano quando si tocca qualcosa. Non girano in automatico:
servono a chi sta lavorando, non a un sistema di build.

Tutti vogliono le variabili d'ambiente del progetto (`.env`) e, dove indicato,
il server acceso.

| File | Cosa guarda |
|---|---|
| `controlla_pagine.py` | Le 8 pagine pubbliche: contrasto, sbordamento, errori di console |
| `controlla_pannello.py` | Le 8 schermate del pannello del team, più la finestra a comparsa |
| `collauda_pannello.py` | Che il pannello *funzioni*: route, permessi, numeri, casi limite |

---

## `controlla_pagine.py` e `controlla_pannello.py` — l'aspetto

Aprono ogni pagina in **due temi × due larghezze** e cercano tre cose:

| Controllo | Perché |
|---|---|
| **contrasto** | il testo si legge davvero sul fondo che ha sotto |
| **sbordamento** | la pagina non scorre lateralmente |
| **errori di console** | niente si rompe in silenzio |

```
# le pagine pubbliche: serve il server acceso a parte
.venv\Scripts\python.exe -m uvicorn server:app --port 8000
.venv\Scripts\python.exe qa\controlla_pagine.py

# il pannello: il server se lo avvia da solo, con la sessione già da team
.venv\Scripts\python.exe qa\controlla_pannello.py
```

⚠️ **Vanno lanciati contro il server, mai su un file salvato su disco.** Le
pagine linkano il CSS con un percorso assoluto (`/static/css/...`): da `file://`
quel foglio non si carica, la pagina appare senza stili e ogni controllo perde
senso. È esattamente il motivo per cui la pagina di accesso è rimasta
**illeggibile in tema chiaro** senza che nessuno se ne accorgesse.

⚠️ `controlla_pannello.py` **si finge il team** (`_current_user` sostituito): il
pannello sta dietro un controllo di ruolo, e da sloggati si vedrebbe solo la
pagina di accesso. Questo vale solo dentro il controllo — il ruolo vero resta
dov'è.

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

### E poi si guardano le schermate

I controlli salvano le pagine in `_schermate/`. **Vanno aperte.** L'automatismo
vede il contrasto e lo sbordamento; non vede un numero che contraddice la tabella
che ha sotto — «1 da contattare» sopra una riga marcata «è già cliente» è passato
indenne da ogni controllo ed è saltato fuori guardando l'immagine.

---

## `collauda_pannello.py` — il funzionamento

```
.venv\Scripts\python.exe qa\collauda_pannello.py
```

Apre le otto schermate per davvero e verifica che le cose ci siano *e*
funzionino: i permessi (un cliente riceve 404 su ogni route), gli indirizzi email
storti rifiutati, i numeri che non si contraddicono, il grafico che non disegna
periodi di cui non sappiamo niente.

⚠️ **Legge dati veri** dal database di produzione, ma **non scrive niente**.
Il collaudo del rilancio in blocco — che invece i dati li crea — sta a parte
proprio per questo: crea tre fallimenti finti, prova, e li cancella verificando
che non ne resti nessuno.

### Provare che un controllo sappia ancora fallire

Dopo ogni ritocco a un controllo, romperlo apposta e verificare che se ne
accorga: tre testi deliberatamente illeggibili per il contrasto, un numero
sbagliato per il collaudo. Un controllo ammorbidito finché non segnala più niente
**sembra** un prodotto sano: è il modo più facile di illudersi.

⚠️ E attenzione a importare da questi file: ognuno tiene la sua esecuzione dentro
`if __name__ == "__main__"`. Senza quella guardia, chi importava il controllo del
contrasto faceva partire l'intero giro sulle pagine pubbliche e poi usciva dal
processo — vedendosi stampare «nessun problema rilevato» e credendo fosse il
proprio esito.
