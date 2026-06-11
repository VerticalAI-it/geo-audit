# pay2vertical – SaaS No-Basket Checkout

Sistema di checkout semplificato per GEO. Completamente auto-contenuto in questa cartella.

## Stack

- **Backend**: Node.js + Express
- **Database**: PostgreSQL (via Docker)
- **Pagamenti**: Stripe Checkout (SCA/PSD2 compliant)
- **Frontend**: HTML5 + Tailwind CSS (CDN) + Vanilla JS

## Avvio rapido

```bash
# 1. Copia e configura le variabili d'ambiente
cp .env.example .env
# → Modifica DATABASE_URL, STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY,
#   STRIPE_WEBHOOK_SECRET, ADMIN_TOKEN, BASE_URL

# 2. Avvia il database PostgreSQL
docker-compose up -d

# 3. Installa le dipendenze Node.js
npm install

# 4. Crea le tabelle
npm run migrate

# 5. Avvia il server
npm start
# oppure in modalità sviluppo:
npm run dev
```

Il server è raggiungibile su `http://localhost:3000`.

## Route

| Path              | Descrizione                                  |
|-------------------|----------------------------------------------|
| `/`               | Landing page utente                          |
| `/success`        | Pagina di successo post-pagamento            |
| `/cancel`         | Pagina annullamento pagamento                |
| `/admin/`         | Pannello amministratore                      |
| `GET  /api/validate/:code` | Valida un codice offerta            |
| `POST /api/checkout`       | Crea sessione Stripe Checkout       |
| `POST /api/webhook`        | Webhook Stripe                      |
| `GET  /api/admin/offers`   | Lista offerte (admin)               |
| `POST /api/admin/offers`   | Crea offerta (admin)                |
| `PATCH /api/admin/offers/:id` | Attiva/disattiva offerta (admin) |
| `DELETE /api/admin/offers/:id` | Elimina offerta (admin)         |
| `GET  /api/admin/orders`   | Lista ordini (admin)                |

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
├── docker-compose.yml     # PostgreSQL
├── .env.example
├── db/
│   ├── index.js           # Pool PostgreSQL
│   ├── schema.sql         # DDL tabelle
│   └── migrate.js         # Script migrazione
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
