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
    { pattern: /^#\/agents$/,                 view: viewUserAgents  },
    { pattern: /^#\/agents\/new$/,            view: viewUserAgentForm },
    { pattern: /^#\/agents\/([\w_]+)\/edit$/, view: viewUserAgentForm },
    { pattern: /^#\/teams$/,                  view: viewTeams  },
    { pattern: /^#\/teams\/new$/,             view: viewTeamForm },
    { pattern: /^#\/teams\/([\w_]+)\/edit$/,  view: viewTeamForm },
    { pattern: /^#\/teams\/([\w_]+)$/,        view: viewTeamDetail },
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
      let activeNav = 'home';
      if (hash.startsWith('#/tasks')) activeNav = 'tasks';
      else if (hash.startsWith('#/agents')) activeNav = 'agents';
      else if (hash.startsWith('#/teams')) activeNav = 'teams';
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

  // ---- View: User Agents list ----
  async function viewUserAgents(root) {
    root.innerHTML = `<div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h2 class="card-title" style="margin:0;">我的 Agent</h2>
        <a href="#/agents/new" class="btn btn-primary">+ 新建 Agent</a>
      </div>
      <div class="card-subtitle">自定义 Agent：配置角色人设 + 勾选可用工具</div>
      <div id="ua-list">${stateLoading('加载 Agent 列表...')}</div>
    </div>`;

    try {
      const data = await api('/api/user-agents');
      const list = root.querySelector('#ua-list');
      if (!data.agents.length) {
        list.innerHTML = stateEmpty('还没有自定义 Agent', '点右上角「新建 Agent」创建一个吧');
        return;
      }
      list.innerHTML = data.agents.map(a => `
        <div class="task-row" style="display:flex;justify-content:space-between;align-items:center;padding:16px;">
          <div>
            <div style="font-weight:600;">${esc(a.name)}</div>
            <div class="task-row-meta">${esc(a.description || '')}</div>
            <div class="task-row-meta" style="margin-top:4px;font-size:12px;">
              工具: ${(a.tools || []).slice(0, 6).join(', ')}${(a.tools || []).length > 6 ? '...' : ''}
            </div>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0;">
            <a href="#/agents/${esc(a.id)}/edit" class="btn">编辑</a>
            <button class="btn btn-danger" data-delete="${esc(a.id)}" data-name="${esc(a.name)}">删除</button>
          </div>
        </div>
      `).join('');

      // Delete handlers
      list.querySelectorAll('[data-delete]').forEach(btn => {
        btn.addEventListener('click', async () => {
          const agentId = btn.dataset.delete;
          const agentName = btn.dataset.name;
          if (!confirm(`确定删除 Agent「${agentName}」？`)) return;
          btn.disabled = true;
          try {
            await api(`/api/user-agents/${agentId}`, { method: 'DELETE' });
            toast('已删除', 'success');
            await viewUserAgents(root);
          } catch (err) {
            toast(`删除失败: ${err.message}`, 'error');
            btn.disabled = false;
          }
        });
      });
    } catch (err) {
      root.querySelector('#ua-list').innerHTML = stateError('加载失败', err.message);
    }
  }

  // ---- View: Teams list ----
  async function viewTeams(root) {
    root.innerHTML = `<div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h2 class="card-title" style="margin:0;">我的团队</h2>
        <a href="#/teams/new" class="btn btn-primary">+ 新建团队</a>
      </div>
      <div class="card-subtitle">组建 Agent 团队，选择工作流模式，协作完成任务</div>
      <div id="team-list">${stateLoading('加载团队列表...')}</div>
    </div>`;

    try {
      const [teamsResp, agentsResp] = await Promise.all([
        api('/api/teams'),
        api('/api/user-agents'),
      ]);
      const agents = {};
      for (const a of agentsResp.agents || []) agents[a.id] = a;

      const list = root.querySelector('#team-list');
      if (!teamsResp.teams.length) {
        list.innerHTML = stateEmpty('还没有团队', '点「新建团队」创建一个吧');
        return;
      }
      list.innerHTML = teamsResp.teams.map(t => {
        const modeLabel = t.workflow_mode === 'sequential' ? '顺序流水线' : '管家模式';
        return `<div class="task-row" style="display:flex;justify-content:space-between;align-items:center;padding:16px;">
          <div>
            <div style="font-weight:600;">${esc(t.name)}</div>
            <div class="task-row-meta">${esc(t.description || '')}</div>
            <div class="task-row-meta" style="font-size:12px;">
              <span class="badge badge-ok">${esc(modeLabel)}</span>
              ${(t.members || []).map(m => esc(agents[m.agent_id]?.name || m.role_name || m.agent_id.slice(0,12))).join(' → ')}
            </div>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0;">
            <a href="#/teams/${esc(t.id)}" class="btn">运行</a>
            <a href="#/teams/${esc(t.id)}/edit" class="btn">编辑</a>
            <button class="btn btn-danger" data-delete="${esc(t.id)}" data-name="${esc(t.name)}">删除</button>
          </div>
        </div>`;
      }).join('');

      list.querySelectorAll('[data-delete]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm(`确定删除团队「${btn.dataset.name}」？`)) return;
          btn.disabled = true;
          try {
            await api(`/api/teams/${btn.dataset.delete}`, { method: 'DELETE' });
            toast('已删除', 'success');
            await viewTeams(root);
          } catch (err) {
            toast(`删除失败: ${err.message}`, 'error');
            btn.disabled = false;
          }
        });
      });
    } catch (err) {
      root.querySelector('#team-list').innerHTML = stateError('加载失败', err.message);
    }
  }

  // ---- View: Team form (create/edit) ----
  async function viewTeamForm(root, match) {
    const teamId = match ? match[1] : null;
    const isEdit = !!teamId;
    let teamData = null;
    let agentsList = [];

    root.innerHTML = stateLoading(isEdit ? '加载团队...' : '');

    try {
      const [agentsResp] = await Promise.all([
        api('/api/user-agents'),
        isEdit ? api(`/api/teams/${teamId}`).then(d => { teamData = d; }).catch(() => {}) : Promise.resolve(),
      ]);
      agentsList = agentsResp.agents || [];
    } catch (err) {
      root.innerHTML = `<div class="card">${stateError('加载失败', err.message)}</div>`;
      return;
    }

    function renderForm() {
      const nameVal = root.querySelector('#tm-name')?.value || (teamData ? teamData.name : '');
      const descVal = root.querySelector('#tm-desc')?.value || (teamData ? teamData.description : '');
      const modeVal = root.querySelector('[name="workflow_mode"]:checked')?.value || (teamData ? teamData.workflow_mode : 'sequential');
      const existingMembers = teamData ? (teamData.members || []) : [];
      const existingAgentIds = existingMembers.map(m => m.agent_id);

      root.innerHTML = `<div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <h2 class="card-title" style="margin:0;">${isEdit ? '编辑团队' : '新建团队'}</h2>
          <a href="#/teams" class="btn">← 返回</a>
        </div>

        <form id="tm-form">
          <div class="field">
            <label>团队名称 *</label>
            <input type="text" id="tm-name" name="name" required maxlength="64"
              placeholder="如：数据分析团队" value="${esc(nameVal)}">
          </div>
          <div class="field">
            <label>描述</label>
            <input type="text" id="tm-desc" name="description" maxlength="200"
              placeholder="团队职责描述" value="${esc(descVal)}">
          </div>
          <div class="field">
            <label>工作流模式</label>
            <div style="display:flex;gap:16px;margin-top:6px;">
              <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
                <input type="radio" name="workflow_mode" value="sequential" ${modeVal === 'sequential' ? 'checked' : ''}>
                顺序流水线 <span class="field-hint">A → B → C</span>
              </label>
              <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
                <input type="radio" name="workflow_mode" value="manager" ${modeVal === 'manager' ? 'checked' : ''}>
                管家模式 <span class="field-hint">PM 拆任务 → 派发 → 汇总</span>
              </label>
            </div>
          </div>
          <div class="field">
            <label>团队成员 <span class="field-hint">选择 Agent 并设定角色</span></label>
            <div id="members-area">
              ${existingMembers.map((m, idx) => memberRow(m.agent_id, m.role_name, idx)).join('')}
              ${existingMembers.length === 0 ? memberRow('', '', 0) : ''}
            </div>
            <button type="button" id="add-member-btn" class="btn" style="margin-top:8px;">+ 添加成员</button>
            <div id="mode-hint" class="field-hint" style="margin-top:8px;">
              ${modeVal === 'manager' ? '管家模式：第一个成员为 PM，其余为专家' : '顺序模式：按成员顺序依次执行，上一步输出传给下一步'}
            </div>
          </div>
          <div style="display:flex;gap:12px;margin-top:20px;">
            <button type="submit" class="btn-primary">${isEdit ? '保存修改' : '创建团队'}</button>
            <a href="#/teams" class="btn">取消</a>
          </div>
          <div id="form-error" class="error-msg hidden" style="margin-top:12px;"></div>
        </form>
      </div>`;

      // Mode hint update
      root.querySelectorAll('[name="workflow_mode"]').forEach(rb => {
        rb.addEventListener('change', () => {
          const hint = root.querySelector('#mode-hint');
          hint.textContent = rb.value === 'manager' ? '管家模式：第一个成员为 PM，其余为专家' : '顺序模式：按成员顺序依次执行，上一步输出传给下一步';
        });
      });

      // Add member
      root.querySelector('#add-member-btn').addEventListener('click', () => {
        const area = root.querySelector('#members-area');
        const count = area.children.length;
        area.insertAdjacentHTML('beforeend', memberRow('', '', count));
      });

      // Form submit
      const form = root.querySelector('#tm-form');
      const errEl = root.querySelector('#form-error');
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errEl.classList.add('hidden');
        const fd = new FormData(form);
        const name = fd.get('name').trim();
        if (!name) { errEl.textContent = '名称不能为空'; errEl.classList.remove('hidden'); return; }

        const memberRows = root.querySelectorAll('.member-row');
        const members = [];
        memberRows.forEach((row, idx) => {
          const sel = row.querySelector('select');
          const role = row.querySelector('input[type="text"]');
          if (sel && sel.value) {
            members.push({
              agent_id: sel.value,
              role_name: (role ? role.value : '') || sel.options[sel.selectedIndex]?.text || '',
              step_order: idx + 1,
            });
          }
        });
        if (members.length === 0) { errEl.textContent = '至少添加一个成员'; errEl.classList.remove('hidden'); return; }

        const body = {
          name: name,
          description: fd.get('description').trim(),
          workflow_mode: fd.get('workflow_mode'),
          members: members,
        };

        const submitBtn = form.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        try {
          if (isEdit) {
            await api(`/api/teams/${teamId}`, { method: 'PUT', body });
            toast('团队已更新', 'success');
          } else {
            await api('/api/teams', { method: 'POST', body });
            toast('团队已创建', 'success');
          }
          navigate('#/teams');
        } catch (err) {
          errEl.textContent = err.message;
          errEl.classList.remove('hidden');
          submitBtn.disabled = false;
        }
      });
    }

    function memberRow(agentId, roleName, idx) {
      return `<div class="member-row" style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
        <select style="flex:2;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface);" ${agentsList.length === 0 ? 'disabled' : ''}>
          <option value="">-- 选择 Agent --</option>
          ${agentsList.map(a => `<option value="${esc(a.id)}" ${a.id === agentId ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}
        </select>
        <input type="text" placeholder="角色名 (如: 数据分析师)" value="${esc(roleName)}"
          style="flex:2;padding:8px;border:1px solid var(--border);border-radius:var(--radius-sm);">
        <button type="button" class="btn btn-danger" style="padding:6px 10px;" onclick="this.closest('.member-row').remove()">✕</button>
      </div>`;
    }

    renderForm();
  }

  // ---- View: Team detail + run workflow ----
  async function viewTeamDetail(root, match) {
    const teamId = match[1];
    let teamData = null;
    let agentsMap = {};
    let pollTimer = null;

    root.innerHTML = stateLoading('加载团队...');

    try {
      const [teamResp, agentsResp] = await Promise.all([
        api(`/api/teams/${teamId}`),
        api('/api/user-agents'),
      ]);
      teamData = teamResp;
      for (const a of agentsResp.agents || []) agentsMap[a.id] = a;
    } catch (err) {
      root.innerHTML = `<div class="card">${stateError('加载失败', err.message)}</div>`;
      return;
    }

    const modeLabel = teamData.workflow_mode === 'sequential' ? '顺序流水线' : '管家模式';
    render();

    function render(runResult) {
      const runSteps = runResult ? (runResult.steps || []) : [];
      const runStatus = runResult ? runResult.status : null;
      const isRunning = runStatus === 'running' || runStatus === 'queued';

      root.innerHTML = `<div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <div>
            <h2 class="card-title" style="margin:0;">${esc(teamData.name)}</h2>
            <div class="task-row-meta">
              <span class="badge badge-ok">${esc(modeLabel)}</span>
              ${esc(teamData.description || '')}
            </div>
          </div>
          <a href="#/teams" class="btn">← 所有团队</a>
        </div>

        <div style="border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:20px;">
          <h3 style="margin:0 0 12px;">运行工作流</h3>
          <div class="field">
            <label>需求描述</label>
            <textarea id="wf-prompt" rows="3" placeholder="输入需求描述..."></textarea>
          </div>
          <div style="display:flex;gap:12px;align-items:center;">
            <button id="wf-run-btn" class="btn-primary">🚀 运行</button>
            <span id="run-status" class="field-hint"></span>
          </div>
          <div id="run-error" class="error-msg hidden" style="margin-top:12px;"></div>
        </div>

        ${runSteps.length > 0 ? `<div style="border:1px solid var(--border);border-radius:var(--radius);padding:20px;">
          <h3 style="margin:0 0 12px;">执行结果</h3>
          <div class="run-status-bar" style="margin-bottom:16px;">
            <span class="badge badge-${esc(runStatus || 'pending')}">${esc(runStatus || 'pending')}</span>
            ${runResult && runResult.error ? `<span class="error-msg" style="display:inline-block;margin-left:8px;">${esc(runResult.error)}</span>` : ''}
          </div>
          ${runSteps.map((s, i) => `
            <div class="workflow-step" style="border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-bottom:12px;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="font-weight:600;">步骤 ${s.step}: ${esc(s.role_name || '')}</div>
                <span class="badge badge-${esc(s.status)}">${esc(s.status)}</span>
              </div>
              ${s.error ? `<div class="error-msg" style="margin-top:8px;">${esc(s.error)}</div>` : ''}
              ${s.output ? `<details style="margin-top:8px;">
                <summary style="cursor:pointer;color:var(--primary);font-size:13px;">查看输出</summary>
                <div class="report-md" style="margin-top:8px;padding:12px;background:var(--bg);border-radius:var(--radius-sm);font-size:13px;">${renderMarkdown(s.output)}</div>
              </details>` : ''}
            </div>
          `).join('')}
          ${runResult && runResult.result ? `<div style="margin-top:16px;padding:16px;background:var(--bg);border-radius:var(--radius);">
            <h4 style="margin:0 0 8px;">最终结果</h4>
            <div class="report-md">${renderMarkdown(runResult.result)}</div>
          </div>` : ''}
        </div>` : ''}
      </div>`;

      // Run button
      const runBtn = root.querySelector('#wf-run-btn');
      const promptEl = root.querySelector('#wf-prompt');
      const statusEl = root.querySelector('#run-status');
      const errEl = root.querySelector('#run-error');

      if (isRunning) {
        runBtn.disabled = true;
        runBtn.textContent = '⏳ 运行中...';
      }

      runBtn.addEventListener('click', async () => {
        const prompt = promptEl.value.trim();
        if (!prompt) { errEl.textContent = '请输入需求描述'; errEl.classList.remove('hidden'); return; }
        errEl.classList.add('hidden');
        runBtn.disabled = true;
        runBtn.textContent = '⏳ 提交中...';
        try {
          const resp = await api(`/api/teams/${teamId}/run`, { method: 'POST', body: { prompt } });
          toast('工作流已启动', 'success');
          statusEl.textContent = '运行中...';
          pollRun(resp.run_id);
        } catch (err) {
          errEl.textContent = err.message;
          errEl.classList.remove('hidden');
          runBtn.disabled = false;
          runBtn.textContent = '🚀 运行';
        }
      });
    }

    async function pollRun(runId) {
      let count = 0;
      async function tick() {
        try {
          const resp = await api(`/api/teams/runs/${runId}`);
          render(resp);
          if (resp.status === 'ok' || resp.status === 'failed') {
            toast(resp.status === 'ok' ? '工作流完成' : '工作流失败', resp.status === 'ok' ? 'success' : 'error');
            return;
          }
          if (count++ < 120) {
            pollTimer = setTimeout(tick, 1000);
          }
        } catch {
          pollTimer = setTimeout(tick, 2000);
        }
      }
      tick();
    }

    window.addEventListener('hashchange', () => {
      if (pollTimer) clearTimeout(pollTimer);
    }, { once: true });
  }

  // ---- View: User Agent form (create/edit) ----
  async function viewUserAgentForm(root, match) {
    const agentId = match ? match[1] : null;
    const isEdit = !!agentId;
    let agentData = null;
    let allTools = [];

    root.innerHTML = stateLoading(isEdit ? '加载 Agent...' : '');

    // Load available tools and optionally existing agent data
    try {
      const [toolsResp] = await Promise.all([
        api('/api/available-tools'),
        isEdit ? api(`/api/user-agents/${agentId}`).then(d => { agentData = d; }).catch(() => {}) : Promise.resolve(),
      ]);
      allTools = toolsResp.tools || [];
    } catch (err) {
      root.innerHTML = `<div class="card">${stateError('加载失败', err.message)}</div>`;
      return;
    }

    const grouped = {};
    for (const t of allTools) {
      const cat = t.category || '其他';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(t);
    }
    const categoryOrder = ['通用', '文件操作', '网络', '数据', '开发', '命令行', 'Git', '浏览器', '媒体分析', '创作', '记忆', '通信', 'MCP', '系统', '笔记本', '指令', '其他'];

    const selectedTools = new Set(agentData ? (agentData.tools || []) : []);

    function renderForm() {
      const promptVal = root.querySelector('#ua-prompt')?.value || (agentData ? agentData.system_prompt : '');
      const nameVal = root.querySelector('#ua-name')?.value || (agentData ? agentData.name : '');
      const descVal = root.querySelector('#ua-desc')?.value || (agentData ? agentData.description : '');
      const modelVal = root.querySelector('#ua-model')?.value || (agentData ? agentData.model : '');
      // Collect selected tools from checkboxes
      const checked = root.querySelectorAll('.tool-checkbox:checked');
      const selected = Array.from(checked).map(cb => cb.value);

      root.innerHTML = `<div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <h2 class="card-title" style="margin:0;">${isEdit ? '编辑 Agent' : '新建 Agent'}</h2>
          <a href="#/agents" class="btn">← 返回</a>
        </div>

        <form id="ua-form">
          <div class="field">
            <label>名称 *</label>
            <input type="text" id="ua-name" name="name" required maxlength="64"
              placeholder="如：数据分析师" value="${esc(nameVal)}">
          </div>

          <div class="field">
            <label>描述</label>
            <input type="text" id="ua-desc" name="description" maxlength="200"
              placeholder="简短描述这个 Agent 的职责" value="${esc(descVal)}">
          </div>

          <div class="field">
            <label>角色人设 (System Prompt)</label>
            <textarea id="ua-prompt" name="system_prompt" rows="6"
              placeholder="定义 Agent 的角色、技能、行为边界...">${esc(promptVal)}</textarea>
            <div class="field-hint">好的 prompt 让 Agent 表现更好。描述它的角色、目标、工作方式。</div>
          </div>

          <div class="field">
            <label>可用工具 <span class="field-hint">勾选该 Agent 可使用的工具</span></label>
            <div class="tools-grid" id="tools-grid">
              ${categoryOrder.map(cat => {
                const tools = grouped[cat];
                if (!tools) return '';
                return `<div class="tool-category">
                  <div class="tool-cat-title" style="font-weight:600;margin:12px 0 8px;color:var(--text-muted);font-size:13px;">${esc(cat)}</div>
                  <div style="display:flex;flex-wrap:wrap;gap:6px;">
                    ${tools.map(t => {
                      const checked = selected.includes(t.name) ? 'checked' : '';
                      return `<label class="tool-chip ${checked ? 'checked' : ''}" data-tool="${esc(t.name)}">
                        <input type="checkbox" class="tool-checkbox" value="${esc(t.name)}" ${checked}
                          onchange="this.parentElement.classList.toggle('checked', this.checked)">
                        <span class="tool-name">${esc(t.name)}</span>
                      </label>`;
                    }).join('')}
                  </div>
                </div>`;
              }).join('')}
            </div>
            <div class="field-hint" style="margin-top:8px;">
              <span id="tool-count">${selected.length}</span> 个工具已选择
            </div>
          </div>

          <div class="field">
            <label>模型 <span class="field-hint">留空使用默认</span></label>
            <input type="text" id="ua-model" name="model" placeholder="如：gpt-4o（留空则用系统默认）" value="${esc(modelVal)}">
          </div>

          <div style="display:flex;gap:12px;margin-top:20px;">
            <button type="submit" class="btn-primary">${isEdit ? '保存修改' : '创建 Agent'}</button>
            <a href="#/agents" class="btn">取消</a>
          </div>
          <div id="form-error" class="error-msg hidden" style="margin-top:12px;"></div>
        </form>
      </div>`;

      // Tool count sync
      root.querySelectorAll('.tool-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
          const count = root.querySelectorAll('.tool-checkbox:checked').length;
          const el = root.querySelector('#tool-count');
          if (el) el.textContent = count;
        });
      });

      // Form submit
      const form = root.querySelector('#ua-form');
      const errEl = root.querySelector('#form-error');
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errEl.classList.add('hidden');
        const fd = new FormData(form);
        const tools = Array.from(root.querySelectorAll('.tool-checkbox:checked')).map(cb => cb.value);
        const body = {
          name: fd.get('name').trim(),
          description: fd.get('description').trim(),
          system_prompt: fd.get('system_prompt').trim(),
          tools: tools,
          model: fd.get('model').trim(),
        };
        if (!body.name) { errEl.textContent = '名称不能为空'; errEl.classList.remove('hidden'); return; }
        const submitBtn = form.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        try {
          if (isEdit) {
            await api(`/api/user-agents/${agentId}`, { method: 'PUT', body });
            toast('Agent 已更新', 'success');
          } else {
            await api('/api/user-agents', { method: 'POST', body });
            toast('Agent 已创建', 'success');
          }
          navigate('#/agents');
        } catch (err) {
          errEl.textContent = err.message;
          errEl.classList.remove('hidden');
          submitBtn.disabled = false;
        }
      });
    }

    renderForm();
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
