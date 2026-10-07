// Expense Tracker — theme + form helpers
(function () {
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
    function checked() {
      return Array.prototype.slice.call(document.querySelectorAll('input.bulk-check:checked'));
    }
    bulkForm.addEventListener('submit', function (e) {
      var ids = checked().map(function (el) { return el.value; });
      if (!ids.length) {
        e.preventDefault();
        alert('Select at least one transaction first.');
        return;
      }
      hidden.value = ids.join(',');
    });
    if (checkAll) {
      checkAll.addEventListener('change', function () {
        document.querySelectorAll('input.bulk-check').forEach(function (el) {
          el.checked = checkAll.checked;
        });
      });
    }
  }
})();
