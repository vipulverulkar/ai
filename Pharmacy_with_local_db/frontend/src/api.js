const BASE = '';
const KEY = 'pharma_token';

export const getToken = () => localStorage.getItem(KEY) || '';
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY));

async function req(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(BASE + path, { ...opts, headers });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    const err = new Error(data.error || 'Login required');
    err.code = 401;
    throw err;
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

export const api = {
  login: (username, password) =>
    req('/api/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => req('/api/logout', { method: 'POST' }).catch(() => ({})),
  me: () => req('/api/me'),
  listMedicines: (args = '') => {
    // string (legacy): search text. object: {search, unit, stock, sort, page, per_page}
    // pass page to get server-paginated {medicines, total, page, per_page, total_pages}
    const o = typeof args === 'string' ? { search: args } : (args || {});
    const p = new URLSearchParams();
    if (o.search) p.set('search', o.search);
    if (o.unit && o.unit !== 'all') p.set('unit', o.unit);
    if (o.stock && o.stock !== 'all') p.set('stock', o.stock);
    if (o.sort && o.sort !== 'name') p.set('sort', o.sort);
    if (o.page != null) p.set('page', o.page);
    if (o.per_page != null) p.set('per_page', o.per_page);
    const qs = p.toString();
    return req(`/api/medicines${qs ? `?${qs}` : ''}`);
  },
  addMedicine: (m) => req('/api/medicines', { method: 'POST', body: JSON.stringify(m) }),
  updateMedicine: (id, m) =>
    req(`/api/medicines/${id}`, { method: 'PUT', body: JSON.stringify(m) }),
  deleteMedicine: (id) => req(`/api/medicines/${id}`, { method: 'DELETE' }),
  createBill: (bill) => req('/api/bills', { method: 'POST', body: JSON.stringify(bill) }),
  listBills: (opts = {}) => {
    const p = new URLSearchParams();
    if (opts.page != null) p.set('page', opts.page);
    if (opts.per_page != null) p.set('per_page', opts.per_page);
    if (opts.search) p.set('search', opts.search);
    if (opts.status && opts.status !== 'all') p.set('status', opts.status);
    if (opts.from) p.set('from', opts.from);
    if (opts.to) p.set('to', opts.to);
    const qs = p.toString();
    return req(`/api/bills${qs ? `?${qs}` : ''}`);
  },
  billDetail: (id) => req(`/api/bills/${id}`),
  returnBill: (id) => req(`/api/bills/${id}/return`, { method: 'POST' }),
  getDashboard: () => req('/api/dashboard'),
  getSalesReport: (days = 14) => req(`/api/reports/sales?days=${days}`),
  listCustomers: (search = '') =>
    req(`/api/customers${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  customerBills: (id) => req(`/api/customers/${id}/bills`),
  listSuppliers: () => req('/api/suppliers'),
  createSupplier: (s) => req('/api/suppliers', { method: 'POST', body: JSON.stringify(s) }),
  updateSupplier: (id, s) => req(`/api/suppliers/${id}`, { method: 'PUT', body: JSON.stringify(s) }),
  deleteSupplier: (id) => req(`/api/suppliers/${id}`, { method: 'DELETE' }),
  createPurchase: (p) => req('/api/purchases', { method: 'POST', body: JSON.stringify(p) }),
  adjustStock: (id, delta, reason) =>
    req(`/api/medicines/${id}/adjust`, { method: 'POST', body: JSON.stringify({ delta, reason }) }),
  listMovements: (medicine_id = '') =>
    req(`/api/stock-movements${medicine_id ? `?medicine_id=${medicine_id}` : ''}`),
  listUsers: () => req('/api/users'),
  createUser: (u) => req('/api/users', { method: 'POST', body: JSON.stringify(u) }),
  deleteUser: (id) => req(`/api/users/${id}`, { method: 'DELETE' }),
  changePassword: (current_password, new_password) =>
    req('/api/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),
  listGstRates: () => req('/api/gst-rates'),
  createGstRate: (rate) => req('/api/gst-rates', { method: 'POST', body: JSON.stringify({ rate }) }),
  updateGstRate: (id, patch) => req(`/api/gst-rates/${id}`, { method: 'PUT', body: JSON.stringify(patch) }),
  deleteGstRate: (id) => req(`/api/gst-rates/${id}`, { method: 'DELETE' }),
  listUnitTypes: () => req('/api/unit-types'),
  createUnitType: (name) => req('/api/unit-types', { method: 'POST', body: JSON.stringify({ name }) }),
  updateUnitType: (id, patch) => req(`/api/unit-types/${id}`, { method: 'PUT', body: JSON.stringify(patch) }),
  deleteUnitType: (id) => req(`/api/unit-types/${id}`, { method: 'DELETE' }),
  listPaymentModes: () => req('/api/payment-modes'),
  createPaymentMode: (name) => req('/api/payment-modes', { method: 'POST', body: JSON.stringify({ name }) }),
  updatePaymentMode: (id, patch) => req(`/api/payment-modes/${id}`, { method: 'PUT', body: JSON.stringify(patch) }),
  deletePaymentMode: (id) => req(`/api/payment-modes/${id}`, { method: 'DELETE' }),
  getSettings: () => req('/api/settings'),
  updateSettings: (s) => req('/api/settings', { method: 'PUT', body: JSON.stringify(s) }),
  uploadLogo: async (file) => {
    const fd = new FormData();
    fd.append('logo', file);
    const headers = {};
    if (getToken()) headers.Authorization = `Bearer ${getToken()}`;
    const res = await fetch('/api/settings/logo', { method: 'POST', headers, body: fd });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { const e = new Error('Login required'); e.code = 401; throw e; }
    if (!res.ok) throw new Error(data.error || 'Upload failed');
    return data;
  },
  deleteLogo: () => req('/api/settings/logo', { method: 'DELETE' }),
};

export const inr = (n) =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
  }).format(Number(n) || 0);
