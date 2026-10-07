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
})();
