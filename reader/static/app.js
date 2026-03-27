/* Autonovel Reader - Frontend */

(() => {
  const content = document.getElementById('content');
  const sidebar = document.getElementById('sidebar');
  const themeToggle = document.getElementById('theme-toggle');
  const beadsContent = document.getElementById('beads-content');

  // --- Theme ---
  function initTheme() {
    const saved = localStorage.getItem('reader-theme');
    if (saved === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      themeToggle.textContent = '\u2600';
    }
  }

  themeToggle.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('reader-theme', next);
    themeToggle.textContent = next === 'dark' ? '\u2600' : '\u263D';
  });

  initTheme();

  // --- Navigation ---
  sidebar.addEventListener('click', (e) => {
    const link = e.target.closest('.nav-item[data-path]');
    if (!link) return;
    e.preventDefault();

    // Update active state
    sidebar.querySelectorAll('.nav-item.active').forEach((el) => {
      el.classList.remove('active');
    });
    link.classList.add('active');

    loadFile(link.dataset.path);
  });

  async function loadFile(path) {
    content.innerHTML = '<div class="loading">Loading...</div>';

    try {
      const resp = await fetch(`/file/${encodeURI(path)}`);
      if (!resp.ok) {
        content.innerHTML = `<div class="file-path">${escapeHtml(path)}</div><p>Error: ${resp.status} ${resp.statusText}</p>`;
        return;
      }
      const data = await resp.json();
      renderContent(data);
    } catch (err) {
      content.innerHTML = `<p>Failed to load: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderContent(data) {
    let html = `<div class="file-path">${escapeHtml(data.path)}</div>`;

    // Meta info
    const meta = [];
    if (data.words) meta.push(`${data.words.toLocaleString()} words`);
    if (data.type) meta.push(data.type);
    if (meta.length) {
      html += `<div class="file-meta">${meta.join(' &middot; ')}</div>`;
    }

    if (data.type === 'directory') {
      html += renderDirectory(data);
    } else if (data.html) {
      html += `<div class="md-content">${data.html}</div>`;
    } else if (data.formatted !== undefined) {
      html += `<div class="json-content">${syntaxHighlightJson(data.formatted)}</div>`;
    } else if (data.text !== undefined) {
      html += `<div class="text-content">${escapeHtml(data.text)}</div>`;
    }

    content.innerHTML = html;

    // Wire up directory file links
    content.querySelectorAll('a[data-file-path]').forEach((a) => {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        loadFile(a.dataset.filePath);
      });
    });
  }

  function renderDirectory(data) {
    let html = '';

    // Run summary card
    if (data.state) {
      const s = data.state;
      html += '<div class="run-summary">';
      html += '<h3>Run State</h3>';
      html += '<div class="run-summary-grid">';
      if (s.state)
        html += `<div class="run-stat"><div class="label">Status</div><div class="value"><span class="badge badge-${s.state}">${s.state}</span></div></div>`;
      if (s.total_words !== undefined)
        html += `<div class="run-stat"><div class="label">Words</div><div class="value">${Number(s.total_words).toLocaleString()}</div></div>`;
      if (s.slop_score !== undefined && s.slop_score !== null)
        html += `<div class="run-stat"><div class="label">Slop Score</div><div class="value">${s.slop_score}</div></div>`;
      if (s.chapters_drafted !== undefined)
        html += `<div class="run-stat"><div class="label">Chapters</div><div class="value">${s.chapters_drafted}</div></div>`;
      html += '</div></div>';
    }

    // Draft content
    if (data.draft_html) {
      html += `<div class="file-meta">${data.draft_file} &middot; ${data.draft_words.toLocaleString()} words</div>`;
      html += `<div class="md-content">${data.draft_html}</div>`;
    }

    // File listing
    if (data.files?.length) {
      html += '<h3>Files</h3>';
      html += '<ul class="file-list">';
      for (const f of data.files) {
        const size = formatBytes(f.size);
        html += `<li><a href="#" data-file-path="${escapeHtml(f.path)}">${escapeHtml(f.name)}</a><span class="file-size">${size}</span></li>`;
      }
      html += '</ul>';
    }

    return html;
  }

  // --- Beads ---
  async function loadBeads() {
    try {
      const resp = await fetch('/beads');
      const data = await resp.json();
      if (data.error) {
        beadsContent.innerHTML = `<span class="nav-item muted">${escapeHtml(data.error)}</span>`;
      } else if (data.output?.trim()) {
        const lines = data.output.trim().split('\n');
        let html = '<div class="beads-output">';
        for (const line of lines) {
          html += `<div class="bead-line">${escapeHtml(line)}</div>`;
        }
        html += '</div>';
        beadsContent.innerHTML = html;
      } else {
        beadsContent.innerHTML =
          '<span class="nav-item muted">no open beads</span>';
      }
    } catch (_) {
      beadsContent.innerHTML =
        '<span class="nav-item muted">failed to load</span>';
    }
  }

  loadBeads();

  // --- Utilities ---
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function syntaxHighlightJson(json) {
    return escapeHtml(json).replace(
      /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
      (match) => {
        let cls = 'json-number';
        if (/^"/.test(match)) {
          cls = /:$/.test(match) ? 'json-key' : 'json-string';
        } else if (/true|false/.test(match)) {
          cls = 'json-bool';
        } else if (/null/.test(match)) {
          cls = 'json-null';
        }
        return `<span class="${cls}">${match}</span>`;
      },
    );
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
})();
