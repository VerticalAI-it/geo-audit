# pay2vertical – SaaS No-Basket Checkout

Sistema di checkout semplificato per GEO. Completamente auto-contenuto in questa cartella.

## Stack

- **Backend**: Node.js + Express
- **Database**: Supabase (PostgreSQL)
- **Pagamenti**: Stripe Checkout (SCA/PSD2 compliant)
- **Frontend**: HTML5 + Tailwind CSS (CDN) + Vanilla JS

## Avvio rapido

```bash
# 1. Copia e configura le variabili d'ambiente
cp .env.example .env
# → Compila DATABASE_URL (da Supabase), STRIPE_*, ADMIN_TOKEN, BASE_URL

# 2. Installa le dipendenze Node.js
npm install

# 3. Crea le tabelle su Supabase
#    Opzione A — SQL editor di Supabase: incolla il contenuto di db/schema.sql
#    Opzione B — script automatico (richiede DATABASE_URL nel .env):
npm run migrate

# 4. Avvia il server
npm start
# oppure in modalità sviluppo:
npm run dev
```

Il server è raggiungibile su `http://localhost:3000`.

## Dove trovare la DATABASE_URL su Supabase

1. Apri il tuo progetto su [supabase.com](https://supabase.com)
2. **Project Settings → Database → Connection string → URI**
3. Copia la stringa e sostituisci `[YOUR-PASSWORD]` con la password del DB
4. Incollala in `.env` come `DATABASE_URL`

## Route

| Path | Descrizione |
|---|---|
| `/` | Landing page utente |
| `/success` | Pagina di successo post-pagamento |
| `/cancel` | Pagina annullamento pagamento |
| `/admin/` | Pannello amministratore |
| `GET  /api/validate/:code` | Valida un codice offerta |
| `POST /api/checkout` | Crea sessione Stripe Checkout |
| `POST /api/webhook` | Webhook Stripe |
| `GET  /api/admin/offers` | Lista offerte (admin) |
| `POST /api/admin/offers` | Crea offerta (admin) |
| `PATCH /api/admin/offers/:id` | Attiva/disattiva offerta (admin) |
| `DELETE /api/admin/offers/:id` | Elimina offerta (admin) |
| `GET  /api/admin/orders` | Lista ordini (admin) |

## Autenticazione Admin

Il pannello admin è protetto da un token statico (`ADMIN_TOKEN` nel `.env`).
Impostarlo su una stringa lunga e casuale prima del deploy in produzione.

## Webhook Stripe

Configura il webhook su [dashboard.stripe.com](https://dashboard.stripe.com/webhooks)
puntando a `https://<tuo-dominio>/api/webhook`.

Eventi gestiti:
- `checkout.session.completed` → attiva l'ordine
- `invoice.payment_failed` → segna l'ordine come fallito
- `customer.subscription.deleted` → segna l'ordine come cancellato

## Struttura cartelle

```
pay2vertical/
├── server.js              # Entry point Express
├── package.json
├── .env.example
├── db/
│   ├── index.js           # Pool PostgreSQL (con SSL per Supabase)
│   ├── schema.sql         # DDL tabelle
│   └── migrate.js         # Script migrazione opzionale
├── routes/
│   ├── checkout.js        # /api/validate + /api/checkout
│   ├── webhook.js         # /api/webhook (Stripe)
│   └── admin.js           # /api/admin/*
└── public/
    ├── index.html         # Landing page utente
    ├── success.html
    ├── cancel.html
    ├── admin/
    │   └── index.html     # Pannello admin
    └── js/
        ├── app.js         # Logica landing page
        └── admin.js       # Logica pannello admin
```
