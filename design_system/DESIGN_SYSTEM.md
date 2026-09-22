# GEO Audit · Design System

Architettura del frontend e delle email.

⚠️ **Le 72 route non stanno tutte qui.** Questo documento descrive **come** è
fatto il frontend; l'elenco completo e aggiornato delle route si ricava dal
codice, che è l'unica fonte che non invecchia:

```
grep -o '@app\.\(get\|post\)("[^"]*")' server.py
```

Fonte di verità visiva: le pagine servite da `templates/` con
`static/css/geo-ds.css`.

---

## Architettura del frontend

### Stack e rendering

| Layer | Tecnologia | Note |
|---|---|---|
| Backend | Python · FastAPI | `server.py` — **una sola applicazione**. Il cron è la route `/api/cron`, non un file a parte |
| Rendering HTML | Template statici + sostituzione di stringhe | Nessun motore di template. I file `.html` di `templates/` sono letti in memoria all'avvio e riempiti con `.replace()`; il corpo delle schede lo compongono `views.py`, `admin.py`, `ai_schermate.py` |
| CSS | Tre fogli, in migrazione | vedi sotto |
| JavaScript | Vanilla, inline | Nessun framework. Gli script stanno accanto al markup che pilotano |
| Deploy | Vercel (serverless) | Tutto passa da `/api/index`; FastAPI serve `/static/*` direttamente |

### I tre fogli di stile, e quale carica cosa

⚠️ **Convivono due generazioni di CSS.** È debito dichiarato
([11 · Next steps](../docs/11-next-steps.md)): `ponte-legacy.css` rimappa i
token vecchi sui nuovi, e va tolto a migrazione finita.

| Foglio | Chi lo carica | Contiene |
|---|---|---|
| `geo-ds.css` | `project.html`, `dashboard.html`, `admin.html` | Il design system nuovo: token, sidebar, schede, tabelle dati, grafici |
| `ponte-legacy.css` | `project.html` | Rimappa i nomi vecchi sui token nuovi, più i componenti che il nuovo non ha ancora (`.alert`, tabelle responsive) |
| `design-system.css` | le pagine pubbliche (`home`, `form`, `login`, `lead`, `privacy`, `cookie`) | La generazione precedente |

⚠️ **Un componente usato su una pagina dev'essere definito nel foglio che
quella pagina carica.** Le classi `.alert--warning` e `.alert--info` esistevano
solo in `design-system.css`: sulla pagina progetto, che non lo carica, un
avviso e una nota uscivano come due scatole grigie identiche. Stesso genere di
problema per il pannello: `admin.html` **non carica `geo-ds.css`**, ha il
proprio `<style>` in testa, quindi le classi del prodotto lì non esistono — le
schermate del monitoraggio AI usano infatti le classi `ai-*` definite dentro
quel template.

### Font

| Ruolo | Famiglia | Dove |
|---|---|---|
| Display / titoli | Space Grotesk | ovunque |
| Body / UI | Inter | ovunque |
| Mono / dati | IBM Plex Mono | prodotto e pannello |
| Mono / dati | JetBrains Mono | solo `design-system.css`, cioè le pagine pubbliche |

⚠️ Le due mono sono un residuo della migrazione, non una scelta: vanno
unificate su IBM Plex Mono quando si toglie il ponte.

### Le route, per famiglia

Non l'elenco (sta nel codice), ma le famiglie e come si comportano:

| Famiglia | Prefisso | Accesso | Risposta a chi non può |
|---|---|---|---|
| Pubbliche | `/`, `/audit`, `/r/{id}`, `/roadmap`, `/privacy`… | nessuno | — |
| Cliente | `/project/{id}`, `/preferenze`, `/auth` | sessione valida | redirect a `/login` |
| Pannello del team | `/admin/*` | ruolo admin in `app_metadata` | **404, non 403** |
| Servizio | `/api/cron`, `/api/cron-ai`, `/t`, `/health` | `CRON_SECRET` sulle prime due, nessuno sulle altre | 401 |

⚠️ Al pannello si risponde **404** apposta: un 403 confermerebbe che a quel
percorso c'è qualcosa.

### Soglie di colore del punteggio

| Intervallo | Etichetta | Token |
|---|---|---|
| 75–100 | Ottimo | `--state-good` |
| 50–74 | Migliorabile | `--state-warn` |
| 0–49 | Critico | `--state-critical` |

⚠️ Il **report generato** da `geo_audit.py` usa una seconda scala a lettere
(A ≥ 90, B ≥ 75, C ≥ 60, D ≥ 45, E ≥ 30, F). Sono due scale diverse sullo
stesso numero, ed è voluto: la lettera è un giudizio sintetico per il cliente,
il colore è uno stato operativo per chi lavora.

---

## Architettura email

Tutte le email passano da **Resend**, con un solo punto di uscita:
`_resend_post()` in `server.py`. Chi aggiunge un'email passa di lì, così la
gestione degli errori e il mittente restano in un posto solo.

### Inventario

| Email | Funzione | Quando parte |
|---|---|---|
| Link di accesso | `_send_magic_link()` | richiesta di accesso, o invito dal pannello |
| Report pronto (sblocco) | `_send_unlock_email()` | `POST /unlock/{job_id}` |
| I miei report | `_send_my_reports_email()` | `POST /miei-report` |
| Notifica contatto (interna) | `_send_contact_notif()` | `POST /contact/{job_id}` |
| Notifica lead (interna) | `_send_lead_notif()` | richiesta di analisi da un nuovo contatto |
| Promemoria tracking | `_send_promemoria_tracking()` | azione dal pannello |
| Avviso calo punteggio | `_send_avviso_calo()` | cron, se il punteggio scende oltre la soglia |
| Avviso nuova criticità grave | `_send_avviso_critica()` | cron, su criticità alta o critica nuova |
| Riepilogo periodico | `_send_digest()` | cron, secondo le preferenze del progetto |
| Richiesta report (al team) | `_send_report_request_admin()` | il cliente chiede un report |
| Richiesta report (al cliente) | `_send_report_request_user()` | conferma al cliente |

### Le tre funzioni senza innesco

Esistono, sono scritte, non le chiama nessuno:

| Funzione | Cosa aspetta |
|---|---|
| `_send_analisi_completa()` | un innesco di follow-up mai deciso |
| `_send_report_mensile()` | uno scheduler mensile; il `digest` periodico copre quasi lo stesso bisogno |

⚠️ `_send_conferma_audit()` è citata in `docs/11-next-steps.md` e in vecchi
appunti come terza funzione orfana: **non esiste più**. Apparteneva alla coda
asincrona, che è stata rimossa; oggi l'audit è sincrono e non c'è un momento in
cui «confermare la presa in carico».

⚠️ Non vanno cancellate né agganciate a caso: sono decisioni di prodotto, non
codice morto per distrazione.

---

## Quando si tocca questo documento

Quando cambia **come** è fatto il frontend — un foglio di stile in più, una
famiglia di route nuova, un'email nuova. Non quando si aggiunge una route: per
quelle c'è il codice, e un elenco copiato a mano invecchia in una settimana.
È già successo: questo documento ha elencato per mesi nove route su settantadue
e un file `api/cron.py` che non esiste più.
