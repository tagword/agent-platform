// Agent Platform — minimal SPA (no build step)
// Hash router: #/login, #/home, #/tasks, #/tasks/:id

(() => {
  'use strict';

  // ---- Config (override at deploy via window.AGENT_PLATFORM_API_BASE
  //      or <meta name="api-base" content="..."> in index.html) ----
  function resolveApiBase() {
    // 1. window override (highest priority)
    const fromGlobal = (window.AGENT_PLATFORM_API_BASE || '').replace(/\/+$/, '');
    if (fromGlobal) return fromGlobal;
    // 2. <meta name="api-base"> — exists → use its content (even if empty = same origin)
    const meta = document.querySelector('meta[name="api-base"]');
    if (meta) {
      return (meta.getAttribute('content') || '').replace(/\/+$/, '');
    }
    // 3. Fallback: dev mode, assume gateway on :8780
    return `${location.protocol}//${location.hostname}:8780`;
  }
  const API_BASE = resolveApiBase();

  // ---- State ----
  const state = {
    token: localStorage.getItem('ap_token') || null,
    user: JSON.parse(localStorage.getItem('ap_user') || 'null'),
    agents: [],
    selectedAgent: null,
    pendingFile: null,
  };

  // ---- API client ----
  async function api(path, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
    let body = opts.body;
    if (body && !(body instanceof FormData) && typeof body !== 'string') {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    const r = await fetch(API_BASE + path, { ...opts, headers, body });
    let data = null;
    const text = await r.text();
    if (text) {
      try { data = JSON.parse(text); } catch { data = { detail: text }; }
    }
    if (!r.ok) {
      const detail = (data && data.detail) || `HTTP ${r.status}`;
      const err = new Error(detail);
      err.status = r.status;
      throw err;
    }
    return data;
  }

  // ---- Toasts ----
  function toast(msg, type = '') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.getElementById('toasts').appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ---- Utility: escape HTML ----
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // ---- State UI helpers (loading/empty/error/success) ----
  function stateLoading(label = '加载中...') {
    return `<div class="state">
      <div class="spinner"></div>
      <div class="state-title">${esc(label)}</div>
    </div>`;
  }
  function stateEmpty(title, hint = '') {
    return `<div class="state">
      <div class="state-icon">📭</div>
      <div class="state-title">${esc(title)}</div>
      ${hint ? `<div>${esc(hint)}</div>` : ''}
    </div>`;
  }
  function stateError(title, hint = '') {
    return `<div class="state">
      <div class="state-icon">⚠️</div>
      <div class="state-title">${esc(title)}</div>
      ${hint ? `<div>${esc(hint)}</div>` : ''}
    </div>`;
  }

  // ---- Markdown rendering (with sanitizer) ----
  function renderMarkdown(md) {
    if (!md) return '';
    if (typeof marked === 'undefined') return esc(md);
    const html = marked.parse(md, { gfm: true, breaks: false });
    if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(html);
    return html;
  }

  // ---- Auth helpers ----
  function setSession(token, user) {
    state.token = token;
    state.user = user;
    localStorage.setItem('ap_token', token);
    localStorage.setItem('ap_user', JSON.stringify(user));
  }
  function clearSession() {
    state.token = null;
    state.user = null;
    localStorage.removeItem('ap_token');
    localStorage.removeItem('ap_user');
  }
  function isAuthed() { return !!state.token; }

  // ---- Router ----
  const routes = [
    { pattern: /^#\/login$/,                  view: viewLogin  },
    { pattern: /^#\/home$/,                   view: viewHome   },
    { pattern: /^#\/tasks$/,                  view: viewTasks  },
    { pattern: /^#\/tasks\/([\w_]+)$/,        view: viewTaskDetail },
  ];

  function navigate(hash) {
    if (location.hash !== hash) {
      location.hash = hash;
    } else {
      render();
    }
  }
  function render() {
    const hash = location.hash || (isAuthed() ? '#/home' : '#/login');
    const topbar = document.getElementById('topbar');
    const bottomnav = document.getElementById('bottomnav');
    const view = document.getElementById('view');
    if (!isAuthed() && hash !== '#/login') {
      navigate('#/login');
      return;
    }
    if (isAuthed()) {
      topbar.classList.remove('hidden');
      bottomnav.classList.remove('hidden');
      document.getElementById('user-name').textContent = state.user?.name || state.user?.email || '';
      // Active nav link (both top and bottom)
      document.querySelectorAll('#topnav a, #bottomnav a[data-nav]').forEach(a => a.classList.remove('active'));
      const isTaskView = hash.startsWith('#/tasks');
      const activeNav = isTaskView ? 'tasks' : 'home';
      document.querySelectorAll(`#topnav a[data-nav="${activeNav}"], #bottomnav a[data-nav="${activeNav}"]`).forEach(a => a.classList.add('active'));
    } else {
      topbar.classList.add('hidden');
      bottomnav.classList.add('hidden');
    }
    for (const r of routes) {
      const m = hash.match(r.pattern);
      if (m) {
        r.view(view, m);
        return;
      }
    }
    // Fallback
    view.innerHTML = stateError('页面未找到', hash);
  }
  window.addEventListener('hashchange', render);

  // ---- Views ---------------------------------------------------------------

  function viewLogin(root) {
    root.innerHTML = `
      <div class="auth-container">
        <div class="card">
          <div class="auth-tabs">
            <div class="auth-tab active" data-tab="login">登录</div>
            <div class="auth-tab" data-tab="register">注册</div>
          </div>
          <form id="auth-form">
            <div class="field">
              <label>邮箱</label>
              <input type="email" name="email" required placeholder="you@example.com" autocomplete="email">
            </div>
            <div class="field">
              <label>密码</label>
              <input type="password" name="password" required minlength="6" placeholder="至少 6 位" autocomplete="current-password">
            </div>
            <div class="field hidden" id="name-field">
              <label>姓名</label>
              <input type="text" name="name" placeholder="您的姓名">
            </div>
            <button type="submit" class="btn-primary" style="width: 100%;">登录</button>
            <div id="auth-error" class="error-msg hidden"></div>
          </form>
        </div>
      </div>
    `;
    let mode = 'login';
    const tabs = root.querySelectorAll('.auth-tab');
    const nameField = root.querySelector('#name-field');
    const submitBtn = root.querySelector('button[type="submit"]');
    tabs.forEach(t => t.addEventListener('click', () => {
      tabs.forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      mode = t.dataset.tab;
      nameField.classList.toggle('hidden', mode !== 'register');
      submitBtn.textContent = mode === 'register' ? '注册' : '登录';
    }));
    const form = root.querySelector('#auth-form');
    const errEl = root.querySelector('#auth-error');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      errEl.classList.add('hidden');
      submitBtn.disabled = true;
      try {
        const fd = new FormData(form);
        const body = {
          email: fd.get('email').trim(),
          password: fd.get('password'),
        };
        const path = mode === 'register' ? '/api/auth/register' : '/api/auth/login';
        if (mode === 'register') body.name = (fd.get('name') || '').trim() || body.email.split('@')[0];
        const data = await api(path, { method: 'POST', body });
        setSession(data.token, data.user);
        toast(`欢迎，${data.user.name || data.user.email}`, 'success');
        navigate('#/home');
      } catch (err) {
        errEl.textContent = err.message;
        errEl.classList.remove('hidden');
      } finally {
        submitBtn.disabled = false;
      }
    });
  }

  async function viewHome(root) {
    root.innerHTML = `
      <div class="card">
        <h2 class="card-title">选择 Agent</h2>
        <div class="card-subtitle">选择一个 Agent 模板来处理你的数据</div>
        <div id="agents-list">${stateLoading('加载 Agent 列表...')}</div>
      </div>
      <div class="card" id="upload-card" style="display:none;">
        <h3 class="card-title">上传数据</h3>
        <div class="card-subtitle">支持 CSV、Excel（.xlsx/.xls）、JSON 格式，单文件 ≤ 10MB</div>
        <div class="upload-zone" id="upload-zone">
          <div class="upload-icon">📁</div>
          <div id="upload-prompt">
            <div>点击或拖拽文件到此处</div>
            <div class="upload-hint">支持 .csv / .xlsx / .xls / .json</div>
          </div>
          <input type="file" id="file-input" accept=".csv,.xlsx,.xls,.json" style="display:none;">
        </div>
      </div>
      <div class="card" id="run-card" style="display:none;">
        <h3 class="card-title">运行任务</h3>
        <div class="field">
          <label>数据集名称（可选）</label>
          <input type="text" id="dataset-name" placeholder="留空则使用文件名">
        </div>
        <div class="field">
          <label>补充说明（可选）</label>
          <textarea id="user-instructions" placeholder="比如：重点关注付费渠道的留存率异常"></textarea>
          <div class="field-hint">将作为补充上下文传给 Agent</div>
        </div>
        <div class="field" style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="async-mode" style="width:auto;">
          <label for="async-mode" style="margin:0;cursor:pointer;">异步模式（提交后不阻塞）</label>
          <div class="field-hint" style="margin-left:8px;">适合长任务；启用后会自动跳到任务详情并轮询</div>
        </div>
        <button id="run-btn" class="btn-primary" disabled>选择文件后运行</button>
        <div id="run-error" class="error-msg hidden" style="margin-top:12px;"></div>
      </div>
    `;

    // Load agents
    try {
      const data = await api('/api/agents');
      state.agents = data.agents;
      const list = root.querySelector('#agents-list');
      if (!data.agents.length) {
        list.innerHTML = stateEmpty('暂无可用 Agent', '请联系管理员启用 Agent 模板');
        return;
      }
      list.innerHTML = data.agents.map(a => `
        <div class="agent-card" data-agent-id="${esc(a.id)}">
          <div class="agent-name">
            ${esc(a.name)}
            <span class="agent-version">v${esc(a.version)}</span>
          </div>
          <div class="agent-desc">${esc(a.description || '')}</div>
        </div>
      `).join('');
      list.querySelectorAll('.agent-card').forEach(card => {
        card.addEventListener('click', () => {
          list.querySelectorAll('.agent-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          state.selectedAgent = data.agents.find(a => a.id === card.dataset.agentId);
          root.querySelector('#upload-card').style.display = '';
          root.querySelector('#run-card').style.display = '';
          updateRunBtn();
        });
      });
    } catch (err) {
      root.querySelector('#agents-list').innerHTML = stateError('加载 Agent 失败', err.message);
      return;
    }

    // Upload zone
    const zone = root.querySelector('#upload-zone');
    const fileInput = root.querySelector('#file-input');
    const promptEl = root.querySelector('#upload-prompt');
    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files[0]) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
      const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
      const allowed = ['.csv', '.xlsx', '.xls', '.json'];
      if (!allowed.includes(ext)) {
        toast(`不支持的文件类型: ${ext}`, 'error');
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        toast('文件超过 10MB 上限', 'error');
        return;
      }
      state.pendingFile = file;
      zone.classList.add('has-file');
      promptEl.innerHTML = `
        <div class="upload-file">📄 ${esc(file.name)}</div>
        <div class="upload-hint">${(file.size / 1024).toFixed(1)} KB · 点击重新选择</div>
      `;
      updateRunBtn();
    }

    function updateRunBtn() {
      const btn = root.querySelector('#run-btn');
      const canRun = state.selectedAgent && state.pendingFile;
      btn.disabled = !canRun;
      btn.textContent = canRun
        ? `运行 ${state.selectedAgent.name}`
        : (state.selectedAgent ? '请选择文件' : '请先选择 Agent');
    }

    // Run button
    const runBtn = root.querySelector('#run-btn');
    const errEl = root.querySelector('#run-error');
    const asyncCheckbox = root.querySelector('#async-mode');
    runBtn.addEventListener('click', async () => {
      if (!state.selectedAgent || !state.pendingFile) return;
      errEl.classList.add('hidden');
      runBtn.disabled = true;
      const originalText = runBtn.textContent;
      const isAsync = asyncCheckbox.checked;
      runBtn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;margin:0 6px 0 0;vertical-align:middle;"></span> 上传中...';
      try {
        // 1. Upload
        const fd = new FormData();
        fd.append('file', state.pendingFile);
        const upload = await api('/api/uploads', { method: 'POST', body: fd });
        if (upload.parse_status !== 'ok') {
          throw new Error(upload.parse_error || '文件解析失败');
        }
        // 2. Run task (sync or async)
        const runBody = {
          upload_id: upload.id,
          agent_id: state.selectedAgent.id,
          user_instructions: root.querySelector('#user-instructions').value.trim(),
        };
        const dsName = root.querySelector('#dataset-name').value.trim();
        if (dsName) runBody.dataset_name = dsName;
        if (isAsync) {
          runBtn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;margin:0 6px 0 0;vertical-align:middle;"></span> 排队中...';
          const enq = await api('/api/tasks', { method: 'POST', body: runBody });
          toast(`任务已加入队列（队列深度 ${enq.queue_depth}）`, 'success');
          navigate(`#/tasks/${enq.task_id}?poll=1`);
        } else {
          runBtn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;margin:0 6px 0 0;vertical-align:middle;"></span> 同步运行中...';
          const task = await api('/api/tasks/run', { method: 'POST', body: runBody });
          if (task.status === 'ok') {
            toast('报告生成完成', 'success');
          } else if (task.status === 'failed') {
            toast(`任务失败: ${task.error || '未知错误'}`, 'error');
          }
          navigate(`#/tasks/${task.task_id}`);
        }
      } catch (err) {
        errEl.textContent = err.message;
        errEl.classList.remove('hidden');
        runBtn.disabled = false;
        runBtn.textContent = originalText;
      }
    });
  }

  async function viewTasks(root) {
    root.innerHTML = `<div class="card">
      <h2 class="card-title">任务历史</h2>
      <div id="tasks-list">${stateLoading('加载任务列表...')}</div>
    </div>`;
    try {
      const data = await api('/api/tasks?limit=50');
      const list = root.querySelector('#tasks-list');
      if (!data.tasks.length) {
        list.innerHTML = stateEmpty('还没有任务', '去主页选择一个 Agent 跑一次吧');
        return;
      }
      list.innerHTML = data.tasks.map(t => `
        <a class="task-row" href="#/tasks/${esc(t.id)}" style="text-decoration:none;color:inherit;">
          <span class="badge badge-${esc(t.status)}">${esc(t.status)}</span>
          <div class="task-row-main">
            <div class="task-row-name">${esc(t.agent_template_id)} ${t.agent_version ? `<span class="agent-version">v${esc(t.agent_version)}</span>` : ''}</div>
            <div class="task-row-meta">
              <span class="task-row-id">${esc(t.id)}</span>
              · ${new Date(t.created_at * 1000).toLocaleString('zh-CN')}
              ${t.duration_ms ? ` · ${(t.duration_ms / 1000).toFixed(1)}s` : ''}
            </div>
          </div>
        </a>
      `).join('');
    } catch (err) {
      root.querySelector('#tasks-list').innerHTML = stateError('加载失败', err.message);
    }
  }

  async function viewTaskDetail(root, match) {
    const taskId = match[1];
    // ?poll=1 in the URL enables auto-polling until task completes.
    // Note: with hash routing, query string lives in the hash, not location.search.
    const hashQuery = (location.hash.split('?')[1] || '');
    const shouldPoll = hashQuery.includes('poll=1');
    root.innerHTML = `<div id="task-detail">${stateLoading('加载报告...')}</div>`;

    let pollTimer = null;
    let pollCount = 0;
    const MAX_POLLS = 600; // 10 minutes at 1s

    async function fetchAndRender() {
      try {
        const task = await api(`/api/tasks/${taskId}`);
        renderTask(task);
        const isFinal = ['ok', 'failed', 'timeout', 'cancelled'].includes(task.status);
        if (shouldPoll && !isFinal && pollCount < MAX_POLLS) {
          pollCount++;
          // Adaptive: 0.5s while queued, 1s while running
          const interval = task.status === 'queued' ? 500 : 1000;
          pollTimer = setTimeout(fetchAndRender, interval);
        } else if (isFinal) {
          if (task.status === 'ok') toast('报告生成完成', 'success');
          else if (task.status === 'failed') toast(`任务失败: ${task.error || '未知错误'}`, 'error');
        }
      } catch (err) {
        root.querySelector('#task-detail').innerHTML = stateError('加载任务失败', err.message);
      }
    }

    function renderTask(task) {
      const det = root.querySelector('#task-detail');
      const isFinal = ['ok', 'failed', 'timeout', 'cancelled'].includes(task.status);
      det.innerHTML = `
        <div class="card">
          <div class="report-header">
            <div>
              <h2 class="card-title" style="margin-bottom:4px;">
                <span class="badge badge-${esc(task.status)}">${esc(task.status)}</span>
                ${esc(task.agent_template_id)}
                <span class="agent-version">v${esc(task.agent_version)}</span>
              </h2>
              <div class="task-row-meta">
                <span class="task-row-id">${esc(task.id)}</span>
                · ${new Date(task.created_at * 1000).toLocaleString('zh-CN')}
                ${task.duration_ms ? ` · 耗时 ${(task.duration_ms / 1000).toFixed(1)}s` : ''}
                ${shouldPoll && !isFinal ? ` · <span class="poll-indicator">轮询中 (#${pollCount})</span>` : ''}
              </div>
            </div>
            <div>
              <button id="back-btn" class="btn">← 返回</button>
              <button id="download-btn" class="btn"${task.status === 'ok' && task.report ? '' : ' disabled'}>下载 .md</button>
            </div>
          </div>
          ${task.error ? `<div class="error-msg" style="margin-bottom:16px;">${esc(task.error)}</div>` : ''}
          ${task.report
            ? `<div class="report-md" id="report-md">${renderMarkdown(task.report)}</div>`
            : (shouldPoll && !isFinal
                ? `<div class="state" id="poll-progress">${stateLoading(task.status === 'queued' ? '等待执行...' : 'Agent 正在生成报告...')}</div>`
                : '<div class="state">⏳ 暂无报告</div>')}
        </div>
      `;
      root.querySelector('#back-btn').addEventListener('click', () => {
        if (pollTimer) clearTimeout(pollTimer);
        navigate('#/tasks');
      });
      const dlBtn = root.querySelector('#download-btn');
      if (!dlBtn.disabled) {
        dlBtn.addEventListener('click', () => {
          const blob = new Blob([task.report], { type: 'text/markdown;charset=utf-8' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `report-${task.id}.md`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
        });
      }
    }

    // Stop polling when user navigates away
    window.addEventListener('hashchange', function stop() {
      if (pollTimer) clearTimeout(pollTimer);
      window.removeEventListener('hashchange', stop);
    }, { once: true });

    await fetchAndRender();
  }

  // ---- Logout ----
  function logout() {
    clearSession();
    toast('已退出', 'success');
    navigate('#/login');
  }
  document.getElementById('logout-btn').addEventListener('click', logout);
  document.getElementById('bnav-logout').addEventListener('click', (e) => {
    e.preventDefault();
    logout();
  });

  // ---- Boot ----
  // If token present but server rejects, clear it.
  (async () => {
    if (isAuthed()) {
      try {
        const me = await api('/api/auth/me');
        state.user = me;
        localStorage.setItem('ap_user', JSON.stringify(me));
      } catch {
        clearSession();
      }
    }
    render();
  })();
})();
