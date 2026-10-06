const express = require('express');
const path = require('path');
const axios = require('axios');
const bodyParser = require('body-parser');
const cors = require('cors');
const session = require('express-session');
const expressLayouts = require('express-ejs-layouts');
const SQLiteStore = require('connect-sqlite3')(session);

const app = express();
const PORT = process.env.PORT || 3000;
const FLASK_API = process.env.FLASK_API || 'http://localhost:5001/api';

app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.set('layout', 'layout');
app.use(expressLayouts);

app.use(session({
  secret: process.env.SESSION_SECRET || require('crypto').randomBytes(32).toString('hex'),
  resave: false,
  saveUninitialized: false,
  store: new SQLiteStore({ db: 'sessions.db', dir: path.join(__dirname), concurrentDB: true }),
  cookie: {
    maxAge: 8 * 60 * 60 * 1000,
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production'
  }
}));

// CSRF protection for cookie-session POST forms: per-session token
// embedded in every form, validated on every POST.
app.use((req, res, next) => {
  if (!req.session.csrf) {
    req.session.csrf = require('crypto').randomBytes(24).toString('hex');
  }
  res.locals.csrfToken = req.session.csrf;
  next();
});
app.use((req, res, next) => {
  if (req.method === 'POST' && !String(req.headers['content-type'] || '').includes('multipart/form-data') && (!req.body || req.body._csrf !== req.session.csrf)) {
    return res.status(403).send('Invalid CSRF token');
  }
  next();
});

// Make logged-in user available in all views (including layout)
app.use((req, res, next) => {
  res.locals.user = req.session.user || null;
  next();
});

// Toast messages: one-shot notices set in session by POST handlers
app.use((req, res, next) => {
  res.locals.toast = (req.session && req.session.toast) || null;
  if (req.session) delete req.session.toast;
  next();
});
// Clinic profile (DB settings) available in all views, refreshed every minute
let clinicCache = { ts: 0, data: null };
async function clinicSettings() {
  if (Date.now() - clinicCache.ts < 60000 && clinicCache.data) return clinicCache.data;
  try {
    const { data } = await api.get('/settings');
    clinicCache = { ts: Date.now(), data };
    return data;
  } catch (err) {
    return clinicCache.data || {};
  }
}
app.use(async (req, res, next) => {
  res.locals.clinic = await clinicSettings();
  next();
});

function requireLogin(req, res, next) {
  if (!req.session.user) return res.redirect('/login');
  next();
}

// Public auth routes
app.get('/login', (req, res) => {
  if (req.session.user) return res.redirect('/dashboard');
  res.render('login', { error: null, layout: false });
});

app.post('/login', async (req, res) => {
  try {
    const { data } = await apiFor(req).post('/auth/login', {
      username: req.body.username,
      password: req.body.password
    });
    req.session.user = data;
    res.redirect('/dashboard');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Login failed. Please try again.';
    res.status(401).render('login', { error: msg, layout: false });
  }
});

app.get('/logout', (req, res) => {
  req.session.destroy(() => res.redirect('/login'));
});

// Everything below requires login
app.use(['/dashboard', '/patients', '/doctors', '/treatments', '/appointments'], requireLogin);

// Master data is admin-only; staff keep Patients, Doctors and Appointments
app.use(['/treatments', '/masters', '/users'], requireAdmin);

const api = axios.create({ baseURL: FLASK_API, timeout: 5000, headers: { 'X-API-Key': process.env.FLASK_API_KEY || 'dev-key' } });

// Per-request client that also identifies the actor for the backend audit trail
function apiFor(req) {
  const username = (req.session && req.session.user && req.session.user.username) || 'anonymous';
  return axios.create({ baseURL: FLASK_API, timeout: 5000, headers: { 'X-API-Key': process.env.FLASK_API_KEY || 'dev-key', 'X-User': username } });
}

app.get('/', (req, res) => res.redirect('/dashboard'));

app.get('/dashboard', async (req, res) => {
  try {
    const [patients, doctors, treatments, appointments, bills, labOrders] = await Promise.all([
      api.get('/patients').catch(() => ({ data: [] })),
      api.get('/doctors').catch(() => ({ data: [] })),
      api.get('/treatments').catch(() => ({ data: [] })),
      api.get('/appointments').catch(() => ({ data: [] })),
      api.get('/bills').catch(() => ({ data: [] })),
      api.get('/lab-orders').catch(() => ({ data: [] }))
    ]);
    res.render('dashboard', {
      patients: patients.data,
      doctors: doctors.data,
      treatments: treatments.data,
      appointments: appointments.data,
      bills: bills.data,
      labOrders: labOrders.data
    });
  } catch (err) {
    res.render('dashboard', { patients: [], doctors: [], treatments: [], appointments: [], bills: [], labOrders: [] });
  }
});

app.get('/patients', async (req, res) => {
  try {
    const { data } = await api.get('/patients');
    res.render('patients', { patients: data });
  } catch (err) {
    res.render('patients', { patients: [] });
  }
});

app.get('/patients/new', async (req, res) => {
  const [genders, blood_groups] = await Promise.all([lookupValues('gender'), lookupValues('blood_group')]);
  res.render('patient_form', { patient: null, genders, blood_groups });
});
app.get('/patients/:id/edit', async (req, res) => {
  try {
    const { data } = await api.get(`/patients/${req.params.id}`);
    const [genders, blood_groups] = await Promise.all([lookupValues('gender'), lookupValues('blood_group')]);
    res.render('patient_form', { patient: data, genders, blood_groups });
  } catch (err) {
    res.redirect('/patients');
  }
});

app.post('/patients', async (req, res) => {
  try {
    await apiFor(req).post('/patients', req.body);
    req.session.toast = 'Patient added';
    res.redirect('/patients');
  } catch (err) {
    res.status(500).send('Error creating patient');
  }
});

app.post('/patients/:id', async (req, res) => {
  try {
    await apiFor(req).put(`/patients/${req.params.id}`, req.body);
    res.redirect('/patients');
  } catch (err) {
    res.status(500).send('Error updating patient');
  }
});

app.post('/patients/:id/delete', async (req, res) => {
  try {
    await apiFor(req).delete(`/patients/${req.params.id}`);
    res.redirect('/patients');
  } catch (err) {
    res.status(500).send('Error deleting patient');
  }
});

app.get('/doctors', async (req, res) => {
  try {
    const { data } = await api.get('/doctors');
    res.render('doctors', { doctors: data });
  } catch (err) {
    res.render('doctors', { doctors: [] });
  }
});

app.get('/doctors/new', async (req, res) => {
  const specializations = await lookupValues('specialization');
  res.render('doctor_form', { doctor: null, specializations });
});
app.get('/doctors/:id/edit', async (req, res) => {
  try {
    const { data } = await api.get(`/doctors/${req.params.id}`);
    const specializations = await lookupValues('specialization');
    res.render('doctor_form', { doctor: data, specializations });
  } catch (err) {
    res.redirect('/doctors');
  }
});

app.post('/doctors', async (req, res) => {
  try {
    await apiFor(req).post('/doctors', req.body);
    req.session.toast = 'Doctor added';
    res.redirect('/doctors');
  } catch (err) {
    res.status(500).send('Error creating doctor');
  }
});

app.post('/doctors/:id', async (req, res) => {
  try {
    await apiFor(req).put(`/doctors/${req.params.id}`, req.body);
    res.redirect('/doctors');
  } catch (err) {
    res.status(500).send('Error updating doctor');
  }
});

app.post('/doctors/:id/delete', async (req, res) => {
  try {
    await apiFor(req).delete(`/doctors/${req.params.id}`);
    res.redirect('/doctors');
  } catch (err) {
    res.status(500).send('Error deleting doctor');
  }
});

app.get('/treatments', async (req, res) => {
  try {
    const { data } = await api.get('/treatments');
    res.render('treatments', { treatments: data });
  } catch (err) {
    res.render('treatments', { treatments: [] });
  }
});

app.get('/treatments/new', async (req, res) => {
  const categories = await lookupValues('treatment_category');
  res.render('treatment_form', { treatment: null, categories });
});
app.get('/treatments/:id/edit', async (req, res) => {
  try {
    const { data } = await api.get(`/treatments/${req.params.id}`);
    const categories = await lookupValues('treatment_category');
    res.render('treatment_form', { treatment: data, categories });
  } catch (err) {
    res.redirect('/treatments');
  }
});

app.post('/treatments', async (req, res) => {
  try {
    await apiFor(req).post('/treatments', req.body);
    req.session.toast = 'Treatment added';
    res.redirect('/treatments');
  } catch (err) {
    res.status(500).send('Error creating treatment');
  }
});

app.post('/treatments/:id', async (req, res) => {
  try {
    await apiFor(req).put(`/treatments/${req.params.id}`, req.body);
    res.redirect('/treatments');
  } catch (err) {
    res.status(500).send('Error updating treatment');
  }
});

app.post('/treatments/:id/delete', async (req, res) => {
  try {
    await apiFor(req).delete(`/treatments/${req.params.id}`);
    res.redirect('/treatments');
  } catch (err) {
    res.status(500).send('Error deleting treatment');
  }
});

app.get('/appointments', async (req, res) => {
  try {
    const [appointments, patients, doctors, treatments] = await Promise.all([
      api.get('/appointments').catch(() => ({ data: [] })),
      api.get('/patients').catch(() => ({ data: [] })),
      api.get('/doctors').catch(() => ({ data: [] })),
      api.get('/treatments').catch(() => ({ data: [] }))
    ]);
    res.render('appointments', {
      appointments: appointments.data,
      patients: patients.data,
      doctors: doctors.data,
      treatments: treatments.data
    });
  } catch (err) {
    res.render('appointments', { appointments: [], patients: [], doctors: [], treatments: [] });
  }
});

app.get('/appointments/new', async (req, res) => {
  try {
    const [patients, doctors, treatments, statuses] = await Promise.all([
      api.get('/patients').catch(() => ({ data: [] })),
      api.get('/doctors').catch(() => ({ data: [] })),
      api.get('/treatments').catch(() => ({ data: [] })),
      lookupValues('appointment_status')
    ]);
    res.render('appointment_form', { appointment: null, patients: patients.data, doctors: doctors.data, treatments: treatments.data, statuses });
  } catch (err) {
    res.render('appointment_form', { appointment: null, patients: [], doctors: [], treatments: [], statuses: [] });
  }
});

app.get('/appointments/:id/edit', async (req, res) => {
  try {
    const [appointment, patients, doctors, treatments, statuses] = await Promise.all([
      api.get(`/appointments/${req.params.id}`),
      api.get('/patients').catch(() => ({ data: [] })),
      api.get('/doctors').catch(() => ({ data: [] })),
      api.get('/treatments').catch(() => ({ data: [] })),
      lookupValues('appointment_status')
    ]);
    res.render('appointment_form', { appointment: appointment.data, patients: patients.data, doctors: doctors.data, treatments: treatments.data, statuses });
  } catch (err) {
    res.redirect('/appointments');
  }
});

app.post('/appointments', async (req, res) => {
  try {
    await apiFor(req).post('/appointments', req.body);
    req.session.toast = 'Appointment booked';
    res.redirect('/appointments');
  } catch (err) {
    res.status(500).send('Error creating appointment');
  }
});

app.post('/appointments/:id', async (req, res) => {
  try {
    await apiFor(req).put(`/appointments/${req.params.id}`, req.body);
    res.redirect('/appointments');
  } catch (err) {
    res.status(500).send('Error updating appointment');
  }
});

app.post('/appointments/:id/delete', async (req, res) => {
  try {
    await apiFor(req).delete(`/appointments/${req.params.id}`);
    res.redirect('/appointments');
  } catch (err) {
    res.status(500).send('Error deleting appointment');
  }
});

// Fetch active values of a master-data (lookup) type from the Flask API
async function lookupValues(type) {
  try {
    const { data } = await api.get('/lookups', { params: { type } });
    return data.filter(l => l.is_active).map(l => l.value);
  } catch (err) {
    return [];
  }
}

function requireAdmin(req, res, next) {
  if (!req.session.user) return res.redirect('/login');
  if (req.session.user.role !== 'admin') return res.status(403).send('Admins only');
  next();
}

// URL slug -> lookup type for dedicated master forms.
// Display metadata (label, icon, description) comes from the /api/lookup-types table.
const MASTER_SECTION_TYPES = {
  specializations: 'specialization',
  categories: 'treatment_category',
  statuses: 'appointment_status'
};

async function lookupTypes() {
  try {
    const { data } = await api.get('/lookup-types');
    return data;
  } catch (err) {
    return [];
  }
}

function sectionKeyFor(lookupType) {
  return Object.keys(MASTER_SECTION_TYPES).find(k => MASTER_SECTION_TYPES[k] === lookupType);
}

app.get('/masters', requireAdmin, async (req, res) => {
  try {
    const [{ data: lookups }, types] = await Promise.all([api.get('/lookups'), lookupTypes()]);
    const groups = {};
    lookups.forEach(l => { (groups[l.type] = groups[l.type] || []).push(l); });
    renderMasters(res, groups, types, null);
  } catch (err) {
    renderMasters(res, {}, [], 'Could not load master data');
  }
});

function renderMasters(res, groups, types, error) {
  const sections = types
    .filter(t => t.has_form && sectionKeyFor(t.type))
    .map(t => ({ key: sectionKeyFor(t.type), ...t }));
  const hubTypes = types.filter(t => !t.has_form);
  res.render('masters', { groups, sections, hubTypes, error });
}

// Dedicated form for one master-data type: /masters/specializations, /masters/categories, /masters/statuses
app.get('/masters/:section', requireAdmin, async (req, res, next) => {
  const lookupType = MASTER_SECTION_TYPES[req.params.section];
  if (!lookupType) return next();
  const section = await lookupSectionMeta(req.params.section, lookupType);
  try {
    const { data } = await api.get('/lookups', { params: { type: lookupType } });
    res.render('master_type', { key: req.params.section, section, values: data, error: null });
  } catch (err) {
    res.render('master_type', { key: req.params.section, section, values: [], error: 'Could not load values' });
  }
});

async function lookupSectionMeta(key, lookupType) {
  const types = await lookupTypes();
  return types.find(t => t.type === lookupType)
    || { type: lookupType, label: key, icon: 'bi-tags', description: '', placeholder: '' };
}

app.post('/masters/:section', requireAdmin, async (req, res, next) => {
  const lookupType = MASTER_SECTION_TYPES[req.params.section];
  if (!lookupType) return next();
  try {
    await apiFor(req).post('/lookups', { type: lookupType, value: req.body.value });
    res.redirect(`/masters/${req.params.section}`);
  } catch (err) {
    const { data } = await api.get('/lookups', { params: { type: lookupType } }).catch(() => ({ data: [] }));
    const section = await lookupSectionMeta(req.params.section, lookupType);
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error adding value';
    res.status(400).render('master_type', { key: req.params.section, section, values: data, error: msg });
  }
});

app.post('/masters', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).post('/lookups', { type: req.body.type, value: req.body.value });
    res.redirect('/masters');
  } catch (err) {
    res.status(500).send('Error adding value');
  }
});

app.post('/masters/:id/toggle', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get(`/lookups/${req.params.id}`);
    await apiFor(req).put(`/lookups/${req.params.id}`, { is_active: !data.is_active });
    res.redirect(req.body.returnTo || '/masters');
  } catch (err) {
    res.status(500).send('Error updating value');
  }
});

app.post('/masters/:id/delete', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).delete(`/lookups/${req.params.id}`);
    res.redirect(req.body.returnTo || '/masters');
  } catch (err) {
    res.status(500).send('Error deleting value');
  }
});

// User management (admin only)
app.get('/users', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get('/users');
    res.render('users', { users: data, error: req.query.error || null });
  } catch (err) {
    res.render('users', { users: [], error: 'Could not load users' });
  }
});

app.get('/users/new', requireAdmin, async (req, res) => {
  const roles = await lookupValues('user_role');
  res.render('user_form', { targetUser: null, roles, error: null });
});

app.get('/users/:id/edit', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get(`/users/${req.params.id}`);
    const roles = await lookupValues('user_role');
    res.render('user_form', { targetUser: data, roles, error: null });
  } catch (err) {
    res.redirect('/users');
  }
});

app.post('/users', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).post('/auth/register', req.body);
    req.session.toast = 'User created';
    res.redirect('/users');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Error creating user';
    const roles = await lookupValues('user_role');
    res.status(400).render('user_form', { targetUser: null, roles, error: msg });
  }
});

app.post('/users/:id', requireAdmin, async (req, res) => {
  try {
    const payload = { username: req.body.username, role: req.body.role };
    if (req.body.password) payload.password = req.body.password;
    const { data } = await apiFor(req).put(`/users/${req.params.id}`, payload);
    if (req.session.user && req.session.user.id === data.id) {
      req.session.user = { ...req.session.user, username: data.username, role: data.role };
    }
    res.redirect('/users');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Error updating user';
    const roles = await lookupValues('user_role');
    res.status(400).render('user_form', {
      targetUser: { id: req.params.id, username: req.body.username, role: req.body.role },
      roles, error: msg
    });
  }
});

app.post('/users/:id/delete', requireAdmin, async (req, res) => {
  if (req.session.user && String(req.session.user.id) === String(req.params.id)) {
    return res.redirect('/users?error=' + encodeURIComponent('You cannot delete your own account'));
  }
  try {
    await apiFor(req).delete(`/users/${req.params.id}`);
    res.redirect('/users');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Error deleting user';
    res.redirect('/users?error=' + encodeURIComponent(msg));
  }
});

// Billing (staff + admin)
app.get('/bills', requireLogin, async (req, res) => {
  try {
    const [{ data: bills }, { data: appointments }] = await Promise.all([
      api.get('/bills'),
      api.get('/appointments').catch(() => ({ data: [] }))
    ]);
    const billedIds = new Set(bills.map(b => b.appointment_id));
    res.render('bills', {
      bills,
      unbilled: appointments.filter(a => !billedIds.has(a.id)),
      error: req.query.error || null
    });
  } catch (err) {
    res.render('bills', { bills: [], unbilled: [], error: 'Could not load bills' });
  }
});

app.post('/bills/generate', requireLogin, async (req, res) => {
  try {
    const { data } = await apiFor(req).post('/bills', { appointment_id: req.body.appointment_id });
    req.session.toast = 'Bill ' + data.bill_no + ' generated';
    res.redirect(`/bills/${data.id}`);
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Error generating bill';
    res.redirect('/bills?error=' + encodeURIComponent(msg));
  }
});

app.get('/bills/:id', requireLogin, async (req, res) => {
  try {
    const { data } = await api.get(`/bills/${req.params.id}`);
    const methods = await lookupValues('payment_method');
    res.render('invoice', { bill: data, methods, error: null });
  } catch (err) {
    res.redirect('/bills');
  }
});

app.post('/bills/:id/pay', requireLogin, async (req, res) => {
  try {
    await apiFor(req).post(`/bills/${req.params.id}/payments`, req.body);
    req.session.toast = 'Payment recorded';
    res.redirect(`/bills/${req.params.id}`);
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Error recording payment';
    try {
      const { data } = await api.get(`/bills/${req.params.id}`);
      const methods = await lookupValues('payment_method');
      res.status(400).render('invoice', { bill: data, methods, error: msg });
    } catch (e) {
      res.redirect('/bills');
    }
  }
});

// Reports (admin only). Defaults to the current day when no range is given.
function dayStr(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function todayStr() {
  return dayStr(new Date());
}
app.get('/reports', requireAdmin, async (req, res) => {
  const from = req.query.from || todayStr();
  const to = req.query.to || todayStr();
  const params = { from, to };
  const t = new Date();
  const presets = {
    today: todayStr(),
    week: dayStr(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 6)),
    month: dayStr(new Date(t.getFullYear(), t.getMonth(), 1))
  };
  try {
    const [revenue, appts, bills] = await Promise.all([
      api.get('/reports/revenue', { params }).catch(() => ({ data: null })),
      api.get('/reports/appointments', { params }).catch(() => ({ data: null })),
      api.get('/bills').catch(() => ({ data: [] }))
    ]);
    const bfrom = new Date(from), bto = new Date(to + 'T23:59:59');
    const outstanding = bills.data
      .filter(b => b.balance > 0 && (!b.created_at || (new Date(b.created_at) >= bfrom && new Date(b.created_at) <= bto)))
      .sort((a, b) => b.balance - a.balance)
      .slice(0, 10);
    res.render('reports', {
      revenue: revenue.data, appts: appts.data,
      outstanding, presets, from, to
    });
  } catch (err) {
    res.render('reports', { revenue: null, appts: null, outstanding: [], presets, from, to });
  }
});

app.get('/reports/:name.csv', requireAdmin, async (req, res, next) => {
  if (!['revenue', 'appointments'].includes(req.params.name)) return next();
  try {
    const r = await apiFor(req).get(`/reports/${req.params.name}.csv`,
      { params: req.query, responseType: 'arraybuffer' });
    res.set('Content-Type', 'text/csv');
    res.set('Content-Disposition', `attachment; filename=${req.params.name}.csv`);
    res.send(Buffer.from(r.data));
  } catch (err) {
    res.status(500).send('Error exporting report');
  }
});

// Audit trail (admin only)
app.get('/audit', requireAdmin, async (req, res) => {
  const params = { limit: 200 };
  if (req.query.entity) params.entity = req.query.entity;
  try {
    const { data } = await api.get('/audit', { params });
    res.render('audit', { logs: data, entity: req.query.entity || '' });
  } catch (err) {
    res.render('audit', { logs: [], entity: '' });
  }
});

// Clinic settings (admin only)
app.get('/settings', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get('/settings');
    res.render('settings', { settings: data, saved: req.query.saved || null, restore_error: req.query.restore_error || null });
  } catch (err) {
    res.render('settings', { settings: {}, saved: null, restore_error: null });
  }
});

app.post('/settings', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).put('/settings', req.body);
    clinicCache.ts = 0;
    res.redirect('/settings?saved=1');
  } catch (err) {
    res.status(500).send('Error saving settings');
  }
});

// Clinical consult (staff + admin)
app.get('/appointments/:id/consult', requireLogin, async (req, res) => {
  try {
    const [{ data: appointment }, { data: prescriptions }] = await Promise.all([
      api.get(`/appointments/${req.params.id}`),
      api.get(`/appointments/${req.params.id}/prescriptions`).catch(() => ({ data: [] }))
    ]);
    res.render('consult', { appointment, prescriptions, error: req.query.error || null });
  } catch (err) {
    res.redirect('/appointments');
  }
});

app.post('/appointments/:id/consult', requireLogin, async (req, res) => {
  try {
    await apiFor(req).put(`/appointments/${req.params.id}`, req.body);
    req.session.toast = 'Clinical notes saved';
    res.redirect(`/appointments/${req.params.id}/consult`);
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Error saving clinical notes';
    res.redirect(`/appointments/${req.params.id}/consult?error=` + encodeURIComponent(msg));
  }
});

app.post('/appointments/:id/prescriptions', requireLogin, async (req, res) => {
  try {
    await apiFor(req).post(`/appointments/${req.params.id}/prescriptions`, req.body);
    req.session.toast = 'Medicine added';
    res.redirect(`/appointments/${req.params.id}/consult`);
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error)
      || 'Error adding medicine';
    res.redirect(`/appointments/${req.params.id}/consult?error=` + encodeURIComponent(msg));
  }
});

app.post('/prescriptions/:id/delete', requireLogin, async (req, res) => {
  const backId = req.body.appointment_id;
  try {
    await apiFor(req).delete(`/prescriptions/${req.params.id}`);
  } catch (err) {}
  res.redirect(backId ? `/appointments/${backId}/consult` : '/appointments');
});

// Patient timeline: visits + bills together
app.get('/patients/:id/timeline', requireLogin, async (req, res) => {
  try {
    const [{ data: patient }, { data: appointments }, { data: bills }, { data: labOrders }] = await Promise.all([
      api.get(`/patients/${req.params.id}`),
      api.get('/appointments').catch(() => ({ data: [] })),
      api.get('/bills').catch(() => ({ data: [] })),
      api.get('/lab-orders').catch(() => ({ data: [] }))
    ]);
    res.render('patient_timeline', {
      patient,
      visits: appointments.filter(a => String(a.patient_id) === String(req.params.id)),
      bills: bills.filter(b => String(b.patient_id) === String(req.params.id)),
      labOrders: labOrders.filter(o => String(o.patient_id) === String(req.params.id))
    });
  } catch (err) {
    res.redirect('/patients');
  }
});

// Global search
app.get('/search', requireLogin, async (req, res) => {
  const q = (req.query.q || '').trim();
  let results = { patients: [], doctors: [], treatments: [], bills: [] };
  if (q.length >= 2) {
    try {
      ({ data: results } = await api.get('/search', { params: { q } }));
    } catch (err) {}
  }
  res.render('search', { q, results });
});

// Calendar (server-rendered month grid)
app.get('/calendar', requireLogin, async (req, res) => {
  const m = /^(\d{4})-(\d{2})$/.test(req.query.month || '') ? req.query.month : todayStr().slice(0, 7);
  const [y, mo] = m.split('-').map(Number);
  const first = new Date(y, mo - 1, 1);
  const { data: appointments } = await api.get('/appointments').catch(() => ({ data: [] }));
  const byDay = {};
  appointments.forEach(a => {
    const d = (a.appointment_date || '').slice(0, 10);
    if (d.startsWith(m)) (byDay[d] = byDay[d] || []).push(a);
  });
  const weeks = [];
  let week = [];
  for (let i = 0; i < first.getDay(); i++) week.push({});
  const daysInMonth = new Date(y, mo, 0).getDate();
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${m}-${String(d).padStart(2, '0')}`;
    week.push({ date: key, num: d, items: byDay[key] || [], today: key === todayStr() });
    if (week.length === 7) { weeks.push(week); week = []; }
  }
  if (week.length) {
    while (week.length < 7) week.push({});
    weeks.push(week);
  }
  const selectedDay = req.query.day && req.query.day.startsWith(m) ? req.query.day : null;
  res.render('calendar', {
    weeks, month: m,
    prev: dayStr(new Date(y, mo - 2, 1)).slice(0, 7),
    next: dayStr(new Date(y, mo, 1)).slice(0, 7),
    monthLabel: first.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' }),
    selectedDay, dayItems: selectedDay ? (byDay[selectedDay] || []) : []
  });
});

// Follow-ups due (overdue + next 7 days, open visits)
app.get('/followups', requireLogin, async (req, res) => {
  const { data: appointments } = await api.get('/appointments').catch(() => ({ data: [] }));
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const horizon = new Date(now.getTime() + 7 * 864e5);
  const items = appointments
    .filter(a => a.follow_up_date && !['completed', 'cancelled'].includes(a.status))
    .map(a => ({ ...a, overdue: new Date(a.follow_up_date) < now }))
    .filter(a => new Date(a.follow_up_date) <= horizon)
    .sort((a, b) => new Date(a.follow_up_date) - new Date(b.follow_up_date));
  res.render('followups', { items });
});

// Expenses (admin only)
app.get('/expenses', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get('/expenses');
    res.render('expenses', {
      expenses: data,
      total: Math.round(data.reduce((s, e) => s + (e.amount || 0), 0)),
      error: req.query.error || null
    });
  } catch (err) {
    res.render('expenses', { expenses: [], total: 0, error: 'Could not load expenses' });
  }
});

app.post('/expenses', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).post('/expenses', req.body);
    req.session.toast = 'Expense recorded';
  } catch (err) {
    req.session.toast = null;
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error saving expense';
    return res.redirect('/expenses?error=' + encodeURIComponent(msg));
  }
  res.redirect('/expenses');
});

app.post('/expenses/:id/delete', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).delete(`/expenses/${req.params.id}`);
    req.session.toast = 'Expense deleted';
  } catch (err) {}
  res.redirect('/expenses');
});

// Bill discount / void (admin only)
app.post('/bills/:id/discount', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).post(`/bills/${req.params.id}/discount`, req.body);
    req.session.toast = 'Discount applied';
    res.redirect(`/bills/${req.params.id}`);
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error applying discount';
    try {
      const { data } = await api.get(`/bills/${req.params.id}`);
      const methods = await lookupValues('payment_method');
      res.status(400).render('invoice', { bill: data, methods, error: msg });
    } catch (e) {
      res.redirect('/bills');
    }
  }
});

app.post('/bills/:id/void', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).post(`/bills/${req.params.id}/void`);
    req.session.toast = 'Bill voided';
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error voiding bill';
    return res.redirect(`/bills/${req.params.id}`);
  }
  res.redirect('/bills');
});

// Payment receipt (printable)
app.get('/bills/:billId/receipts/:payId', requireLogin, async (req, res) => {
  try {
    const { data: bill } = await api.get(`/bills/${req.params.billId}`);
    const payment = (bill.payments || []).find(p => String(p.id) === String(req.params.payId));
    if (!payment) return res.redirect(`/bills/${req.params.billId}`);
    res.render('receipt', { bill, payment });
  } catch (err) {
    res.redirect('/bills');
  }
});

// Active sessions (admin only)
function currentSid(req) {
  const raw = req.headers.cookie || '';
  const m = raw.match(/connect\.sid=s(?:%3A|:)([^.]+)\./);
  return m ? decodeURIComponent(m[1]) : null;
}

app.get('/sessions', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get('/sessions');
    res.render('sessions', { sessions: data, currentSid: currentSid(req) });
  } catch (err) {
    res.render('sessions', { sessions: [], currentSid: currentSid(req) });
  }
});

app.post('/sessions/:sid/revoke', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).delete(`/sessions/${req.params.sid}`);
    req.session.toast = 'Session revoked';
  } catch (err) {}
  res.redirect('/sessions');
});

// Change own password
app.get('/change-password', requireLogin, (req, res) => {
  res.render('change-password', {
    error: null, done: req.query.done || null,
    minLen: (res.locals.clinic && res.locals.clinic.password_min_length) || '8'
  });
});

app.post('/change-password', requireLogin, async (req, res) => {
  const minLen = (res.locals.clinic && res.locals.clinic.password_min_length) || '8';
  if (req.body.new_password !== req.body.confirm_password) {
    return res.status(400).render('change-password', { error: 'New passwords do not match', done: null, minLen });
  }
  try {
    await apiFor(req).put(`/users/${req.session.user.id}/password`, {
      current_password: req.body.current_password,
      new_password: req.body.new_password
    });
    req.session.toast = 'Password changed';
    res.redirect('/dashboard');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error changing password';
    res.status(400).render('change-password', { error: msg, done: null, minLen });
  }
});

// Help
app.get('/help', requireLogin, (req, res) => res.render('help'));

// Backup download + restore upload (admin only)
app.get('/settings/backup', requireAdmin, async (req, res) => {
  try {
    const r = await apiFor(req).get('/backup', { responseType: 'arraybuffer' });
    res.set('Content-Type', 'application/sql');
    res.set('Content-Disposition', r.headers['content-disposition'] || 'attachment; filename=clinic-backup.sql');
    res.send(Buffer.from(r.data));
  } catch (err) {
    res.redirect('/settings?restore_error=' + encodeURIComponent('Backup failed'));
  }
});

const multer = require('multer');
const _upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 50 * 1024 * 1024 } });

app.post('/settings/restore', requireAdmin, _upload.single('backup'), async (req, res) => {
  if (!req.body || req.body._csrf !== req.session.csrf) {
    return res.status(403).send('Invalid CSRF token');
  }
  try {
    if (!req.file) throw new Error('nofile');
    const fd = new FormData();
    fd.append('backup', new Blob([req.file.buffer]), req.file.originalname);
    await apiFor(req).post('/restore', fd);
    req.session.toast = 'Backup restored successfully';
    res.redirect('/settings');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Restore failed';
    res.redirect('/settings?restore_error=' + encodeURIComponent(msg));
  }
});

// Lab test catalog (admin only)
app.get('/lab-tests', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get('/lab-tests');
    res.render('labtests', { tests: data, error: req.query.error || null });
  } catch (err) {
    res.render('labtests', { tests: [], error: 'Could not load lab tests' });
  }
});

app.get('/lab-tests/new', requireAdmin, (req, res) => {
  res.render('labtest_form', { test: null, error: null });
});

app.get('/lab-tests/:id/edit', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get(`/lab-tests/${req.params.id}`);
    res.render('labtest_form', { test: data, error: null });
  } catch (err) {
    res.redirect('/lab-tests');
  }
});

app.post('/lab-tests', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).post('/lab-tests', req.body);
    req.session.toast = 'Lab test added';
    res.redirect('/lab-tests');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error saving test';
    res.status(400).render('labtest_form', { test: null, error: msg });
  }
});

app.post('/lab-tests/:id', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).put(`/lab-tests/${req.params.id}`, req.body);
    req.session.toast = 'Lab test updated';
    res.redirect('/lab-tests');
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error saving test';
    res.status(400).render('labtest_form', { test: { id: req.params.id, ...req.body }, error: msg });
  }
});

app.post('/lab-tests/:id/toggle', requireAdmin, async (req, res) => {
  try {
    const { data } = await api.get(`/lab-tests/${req.params.id}`);
    await apiFor(req).put(`/lab-tests/${req.params.id}`, { is_active: !data.is_active });
  } catch (err) {}
  res.redirect('/lab-tests');
});

app.post('/lab-tests/:id/delete', requireAdmin, async (req, res) => {
  try {
    await apiFor(req).delete(`/lab-tests/${req.params.id}`);
    req.session.toast = 'Lab test deleted';
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error deleting test';
    return res.redirect('/lab-tests?error=' + encodeURIComponent(msg));
  }
  res.redirect('/lab-tests');
});

// Lab orders (staff + admin)
const LAB_FLOW = {
  ordered: ['collected', 'cancelled'],
  collected: ['in_progress', 'cancelled'],
  in_progress: ['completed', 'cancelled'],
  completed: [], cancelled: []
};

app.get('/lab-orders', requireLogin, async (req, res) => {
  try {
    const params = {};
    if (req.query.status) params.status = req.query.status;
    const { data } = await api.get('/lab-orders', { params });
    res.render('laborders', { orders: data, status: req.query.status || '', error: req.query.error || null });
  } catch (err) {
    res.render('laborders', { orders: [], status: '', error: 'Could not load lab orders' });
  }
});

app.get('/lab-orders/new', requireLogin, async (req, res) => {
  try {
    const [patients, tests, appointments] = await Promise.all([
      api.get('/patients').catch(() => ({ data: [] })),
      api.get('/lab-tests', { params: { active: '1' } }).catch(() => ({ data: [] })),
      api.get('/appointments').catch(() => ({ data: [] }))
    ]);
    res.render('laborder_form', {
      patients: patients.data, tests: tests.data, appointments: appointments.data,
      selectedPatientId: String(req.query.patient_id || ''), error: null
    });
  } catch (err) {
    res.render('laborder_form', { patients: [], tests: [], appointments: [], selectedPatientId: '', error: null });
  }
});

app.post('/lab-orders', requireLogin, async (req, res) => {
  try {
    const test_ids = [].concat(req.body.test_ids || []).map(Number).filter(Boolean);
    const { data } = await apiFor(req).post('/lab-orders', {
      patient_id: req.body.patient_id, appointment_id: req.body.appointment_id || null,
      priority: req.body.priority, test_ids
    });
    req.session.toast = 'Lab order ' + data.order_no + ' created';
    res.redirect(`/lab-orders/${data.id}`);
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error creating order';
    try {
      const [patients, tests] = await Promise.all([
        api.get('/patients').catch(() => ({ data: [] })),
        api.get('/lab-tests', { params: { active: '1' } }).catch(() => ({ data: [] }))
      ]);
      res.status(400).render('laborder_form', { patients: patients.data, tests: tests.data, error: msg });
    } catch (e) {
      res.redirect('/lab-orders');
    }
  }
});

app.get('/lab-orders/:id', requireLogin, async (req, res) => {
  try {
    const { data } = await api.get(`/lab-orders/${req.params.id}`);
    res.render('laborder_detail', { order: data, nextStatuses: LAB_FLOW[data.status] || [], error: req.query.error || null });
  } catch (err) {
    res.redirect('/lab-orders');
  }
});

app.post('/lab-orders/:id/status', requireLogin, async (req, res) => {
  try {
    await apiFor(req).post(`/lab-orders/${req.params.id}/status`, { status: req.body.status });
    req.session.toast = 'Order ' + req.body.status;
    res.redirect(`/lab-orders/${req.params.id}`);
  } catch (err) {
    const msg = (err.response && err.response.data && err.response.data.error) || 'Error updating status';
    res.redirect(`/lab-orders/${req.params.id}`);
  }
});

app.post('/lab-orders/:id/delete', requireLogin, async (req, res) => {
  try {
    await apiFor(req).delete(`/lab-orders/${req.params.id}`);
    req.session.toast = 'Lab order deleted';
  } catch (err) {}
  res.redirect('/lab-orders');
});

app.post('/order-items/:id', requireLogin, async (req, res) => {
  try {
    const { data } = await apiFor(req).put(`/order-items/${req.params.id}`, req.body);
    req.session.toast = 'Result saved';
    res.redirect(`/lab-orders/${data.order_id}`);
  } catch (err) {
    res.redirect('/lab-orders');
  }
});

app.listen(PORT, () => console.log(`Frontend running on http://localhost:${PORT}`));