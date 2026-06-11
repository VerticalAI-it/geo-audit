(() => {
  let adminToken = sessionStorage.getItem('p2v_admin_token') || '';

  const loginOverlay = document.getElementById('login-overlay');
  const app          = document.getElementById('app');
  const loginError   = document.getElementById('login-error');

  // ---- Auth ----

  function applyAuth() {
    if (adminToken) { loginOverlay.classList.add('hidden'); app.classList.remove('hidden'); }
  }

  document.getElementById('login-btn').addEventListener('click', async () => {
    const token = document.getElementById('token-input').value.trim();
    if (!token) return;

    const res = await fetch('/api/admin/offers', { headers: { 'x-admin-token': token } });
    if (res.status === 401) {
      loginError.classList.remove('hidden');
      return;
    }
    adminToken = token;
    sessionStorage.setItem('p2v_admin_token', token);
    loginError.classList.add('hidden');
    applyAuth();
    loadOffers();
  });

  document.getElementById('token-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('login-btn').click();
  });

  document.getElementById('logout-btn').addEventListener('click', () => {
    sessionStorage.removeItem('p2v_admin_token');
    adminToken = '';
    loginOverlay.classList.remove('hidden');
    app.classList.add('hidden');
  });

  applyAuth();
  if (adminToken) loadOffers();

  // ---- Tabs ----

  window.switchTab = (tab) => {
    ['offers', 'orders'].forEach((t) => {
      document.getElementById(`tab-${t}`).classList.toggle('hidden', t !== tab);
      document.querySelector(`[data-tab="${t}"]`).className =
        t === tab ? 'tab-active pb-3 px-1 text-sm transition' : 'tab-inactive pb-3 px-1 text-sm transition';
    });
    if (tab === 'orders') loadOrders();
  };

  // ---- API helpers ----

  function authHeaders() {
    return { 'Content-Type': 'application/json', 'x-admin-token': adminToken };
  }

  function fmt(amount, currency = 'EUR') {
    return new Intl.NumberFormat('it-IT', { style: 'currency', currency }).format(amount);
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  function badgeHtml(is_active) {
    return is_active
      ? '<span class="badge-active text-xs font-semibold px-2 py-0.5 rounded-full">Attiva</span>'
      : '<span class="badge-inactive text-xs font-semibold px-2 py-0.5 rounded-full">Inattiva</span>';
  }

  function orderBadge(status) {
    const map = {
      pending:  ['badge-pending',   'In attesa'],
      completed:['badge-completed', 'Completato'],
      payment_failed: ['badge-failed', 'Fallito'],
      cancelled: ['badge-failed',   'Cancellato'],
    };
    const [cls, label] = map[status] || ['badge-pending', status];
    return `<span class="${cls} text-xs font-semibold px-2 py-0.5 rounded-full">${label}</span>`;
  }

  // ---- Offers ----

  window.loadOffers = async () => {
    document.getElementById('offers-loading').classList.remove('hidden');
    document.getElementById('offers-table').classList.add('hidden');
    document.getElementById('offers-empty').classList.add('hidden');

    const res  = await fetch('/api/admin/offers', { headers: authHeaders() });
    const rows = await res.json();

    document.getElementById('offers-loading').classList.add('hidden');

    if (!rows.length) { document.getElementById('offers-empty').classList.remove('hidden'); return; }

    const tbody = document.getElementById('offers-body');
    tbody.innerHTML = rows.map((o) => `
      <tr class="hover:bg-gray-50">
        <td class="px-6 py-3 font-mono font-semibold text-gray-800">${o.code}</td>
        <td class="px-6 py-3 text-gray-600">${o.description}</td>
        <td class="px-6 py-3 font-semibold text-gray-800">${fmt(o.amount, o.currency)}</td>
        <td class="px-6 py-3 text-gray-500">${o.billing_cycle === 'recurring_monthly' ? 'Mensile' : 'Una tantum'}</td>
        <td class="px-6 py-3">${badgeHtml(o.is_active)}</td>
        <td class="px-6 py-3 flex gap-3">
          <button onclick="toggleOffer(${o.id}, ${!o.is_active})"
            class="text-xs text-indigo-500 hover:text-indigo-700 font-medium">
            ${o.is_active ? 'Disattiva' : 'Attiva'}
          </button>
          <button onclick="deleteOffer(${o.id})"
            class="text-xs text-red-400 hover:text-red-600 font-medium">
            Elimina
          </button>
        </td>
      </tr>
    `).join('');

    document.getElementById('offers-table').classList.remove('hidden');
  };

  window.toggleOffer = async (id, is_active) => {
    await fetch(`/api/admin/offers/${id}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ is_active }),
    });
    loadOffers();
  };

  window.deleteOffer = async (id) => {
    if (!confirm('Eliminare questa offerta?')) return;
    await fetch(`/api/admin/offers/${id}`, { method: 'DELETE', headers: authHeaders() });
    loadOffers();
  };

  document.getElementById('create-btn').addEventListener('click', async () => {
    const formError = document.getElementById('form-error');
    const payload = {
      code:         document.getElementById('f-code').value.trim(),
      description:  document.getElementById('f-description').value.trim(),
      amount:       parseFloat(document.getElementById('f-amount').value),
      currency:     document.getElementById('f-currency').value,
      billing_cycle: document.getElementById('f-billing').value,
    };

    if (!payload.code || !payload.description || isNaN(payload.amount)) {
      formError.textContent = 'Compila tutti i campi obbligatori.';
      formError.classList.remove('hidden');
      return;
    }

    const res  = await fetch('/api/admin/offers', {
      method: 'POST', headers: authHeaders(), body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok) {
      formError.textContent = data.error || 'Errore nella creazione.';
      formError.classList.remove('hidden');
      return;
    }

    formError.classList.add('hidden');
    ['f-code', 'f-description', 'f-amount'].forEach((id) => { document.getElementById(id).value = ''; });
    loadOffers();
  });

  // ---- Orders ----

  window.loadOrders = async () => {
    document.getElementById('orders-loading').classList.remove('hidden');
    document.getElementById('orders-table').classList.add('hidden');
    document.getElementById('orders-empty').classList.add('hidden');

    const res  = await fetch('/api/admin/orders', { headers: authHeaders() });
    const rows = await res.json();

    document.getElementById('orders-loading').classList.add('hidden');

    if (!rows.length) { document.getElementById('orders-empty').classList.remove('hidden'); return; }

    const tbody = document.getElementById('orders-body');
    tbody.innerHTML = rows.map((o) => `
      <tr class="hover:bg-gray-50">
        <td class="px-6 py-3 text-gray-500">${fmtDate(o.created_at)}</td>
        <td class="px-6 py-3 text-gray-700">${o.customer_email || '—'}</td>
        <td class="px-6 py-3 font-mono text-gray-700">${o.offer_code || '—'}</td>
        <td class="px-6 py-3 font-semibold text-gray-800">${o.amount_paid != null ? fmt(o.amount_paid) : '—'}</td>
        <td class="px-6 py-3 text-gray-500">${o.billing_cycle === 'recurring_monthly' ? 'Mensile' : 'Una tantum'}</td>
        <td class="px-6 py-3">${orderBadge(o.status)}</td>
      </tr>
    `).join('');

    document.getElementById('orders-table').classList.remove('hidden');
  };

})();
