/* Autonovel Reader - Frontend */

(() => {
  const content = document.getElementById('content');
  const sidebar = document.getElementById('sidebar');
  const themeToggle = document.getElementById('theme-toggle');
  const beadsContent = document.getElementById('beads-content');
  const homeLink = document.getElementById('home-link');

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

  // --- Home link ---
  if (homeLink) {
    homeLink.addEventListener('click', (e) => {
      e.preventDefault();
      sidebar.querySelectorAll('.nav-item.active').forEach((el) => {
        el.classList.remove('active');
      });
      showHomepage();
    });
  }

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

  // --- Homepage / Experiment Timeline ---
  function showHomepage() {
    content.innerHTML = `
      <div class="homepage" id="homepage">
        <header class="home-header">
          <h1 class="home-title">Experiment Journal</h1>
          <p class="home-subtitle">Voice calibration and creative experiments, chronicled.</p>
        </header>
        <div class="home-loading" id="home-loading">
          <p class="loading-text">Gathering experiment data...</p>
        </div>
        <div id="timeline-container" style="display:none;">
          <section class="timeline-section" id="experiment-timeline"></section>
          <section class="recent-section" id="recent-changes">
            <h2 class="section-heading">Recent Changes</h2>
            <div id="recent-commits-list"></div>
          </section>
        </div>
      </div>`;
    loadExperiments();
  }

  async function loadExperiments() {
    const loadingEl = document.getElementById('home-loading');
    const containerEl = document.getElementById('timeline-container');
    const timelineEl = document.getElementById('experiment-timeline');
    const recentEl = document.getElementById('recent-commits-list');

    if (!loadingEl || !containerEl) return;

    try {
      const resp = await fetch('/api/experiments');
      if (!resp.ok) {
        loadingEl.innerHTML =
          '<p class="loading-text">Failed to load experiment data.</p>';
        return;
      }
      const data = await resp.json();

      // Render experiment timeline
      timelineEl.innerHTML = renderExperimentTimeline(data.experiments || []);

      // Render recent commits
      recentEl.innerHTML = renderRecentCommits(data.recent_commits || []);

      // Wire up interactive elements
      wireUpTimeline(containerEl);

      // Show the content
      loadingEl.style.display = 'none';
      containerEl.style.display = 'block';
    } catch (err) {
      loadingEl.innerHTML = `<p class="loading-text">Error: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderExperimentTimeline(experiments) {
    if (!experiments.length) {
      return '<p class="loading-text">No experiments found.</p>';
    }

    let html = '';
    for (const exp of experiments) {
      html += '<article class="experiment-entry">';

      // Header: bead ID + status
      html += '<div class="entry-header">';
      html += `<span class="entry-bead-id">${escapeHtml(exp.bead_id)}</span>`;
      html += `<span class="entry-status entry-status-${exp.status}">${escapeHtml(exp.status)}</span>`;
      html += '</div>';

      // Title
      html += `<h3 class="entry-title">${escapeHtml(exp.title)}</h3>`;

      // Description snippet
      if (exp.description) {
        html += `<div class="entry-description">${escapeHtml(exp.description)}</div>`;
      }

      // Run info
      if (exp.run) {
        const r = exp.run;
        html += '<div class="entry-run">';
        if (r.title) {
          html += `<div class="entry-run-title">${escapeHtml(r.title)}</div>`;
        }
        html += '<div class="entry-run-meta">';
        if (r.words) {
          html += `<span>${Number(r.words).toLocaleString()} words</span>`;
        }
        if (r.slop_score !== null && r.slop_score !== undefined) {
          html += `<span>slop ${r.slop_score}</span>`;
        }
        if (r.created) {
          const dateStr = r.created.slice(0, 10);
          if (dateStr && dateStr !== 'None') {
            html += `<span>${escapeHtml(dateStr)}</span>`;
          }
        }
        html += '</div>';

        // Links to draft and brief
        html += '<div class="entry-run-links">';
        if (r.draft_path) {
          html += `<a href="#" data-file-path="${escapeHtml(r.draft_path)}">read draft</a>`;
        }
        if (r.brief_path) {
          html += `<a href="#" data-file-path="${escapeHtml(r.brief_path)}">view brief</a>`;
        }
        html += '</div>';
        html += '</div>';
      }

      // Related commits
      if (exp.commits && exp.commits.length > 0) {
        html += '<div class="entry-commits">';
        html += `<button type="button" class="entry-commits-toggle" data-expanded="false">${exp.commits.length} related commit${exp.commits.length === 1 ? '' : 's'}</button>`;
        html += '<div class="entry-commits-list" style="display:none;">';
        for (const c of exp.commits) {
          html += '<div class="commit-line">';
          html += `<span class="commit-sha">${escapeHtml(c.sha)}</span>`;
          html += `<span class="commit-subject">${escapeHtml(c.subject)}</span>`;
          html += '</div>';
          if (c.files && c.files.length > 0) {
            html += '<div class="commit-files">';
            html += c.files
              .map(
                (f) =>
                  `<a class="commit-file-link" href="#" data-file-path="${escapeHtml(f)}">${escapeHtml(f)}</a>`,
              )
              .join(', ');
            html += '</div>';
          }
        }
        html += '</div></div>';
      }

      // Identity changes
      if (exp.identity_changes && exp.identity_changes.length > 0) {
        html += '<div class="identity-changes">';
        html += '<span>Identity updated: </span>';
        html += exp.identity_changes
          .map(
            (f) =>
              `<a class="identity-file-link" href="#" data-file-path="${escapeHtml(f)}">${escapeHtml(f)}</a>`,
          )
          .join(', ');
        html += '</div>';
      }

      html += '</article>';
    }
    return html;
  }

  function renderRecentCommits(commits) {
    if (!commits.length) {
      return '<p class="loading-text">No recent commits.</p>';
    }

    let html = '';
    for (const c of commits) {
      html += '<div class="recent-commit">';
      html += '<div class="recent-commit-header">';
      html += `<span class="recent-commit-date">${escapeHtml(c.date)}</span>`;
      html += `<span class="recent-commit-sha">${escapeHtml(c.sha)}</span>`;
      html += `<span class="recent-commit-subject">${escapeHtml(c.subject)}</span>`;
      html += '</div>';
      if (c.files && c.files.length > 0) {
        html += '<div class="recent-commit-files">';
        html += c.files
          .map(
            (f) =>
              `<a class="commit-file-link" href="#" data-file-path="${escapeHtml(f)}">${escapeHtml(f)}</a>`,
          )
          .join(', ');
        html += '</div>';
      }
      html += '</div>';
    }
    return html;
  }

  function wireUpTimeline(container) {
    // Toggle commit details
    container.querySelectorAll('.entry-commits-toggle').forEach((btn) => {
      btn.addEventListener('click', () => {
        const list = btn.nextElementSibling;
        const expanded = btn.dataset.expanded === 'true';
        list.style.display = expanded ? 'none' : 'block';
        btn.dataset.expanded = expanded ? 'false' : 'true';
      });
    });

    // File links within the timeline
    container.querySelectorAll('a[data-file-path]').forEach((a) => {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        loadFile(a.dataset.filePath);
      });
    });
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

  // Load homepage experiments if we're on the homepage
  if (document.getElementById('homepage')) {
    loadExperiments();
  }

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
