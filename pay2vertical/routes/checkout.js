const express = require('express');
const router = express.Router();
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const db = require('../db');

router.get('/validate/:code', async (req, res) => {
  try {
    const result = await db.query(
      'SELECT id, code, description, amount, currency, billing_cycle FROM offers WHERE UPPER(code) = UPPER($1) AND is_active = true',
      [req.params.code.trim()]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ valid: false, message: 'Codice non valido o scaduto' });
    }

    const offer = result.rows[0];
    res.json({
      valid: true,
      offer: {
        code: offer.code,
        description: offer.description,
        amount: parseFloat(offer.amount),
        currency: offer.currency,
        billing_cycle: offer.billing_cycle,
      },
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ valid: false, message: 'Errore interno del server' });
  }
});

router.post('/checkout', async (req, res) => {
  try {
    const { code } = req.body;
    if (!code) return res.status(400).json({ error: 'Codice mancante' });

    const result = await db.query(
      'SELECT * FROM offers WHERE UPPER(code) = UPPER($1) AND is_active = true',
      [code.trim()]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Codice non valido o scaduto' });
    }

    const offer = result.rows[0];
    const amountCents = Math.round(parseFloat(offer.amount) * 100);
    const isRecurring = offer.billing_cycle === 'recurring_monthly';

    const priceData = {
      currency: offer.currency.toLowerCase(),
      product_data: { name: offer.description },
      unit_amount: amountCents,
    };

    if (isRecurring) {
      priceData.recurring = { interval: 'month' };
    }

    const session = await stripe.checkout.sessions.create({
      payment_method_types: ['card'],
      line_items: [{ price_data: priceData, quantity: 1 }],
      mode: isRecurring ? 'subscription' : 'payment',
      success_url: `${process.env.BASE_URL}/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${process.env.BASE_URL}/cancel`,
      metadata: {
        offer_id: offer.id.toString(),
        offer_code: offer.code,
      },
    });

    await db.query(
      'INSERT INTO orders (offer_id, stripe_session_id, status) VALUES ($1, $2, $3)',
      [offer.id, session.id, 'pending']
    );

    res.json({ url: session.url });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Errore nella creazione del checkout' });
  }
});

module.exports = router;
