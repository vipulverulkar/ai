import { useEffect, useMemo, useRef, useState } from 'react';
import { api, inr, getToken, setToken } from './api.js';

const EMPTY_MED = { name: '', composition: '', unit: 'tablet', batch_no: '', expiry_date: '', quantity: 0, price: 0, mrp: 0, gst_percent: 5, description: '', usage: '', supplier: '', rack: '', schedule: '', rx_required: false, min_stock: 0 };

/* Selectable app themes (persisted in localStorage as pharma_theme). */
const THEMES = [
  { id: 'light', label: 'Light', icon: '☀️', sw: ['#0f766e', '#eef3f2'] },
  { id: 'ocean', label: 'Ocean', icon: '🌊', sw: ['#0284c7', '#e9f2f9'] },
  { id: 'forest', label: 'Forest', icon: '🌲', sw: ['#16a34a', '#ecf4ec'] },
  { id: 'sunset', label: 'Sunset', icon: '🌅', sw: ['#ea580c', '#faf1e8'] },
  { id: 'lavender', label: 'Lavender', icon: '💜', sw: ['#7c3aed', '#f1edfb'] },
  { id: 'rose', label: 'Rose', icon: '🌹', sw: ['#e11d48', '#fbeef2'] },
  { id: 'mocha', label: 'Mocha', icon: '☕', sw: ['#8a5a2b', '#f3ede4'] },
  { id: 'honey', label: 'Honey', icon: '🍯', sw: ['#ca8a04', '#faf4e2'] },
  { id: 'dark', label: 'Dark', icon: '🌙', sw: ['#14b8a6', '#0b1413'] },
  { id: 'midnight', label: 'Midnight', icon: '🌌', sw: ['#22d3ee', '#0a0f24'] },
  { id: 'graphite', label: 'Graphite', icon: '🩶', sw: ['#9aa0a6', '#101214'] },
  { id: 'plum', label: 'Plum', icon: '🍇', sw: ['#8b5cf6', '#150f22'] },
];
const DARK_TONES = ['dark', 'midnight', 'graphite', 'plum'];
const SAVED_THEME = (() => {
  try {
    const v = localStorage.getItem('pharma_theme') || 'light';
    return THEMES.some((t) => t.id === v) ? v : 'light';
  } catch { return 'light'; }
})();

/* Amount in words, Indian numbering (lakh/crore). */
function amountInWords(n) {
  const a = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
    'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'];
  const b = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'];
  const two = (x) => (x < 20 ? a[x] : b[Math.floor(x / 10)] + (x % 10 ? ' ' + a[x % 10] : ''));
  const three = (x) =>
    (Math.floor(x / 100) ? a[Math.floor(x / 100)] + ' Hundred' + (x % 100 ? ' ' : '') : '') +
    (x % 100 ? two(x % 100) : '');
  const integer = (x) => {
    if (!x) return 'Zero';
    let s = '';
    const cr = Math.floor(x / 1e7); x %= 1e7;
    const lk = Math.floor(x / 1e5); x %= 1e5;
    const th = Math.floor(x / 1e3); x %= 1e3;
    if (cr) s += three(cr) + ' Crore ';
    if (lk) s += two(lk) + ' Lakh ';
    if (th) s += two(th) + ' Thousand ';
    if (x) s += three(x);
    return s.trim();
  };
  const rupees = Math.floor(Number(n) || 0);
  const paise = Math.round(((Number(n) || 0) - rupees) * 100);
  return 'Rupees ' + integer(rupees) + (paise ? ' and Paise ' + two(paise) : '') + ' Only';
}

function todayStr() { return new Date().toISOString().slice(0, 10); }
function expiryStatus(m) {
  const e = m.expiry_date || '';
  if (!e) return 'none';
  const t = todayStr();
  if (e < t) return 'expired';
  const soon = new Date(); soon.setDate(soon.getDate() + 90);
  if (e <= soon.toISOString().slice(0, 10)) return 'soon';
  return 'ok';
}

function Invoice({ bill, settings, onNew }) {
  const discPct = Number(bill.discount_percent) || 0;
  const discAmt = Number(bill.discount_amount) || 0;
  const st = settings || {};
  const cgst = Math.round((Number(bill.gst_total) || 0) / 2 * 100) / 100;
  const sgst = Math.round(((Number(bill.gst_total) || 0) - cgst) * 100) / 100;
  const returned = (bill.status || 'completed') === 'returned';
  return (
    <div className="invoice">
      <div className="inv-head">
        {st.logo_url ? <img src={st.logo_url} className="logo-img big" alt="logo" /> : <div className="brand-mark">⚕️</div>}
        <div style={{ flex: 1 }}>
          <h2>{st.name || 'MediCare Pharmacy'}</h2>
          <p>{[st.address, st.phone && ('Ph: ' + st.phone), st.gstin && ('GSTIN: ' + st.gstin)].filter(Boolean).join(' · ') || st.tagline || 'Your trusted neighbourhood pharmacy'}</p>
        </div>
        {returned && <span className="stamp returned">Returned</span>}
      </div>
      <div className="inv-title">TAX INVOICE</div>
      <div className="inv-meta">
        <div><span>Bill No</span><b>#{bill.id}</b></div>
        <div><span>Date</span><b>{(bill.created_at || '').replace('T', ' ')}</b></div>
        <div><span>Customer</span><b>{bill.customer_name || '—'}</b></div>
        <div><span>Phone</span><b>{bill.customer_phone || '—'}</b></div>
        <div><span>Payment</span><b>{bill.payment_mode || 'Cash'}</b></div>
        <div><span>Doctor</span><b>{bill.doctor_name ? `Dr. ${bill.doctor_name}` : '—'}{bill.prescription_no ? ` (Rx ${bill.prescription_no})` : ''}</b></div>
      </div>
      <table>
        <thead><tr><th>#</th><th>Item</th><th>Qty</th><th>Rate (₹)</th><th>GST%</th><th>Amount (₹)</th></tr></thead>
        <tbody>
          {bill.items.map((it, i) => (
            <tr key={i}>
              <td>{i + 1}</td>
              <td><b>{it.medicine_name}</b><span className="no-print">{it.medicine_description ? <small> ({it.medicine_description})</small> : null}{it.medicine_usage ? <small> → {it.medicine_usage}</small> : null}<br /><small>{inr(it.unit_price)} + {it.gst_percent}% GST</small></span></td>
              <td>{it.qty}</td>
              <td>{inr(it.unit_price)}</td>
              <td>{it.gst_percent}%</td>
              <td className="price">{inr(it.line_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="totals">
        <div><span>Subtotal</span><span>{inr(bill.subtotal)}</span></div>
        <div><span>CGST</span><span>{inr(cgst)}</span></div>
        <div><span>SGST</span><span>{inr(sgst)}</span></div>
        {discAmt > 0 && <div><span>Discount ({discPct}%)</span><span>− {inr(discAmt)}</span></div>}
        <div className="grand"><span>Total</span><span>{inr(bill.grand_total)}</span></div>
      </div>
      <p className="inv-words">{amountInWords(bill.grand_total)}</p>
      <div className="row no-print inv-actions">
        <button className="primary" onClick={() => window.print()}>🖨 Print Invoice</button>
        {onNew && <button className="ghost" onClick={onNew}>+ New Bill</button>}
      </div>
      <p className="inv-foot">Thank you, get well soon! · E. &amp; O.E. · {st.gstin ? `GSTIN: ${st.gstin}` : 'GST invoice'}</p>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState('dashboard');
  const [medicines, setMedicines] = useState([]);
  const [search, setSearch] = useState('');
  // medicines are server-paginated (catalog can be huge); medCache keeps every
  // fetched row so cart lines resolve even when their medicine is off-page.
  const [medsPage, setMedsPage] = useState(1);
  const [medsTotal, setMedsTotal] = useState(0);
  const [medsTotalPages, setMedsTotalPages] = useState(1);
  const medCache = useRef({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [theme, setTheme] = useState(SAVED_THEME);
  const [themeMenuOpen, setThemeMenuOpen] = useState(false);

  // inventory form
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_MED);
  const [stockFilter, setStockFilter] = useState('all');
  const [sortBy, setSortBy] = useState('name');
  const [adjusting, setAdjusting] = useState(null);
  const [adjustForm, setAdjustForm] = useState({ delta: '', reason: '' });

  // billing cart
  const [cart, setCart] = useState([]);
  const [customer, setCustomer] = useState({ customer_name: '', customer_phone: '', doctor_name: '', prescription_no: '' });
  const [discount, setDiscount] = useState(0);
  const [payMode, setPayMode] = useState('Cash');
  const [tendered, setTendered] = useState('');
  const [unitFilter, setUnitFilter] = useState('all');
  const medsReq = useRef(0);
  const [lastBill, setLastBill] = useState(null);

  // bills history (server-paginated, 10 per page, full history)
  const [bills, setBills] = useState([]);
  const [billDetail, setBillDetail] = useState(null);
  const [billSearch, setBillSearch] = useState('');
  const [billStatus, setBillStatus] = useState('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [billsPage, setBillsPage] = useState(1);
  const [billsTotal, setBillsTotal] = useState(0);
  const [billsTotalPages, setBillsTotalPages] = useState(1);
  const [billsLoading, setBillsLoading] = useState(false);
  const BILLS_PER_PAGE = 10;
  const MEDS_PER_PAGE = 20;

  // auth
  const [authed, setAuthed] = useState(!!getToken());
  const [username, setUsername] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [loginError, setLoginError] = useState('');

  // users
  const [users, setUsers] = useState([]);
  const [userForm, setUserForm] = useState({ username: '', password: '', is_admin: false });
  const [pwdForm, setPwdForm] = useState({ current: '', next: '', confirm: '' });

  // masters
  const [gstRates, setGstRates] = useState([]);
  const [gstForm, setGstForm] = useState({ rate: '', is_active: true });
  const [editingRate, setEditingRate] = useState(null);
  const [unitTypes, setUnitTypes] = useState([]);
  const [typeForm, setTypeForm] = useState({ name: '', is_active: true });
  const [editingType, setEditingType] = useState(null);
  const [mastersMenuOpen, setMastersMenuOpen] = useState(false);
  const [paymentModes, setPaymentModes] = useState([]);
  const [modeForm, setModeForm] = useState({ name: '', is_active: true });
  const [editingMode, setEditingMode] = useState(null);

  // store
  const [settings, setSettings] = useState({ name: 'MediCare Pharmacy', tagline: '', address: '', phone: '', gstin: '', logo_url: '', low_stock_limit: 10 });
  const [storeForm, setStoreForm] = useState({ name: '', tagline: '', address: '', phone: '', gstin: '', low_stock_limit: 10 });

  // new pharmacy modules
  const [dashboard, setDashboard] = useState(null);
  const [recentPage, setRecentPage] = useState(1);
  const RECENT_PER_PAGE = 5;
  const [report, setReport] = useState(null);
  const [reportDays, setReportDays] = useState(14);
  const [customers, setCustomers] = useState([]);
  const [custSearch, setCustSearch] = useState('');
  const [custDetail, setCustDetail] = useState(null);
  const [suppliers, setSuppliers] = useState([]);
  const [supForm, setSupForm] = useState({ name: '', phone: '', address: '', gstin: '' });
  const [editingSup, setEditingSup] = useState(null);
  const [purchase, setPurchase] = useState({ supplier: '', note: '', medicine_id: '', qty: '' });
  const [purSearch, setPurSearch] = useState('');
  const [purOptions, setPurOptions] = useState([]);
  const [movements, setMovements] = useState([]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('data-tone', DARK_TONES.includes(theme) ? 'dark' : 'light');
    try { localStorage.setItem('pharma_theme', theme); } catch { /* ignore */ }
  }, [theme]);

  const authGuard = (e) => {
    if (e && e.code === 401) { setToken(''); setAuthed(false); return true; }
    return false;
  };
  const flash = (msg, isErr) => {
    if (isErr) { setError(msg); setNotice(''); } else { setNotice(msg); setError(''); }
    setTimeout(() => { setError(''); setNotice(''); }, 5000);
  };

  const doLogin = async (e) => {
    e.preventDefault();
    setLoginError('');
    try {
      const r = await api.login(loginForm.username.trim(), loginForm.password);
      setToken(r.token); setUsername(r.username); setIsAdmin(!!r.is_admin);
      setLoginForm({ username: '', password: '' }); setAuthed(true); setTab('dashboard');
    } catch (err) { setLoginError(err.message); }
  };
  const doLogout = async () => {
    try { await api.logout(); } catch { /* ignore */ }
    setToken(''); setAuthed(false); setIsAdmin(false); setUsername('');
    setUsers([]); setGstRates([]); setEditingRate(null); setUnitTypes([]); setEditingType(null);
    setPaymentModes([]); setEditingMode(null); setCart([]); setBillDetail(null);
    setDashboard(null); setCustomers([]); setSuppliers([]); setMovements([]);
    setMedicines([]); setMedsPage(1); setMedsTotal(0); setMedsTotalPages(1);
    medCache.current = {}; setPurSearch(''); setPurOptions([]);
  };

  const medParams = (q, page, ov = {}) => {
    // Billing tab filters by unit; inventory tab by stock/sort — never mix,
    // so switching tabs can't silently narrow the other tab's list.
    const billing = ov.billing ?? (tab === 'billing');
    const p = { search: q, page, per_page: MEDS_PER_PAGE };
    if (billing) p.unit = ov.unit ?? unitFilter;
    else { p.stock = ov.stock ?? stockFilter; p.sort = ov.sort ?? sortBy; }
    return p;
  };
  const loadMeds = async (q = search, page = medsPage, ov = {}) => {
    const reqId = ++medsReq.current;
    setLoading(true); setError('');
    try {
      const r = await api.listMedicines(medParams(q, page, ov));
      if (reqId !== medsReq.current) return;
      const list = r.medicines || [];
      for (const m of list) medCache.current[m.id] = m;
      setMedicines(list);
      setMedsTotal(r.total || 0);
      setMedsTotalPages(r.total_pages || 1);
      setMedsPage(r.page || page);
    } catch (e) { if (authGuard(e)) return; setError(e.message); }
    finally { if (reqId === medsReq.current) setLoading(false); }
  };
  const gotoMedsPage = (p) => {
    const next = Math.min(Math.max(1, p), Math.max(1, medsTotalPages));
    setMedsPage(next);
    loadMeds(search, next);
  };
  // Compact page-number window (e.g. 1 … 4 5 6 … 12) for the medicine pagers.
  const medsPageNums = (() => {
    const total = Math.max(1, medsTotalPages);
    const cur = Math.min(Math.max(1, medsPage), total);
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
    const set = new Set([1, 2, cur - 1, cur, cur + 1, total - 1, total]);
    return [...set].filter((n) => n >= 1 && n <= total).sort((a, b) => a - b);
  })();
  const loadBills = async (page = billsPage, q = billSearch, st = billStatus, df = dateFrom, dt = dateTo) => {
    setBillsLoading(true);
    try {
      const r = await api.listBills({ page, per_page: BILLS_PER_PAGE, search: q, status: st, from: df, to: dt });
      if (Array.isArray(r)) {
        // legacy fallback (very old backend): plain array, latest first
        setBills(r); setBillsTotal(r.length); setBillsTotalPages(1); setBillsPage(1);
      } else {
        setBills(r.bills || []);
        setBillsTotal(r.total || 0);
        setBillsTotalPages(r.total_pages || 1);
        if (r.page && r.page !== page) setBillsPage(r.page);
      }
    } catch (e) { if (authGuard(e)) return; setError(e.message); }
    finally { setBillsLoading(false); }
  };
  const gotoBillsPage = (p) => {
    const next = Math.min(Math.max(1, p), Math.max(1, billsTotalPages));
    setBillsPage(next);
    loadBills(next, billSearch, billStatus, dateFrom, dateTo);
  };
  const setBillsRange = (df, dt) => {
    setDateFrom(df); setDateTo(dt); setBillsPage(1);
    loadBills(1, billSearch, billStatus, df, dt);
  };
  const clearBillsFilters = () => {
    setBillSearch(''); setBillStatus('all'); setDateFrom(''); setDateTo(''); setBillsPage(1);
    loadBills(1, '', 'all', '', '');
  };
  // Compact page-number window (e.g. 1 … 4 5 6 … 12) for the Bills pager.
  const billsPageNums = (() => {
    const total = Math.max(1, billsTotalPages);
    const cur = Math.min(Math.max(1, billsPage), total);
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
    const set = new Set([1, 2, cur - 1, cur, cur + 1, total - 1, total]);
    return [...set].filter((n) => n >= 1 && n <= total).sort((a, b) => a - b);
  })();
  const loadUsers = async () => {
    try { setUsers(await api.listUsers()); } catch (e) { if (authGuard(e)) return; setError(e.message); }
  };
  const loadGst = async () => {
    try { setGstRates(await api.listGstRates()); } catch (e) { if (authGuard(e)) return; setError(e.message); }
  };
  const loadTypes = async () => {
    try { setUnitTypes(await api.listUnitTypes()); } catch (e) { if (authGuard(e)) return; setError(e.message); }
  };
  const loadPayModes = async () => {
    try {
      const modes = await api.listPaymentModes();
      setPaymentModes(modes);
      const act = modes.filter((p) => p.is_active).map((p) => p.name);
      if (act.length && !act.includes(payMode)) setPayMode(act.includes('Cash') ? 'Cash' : act[0]);
    } catch (e) { if (authGuard(e)) return; setError(e.message); }
  };
  const loadDashboard = async () => {
    try { setDashboard(await api.getDashboard()); } catch (e) { if (!authGuard(e)) console.warn(e.message); }
  };
  const loadReport = async (days) => {
    try { setReport(await api.getSalesReport(days)); } catch (e) { if (authGuard(e)) return; setError(e.message); }
  };
  const loadCustomers = async (q = '') => {
    try { setCustomers(await api.listCustomers(q)); } catch (e) { if (authGuard(e)) return; setError(e.message); }
  };
  const loadSuppliers = async () => {
    try { setSuppliers(await api.listSuppliers()); } catch (e) { if (authGuard(e)) return; setError(e.message); }
  };
  const loadMovements = async () => {
    try { setMovements(await api.listMovements()); } catch (e) { if (authGuard(e)) return; }
  };

  useEffect(() => { api.getSettings().then(setSettings).catch(() => {}); }, []);
  useEffect(() => {
    if (!authed) return;
    api.me().then((r) => { setUsername(r.username); setIsAdmin(!!r.is_admin); })
      .catch(() => { setToken(''); setAuthed(false); return; });
    loadMeds(); loadBills(); loadGst(); loadTypes(); loadPayModes();
    loadDashboard(); loadCustomers(); loadSuppliers(); loadMovements(); loadReport(reportDays);
  }, [authed]);
  useEffect(() => { if (authed && isAdmin && tab === 'users') loadUsers(); }, [authed, isAdmin, tab]);
  useEffect(() => { if (authed && tab === 'reports') loadReport(reportDays); }, [tab, reportDays]);
  useEffect(() => { if (authed && (tab === 'dashboard' || tab === 'billing')) loadDashboard(); }, [tab]);
  useEffect(() => { if (authed && tab === 'customers') loadCustomers(custSearch); }, [tab]);
  useEffect(() => { if (authed && tab === 'bills') loadBills(billsPage, billSearch, billStatus, dateFrom, dateTo); }, [tab]);
  useEffect(() => {
    if (!authed || tab !== 'bills') return;
    const t = setTimeout(() => { setBillsPage(1); loadBills(1, billSearch, billStatus, dateFrom, dateTo); }, 350);
    return () => clearTimeout(t);
  }, [billSearch, billStatus]);
  // Note: date-range changes go through setBillsRange() (immediate load),
  // so dateFrom/dateTo stay out of the debounced search effect above.
  useEffect(() => {
    const t = setTimeout(() => { if (authed) { setMedsPage(1); loadMeds(search, 1); } }, 300);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    // Entering billing/inventory (re)loads page 1 with that tab's own filters.
    if (!authed || (tab !== 'billing' && tab !== 'inventory')) return;
    setMedsPage(1); loadMeds(search, 1);
  }, [tab]);
  useEffect(() => {
    // Purchase-tab medicine picker: server search, top 10 matches.
    if (!authed || !purSearch.trim() || purchase.medicine_id) { setPurOptions([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await api.listMedicines({ search: purSearch.trim(), page: 1, per_page: 10 });
        const list = r.medicines || [];
        for (const m of list) medCache.current[m.id] = m;
        setPurOptions(list);
      } catch { /* picker is best-effort; main form error handling covers failures */ }
    }, 300);
    return () => clearTimeout(t);
  }, [purSearch, purchase.medicine_id, authed]);
  useEffect(() => {
    const t = setTimeout(() => { if (authed && tab === 'customers') loadCustomers(custSearch); }, 350);
    return () => clearTimeout(t);
  }, [custSearch]);

  const medById = useMemo(() => ({ ...medCache.current }), [medicines]);
  const cartQty = useMemo(() => Object.fromEntries(cart.map((c) => [c.medicine_id, c.qty])), [cart]);
  const lowLimit = useMemo(() => {
    const v = Number(settings.low_stock_limit);
    return Number.isFinite(v) && v >= 0 ? v : 10;
  }, [settings]);

  const filteredBilling = useMemo(() => {
    let list = medicines.filter((m) => unitFilter === 'all' || (m.unit || 'tablet') === unitFilter);
    return list;
  }, [medicines, unitFilter]);

  const inventoryList = useMemo(() => {
    let list = [...medicines];
    if (stockFilter === 'low') list = list.filter((m) => m.quantity <= Math.max(lowLimit, m.min_stock || 0) && m.quantity > 0);
    if (stockFilter === 'out') list = list.filter((m) => m.quantity <= 0);
    if (stockFilter === 'expiring') list = list.filter((m) => expiryStatus(m) === 'soon');
    if (stockFilter === 'expired') list = list.filter((m) => expiryStatus(m) === 'expired');
    if (stockFilter === 'rx') list = list.filter((m) => m.rx_required);
    if (sortBy === 'name') list.sort((a, b) => a.name.localeCompare(b.name));
    if (sortBy === 'stock') list.sort((a, b) => a.quantity - b.quantity);
    if (sortBy === 'expiry') list.sort((a, b) => (a.expiry_date || '9999').localeCompare(b.expiry_date || '9999'));
    if (sortBy === 'value') list.sort((a, b) => (b.price * b.quantity) - (a.price * a.quantity));
    return list;
  }, [medicines, stockFilter, sortBy, lowLimit]);

  // Dashboard "Today's bills": client-side pagination over today's bills.
  const recentBills = dashboard?.recent_bills || [];
  const recentTotalPages = Math.max(1, Math.ceil(recentBills.length / RECENT_PER_PAGE));
  const safeRecentPage = Math.min(Math.max(1, recentPage), recentTotalPages);
  const recentSlice = recentBills.slice((safeRecentPage - 1) * RECENT_PER_PAGE, safeRecentPage * RECENT_PER_PAGE);
  const recentFrom = recentBills.length === 0 ? 0 : (safeRecentPage - 1) * RECENT_PER_PAGE + 1;
  const recentTo = Math.min(safeRecentPage * RECENT_PER_PAGE, recentBills.length);
  useEffect(() => {
    // Clamp back into range whenever today's list shrinks (e.g. fresh load).
    if (recentPage > recentTotalPages) setRecentPage(recentTotalPages);
  }, [recentTotalPages]);

  const quickAddFirst = () => {
    const target = filteredBilling.find((m) => m.quantity > 0);
    if (target) addToCart(target.id);
  };

  const cartLines = cart.map((c) => {
    const m = medById[c.medicine_id];
    if (!m) return null;
    const base = m.price * c.qty;
    const gst = (base * m.gst_percent) / 100;
    return { ...c, med: m, base, gst, total: base + gst };
  }).filter(Boolean);
  const subtotal = cartLines.reduce((s, l) => s + l.base, 0);
  const gstTotal = cartLines.reduce((s, l) => s + l.gst, 0);
  const discPct = Math.max(0, Math.min(100, Number(discount) || 0));
  const discAmount = Math.round((subtotal + gstTotal) * discPct) / 100;
  const grandTotal = Math.round((subtotal + gstTotal - discAmount) * 100) / 100;
  const tenderedNum = tendered === '' ? null : Number(tendered);
  const change = tenderedNum === null || isNaN(tenderedNum) ? null : Math.round((tenderedNum - grandTotal) * 100) / 100;
  const rxInCart = cartLines.filter((l) => l.med.rx_required);

  const openNew = () => { setEditing('new'); setForm({ ...EMPTY_MED, unit: unitTypes.find((t) => t.is_active)?.name || 'tablet', gst_percent: gstRates.find((s) => s.is_active)?.rate ?? 5 }); };
  const openEdit = (m) => { setEditing(m.id); setForm({ ...EMPTY_MED, ...m }); };

  const saveMed = async (e) => {
    e.preventDefault(); setError(''); setNotice('');
    try {
      const payload = { ...form, quantity: Number(form.quantity), price: Number(form.price), mrp: Number(form.mrp || form.price), gst_percent: Number(form.gst_percent), min_stock: Number(form.min_stock || 0) };
      if (editing === 'new') { await api.addMedicine(payload); flash('Medicine added.'); }
      else { await api.updateMedicine(editing, payload); flash('Medicine updated.'); }
      setEditing(null); loadMeds(search); loadDashboard();
    } catch (err) { if (authGuard(err)) return; flash(err.message, true); }
  };
  const removeMed = async (id) => {
    if (!window.confirm('Remove this medicine from inventory?')) return;
    try { await api.deleteMedicine(id); flash('Medicine removed.'); loadMeds(search); }
    catch (e) { if (authGuard(e)) return; flash(e.message, true); }
  };
  const submitAdjust = async (e) => {
    e.preventDefault();
    try {
      await api.adjustStock(adjusting.id, Number(adjustForm.delta), adjustForm.reason);
      flash(`Stock adjusted (${adjustForm.delta > 0 ? '+' : ''}${adjustForm.delta}).`);
      setAdjusting(null); setAdjustForm({ delta: '', reason: '' }); loadMeds(search); loadMovements(); loadDashboard();
    } catch (err) { if (authGuard(err)) return; flash(err.message, true); }
  };

  const addToCart = (id) => {
    setCart((prev) => {
      const found = prev.find((c) => c.medicine_id === id);
      if (found) return prev.map((c) => (c.medicine_id === id ? { ...c, qty: c.qty + 1 } : c));
      return [...prev, { medicine_id: id, qty: 1 }];
    });
  };
  const setQty = (id, qty) => {
    const n = Math.round(Number(qty) || 0);
    if (n < 1) { setCart((prev) => prev.filter((c) => c.medicine_id !== id)); return; }
    const m = medById[id];
    const clamped = Math.min(m ? m.quantity : 99, n);
    setCart((prev) => prev.map((c) => (c.medicine_id === id ? { ...c, qty: clamped } : c)));
  };
  const checkout = async () => {
    setError(''); setNotice('');
    if (cartLines.length === 0) { flash('Cart is empty — add medicines first.', true); return; }
    try {
      const bill = await api.createBill({
        ...customer,
        items: cart.map((c) => ({ medicine_id: c.medicine_id, qty: c.qty })),
        discount_percent: discPct, payment_mode: payMode,
      });
      setLastBill(bill);
      flash(`Bill #${bill.id} created — ${inr(bill.grand_total)} (${bill.payment_mode})`);
      setCart([]); setCustomer({ customer_name: '', customer_phone: '', doctor_name: '', prescription_no: '' });
      setDiscount(0); setPayMode('Cash'); setTendered('');
      loadMeds(search); loadBills(); loadDashboard(); loadCustomers(custSearch);
    } catch (e) { if (authGuard(e)) return; flash(e.message, true); }
  };
  const viewBill = async (id) => {
    try { setBillDetail(await api.billDetail(id)); } catch (e) { if (authGuard(e)) return; flash(e.message, true); }
  };
  const doReturn = async (id) => {
    if (!window.confirm(`Accept full return of bill #${id}? Stock will be restored.`)) return;
    try {
      const b = await api.returnBill(id);
      setBillDetail(b); flash(`Bill #${id} returned — stock restored.`);
      loadBills(); loadMeds(search); loadDashboard();
    } catch (e) { if (authGuard(e)) return; flash(e.message, true); }
  };

  // masters helpers (compact)
  const addSlab = async (e) => { e.preventDefault(); try { const r = await api.createGstRate(Number(gstForm.rate)); flash(`GST slab ${r.rate}% added.`); setGstForm({ rate: '', is_active: true }); loadGst(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const saveSlab = async (e) => { e.preventDefault(); try { const r = await api.updateGstRate(editingRate, { rate: Number(gstForm.rate), is_active: gstForm.is_active }); flash(`Slab updated to ${r.rate}%.`); setEditingRate(null); setGstForm({ rate: '', is_active: true }); loadGst(); loadMeds(search); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const toggleSlab = async (s) => { try { await api.updateGstRate(s.id, { is_active: !s.is_active }); flash(`Slab ${s.rate}% ${s.is_active ? 'deactivated' : 'activated'}.`); loadGst(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const removeSlab = async (s) => { if (!window.confirm(`Delete GST slab ${s.rate}%?`)) return; try { await api.deleteGstRate(s.id); flash(`Slab ${s.rate}% deleted.`); loadGst(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const addType = async (e) => { e.preventDefault(); try { const t = await api.createUnitType(typeForm.name); flash(`Type '${t.name}' added.`); setTypeForm({ name: '', is_active: true }); loadTypes(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const saveType = async (e) => { e.preventDefault(); try { const t = await api.updateUnitType(editingType, { name: typeForm.name, is_active: typeForm.is_active }); flash(`Type updated to '${t.name}'.`); setEditingType(null); setTypeForm({ name: '', is_active: true }); loadTypes(); loadMeds(search); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const toggleType = async (t) => { try { await api.updateUnitType(t.id, { is_active: !t.is_active }); flash(`Type '${t.name}' ${t.is_active ? 'deactivated' : 'activated'}.`); loadTypes(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const removeType = async (t) => { if (!window.confirm(`Delete type '${t.name}'?`)) return; try { await api.deleteUnitType(t.id); flash(`Type '${t.name}' deleted.`); loadTypes(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const addMode = async (e) => { e.preventDefault(); try { const m = await api.createPaymentMode(modeForm.name); flash(`Mode '${m.name}' added.`); setModeForm({ name: '', is_active: true }); loadPayModes(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const saveMode = async (e) => { e.preventDefault(); try { const m = await api.updatePaymentMode(editingMode, { name: modeForm.name, is_active: modeForm.is_active }); flash(`Mode updated to '${m.name}'.`); setEditingMode(null); setModeForm({ name: '', is_active: true }); loadPayModes(); loadBills(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const toggleMode = async (m) => { try { await api.updatePaymentMode(m.id, { is_active: !m.is_active }); flash(`Mode '${m.name}' ${m.is_active ? 'deactivated' : 'activated'}.`); loadPayModes(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const removeMode = async (m) => { if (!window.confirm(`Delete mode '${m.name}'?`)) return; try { await api.deletePaymentMode(m.id); flash(`Mode '${m.name}' deleted.`); loadPayModes(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const addUser = async (e) => { e.preventDefault(); try { const u = await api.createUser(userForm); flash(`User '${u.username}' created.`); setUserForm({ username: '', password: '', is_admin: false }); loadUsers(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const removeUser = async (id, name) => { if (!window.confirm(`Remove login for '${name}'?`)) return; try { await api.deleteUser(id); flash(`User '${name}' removed.`); loadUsers(); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const changePwd = async (e) => { e.preventDefault(); if (pwdForm.next !== pwdForm.confirm) { flash('New passwords do not match.', true); return; } try { await api.changePassword(pwdForm.current, pwdForm.next); flash('Password changed.'); setPwdForm({ current: '', next: '', confirm: '' }); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const saveStore = async (e) => { e.preventDefault(); try { const st = await api.updateSettings(storeForm); setSettings(st); flash('Store profile updated.'); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const uploadLogoFile = async (e) => { const file = (e.target.files || [])[0]; e.target.value = ''; if (!file) return; try { const st = await api.uploadLogo(file); setSettings(st); flash('Logo updated.'); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const removeLogo = async () => { try { const st = await api.deleteLogo(); setSettings(st); flash('Logo removed.'); } catch (err) { if (authGuard(err)) return; flash(err.message, true); } };
  const openStoreTab = () => { setStoreForm({ name: settings.name || '', tagline: settings.tagline || '', address: settings.address || '', phone: settings.phone || '', gstin: settings.gstin || '', low_stock_limit: settings.low_stock_limit ?? 10 }); setTab('masters-store'); setMastersMenuOpen(false); };

  // suppliers / purchase
  const saveSupplier = async (e) => {
    e.preventDefault();
    try {
      if (editingSup) { await api.updateSupplier(editingSup, supForm); flash('Supplier updated.'); }
      else { await api.createSupplier(supForm); flash('Supplier added.'); }
      setEditingSup(null); setSupForm({ name: '', phone: '', address: '', gstin: '' }); loadSuppliers();
    } catch (err) { if (authGuard(err)) return; flash(err.message, true); }
  };
  const removeSupplier = async (id) => {
    if (!window.confirm('Delete this supplier?')) return;
    try { await api.deleteSupplier(id); flash('Supplier deleted.'); loadSuppliers(); } catch (e) { if (authGuard(e)) return; flash(e.message, true); }
  };
  const submitPurchase = async (e) => {
    e.preventDefault();
    if (!purchase.medicine_id || !purchase.qty) { flash('Pick a medicine and quantity.', true); return; }
    try {
      await api.createPurchase({ supplier: purchase.supplier, note: purchase.note, items: [{ medicine_id: Number(purchase.medicine_id), qty: Number(purchase.qty) }] });
      flash('Purchase recorded — stock increased.');
      setPurchase({ supplier: '', note: '', medicine_id: '', qty: '' });
      setPurSearch(''); setPurOptions([]);
      loadMeds(search); loadMovements(); loadDashboard();
    } catch (err) { if (authGuard(err)) return; flash(err.message, true); }
  };
  const viewCustomer = async (c) => {
    try { setCustDetail(await api.customerBills(c.id)); } catch (e) { if (authGuard(e)) return; flash(e.message, true); }
  };

  if (!authed) {
    return (
      <div className="login-wrap">
        <div className="login-hero">
          <div className="brand-mark" style={{ marginBottom: 14 }}>⚕️</div>
          <h1>{settings.name || 'MediCare Pharmacy'}</h1>
          <p>{settings.tagline || 'GST-ready billing, smart inventory, and patient care — all in one counter-friendly app.'}</p>
          <div className="feat">
            <div>🧾 Fast billing with GST, discounts &amp; UPI / cash tender</div>
            <div>📦 Expiry + low-stock alerts, suppliers &amp; stock ledger</div>
            <div>📊 Dashboard &amp; sales reports in Indian Rupees</div>
          </div>
        </div>
        <form className="login-card" onSubmit={doLogin}>
          {settings.logo_url ? <img src={settings.logo_url} className="logo-preview" alt="logo" /> : <div className="brand-mark big">⚕️</div>}
          <h2>Welcome back</h2>
          <p className="login-sub">Sign in to continue</p>
          {loginError && <div className="error">⚠ {loginError}</div>}
          <label>Username
            <input value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} autoComplete="username" required />
          </label>
          <label>Password
            <input type="password" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} autoComplete="current-password" required />
          </label>
          <button className="primary" type="submit" style={{ width: '100%', marginTop: 6 }}>Login →</button>
          <p className="login-hint">Default login — username: <b>admin</b>, password: <b>admin</b></p>
        </form>
      </div>
    );
  }

  const TABS = [
    { id: 'dashboard', label: '📊 Dashboard' },
    { id: 'billing', label: `🧾 Billing${cart.length ? ` (${cart.length})` : ''}` },
    { id: 'inventory', label: '📦 Inventory' },
    { id: 'bills', label: '📜 Bills' },
    { id: 'customers', label: '🧑‍🤝‍🧑 Customers' },
    { id: 'purchase', label: '🚚 Stock-In' },
    { id: 'reports', label: '📈 Reports' },
    { id: 'users', label: isAdmin ? '👥 Users' : '👤 Account' },
  ];
  const maxDaily = Math.max(1, ...(report?.daily || []).map((d) => d.sales));

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          {settings.logo_url ? <img src={settings.logo_url} className="logo-img" alt="logo" /> : <div className="brand-mark">⚕️</div>}
          <div>
            <h1>{settings.name}</h1>
            <small>{(settings.tagline || 'BILLING IN ₹ INR · GST-READY').toUpperCase()}</small>
          </div>
        </div>
        <div className="stats no-print">
          <span className="chip">💊 {dashboard?.total_medicines ?? medsTotal}</span>
          <span className={`chip ${(dashboard?.low_stock_count || 0) ? 'warn' : 'good'}`}>⚠️ {dashboard?.low_stock_count || 0} low</span>
          <span className="chip">📈 Today {inr(dashboard?.today_sales || 0)}</span>
          <span className="chip">👤 {username || '…'}{isAdmin ? ' · admin' : ''}</span>
          <div className="menu-wrap">
            <button className="icon-btn" onClick={() => setThemeMenuOpen((o) => !o)} title="Choose app theme">🎨 {THEMES.find((t) => t.id === theme)?.label || 'Theme'}</button>
            {themeMenuOpen && (
              <>
                <div className="menu-backdrop" onClick={() => setThemeMenuOpen(false)} />
                <div className="dropdown">
                  {THEMES.map((t) => (
                    <button key={t.id} className={theme === t.id ? 'on' : ''} onClick={() => { setTheme(t.id); setThemeMenuOpen(false); }}>
                      <span className="swatch"><i style={{ background: t.sw[0] }} /><i style={{ background: t.sw[1] }} /></span>
                      {t.icon} {t.label}{theme === t.id ? ' ✓' : ''}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <button className="logout-btn" onClick={doLogout} title="Log out">⏻ Logout</button>
        </div>
      </header>
      <nav className="tabs no-print">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? 'tab active' : 'tab'} onClick={() => { setTab(t.id); setMastersMenuOpen(false); }}>{t.label}</button>
        ))}
        {isAdmin && (
          <div className="menu-wrap">
            <button className={tab.startsWith('masters-') ? 'menu-btn active' : 'menu-btn'} onClick={() => setMastersMenuOpen((o) => !o)}>🏷️ Masters ▾</button>
            {mastersMenuOpen && (
              <>
                <div className="menu-backdrop" onClick={() => setMastersMenuOpen(false)} />
                <div className="dropdown">
                  <button className={tab === 'masters-gst' ? 'on' : ''} onClick={() => { setTab('masters-gst'); setMastersMenuOpen(false); }}>📊 GST Rates</button>
                  <button className={tab === 'masters-types' ? 'on' : ''} onClick={() => { setTab('masters-types'); setMastersMenuOpen(false); }}>💊 Medicine Types</button>
                  <button className={tab === 'masters-pay' ? 'on' : ''} onClick={() => { setTab('masters-pay'); setMastersMenuOpen(false); }}>💳 Payment Modes</button>
                  <button className={tab === 'masters-store' ? 'on' : ''} onClick={openStoreTab}>🏪 Store Profile</button>
                </div>
              </>
            )}
          </div>
        )}
      </nav>
      <main>
        {error && <div className="error">⚠ {error}</div>}
        {notice && <div className="success">✅ {notice}</div>}

        {tab === 'dashboard' && (
          <div>
            <div className="kpis">
              <div className="kpi"><small>Today's sales</small><b>{inr(dashboard?.today_sales || 0)}</b><span className="sub">{dashboard?.today_bills || 0} bills today</span></div>
              <div className="kpi"><small>Last 7 days</small><b>{inr(dashboard?.week_sales || 0)}</b><span className="sub">rolling week revenue</span></div>
              <div className="kpi"><small>Stock value</small><b>{inr(dashboard?.stock_value || 0)}</b><span className="sub">{dashboard?.total_medicines || 0} medicines</span></div>
              <div className="kpi"><small>Attention needed</small><b>{(dashboard?.low_stock_count || 0) + (dashboard?.expired_count || 0)} ⚠️</b><span className="sub">{dashboard?.low_stock_count || 0} low · {dashboard?.expired_count || 0} expired · {dashboard?.out_of_stock || 0} out</span></div>
            </div>
            <div className="grid2">
              <div className="panel">
                <h3>🏆 Top sellers (by quantity)</h3>
                {(dashboard?.top_sellers || []).length === 0 ? <div className="empty"><span className="big">📦</span>No sales yet.</div> : (
                  <div className="mini-list">
                    {(dashboard?.top_sellers || []).map((t, i) => (
                      <div key={i} className="mini-item"><span><b>#{i + 1}</b> {t.name}</span><span className="price">{t.qty} sold · {inr(t.revenue)}</span></div>
                    ))}
                  </div>
                )}
              </div>
              <div className="panel">
                <h3>💳 Revenue by payment mode</h3>
                {Object.keys(dashboard?.by_mode || {}).length === 0 ? <div className="empty"><span className="big">💳</span>No payments yet.</div> : (
                  Object.entries(dashboard?.by_mode || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => {
                    const total = Object.values(dashboard.by_mode).reduce((s, x) => s + x, 0) || 1;
                    return (
                      <div key={k} className="mode-row"><span style={{ minWidth: 70 }}>{k}</span>
                        <div className="mode-track"><div className="mode-fill" style={{ width: `${Math.round((v / total) * 100)}%` }} /></div>
                        <b>{inr(v)}</b></div>
                    );
                  })
                )}
              </div>
              <div className="panel">
                <h3>⏰ Expiring within 90 days ({(dashboard?.expiry_soon || []).length})</h3>
                {(dashboard?.expiry_soon || []).length === 0 ? <p className="muted">Nothing expiring soon. 🎉</p> : (
                  <div className="mini-list">
                    {(dashboard?.expiry_soon || []).slice(0, 6).map((m) => (
                      <div key={m.id} className="mini-item"><span><b>{m.name}</b> <small>· exp {m.expiry_date} · {m.quantity} left</small></span><span className="pill warn">soon</span></div>
                    ))}
                  </div>
                )}
                {(dashboard?.expired || []).length > 0 && (
                  <p className="muted" style={{ marginBottom: 0 }}>⛔ {(dashboard?.expired || []).length} expired — quarantine: {(dashboard?.expired || []).slice(0, 3).map((m) => m.name).join(', ')}{dashboard.expired.length > 3 ? '…' : ''}</p>
                )}
              </div>
              <div className="panel">
                <h3>📉 Low stock ({(dashboard?.low_stock || []).length})</h3>
                {(dashboard?.low_stock || []).length === 0 ? <p className="muted">Stock levels look healthy. 🎉</p> : (
                  <div className="mini-list">
                    {(dashboard?.low_stock || []).slice(0, 6).map((m) => (
                      <div key={m.id} className="mini-item"><span><b>{m.name}</b> <small>· {m.quantity} left {m.rack ? `· rack ${m.rack}` : ''}</small></span><span className="pill low">{m.quantity}</span></div>
                    ))}
                  </div>
                )}
                <div className="row" style={{ marginTop: 10 }}>
                  <button className="ghost" onClick={() => { setTab('inventory'); setStockFilter('low'); }}>View all low stock</button>
                  <button className="ghost" onClick={() => { setTab('purchase'); }}>🚚 Restock</button>
                </div>
              </div>
            </div>
            <div className="panel" style={{ marginTop: 16 }}>
              <h3>🧾 Today&apos;s bills <span className="pill tag">{recentBills.length} today</span></h3>
              {recentBills.length === 0 ? <p className="muted">No bills today yet — new sales will appear here.</p> : (
                <>
                  <table><thead><tr><th>#</th><th>Customer</th><th>Total</th><th>Mode</th><th>Time</th><th>Status</th></tr></thead>
                    <tbody>{recentSlice.map((b) => (
                      <tr key={b.id}><td><b>#{b.id}</b></td><td>{b.customer_name || '—'}</td><td className="price">{inr(b.grand_total)}</td><td>{b.payment_mode}</td><td><small>{(b.created_at || '').slice(11)}</small></td><td>{b.status === 'returned' ? <span className="pill low">returned</span> : <span className="pill ok">completed</span>}</td></tr>
                    ))}</tbody></table>
                  <div className="row no-print" style={{ marginTop: 10, justifyContent: 'space-between' }}>
                    <small className="muted">Showing {recentFrom}–{recentTo} of {recentBills.length} · {todayStr()}</small>
                    <div className="row">
                      <button className="ghost" disabled={safeRecentPage <= 1} onClick={() => setRecentPage((p) => Math.max(1, p - 1))}>‹ Prev</button>
                      <small className="muted">Page {safeRecentPage} of {recentTotalPages}</small>
                      <button className="ghost" disabled={safeRecentPage >= recentTotalPages} onClick={() => setRecentPage((p) => Math.min(recentTotalPages, p + 1))}>Next ›</button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {tab === 'billing' && (
          <>
            <div className="cards billing">
              <div className="no-print">
                <div className="row no-print">
                  <input className="search-big" autoFocus placeholder="🔍 Name, salt, use, batch, supplier or rack… (Enter = add first match)" value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') quickAddFirst(); }} style={{ flex: 1 }} />
                  <button className="ghost" onClick={() => loadMeds(search, medsPage)}>Refresh</button>
                </div>
                <div className="chip-row no-print">
                  <button type="button" className={unitFilter === 'all' ? 'fchip on' : 'fchip'} onClick={() => { setUnitFilter('all'); setMedsPage(1); loadMeds(search, 1, { billing: true, unit: 'all' }); }}>All</button>
                  {unitTypes.filter((t) => t.is_active).map((t) => (
                    <button key={t.id} type="button" className={unitFilter === t.name ? 'fchip on' : 'fchip'} onClick={() => { setUnitFilter(t.name); setMedsPage(1); loadMeds(search, 1, { billing: true, unit: t.name }); }}>{t.name}</button>
                  ))}
                </div>
                {rxInCart.length > 0 && (
                  <div className="warnbox">℞ This bill contains prescription items: {rxInCart.map((l) => l.med.name).join(', ')} — verify prescription before dispensing.</div>
                )}
                {loading ? <p>Loading…</p> : filteredBilling.length === 0 ? (
                  <div className="empty"><span className="big">💊</span>No medicines found.</div>
                ) : (
                  <table className="med-table">
                    <thead><tr><th>Medicine</th><th>Stock</th><th>Price</th><th></th></tr></thead>
                    <tbody>
                      {filteredBilling.map((m) => {
                        const inCart = cartQty[m.id] || 0;
                        const st = expiryStatus(m);
                        return (
                          <tr key={m.id} className={inCart ? 'in-cart' : ''}>
                            <td><b>{m.name}</b> <span className="pill tag">{m.unit || 'tablet'}</span>{' '}
                              {m.rx_required && <span className="pill rx">℞ Rx</span>}{' '}
                              {m.schedule && <span className="pill warn">Sch {m.schedule}</span>}{' '}
                              {st === 'expired' && <span className="pill low">expired</span>}
                              {st === 'soon' && <span className="pill warn">exp {m.expiry_date}</span>}
                              <br /><small>{m.composition ? `Salt: ${m.composition} · ` : ''}{m.batch_no} · exp {m.expiry_date || '—'}{m.rack ? ` · rack ${m.rack}` : ''} · +{m.gst_percent}% GST</small>
                              {m.mrp > m.price && <><br /><small>MRP {inr(m.mrp)} · you save {inr(m.mrp - m.price)}</small></>}
                            </td>
                            <td><span className={m.quantity <= Math.max(lowLimit, m.min_stock || 0) ? 'pill low' : 'pill ok'}>{m.quantity}</span></td>
                            <td className="price">{inr(m.price)}</td>
                            <td>
                              {inCart ? (
                                <div className="stepper">
                                  <button type="button" onClick={() => setQty(m.id, inCart - 1)}>−</button>
                                  <span>{inCart}</span>
                                  <button type="button" onClick={() => setQty(m.id, inCart + 1)}>+</button>
                                </div>
                              ) : (
                                <button className="add-btn" onClick={() => addToCart(m.id)} disabled={m.quantity === 0 || st === 'expired'}>{st === 'expired' ? 'Expired' : 'Add +'}</button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
                {!loading && medsTotalPages > 1 && (
                  <div className="row no-print" style={{ marginTop: 10, justifyContent: 'space-between' }}>
                    <small className="muted">
                      Showing {medsTotal === 0 ? 0 : (medsPage - 1) * MEDS_PER_PAGE + 1}–{Math.min(medsPage * MEDS_PER_PAGE, medsTotal)} of {medsTotal}
                    </small>
                    <div className="row">
                      <button className="ghost" disabled={medsPage <= 1} onClick={() => gotoMedsPage(medsPage - 1)}>‹ Prev</button>
                      {medsPageNums.map((n, i, arr) => (
                        <span key={n} className="row" style={{ gap: 4 }}>
                          {i > 0 && n - arr[i - 1] > 1 && <small className="muted">…</small>}
                          <button className={n === medsPage ? 'preset on' : 'preset'} onClick={() => gotoMedsPage(n)}>{n}</button>
                        </span>
                      ))}
                      <button className="ghost" disabled={medsPage >= medsTotalPages} onClick={() => gotoMedsPage(medsPage + 1)}>Next ›</button>
                    </div>
                  </div>
                )}
              </div>
              <div className={cartLines.length > 0 ? 'cart has-items' : 'cart'} id="bill-cart">
                {cartLines.length > 0 ? (
                  <div className="editor">
                    <h3>🧾 Current Bill <span className="pill tag">{cartLines.length} item{cartLines.length > 1 ? 's' : ''}</span></h3>
                    <input placeholder="Customer name *" value={customer.customer_name} onChange={(e) => setCustomer({ ...customer, customer_name: e.target.value })} style={{ width: '100%', marginBottom: 8 }} list="cust-names" />
                    <datalist id="cust-names">{customers.slice(0, 20).map((c) => <option key={c.id} value={c.name}>{`${c.name} · ${c.phone}`}</option>)}</datalist>
                    <div className="row">
                      <input placeholder="Phone" value={customer.customer_phone} onChange={(e) => setCustomer({ ...customer, customer_phone: e.target.value })} style={{ flex: 1, minWidth: 110, marginBottom: 8 }} />
                      <input placeholder="Rx / prescription no." value={customer.prescription_no} onChange={(e) => setCustomer({ ...customer, prescription_no: e.target.value })} style={{ flex: 1, minWidth: 110, marginBottom: 8 }} />
                    </div>
                    <input placeholder="Doctor name (for Rx bills)" value={customer.doctor_name} onChange={(e) => setCustomer({ ...customer, doctor_name: e.target.value })} style={{ width: '100%', marginBottom: 8 }} />
                    <div className="pay-row">
                      <span>Pay via</span>
                      {(paymentModes.filter((p) => p.is_active).map((p) => p.name).length ? paymentModes.filter((p) => p.is_active).map((p) => p.name) : ['Cash']).map((p) => (
                        <button key={p} type="button" className={payMode === p ? 'preset on' : 'preset'} onClick={() => setPayMode(p)}>{p}</button>
                      ))}
                    </div>
                    <div className="cart-scroll">
                      <table>
                        <thead><tr><th>Item</th><th>Qty</th><th>Total</th><th></th></tr></thead>
                        <tbody>
                          {cartLines.map((l) => (
                            <tr key={l.medicine_id}>
                              <td><small><b>{l.med.name}</b>{l.med.rx_required ? ' ℞' : ''}</small><span className="no-print"><small><br />{inr(l.med.price)}/{l.med.unit || 'tablet'} + {l.med.gst_percent}% GST</small></span></td>
                              <td>
                                <div className="stepper">
                                  <button type="button" onClick={() => setQty(l.medicine_id, l.qty - 1)}>−</button>
                                  <span>{l.qty}</span>
                                  <button type="button" onClick={() => setQty(l.medicine_id, l.qty + 1)}>+</button>
                                </div>
                                <small>max {l.med.quantity}</small>
                              </td>
                              <td><small className="price">{inr(l.total)}</small></td>
                              <td><button className="ghost" onClick={() => setCart((prev) => prev.filter((c) => c.medicine_id !== l.medicine_id))}>✕</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="disc-row">
                      <span>Discount</span>
                      {[0, 5, 10].map((d) => (
                        <button key={d} type="button" className={discPct === d ? 'preset on' : 'preset'} onClick={() => setDiscount(d)}>{d}%</button>
                      ))}
                      <input type="number" min="0" max="100" value={discount} onChange={(e) => setDiscount(e.target.value)} style={{ width: 70 }} /> %
                    </div>
                    <div className="totals">
                      <div><span>Subtotal</span><span>{inr(subtotal)}</span></div>
                      <div><span>GST</span><span>{inr(gstTotal)}</span></div>
                      {discAmount > 0 && <div><span>Discount ({discPct}%)</span><span>− {inr(discAmount)}</span></div>}
                      <div className="grand"><span>Total</span><span>{inr(grandTotal)}</span></div>
                    </div>
                    <div className="tender-row">
                      <span>Cash received</span>
                      <input type="number" min="0" placeholder="₹ tendered" value={tendered} onChange={(e) => setTendered(e.target.value)} style={{ width: 120 }} />
                      {change !== null && (change >= 0 ? <span className="pill ok">Change: {inr(change)}</span> : <span className="pill low">Short: {inr(-change)}</span>)}
                    </div>
                    <div className="row no-print bill-actions" style={{ marginTop: 12 }}>
                      <button className="primary bill-btn" onClick={checkout}>✓ Bill {inr(grandTotal)}</button>
                      <button className="ghost" onClick={() => { setCart([]); setDiscount(0); setTendered(''); }}>Clear</button>
                    </div>
                  </div>
                ) : lastBill ? (
                  <Invoice bill={lastBill} settings={settings} onNew={() => setLastBill(null)} />
                ) : (
                  <>
                    <h3>🧾 Current Bill</h3>
                    <div className="empty"><span className="big">🧺</span>Cart is empty.<br />Tap <b>Add +</b> on any medicine to start billing.</div>
                  </>
                )}
              </div>
            </div>
            {cartLines.length > 0 && (
              <button className="float-bill no-print" onClick={() => document.getElementById('bill-cart')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
                🧾 {cartLines.length} item{cartLines.length > 1 ? 's' : ''} · {inr(grandTotal)} →
              </button>
            )}
          </>
        )}

        {tab === 'inventory' && (
          <div>
            <div className="toolbar no-print">
              <input placeholder="🔍 Search name, salt, batch, supplier, rack…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ flex: 2, minWidth: 180 }} />
              <select value={stockFilter} onChange={(e) => { const v = e.target.value; setStockFilter(v); setMedsPage(1); loadMeds(search, 1, { billing: false, stock: v }); }}>
                <option value="all">All stock</option>
                <option value="low">⚠️ Low stock ({dashboard?.low_stock_count || 0})</option>
                <option value="out">⛔ Out of stock</option>
                <option value="expiring">⏰ Expiring ≤ 90 days</option>
                <option value="expired">☠️ Expired</option>
                <option value="rx">℞ Prescription drugs</option>
              </select>
              <select value={sortBy} onChange={(e) => { const v = e.target.value; setSortBy(v); setMedsPage(1); loadMeds(search, 1, { billing: false, sort: v }); }}>
                <option value="name">Sort: Name</option>
                <option value="stock">Sort: Lowest stock</option>
                <option value="expiry">Sort: Expiry</option>
                <option value="value">Sort: Stock value</option>
              </select>
              {isAdmin ? <button className="primary" onClick={openNew}>+ Add Medicine</button>
                : <span className="pill tag">👁️ View only</span>}
            </div>
            <table>
              <thead><tr><th>Name</th><th>Batch / Expiry</th><th>Stock</th><th>Price / MRP</th><th>GST</th>{isAdmin && <th className="no-print">Actions</th>}</tr></thead>
              <tbody>
                {inventoryList.map((m) => {
                  const st = expiryStatus(m);
                  return (
                    <tr key={m.id}>
                      <td><b>{m.name}</b> <span className="pill tag">{m.unit || 'tablet'}</span>{' '}
                        {m.rx_required && <span className="pill rx">℞</span>}{' '}
                        {m.schedule && <span className="pill warn">{m.schedule}</span>}
                        <br /><small>{m.composition || '—'}{m.supplier ? ` · ${m.supplier}` : ''}{m.rack ? ` · rack ${m.rack}` : ''}</small>
                        {m.description ? <><br /><small>💊 {m.description}</small></> : null}</td>
                      <td><small>{m.batch_no || '—'}<br />{m.expiry_date || '—'}</small><br />{st === 'expired' ? <span className="pill low">expired</span> : st === 'soon' ? <span className="pill warn">expiring</span> : null}</td>
                      <td><span className={m.quantity <= Math.max(lowLimit, m.min_stock || 0) ? 'pill low' : 'pill ok'}>{m.quantity}</span>{m.min_stock ? <><br /><small>min {m.min_stock}</small></> : null}</td>
                      <td className="price">{inr(m.price)}{m.mrp > 0 && <><br /><small>MRP {inr(m.mrp)}</small></>}</td>
                      <td>{m.gst_percent}%</td>
                      {isAdmin && (
                        <td className="no-print">
                          <div className="row">
                            <button className="ghost" onClick={() => openEdit(m)}>Edit</button>
                            <button className="ghost" onClick={() => { setAdjusting(m); setAdjustForm({ delta: '', reason: '' }); }} title="Stock correction">±</button>
                            <button className="danger" onClick={() => removeMed(m.id)}>Remove</button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {inventoryList.length === 0 && <div className="empty"><span className="big">📦</span>Nothing matches this filter.</div>}
            {!loading && medsTotalPages > 1 && (
              <div className="row no-print" style={{ marginTop: 10, justifyContent: 'space-between' }}>
                <small className="muted">
                  Showing {medsTotal === 0 ? 0 : (medsPage - 1) * MEDS_PER_PAGE + 1}–{Math.min(medsPage * MEDS_PER_PAGE, medsTotal)} of {medsTotal}
                </small>
                <div className="row">
                  <button className="ghost" disabled={medsPage <= 1} onClick={() => gotoMedsPage(medsPage - 1)}>‹ Prev</button>
                  {medsPageNums.map((n, i, arr) => (
                    <span key={n} className="row" style={{ gap: 4 }}>
                      {i > 0 && n - arr[i - 1] > 1 && <small className="muted">…</small>}
                      <button className={n === medsPage ? 'preset on' : 'preset'} onClick={() => gotoMedsPage(n)}>{n}</button>
                    </span>
                  ))}
                  <button className="ghost" disabled={medsPage >= medsTotalPages} onClick={() => gotoMedsPage(medsPage + 1)}>Next ›</button>
                </div>
              </div>
            )}
            {editing && isAdmin && (
              <div className="modal"><div>
                <h3>{editing === 'new' ? '➕ Add Medicine' : `✏️ Edit #${editing}`}</h3>
                <form onSubmit={saveMed}>
                  <div className="form-grid">
                    <label className="full">Medicine name *<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder="e.g. Paracetamol 650mg Tablet" /></label>
                    <label className="full">Composition / salt<input value={form.composition || ''} onChange={(e) => setForm({ ...form, composition: e.target.value })} placeholder="e.g. Paracetamol" /></label>
                    <label className="full">Description<input value={form.description || ''} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What this treats" /></label>
                    <label className="full">Usage / how to take<input value={form.usage || ''} onChange={(e) => setForm({ ...form, usage: e.target.value })} placeholder="Dose instructions" /></label>
                    <label>Medicine type<select value={form.unit || 'tablet'} onChange={(e) => setForm({ ...form, unit: e.target.value })}>
                      {unitTypes.filter((t) => t.is_active).map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
                    </select></label>
                    <label>Batch no<input value={form.batch_no} onChange={(e) => setForm({ ...form, batch_no: e.target.value })} placeholder="B101" /></label>
                    <label>Expiry date<input type="date" value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} /></label>
                    <label>Rack / shelf<input value={form.rack || ''} onChange={(e) => setForm({ ...form, rack: e.target.value })} placeholder="A-12" /></label>
                    <label>Stock quantity<input type="number" min="0" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></label>
                    <label>Min stock alert<input type="number" min="0" value={form.min_stock || 0} onChange={(e) => setForm({ ...form, min_stock: e.target.value })} /></label>
                    <label>Selling price (₹)<input type="number" min="0" step="0.01" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></label>
                    <label>MRP (₹)<input type="number" min="0" step="0.01" value={form.mrp || ''} onChange={(e) => setForm({ ...form, mrp: e.target.value })} placeholder="MRP" /></label>
                    <label>GST slab<select value={form.gst_percent} onChange={(e) => setForm({ ...form, gst_percent: Number(e.target.value) })}>
                      {gstRates.filter((s) => s.is_active).map((s) => <option key={s.id} value={s.rate}>{s.rate}% GST</option>)}
                    </select></label>
                    <label>Schedule (H/H1/X)<input value={form.schedule || ''} onChange={(e) => setForm({ ...form, schedule: e.target.value.toUpperCase() })} placeholder="H, H1, X or blank" /></label>
                    <label>Supplier<input value={form.supplier || ''} onChange={(e) => setForm({ ...form, supplier: e.target.value })} placeholder="Distributor" list="sup-list" /></label>
                    <label className="row" style={{ alignItems: 'center' }}><input type="checkbox" checked={!!form.rx_required} onChange={(e) => setForm({ ...form, rx_required: e.target.checked })} /> ℞ Prescription required</label>
                  </div>
                  <datalist id="sup-list">{suppliers.map((s) => <option key={s.id} value={s.name} />)}</datalist>
                  <div className="row" style={{ marginTop: 12 }}>
                    <button className="primary" type="submit">Save</button>
                    <button className="ghost" type="button" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </form>
              </div></div>
            )}
            {adjusting && isAdmin && (
              <div className="modal"><div style={{ width: 420 }}>
                <h3>± Adjust stock — {adjusting.name}</h3>
                <p className="muted">Current stock: <b>{adjusting.quantity}</b>. Positive adds, negative removes. Logged in the audit trail.</p>
                <form onSubmit={submitAdjust}>
                  <input type="number" placeholder="+50 or -5 (not zero)" value={adjustForm.delta} onChange={(e) => setAdjustForm({ ...adjustForm, delta: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                  <input placeholder="Reason (e.g. breakage, recount)" value={adjustForm.reason} onChange={(e) => setAdjustForm({ ...adjustForm, reason: e.target.value })} style={{ width: '100%', marginBottom: 8 }} />
                  <div className="row">
                    <button className="primary" type="submit">Apply</button>
                    <button className="ghost" type="button" onClick={() => setAdjusting(null)}>Cancel</button>
                  </div>
                </form>
              </div></div>
            )}
          </div>
        )}

        {tab === 'bills' && (
          <div className="cards">
            <div className="no-print">
              <div className="toolbar">
                <input placeholder="🔍 Bill #, customer, phone…" value={billSearch} onChange={(e) => setBillSearch(e.target.value)} style={{ flex: 2, minWidth: 160 }} />
                <select value={billStatus} onChange={(e) => setBillStatus(e.target.value)}>
                  <option value="all">All</option>
                  <option value="completed">Completed</option>
                  <option value="returned">Returned</option>
                </select>
                <button className="ghost" onClick={() => loadBills(billsPage, billSearch, billStatus, dateFrom, dateTo)}>Refresh</button>
              </div>
              <div className="toolbar">
                <label className="muted"><small>From <input type="date" value={dateFrom} max={dateTo || todayStr()} onChange={(e) => setBillsRange(e.target.value, dateTo)} /></small></label>
                <label className="muted"><small>To <input type="date" value={dateTo} min={dateFrom || undefined} max={todayStr()} onChange={(e) => setBillsRange(dateFrom, e.target.value)} /></small></label>
                <button className="preset" onClick={() => setBillsRange(todayStr(), todayStr())}>Today</button>
                <button className="preset" onClick={() => setBillsRange(new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10), todayStr())}>Last 7 days</button>
                {(dateFrom || dateTo) && <button className="ghost" onClick={() => setBillsRange('', '')}>✕ Clear dates</button>}
                {(billSearch || billStatus !== 'all' || dateFrom || dateTo) && <button className="ghost" onClick={clearBillsFilters}>Reset all</button>}
              </div>
              {billsLoading ? <p>Loading bills…</p> : bills.length === 0 ? <div className="empty"><span className="big">🧾</span>No bills found. Try another search or status.</div> : (
                <>
                  <table>
                    <thead><tr><th>#</th><th>Customer</th><th>Total</th><th>Status</th><th></th></tr></thead>
                    <tbody>
                      {bills.map((b) => (
                        <tr key={b.id}>
                          <td><b>#{b.id}</b><br /><small>{b.created_at}</small></td>
                          <td>{b.customer_name || '—'}<br /><small>{b.customer_phone}</small></td>
                          <td className="price">{inr(b.grand_total)}<br /><small>{b.payment_mode}</small></td>
                          <td>{(b.status || 'completed') === 'returned' ? <span className="pill low">returned</span> : <span className="pill ok">paid</span>}</td>
                          <td><button className="ghost" onClick={() => viewBill(b.id)}>View</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="row no-print" style={{ marginTop: 10, justifyContent: 'space-between' }}>
                    <small className="muted">
                      Showing {billsTotal === 0 ? 0 : (billsPage - 1) * BILLS_PER_PAGE + 1}–{Math.min(billsPage * BILLS_PER_PAGE, billsTotal)} of {billsTotal}
                      {(dateFrom || dateTo) && ` · ${dateFrom || '…'} → ${dateTo || '…'}`}
                    </small>
                    <div className="row">
                      <button className="ghost" disabled={billsPage <= 1} onClick={() => gotoBillsPage(billsPage - 1)}>‹ Prev</button>
                      {billsPageNums.map((n, i, arr) => (
                        <span key={n} className="row" style={{ gap: 4 }}>
                          {i > 0 && n - arr[i - 1] > 1 && <small className="muted">…</small>}
                          <button className={n === billsPage ? 'preset on' : 'preset'} onClick={() => gotoBillsPage(n)}>{n}</button>
                        </span>
                      ))}
                      <button className="ghost" disabled={billsPage >= billsTotalPages} onClick={() => gotoBillsPage(billsPage + 1)}>Next ›</button>
                    </div>
                  </div>
                </>
              )}
            </div>
            <div className="cart">
              {!billDetail ? (
                <><h3>Bill detail</h3><div className="empty"><span className="big">🧾</span>Select a bill to view its invoice.</div></>
              ) : (
                <>
                  <Invoice bill={billDetail} settings={settings} />
                  {(billDetail.status || 'completed') !== 'returned' && (
                    <div className="row no-print" style={{ marginTop: 10 }}>
                      <button className="danger" onClick={() => doReturn(billDetail.id)}>↩ Accept return (restock)</button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {tab === 'customers' && (
          <div className="cards">
            <div>
              <div className="toolbar no-print">
                <input placeholder="🔍 Search customers…" value={custSearch} onChange={(e) => setCustSearch(e.target.value)} style={{ flex: 1 }} />
                <button className="ghost" onClick={() => loadCustomers(custSearch)}>Refresh</button>
              </div>
              {customers.length === 0 ? <div className="empty"><span className="big">🧑‍🤝‍🧑</span>No customers yet — they appear automatically after billing.</div> : (
                <table>
                  <thead><tr><th>Customer</th><th>Bills</th><th>Spent</th><th></th></tr></thead>
                  <tbody>
                    {customers.map((c) => (
                      <tr key={c.id}>
                        <td><b>{c.name || '—'}</b><br /><small>{c.phone || 'no phone'} · last {c.last_visit ? c.last_visit.slice(0, 10) : '—'}</small></td>
                        <td>{c.total_bills}</td>
                        <td className="price">{inr(c.total_spent)}</td>
                        <td><button className="ghost" onClick={() => viewCustomer(c)}>History</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="cart">
              {!custDetail ? <><h3>Customer history</h3><div className="empty"><span className="big">🧾</span>Pick a customer to see repeat purchases.</div></> : (
                <div>
                  <h3>🧑 {custDetail.customer.name || '—'} <span className="pill tag">{custDetail.customer.total_bills} bills</span></h3>
                  <p className="muted">{custDetail.customer.phone} · lifetime {inr(custDetail.customer.total_spent)} · last {custDetail.customer.last_visit?.slice(0, 10)}</p>
                  <div className="mini-list">
                    {custDetail.bills.map((b) => (
                      <div key={b.id} className="mini-item"><span><b>#{b.id}</b> <small>{b.created_at} · {b.payment_mode}</small></span><span className="price">{inr(b.grand_total)}</span></div>
                    ))}
                  </div>
                  {custDetail.bills.length === 0 && <p className="muted">No bills found.</p>}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'purchase' && (
          <div>
            {!isAdmin && <div className="warnbox">👁️ Staff view only — only admin can record purchases or manage suppliers.</div>}
            <div className="grid2">
              <div className="panel">
                <h3>🚚 Record purchase / stock-in</h3>
                <form onSubmit={submitPurchase}>
                  <input placeholder="🔍 Type to search medicine…" value={purSearch} onChange={(e) => { setPurSearch(e.target.value); if (purchase.medicine_id) setPurchase({ ...purchase, medicine_id: '' }); }} style={{ width: '100%', marginBottom: 8 }} required={!purchase.medicine_id} />
                  {purOptions.length > 0 && !purchase.medicine_id && (
                    <div className="mini-list" style={{ marginBottom: 8 }}>
                      {purOptions.map((m) => (
                        <div key={m.id} className="mini-item">
                          <span><b>{m.name}</b><br /><small>stock {m.quantity} · {inr(m.price)}{m.supplier ? ` · ${m.supplier}` : ''}</small></span>
                          <button type="button" className="ghost" onClick={() => { setPurchase({ ...purchase, medicine_id: m.id }); setPurSearch(m.name); setPurOptions([]); }}>Select</button>
                        </div>
                      ))}
                    </div>
                  )}
                  {purchase.medicine_id ? <p><small>Selected: <b>{purSearch}</b> <button type="button" className="ghost" onClick={() => { setPurchase({ ...purchase, medicine_id: '' }); setPurSearch(''); }}>✕</button></small></p> : null}
                  <div className="row">
                    <input type="number" min="1" placeholder="Qty received" value={purchase.qty} onChange={(e) => setPurchase({ ...purchase, qty: e.target.value })} style={{ flex: 1, minWidth: 120 }} required />
                    <input placeholder="Supplier" value={purchase.supplier} onChange={(e) => setPurchase({ ...purchase, supplier: e.target.value })} style={{ flex: 2, minWidth: 140 }} list="sup-list2" />
                  </div>
                  <datalist id="sup-list2">{suppliers.map((s) => <option key={s.id} value={s.name} />)}</datalist>
                  <input placeholder="Invoice / note (optional)" value={purchase.note} onChange={(e) => setPurchase({ ...purchase, note: e.target.value })} style={{ width: '100%', margin: '8px 0' }} />
                  <button className="primary" type="submit" disabled={!isAdmin} style={{ width: '100%' }}>➕ Add stock</button>
                </form>
                <h3 style={{ marginTop: 18 }}>📒 Recent stock movements</h3>
                <div className="mini-list">
                  {movements.slice(0, 10).map((mv) => (
                    <div key={mv.id} className="mini-item">
                      <span><b>{mv.medicine_name}</b> <small>· {mv.reason} · {mv.ref} · {mv.created_by}</small><br /><small>{mv.created_at}</small></span>
                      <span className={mv.change >= 0 ? 'pill ok' : 'pill low'}>{mv.change >= 0 ? '+' : ''}{mv.change}</span>
                    </div>
                  ))}
                  {movements.length === 0 && <p className="muted">No movements logged yet.</p>}
                </div>
              </div>
              <div className="panel">
                <h3>🏭 Suppliers {isAdmin ? '' : '(view)'}</h3>
                {isAdmin && (
                  <form onSubmit={saveSupplier} style={{ marginBottom: 12 }}>
                    <input placeholder="Supplier name *" value={supForm.name} onChange={(e) => setSupForm({ ...supForm, name: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                    <div className="row">
                      <input placeholder="Phone" value={supForm.phone} onChange={(e) => setSupForm({ ...supForm, phone: e.target.value })} style={{ flex: 1, minWidth: 110 }} />
                      <input placeholder="GSTIN" value={supForm.gstin} onChange={(e) => setSupForm({ ...supForm, gstin: e.target.value.toUpperCase() })} style={{ flex: 1, minWidth: 110 }} />
                    </div>
                    <input placeholder="Address" value={supForm.address} onChange={(e) => setSupForm({ ...supForm, address: e.target.value })} style={{ width: '100%', margin: '8px 0' }} />
                    <div className="row">
                      <button className="primary" type="submit">{editingSup ? 'Save' : 'Add supplier'}</button>
                      {editingSup && <button className="ghost" type="button" onClick={() => { setEditingSup(null); setSupForm({ name: '', phone: '', address: '', gstin: '' }); }}>Cancel</button>}
                    </div>
                  </form>
                )}
                <div className="mini-list">
                  {suppliers.map((s) => (
                    <div key={s.id} className="mini-item">
                      <span><b>{s.name}</b><br /><small>{s.phone} {s.gstin ? `· ${s.gstin}` : ''}</small></span>
                      {isAdmin && <span className="row"><button className="ghost" onClick={() => { setEditingSup(s.id); setSupForm({ name: s.name, phone: s.phone, address: s.address, gstin: s.gstin }); }}>Edit</button><button className="danger" onClick={() => removeSupplier(s.id)}>Del</button></span>}
                    </div>
                  ))}
                  {suppliers.length === 0 && <div className="empty"><span className="big">🏭</span>No suppliers yet.</div>}
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === 'reports' && (
          <div>
            <div className="toolbar no-print">
              <h3 className="section-title">📈 Sales reports</h3>
              {[7, 14, 30].map((d) => (
                <button key={d} className={reportDays === d ? 'preset on' : 'preset'} onClick={() => setReportDays(d)}>Last {d} days</button>
              ))}
              <button className="ghost" onClick={() => loadReport(reportDays)}>Refresh</button>
              <span className="chip good">Total {inr(report?.total_sales || 0)} · {report?.total_bills || 0} bills</span>
            </div>
            <div className="panel">
              <h3>Daily revenue</h3>
              <div className="bars">
                {(report?.daily || []).map((d) => (
                  <div key={d.date} className="bar" style={{ height: `${Math.max(3, Math.round((d.sales / maxDaily) * 140))}px` }} data-tip={`${d.date}: ${inr(d.sales)} (${d.bills})`} />
                ))}
              </div>
              <div className="bar-axis">{(report?.daily || []).map((d) => <span key={d.date}>{d.date.slice(5)}</span>)}</div>
            </div>
            <div className="grid2" style={{ marginTop: 16 }}>
              <div className="panel">
                <h3>💳 By payment mode</h3>
                {Object.keys(report?.by_mode || {}).length === 0 ? <p className="muted">No sales in this window.</p> :
                  Object.entries(report?.by_mode || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => {
                    const total = Object.values(report.by_mode).reduce((s, x) => s + x, 0) || 1;
                    return <div key={k} className="mode-row"><span style={{ minWidth: 70 }}>{k}</span><div className="mode-track"><div className="mode-fill" style={{ width: `${Math.round((v / total) * 100)}%` }} /></div><b>{inr(v)}</b></div>;
                  })}
              </div>
              <div className="panel">
                <h3>🏆 Top items by revenue</h3>
                <div className="mini-list">
                  {(report?.top_items || []).map((t, i) => (
                    <div key={i} className="mini-item"><span><b>#{i + 1}</b> {t.name} <small>· {t.qty} sold</small></span><span className="price">{inr(t.revenue)}</span></div>
                  ))}
                  {(report?.top_items || []).length === 0 && <p className="muted">No item sales yet.</p>}
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === 'masters-gst' && isAdmin && (
          <div className="cards">
            <div>
              <h3 className="section-title">Master GST slabs</h3>
              <p className="muted"><small>Medicines must use one of these slabs. Renaming updates all medicines on it.</small></p>
              <table>
                <thead><tr><th>Slab</th><th>Status</th><th>Using</th><th></th></tr></thead>
                <tbody>
                  {gstRates.map((s) => (
                    <tr key={s.id}>
                      <td className="price">{s.rate}%</td>
                      <td>{s.is_active ? <span className="pill ok">active</span> : <span className="pill low">inactive</span>}</td>
                      <td>{s.medicines_using}</td>
                      <td className="no-print">
                        <button className="ghost" onClick={() => { setEditingRate(s.id); setGstForm({ rate: s.rate, is_active: !!s.is_active }); }}>Edit</button>{' '}
                        <button className="ghost" onClick={() => toggleSlab(s)}>{s.is_active ? 'Deactivate' : 'Activate'}</button>{' '}
                        <button className="danger" onClick={() => removeSlab(s)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="cart">
              <h3>{editingRate ? '✏️ Edit slab' : '➕ Add slab'}</h3>
              <form onSubmit={editingRate ? saveSlab : addSlab}>
                <input type="number" min="0" max="100" step="0.01" placeholder="GST rate % (e.g. 5)" value={gstForm.rate} onChange={(e) => setGstForm({ ...gstForm, rate: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                {editingRate && (
                  <label className="row" style={{ fontSize: 14, marginBottom: 10 }}>
                    <input type="checkbox" checked={gstForm.is_active} onChange={(e) => setGstForm({ ...gstForm, is_active: e.target.checked })} /> Active
                  </label>
                )}
                <div className="row">
                  <button className="primary" type="submit">{editingRate ? 'Save' : 'Add slab'}</button>
                  {editingRate && <button className="ghost" type="button" onClick={() => { setEditingRate(null); setGstForm({ rate: '', is_active: true }); }}>Cancel</button>}
                </div>
              </form>
            </div>
          </div>
        )}
        {tab === 'masters-types' && isAdmin && (
          <div className="cards">
            <div>
              <h3 className="section-title">Medicine types</h3>
              <p className="muted"><small>Every medicine uses one of these types (billing unit).</small></p>
              <table>
                <thead><tr><th>Type</th><th>Status</th><th>Using</th><th></th></tr></thead>
                <tbody>
                  {unitTypes.map((t) => (
                    <tr key={t.id}>
                      <td><span className="pill tag">{t.name}</span></td>
                      <td>{t.is_active ? <span className="pill ok">active</span> : <span className="pill low">inactive</span>}</td>
                      <td>{t.medicines_using}</td>
                      <td className="no-print">
                        <button className="ghost" onClick={() => { setEditingType(t.id); setTypeForm({ name: t.name, is_active: !!t.is_active }); }}>Edit</button>{' '}
                        <button className="ghost" onClick={() => toggleType(t)}>{t.is_active ? 'Deactivate' : 'Activate'}</button>{' '}
                        <button className="danger" onClick={() => removeType(t)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="cart">
              <h3>{editingType ? '✏️ Edit type' : '➕ Add type'}</h3>
              <form onSubmit={editingType ? saveType : addType}>
                <input placeholder="Type name (e.g. drops)" value={typeForm.name} onChange={(e) => setTypeForm({ ...typeForm, name: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                {editingType && (
                  <label className="row" style={{ fontSize: 14, marginBottom: 10 }}>
                    <input type="checkbox" checked={typeForm.is_active} onChange={(e) => setTypeForm({ ...typeForm, is_active: e.target.checked })} /> Active
                  </label>
                )}
                <div className="row">
                  <button className="primary" type="submit">{editingType ? 'Save' : 'Add type'}</button>
                  {editingType && <button className="ghost" type="button" onClick={() => { setEditingType(null); setTypeForm({ name: '', is_active: true }); }}>Cancel</button>}
                </div>
              </form>
            </div>
          </div>
        )}
        {tab === 'masters-pay' && isAdmin && (
          <div className="cards">
            <div>
              <h3 className="section-title">Payment modes</h3>
              <p className="muted"><small>Bills must use one of these modes.</small></p>
              <table>
                <thead><tr><th>Mode</th><th>Status</th><th>Bills</th><th></th></tr></thead>
                <tbody>
                  {paymentModes.map((m) => (
                    <tr key={m.id}>
                      <td><span className="pill tag">{m.name}</span></td>
                      <td>{m.is_active ? <span className="pill ok">active</span> : <span className="pill low">inactive</span>}</td>
                      <td>{m.bills_using}</td>
                      <td className="no-print">
                        <button className="ghost" onClick={() => { setEditingMode(m.id); setModeForm({ name: m.name, is_active: !!m.is_active }); }}>Edit</button>{' '}
                        <button className="ghost" onClick={() => toggleMode(m)}>{m.is_active ? 'Deactivate' : 'Activate'}</button>{' '}
                        <button className="danger" onClick={() => removeMode(m)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="cart">
              <h3>{editingMode ? '✏️ Edit mode' : '➕ Add mode'}</h3>
              <form onSubmit={editingMode ? saveMode : addMode}>
                <input placeholder="Mode name (e.g. NetBanking)" value={modeForm.name} onChange={(e) => setModeForm({ ...modeForm, name: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                {editingMode && (
                  <label className="row" style={{ fontSize: 14, marginBottom: 10 }}>
                    <input type="checkbox" checked={modeForm.is_active} onChange={(e) => setModeForm({ ...modeForm, is_active: e.target.checked })} /> Active
                  </label>
                )}
                <div className="row">
                  <button className="primary" type="submit">{editingMode ? 'Save' : 'Add mode'}</button>
                  {editingMode && <button className="ghost" type="button" onClick={() => { setEditingMode(null); setModeForm({ name: '', is_active: true }); }}>Cancel</button>}
                </div>
              </form>
            </div>
          </div>
        )}
        {tab === 'masters-store' && isAdmin && (
          <div className="cards">
            <div className="cart">
              <h3>🏪 Pharmacy details</h3>
              <form onSubmit={saveStore}>
                <input placeholder="Pharmacy name *" value={storeForm.name} onChange={(e) => setStoreForm({ ...storeForm, name: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                <input placeholder="Tagline" value={storeForm.tagline} onChange={(e) => setStoreForm({ ...storeForm, tagline: e.target.value })} style={{ width: '100%', marginBottom: 8 }} />
                <textarea placeholder="Address" value={storeForm.address} onChange={(e) => setStoreForm({ ...storeForm, address: e.target.value })} rows={3} style={{ width: '100%', marginBottom: 8 }} />
                <div className="row">
                  <input placeholder="Phone" value={storeForm.phone} onChange={(e) => setStoreForm({ ...storeForm, phone: e.target.value })} style={{ flex: 1, minWidth: 120 }} />
                  <input placeholder="GSTIN" value={storeForm.gstin} onChange={(e) => setStoreForm({ ...storeForm, gstin: e.target.value.toUpperCase() })} style={{ flex: 1, minWidth: 140 }} />
                </div>
                <div className="row" style={{ marginTop: 8, fontSize: 14 }}>
                  <label htmlFor="lowstock">Low-stock alert below:</label>
                  <input id="lowstock" type="number" min="0" value={storeForm.low_stock_limit} onChange={(e) => setStoreForm({ ...storeForm, low_stock_limit: e.target.value })} style={{ width: 90 }} />
                </div>
                <button className="primary" type="submit" style={{ width: '100%', marginTop: 10 }}>Save profile</button>
              </form>
            </div>
            <div className="cart">
              <h3>🖼️ Logo</h3>
              <p className="muted"><small>PNG, JPG, GIF, WebP or SVG · up to 2 MB.</small></p>
              {settings.logo_url ? <img src={settings.logo_url} className="logo-preview" alt="store logo" /> : <div className="empty"><span className="big">🖼️</span>No logo yet.</div>}
              <div className="row" style={{ marginTop: 10 }}>
                <label className="ghost" style={{ cursor: 'pointer' }}>
                  ⬆️ Upload logo
                  <input type="file" accept="image/*,.svg" onChange={uploadLogoFile} style={{ display: 'none' }} />
                </label>
                {settings.logo_url && <button className="danger" onClick={removeLogo}>Remove</button>}
              </div>
            </div>
          </div>
        )}
        {tab === 'users' && (
          <div className={isAdmin ? 'cards' : ''}>
            {isAdmin && (
              <div>
                <h3 className="section-title">User logins</h3>
                <table>
                  <thead><tr><th>#</th><th>Username</th><th>Role</th><th>Created</th><th></th></tr></thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td>{u.id}</td>
                        <td><b>{u.username}</b>{u.username === username && ' (you)'}</td>
                        <td>{u.is_admin ? <span className="pill tag">admin</span> : <span className="pill ok">staff</span>}</td>
                        <td><small>{u.created_at}</small></td>
                        <td className="no-print">{u.username !== username && <button className="danger" onClick={() => removeUser(u.id, u.username)}>Remove</button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div>
              {isAdmin && (
                <div className="cart" style={{ marginBottom: 16 }}>
                  <h3>➕ Add new user</h3>
                  <form onSubmit={addUser}>
                    <input placeholder="Username (min 3 chars)" value={userForm.username} onChange={(e) => setUserForm({ ...userForm, username: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                    <input type="password" placeholder="Password (min 4 chars)" value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                    <label className="row" style={{ fontSize: 14, marginBottom: 10 }}>
                      <input type="checkbox" checked={userForm.is_admin} onChange={(e) => setUserForm({ ...userForm, is_admin: e.target.checked })} /> Make admin
                    </label>
                    <button className="primary" type="submit" style={{ width: '100%' }}>Create user</button>
                  </form>
                </div>
              )}
              <div className="cart">
                <h3>🔑 My account — {username}</h3>
                <form onSubmit={changePwd}>
                  <input type="password" placeholder="Current password" value={pwdForm.current} onChange={(e) => setPwdForm({ ...pwdForm, current: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                  <input type="password" placeholder="New password" value={pwdForm.next} onChange={(e) => setPwdForm({ ...pwdForm, next: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                  <input type="password" placeholder="Confirm new password" value={pwdForm.confirm} onChange={(e) => setPwdForm({ ...pwdForm, confirm: e.target.value })} style={{ width: '100%', marginBottom: 8 }} required />
                  <button className="ghost" type="submit" style={{ width: '100%' }}>Change password</button>
                </form>
              </div>
            </div>
          </div>
        )}
      </main>
      <footer className="foot">MediCare Pharmacy · React + Flask + SQLite · All prices in ₹ INR · CGST/SGST-ready invoices</footer>
    </div>
  );
}
