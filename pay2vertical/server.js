require('dotenv').config();
const express = require('express');
const path = require('path');

const webhookRouter  = require('./routes/webhook');
const checkoutRouter = require('./routes/checkout');
const adminRouter    = require('./routes/admin');

const app = express();
const PORT = process.env.PORT || 3000;

// Stripe webhook requires the raw body — must be registered before express.json()
app.use('/api/webhook', express.raw({ type: 'application/json' }), webhookRouter);

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

app.use('/api/admin', adminRouter);
app.use('/api', checkoutRouter);

// SPA-style catch-all: serve index.html for unknown paths
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Local dev: listen directly. Vercel imports this file as a module (no listen needed).
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`pay2vertical server running on http://localhost:${PORT}`);
  });
}

module.exports = app;
