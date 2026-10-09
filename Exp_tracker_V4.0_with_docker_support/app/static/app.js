// Expense Tracker — theme + form helpers
(function () {
  // Data submenu: tap-to-toggle for touch (first tap opens, second follows).
  // Hover/focus-within already cover mouse + keyboard via CSS.
  document.addEventListener('click', function (e) {
    var toggle = e.target.closest ? e.target.closest('.drop > a') : null;
    var openDrop = document.querySelector('.drop.open');
    if (toggle) {
      var drop = toggle.parentElement;
      if (!drop.classList.contains('open')) {
        e.preventDefault();
        if (openDrop) {
          openDrop.classList.remove('open');
          var prev = openDrop.querySelector(':scope > a');
          if (prev) prev.setAttribute('aria-expanded', 'false');
        }
        drop.classList.add('open');
        toggle.setAttribute('aria-expanded', 'true');
      }
      return;
    }
    if (openDrop && !(e.target.closest && e.target.closest('.drop'))) {
      openDrop.classList.remove('open');
      var cur = openDrop.querySelector(':scope > a');
      if (cur) cur.setAttribute('aria-expanded', 'false');
    }
  });
  var root = document.documentElement;

  // Theme: respect saved choice, else prefers-color-scheme
  try {
    var saved = localStorage.getItem('exp-theme');
    if (saved) root.setAttribute('data-theme', saved);
    else if (window.matchMedia('(prefers-color-scheme: dark)').matches)
      root.setAttribute('data-theme', 'dark');
  } catch (e) {}

  function syncBtn() {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.textContent = root.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙';
    btn.title = root.getAttribute('data-theme') === 'dark'
      ? 'Switch to light mode' : 'Switch to dark mode';
  }
  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'theme-toggle') {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('exp-theme', next); } catch (err) {}
      syncBtn();
      if (window.__redrawCharts) window.__redrawCharts();
    }
    var flash = e.target && e.target.closest ? e.target.closest('.flash') : null;
    if (flash) flash.remove();
  });
  syncBtn();

  // Auto-switch category dropdown based on income/expense radio
  window.bindTypeCategory = function (formId) {
    var form = document.getElementById(formId);
    if (!form) return;
    var radios = form.querySelectorAll('input[name="type"]');
    var select = form.querySelector('select[name="category_id"]');
    if (!radios.length || !select) return;
    function apply() {
      var checked = form.querySelector('input[name="type"]:checked');
      if (!checked) return;
      var t = checked.value;
      Array.prototype.forEach.call(select.options, function (o) {
        o.hidden = o.dataset.type && o.dataset.type !== t;
      });
      var sel = select.selectedOptions && select.selectedOptions[0];
      if (sel && sel.hidden) {
        var visible = Array.prototype.filter.call(select.options, function (o) {
          return !o.hidden && o.value;
        });
        if (visible.length) select.value = visible[0].value;
      }
    }
    radios.forEach(function (r) { r.addEventListener('change', apply); });
    apply();
  };
  window.bindTypeCategory('add-form');
  window.bindTypeCategory('edit-form');

  // Indian-style live formatting for amount inputs: 100000 -> 1,00,000
  function groupIndian(intStr) {
    if (intStr.length <= 3) return intStr;
    var last3 = intStr.slice(-3);
    var rest = intStr.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',');
    return rest + ',' + last3;
  }
  function formatINRInput(raw) {
    var clean = raw.replace(/[^0-9.]/g, '');
    var parts = clean.split('.');
    var intPart = parts[0].replace(/^0+(?=\d)/, '');
    var out = groupIndian(intPart);
    if (parts.length > 1) out += '.' + parts.slice(1).join('').slice(0, 2);
    return out;
  }
  document.querySelectorAll('input.amount-inr').forEach(function (el) {
    if (el.value && /^[0-9.]+$/.test(el.value)) el.value = formatINRInput(el.value);
    el.addEventListener('input', function () {
      el.value = formatINRInput(el.value);
    });
    el.addEventListener('blur', function () {
      if (/^\d+$/.test(el.value.replace(/,/g, ''))) el.value = formatINRInput(el.value + '.00');
    });
    var form = el.closest('form');
    if (form && !form.dataset.inrBound) {
      form.dataset.inrBound = '1';
      form.addEventListener('submit', function () {
        form.querySelectorAll('input.amount-inr').forEach(function (i) {
          i.value = i.value.replace(/,/g, '');
        });
      });
    }
  });

  // Auto-dismiss toasts
  setTimeout(function () {
    document.querySelectorAll('.flash').forEach(function (f) {
      f.style.opacity = '0'; f.style.transition = 'opacity .4s';
      setTimeout(function () { f.remove(); }, 400);
    });
  }, 5000);

  // ---- Client-side validation for transaction forms (fast feedback, no reload) ----
  function showFormError(form, msg) {
    var box = form.querySelector('.form-error');
    if (!box) { alert(msg); return; }
    box.textContent = msg;
    box.hidden = false;
  }
  function clearFormError(form) {
    var box = form.querySelector('.form-error');
    if (box) { box.hidden = true; box.textContent = ''; }
  }
  ['add-form', 'edit-form'].forEach(function (id) {
    var form = document.getElementById(id);
    if (!form) return;
    form.addEventListener('submit', function (e) {
      clearFormError(form);
      var amountEl = form.querySelector('input[name="amount"]');
      var dateEl = form.querySelector('input[name="date"]');
      var catEl = form.querySelector('select[name="category_id"]');
      var amount = parseFloat((amountEl && amountEl.value || '').replace(/,/g, ''));
      if (!amountEl || !amountEl.value.trim() || isNaN(amount) || amount <= 0) {
        e.preventDefault();
        return showFormError(form, 'Amount must be a positive number.');
      }
      if (dateEl && dateEl.value) {
        var today = new Date(); today.setHours(0, 0, 0, 0);
        var d = new Date(dateEl.value + 'T00:00:00');
        if (d > today) {
          e.preventDefault();
          return showFormError(form, 'Date cannot be in the future.');
        }
      }
      if (catEl && !catEl.value) {
        e.preventDefault();
        return showFormError(form, 'Please select a category.');
      }
      // Split lines: every filled line needs both fields; the remainder
      // stays on the main category, so lines must sum to LESS than the total.
      var lines = [];
      for (var n = 2; n <= 4; n++) {
        var c = form.querySelector('select[name="split_category_' + n + '"]');
        var a = form.querySelector('input[name="split_amount_' + n + '"]');
        if (!c && !a) continue;
        var cv = c && c.value, av = a && parseFloat((a.value || '').replace(/,/g, ''));
        if ((cv && (!a || !av || av <= 0)) || (!cv && a && a.value.trim())) {
          e.preventDefault();
          return showFormError(form, 'Each split line needs both a category and a positive amount.');
        }
        if (cv && av > 0) lines.push(av);
      }
      if (lines.length) {
        var total = Math.round(amount * 100);
        var sum = lines.reduce(function (s, v) { return s + Math.round(v * 100); }, 0);
        if (sum >= total) {
          e.preventDefault();
          return showFormError(form, 'Split amounts must be less than the main amount — the remainder stays on the main category.');
        }
      }
    });
  });

  // ---- Bulk selection on the transactions page ----
  var bulkForm = document.getElementById('bulk-form');
  if (bulkForm) {
    var hidden = document.getElementById('bulk-ids');
    var checkAll = document.getElementById('check-all');
    var actionSel = document.getElementById('bulkAction');
    var catWrap = document.getElementById('bulkCategoryWrap');
    var catSel = document.getElementById('bulkCategory');
    var applyBtn = document.getElementById('bulkApply');
    var hint = document.getElementById('bulkHint');
    function checked() {
      return Array.prototype.slice.call(document.querySelectorAll('input.bulk-check:checked'));
    }
    // Keep the row self-explanatory: the category box only matters for
    // "Change category", and the button names the actual action.
    function bulkSync() {
      var isDel = !actionSel || actionSel.value === 'delete';
      if (catWrap) catWrap.classList.toggle('dimmed', isDel);
      if (catSel) catSel.disabled = isDel;
      if (applyBtn) {
        applyBtn.textContent = isDel ? 'Delete selected' : 'Change category';
        applyBtn.classList.toggle('danger', isDel);
        applyBtn.classList.toggle('primary', !isDel);
      }
      var n = checked().length;
      if (hint) hint.textContent = n === 0
        ? 'Tick rows with the checkboxes above, then choose what to do with them.'
        : isDel ? n + ' selected — delete moves them to Trash (recoverable).'
        : n + ' selected — only rows whose type matches the new category will change.';
    }
    bulkForm.addEventListener('submit', function (e) {
      var ids = checked().map(function (el) { return el.value; });
      if (!ids.length) {
        e.preventDefault();
        alert('Select at least one transaction first.');
        return;
      }
      hidden.value = ids.join(',');
      if (actionSel && actionSel.value === 'category' && catSel && !catSel.value) {
        e.preventDefault();
        alert('Choose the new category first.');
        return;
      }
      if (actionSel && actionSel.value === 'delete') {
        if (!confirm('Delete ' + ids.length + ' selected transaction(s)? They go to Trash and can be restored.')) {
          e.preventDefault();
        }
      }
    });
    if (actionSel) actionSel.addEventListener('change', bulkSync);
    document.querySelectorAll('input.bulk-check').forEach(function (el) {
      el.addEventListener('change', bulkSync);
    });
    if (checkAll) {
      checkAll.addEventListener('change', function () {
        document.querySelectorAll('input.bulk-check').forEach(function (el) {
          el.checked = checkAll.checked;
        });
        bulkSync();
      });
    }
    bulkSync();
  }
  // ---- Idle-session countdown (mirrors the server's last_active timeout) ----
  // The server stamps last_active on every page load, so this per-page
  // countdown stays accurate; any navigation re-renders it fresh.
  // At 1 minute left a warning toast appears; at zero the page signs out
  // automatically (the server session is expired by then too).
  var idlePill = document.getElementById('idle-pill');
  if (idlePill) {
    var idleLeft = parseInt(idlePill.dataset.remaining, 10) || 0;
    var idleEl = document.getElementById('idle-left');
    var idleTimer = null;
    var expired = false, warned = false;
    function idleFmt(s) {
      s = Math.max(0, s);
      var m = Math.floor(s / 60), r = s % 60;
      return m + ':' + (r < 10 ? '0' : '') + r;
    }
    function idleWarn() {
      var wrap = document.querySelector('.toast-wrap');
      if (!wrap || document.getElementById('idle-warn')) return;
      var d = document.createElement('div');
      d.className = 'flash error';
      d.id = 'idle-warn';
      d.setAttribute('role', 'alert');
      d.title = 'Click to dismiss';
      var fi = document.createElement('span');
      fi.className = 'fi';
      fi.textContent = '!';
      var msg = document.createElement('span');
      msg.textContent = 'Signing out in 1 minute due to inactivity — move the mouse or press a key to stay signed in.';
      d.appendChild(fi);
      d.appendChild(msg);
      d.addEventListener('click', function () { d.remove(); });
      wrap.appendChild(d);
    }
    function idleTick() {
      if (idleEl) idleEl.textContent = idleFmt(idleLeft);
      idlePill.classList.toggle('warn', idleLeft <= 120 && idleLeft > 60);
      idlePill.classList.toggle('urgent', idleLeft <= 60 && idleLeft > 0);
      if (idleLeft === 60 && !warned) {
        warned = true;
        idleWarn();
      }
      if (idleLeft <= 0 && !expired) {
        expired = true;
        idlePill.classList.remove('warn', 'urgent');
        idlePill.classList.add('expired');
        if (idleEl) idleEl.textContent = 'expired';
        idlePill.title = 'Session expired due to inactivity — signing out…';
        if (idleTimer) clearInterval(idleTimer);
        // Give the user a beat to see the state, then sign out for real.
        // Safe: the countdown only reaches zero after a full window with no
        // activity, so the server session is expired too — and any activity
        // in the meantime already failed to revive it (ping 401s).
        setTimeout(function () {
          if (idlePill.dataset.login) window.location.href = idlePill.dataset.login;
        }, 3000);
        return;
      }
      idleLeft -= 1;
    }
    idlePill.addEventListener('click', function () {
      if (expired && idlePill.dataset.login) window.location.href = idlePill.dataset.login;
    });
    idleTick();
    idleTimer = setInterval(idleTick, 1000);
    // Keep-alive: real activity (mouse/keyboard/touch/scroll) pings the
    // server, which refreshes last_active; the pill resets from the reply.
    // Pings only fire on activity (never a blind timer) and never while the
    // tab is hidden, so an unattended session still expires on time.
    var idleActive = false, idleLastPing = 0;
    ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(function (ev) {
      document.addEventListener(ev, function () { idleActive = true; }, { passive: true });
    });
    setInterval(function () {
      if (expired || document.hidden || !idleActive) return;
      if (Date.now() - idleLastPing < 60000) return;
      if (!idlePill.dataset.ping) return;
      idleLastPing = Date.now();
      idleActive = false;
      fetch(idlePill.dataset.ping, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('ping'); return r.json(); })
        .then(function (d) {
          if (d && typeof d.remaining === 'number' && d.remaining > 0) {
            idleLeft = d.remaining;
            warned = false;
            var w = document.getElementById('idle-warn');
            if (w) w.remove();
            idleTick();
          }
        })
        .catch(function () { /* countdown keeps running to expiry */ });
    }, 30000);
  }
})();
