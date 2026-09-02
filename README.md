# GEO Audit — Vertical AI

Piattaforma di **Generative Engine Optimization**: misura quanto un sito è
leggibile, citabile e consigliabile dagli assistenti AI (ChatGPT, Gemini,
Claude, Perplexity), produce un report con punteggio e interventi prioritari, e
monitora l'andamento nel tempo.

In produzione su **[geo.verticalai.it](https://geo.verticalai.it)**.

> Non è un tool SEO. La SEO ottimizza per *comparire in una lista di link*; la
> GEO ottimizza per *essere la fonte che l'assistente legge, sintetizza e cita*.
> Cambiano i segnali che contano — dati strutturati, contenuto leggibile senza
> JavaScript, accesso dei crawler AI — e cambia il modo di misurare l'esito.

---

## Documentazione

**La documentazione completa è in [`docs/`](docs/README.md).** Questo file è solo
la porta d'ingresso.

| Se devi… | Leggi |
|---|---|
| Capire cos'è il prodotto | [docs/01-prodotto.md](docs/01-prodotto.md) |
| Mettere le mani nel codice | [docs/02-architettura.md](docs/02-architettura.md) |
| Far girare tutto in locale | [docs/08-setup-e-deploy.md](docs/08-setup-e-deploy.md) |
| Sapere dove sono le mine | [docs/10-stato-e-debito-tecnico.md](docs/10-stato-e-debito-tecnico.md) |
| Pianificare il prossimo lavoro | [docs/11-next-steps.md](docs/11-next-steps.md) |
| Toccare HTML, CSS o email | [design_system/DESIGN_SYSTEM.md](design_system/DESIGN_SYSTEM.md) |

**Regole operative vincolanti per chi modifica il repo: [CLAUDE.md](CLAUDE.md).**
Leggilo prima di aprire un file: contiene gli errori già pagati una volta.

---

## Come è fatto

| Layer | Tecnologia |
|---|---|
| Backend | Python 3.12 · FastAPI |
| Motore di audit | `geo_audit.py` — requests + BeautifulSoup, nessun LLM |
| Database e autenticazione | Supabase (Postgres + magic link) |
| Email | Resend |
| Frontend | HTML server-rendered, CSS con token, JavaScript senza framework |
| Hosting | Vercel (serverless) |

Il codice sta in quattro moduli, con gli import a senso unico:

```
server.py  →  views.py  →  db.py  →  config.py
   route      HTML delle    accesso    variabili
   auth       schermate     ai dati    d'ambiente
   email
   cron
```

**Mai il contrario**: `db.py` e `views.py` non importano `server.py`, o si crea
un ciclo.

---

## Avvio rapido

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env      # compila almeno SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY
set -a && source .env && set +a

uvicorn server:app --reload
# → http://localhost:8000
```

> **In locale serve `DEV_INSECURE_COOKIES=1` nel `.env`.** I cookie di sessione
> sono `secure` e su http il browser li scarta: senza quella variabile si fa il
> login e non si entra mai, senza nessun messaggio d'errore.

Il solo motore di audit gira anche senza database e senza credenziali:

```bash
python geo_audit.py www.esempio.it --max-pages 20 --out report.html
```

---

## Prima di un commit

Non ci sono test automatici ([è il primo debito da sanare](docs/11-next-steps.md)).
Il minimo sindacale:

```bash
python -m py_compile server.py views.py db.py config.py api/index.py geo_audit.py
python -c "import json; json.load(open('vercel.json'))"
python geo_audit.py example.com --no-pdf --max-pages 3
```

E una prova a occhio su **entrambi i temi** e su **schermo stretto**: il
comportamento responsive è pieno di dettagli che si rompono in silenzio.

---

## Tre cose che è costato caro imparare

1. **Niente `rewrites` in `vercel.json`.** Vercel serve l'app FastAPI come
   singola function e un catch-all manuale manda in conflitto il routing: build
   verde, produzione con `{"detail":"Not Found"}` su ogni pagina.
2. **Ogni endpoint va aggiunto come route FastAPI in `server.py`**, cron
   compreso. Un file in `api/` che non sia `index.py` non diventa mai una
   function — un cron è rimasto morto due settimane per questo.
3. **`NOTIFY pgrst, 'reload schema';`** dopo ogni migrazione, o le colonne nuove
   restano invisibili all'API con errore `PGRST205`.
