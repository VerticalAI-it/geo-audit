(() => {
  const input      = document.getElementById('code-input');
  const validateBtn = document.getElementById('validate-btn');
  const errorMsg   = document.getElementById('error-msg');
  const errorText  = document.getElementById('error-text');
  const offerBox   = document.getElementById('offer-box');
  const payBtn     = document.getElementById('pay-btn');
  const payBtnText = document.getElementById('pay-btn-text');
  const paySpinner = document.getElementById('pay-spinner');

  let currentCode = null;
  let debounceTimer = null;

  function showError(msg) {
    errorText.textContent = msg;
    errorMsg.classList.remove('hidden');
    offerBox.classList.add('hidden');
    currentCode = null;
  }

  function hideError() {
    errorMsg.classList.add('hidden');
  }

  function showOffer(offer) {
    hideError();
    currentCode = offer.code;

    document.getElementById('offer-description').textContent = offer.description;
    document.getElementById('offer-code').textContent        = offer.code;

    const formatter = new Intl.NumberFormat('it-IT', {
      style: 'currency', currency: offer.currency, minimumFractionDigits: 0,
    });

    document.getElementById('offer-price').textContent = formatter.format(offer.amount);

    const isRecurring = offer.billing_cycle === 'recurring_monthly';
    document.getElementById('offer-cycle').textContent = isRecurring ? '/mese' : 'una tantum';
    document.getElementById('offer-badge').textContent  = isRecurring ? 'Abbonamento mensile' : 'Pagamento unico';

    offerBox.classList.remove('hidden');
  }

  async function validateCode(code) {
    if (!code) { hideError(); offerBox.classList.add('hidden'); currentCode = null; return; }

    validateBtn.disabled = true;
    try {
      const res = await fetch(`/api/validate/${encodeURIComponent(code)}`);
      const data = await res.json();

      if (res.ok && data.valid) {
        showOffer(data.offer);
      } else {
        showError(data.message || 'Codice non valido o scaduto');
      }
    } catch {
      showError('Errore di connessione. Riprova.');
    } finally {
      validateBtn.disabled = false;
    }
  }

  // Validate on button click
  validateBtn.addEventListener('click', () => {
    validateCode(input.value.trim().toUpperCase());
  });

  // Validate on Enter key
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') validateCode(input.value.trim().toUpperCase());
  });

  // Real-time debounced validation
  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const code = input.value.trim().toUpperCase();
    if (!code) { hideError(); offerBox.classList.add('hidden'); currentCode = null; return; }
    debounceTimer = setTimeout(() => validateCode(code), 600);
  });

  // Checkout
  payBtn.addEventListener('click', async () => {
    if (!currentCode) return;

    payBtnText.textContent = 'Reindirizzamento in corso…';
    paySpinner.classList.remove('hidden');
    payBtn.disabled = true;

    try {
      const res = await fetch('/api/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: currentCode }),
      });
      const data = await res.json();

      if (res.ok && data.url) {
        window.location.href = data.url;
      } else {
        showError(data.error || 'Errore nel checkout. Riprova.');
        payBtnText.textContent = 'Procedi al pagamento sicuro';
        paySpinner.classList.add('hidden');
        payBtn.disabled = false;
      }
    } catch {
      showError('Errore di connessione. Riprova.');
      payBtnText.textContent = 'Procedi al pagamento sicuro';
      paySpinner.classList.add('hidden');
      payBtn.disabled = false;
    }
  });
})();
