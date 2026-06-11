const express = require('express');
const router = express.Router();
const db = require('../db');

const adminAuth = (req, res, next) => {
  const token = req.headers['x-admin-token'];
  if (!token || token !== process.env.ADMIN_TOKEN) {
    return res.status(401).json({ error: 'Non autorizzato' });
  }
  next();
};

router.use(adminAuth);

// -- Offers --

router.get('/offers', async (req, res) => {
  try {
    const result = await db.query('SELECT * FROM offers ORDER BY created_at DESC');
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.post('/offers', async (req, res) => {
  const { code, description, amount, currency = 'EUR', billing_cycle } = req.body;

  if (!code || !description || amount == null || !billing_cycle) {
    return res.status(400).json({ error: 'Campi obbligatori mancanti: code, description, amount, billing_cycle' });
  }

  if (!['one_time', 'recurring_monthly'].includes(billing_cycle)) {
    return res.status(400).json({ error: "billing_cycle deve essere 'one_time' o 'recurring_monthly'" });
  }

  try {
    const result = await db.query(
      'INSERT INTO offers (code, description, amount, currency, billing_cycle) VALUES (UPPER($1), $2, $3, $4, $5) RETURNING *',
      [code, description, amount, currency.toUpperCase(), billing_cycle]
    );
    res.status(201).json(result.rows[0]);
  } catch (err) {
    if (err.code === '23505') {
      return res.status(409).json({ error: 'Codice già esistente' });
    }
    res.status(500).json({ error: err.message });
  }
});

router.patch('/offers/:id', async (req, res) => {
  const { is_active } = req.body;
  try {
    const result = await db.query(
      'UPDATE offers SET is_active = $1 WHERE id = $2 RETURNING *',
      [is_active, req.params.id]
    );
    if (result.rows.length === 0) return res.status(404).json({ error: 'Offerta non trovata' });
    res.json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.delete('/offers/:id', async (req, res) => {
  try {
    await db.query('DELETE FROM offers WHERE id = $1', [req.params.id]);
    res.status(204).end();
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// -- Orders --

router.get('/orders', async (req, res) => {
  try {
    const result = await db.query(`
      SELECT
        o.id, o.stripe_session_id, o.stripe_subscription_id,
        o.customer_email, o.status, o.amount_paid,
        o.created_at, o.completed_at,
        of.code AS offer_code, of.description AS offer_description,
        of.billing_cycle
      FROM orders o
      LEFT JOIN offers of ON o.offer_id = of.id
      ORDER BY o.created_at DESC
    `);
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
