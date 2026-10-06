document.addEventListener('DOMContentLoaded', () => {
  // Multi-theme system: presets loaded from /config/themes.json,
  // selected id persisted in localStorage, applied as
  // data-bs-theme + data-accent on <html>
  let THEMES = [
    { id: 'ocean-light', name: 'Ocean Light', icon: 'bi-sun', bs: 'light', accent: 'blue' },
    { id: 'ocean-dark', name: 'Ocean Dark', icon: 'bi-moon-stars', bs: 'dark', accent: 'blue' }
  ];
  const themeMenus = document.querySelectorAll('.themeMenu');
  const currentThemeId = () => {
    try { return localStorage.getItem('clinic-theme') || 'ocean-light'; }
    catch (e) { return 'ocean-light'; }
  };
  function applyTheme(id) {
    const t = THEMES.find(x => x.id === id) || THEMES[0];
    document.documentElement.setAttribute('data-bs-theme', t.bs);
    document.documentElement.setAttribute('data-accent', t.accent);
    try {
      localStorage.setItem('clinic-theme', t.id);
      localStorage.setItem('clinic-bs', t.bs);
      localStorage.setItem('clinic-accent', t.accent);
    } catch (e) {}
    themeMenus.forEach(menu => {
      menu.innerHTML = THEMES.map(x =>
        `<li><a class="dropdown-item${x.id === t.id ? ' active' : ''}" href="#" data-theme="${x.id}">` +
        `<i class="bi ${x.icon} me-2"></i>${x.name}` +
        `${x.id === t.id ? '<i class="bi bi-check-lg ms-auto"></i>' : ''}</a></li>`
      ).join('');
    });
  }
  themeMenus.forEach(menu => {
    menu.addEventListener('click', (e) => {
      const item = e.target.closest('[data-theme]');
      if (!item) return;
      e.preventDefault();
      applyTheme(item.getAttribute('data-theme'));
    });
  });
  applyTheme(currentThemeId());
  fetch('/config/themes.json')
    .then(r => { if (!r.ok) throw new Error('themes config missing'); return r.json(); })
    .then(list => {
      if (Array.isArray(list) && list.length) {
        THEMES = list;
        applyTheme(currentThemeId());
      }
    })
    .catch(() => {});

  // Mobile sidebar drawer
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebarBackdrop = document.getElementById('sidebarBackdrop');
  if (sidebarToggle) {
    sidebarToggle.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
  }
  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  }
  document.querySelectorAll('.sidebar-link').forEach(link => {
    link.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  });

  // Auto-dismiss toast notifications
  setTimeout(() => {
    document.querySelectorAll('.toast-fixed').forEach(t => t.remove());
  }, 4200);

  // Highlight active nav link based on current path
  const currentPath = window.location.pathname;
  document.querySelectorAll('.sidebar-link[href], .navbar-nav .nav-link[href]').forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPath || (href !== '/dashboard' && currentPath.startsWith(href + '/'))) {
      link.classList.add('active');
    }
  });

  const tables = document.querySelectorAll('table');
  tables.forEach(table => {
    if (!table.id) return;
    const rows = table.querySelectorAll('tbody tr');
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'form-control table-search mb-3';
    searchInput.placeholder = 'Search...';
    table.parentElement.insertBefore(searchInput, table);
    searchInput.addEventListener('input', () => {
      const term = searchInput.value.toLowerCase();
      rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
      });
    });
  });

  // Client-side pagination for tables with data-paginate (default 10 rows,
  // page size selectable by the user). Works together with the search box.
  document.querySelectorAll('table[data-paginate]').forEach(table => {
    const tbody = table.querySelector('tbody');
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const searchInput = table.parentElement.querySelector('.table-search');
    const pager = document.createElement('div');
    pager.className = 'table-pager';
    const defaultSize = parseInt(table.getAttribute('data-page-size') || '10', 10);
    pager.innerHTML =
      '<span class="pager-info"></span>' +
      '<label>Rows per page: <select class="pager-size">' +
      [5, 10, 25, 50].map(n =>
        `<option value="${n}"${n === defaultSize ? ' selected' : ''}>${n}</option>`
      ).join('') +
      '</select></label>' +
      '<button type="button" class="pager-prev">&lsaquo; Prev</button>' +
      '<span class="pager-pages"></span>' +
      '<button type="button" class="pager-next">Next &rsaquo;</button>';
    const host = table.closest('.card-body') || table.parentElement;
    host.appendChild(pager);

    let page = 1;
    const sizeSel = pager.querySelector('.pager-size');
    const info = pager.querySelector('.pager-info');
    const pagesEl = pager.querySelector('.pager-pages');
    const prevBtn = pager.querySelector('.pager-prev');
    const nextBtn = pager.querySelector('.pager-next');
    const perPage = () => parseInt(sizeSel.value, 10);

    function render() {
      const term = (searchInput ? searchInput.value : '').toLowerCase();
      const filtered = rows.filter(r => r.textContent.toLowerCase().includes(term));
      const pages = Math.max(1, Math.ceil(filtered.length / perPage()));
      page = Math.min(Math.max(page, 1), pages);
      rows.forEach(r => { r.style.display = 'none'; });
      const start = (page - 1) * perPage();
      filtered.slice(start, start + perPage()).forEach(r => { r.style.display = ''; });
      const end = Math.min(start + perPage(), filtered.length);
      info.textContent = `Showing ${filtered.length ? start + 1 : 0}\u2013${end} of ${filtered.length}`;
      prevBtn.disabled = page <= 1;
      nextBtn.disabled = page >= pages;
      // Numbered buttons: window of up to 5 around current page
      let from = Math.max(1, Math.min(page - 2, pages - 4));
      let to = Math.min(pages, from + 4);
      from = Math.max(1, to - 4);
      pagesEl.innerHTML = '';
      for (let n = from; n <= to; n++) {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = n;
        if (n === page) b.classList.add('current');
        b.addEventListener('click', () => { page = n; render(); });
        pagesEl.appendChild(b);
      }
      pager.style.display = rows.length ? '' : 'none';
    }

    prevBtn.addEventListener('click', () => { page--; render(); });
    nextBtn.addEventListener('click', () => { page++; render(); });
    sizeSel.addEventListener('change', () => { page = 1; render(); });
    if (searchInput) {
      searchInput.addEventListener('input', () => { page = 1; render(); });
    }
    render();
  });

  const forms = document.querySelectorAll('form');
  forms.forEach(form => {
    form.addEventListener('submit', (e) => {
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
      }
    });
  });

  const deleteForms = document.querySelectorAll('form[action*="/delete"]');
  deleteForms.forEach(form => {
    form.addEventListener('submit', (e) => {
      if (!confirm('Are you sure you want to delete this item?')) {
        e.preventDefault();
      }
    });
  });

  const datetimeInputs = document.querySelectorAll('input[type="datetime-local"]');
  datetimeInputs.forEach(input => {
    if (!input.value) {
      const now = new Date();
      now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
      input.min = now.toISOString().slice(0, 16);
    }
  });
});

function formatDate(dateStr) {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleDateString();
}

function formatDateTime(dateStr) {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleString();
}