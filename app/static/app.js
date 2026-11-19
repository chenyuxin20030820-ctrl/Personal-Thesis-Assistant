const state = { conversationId: null, attachments: [], busy: false, searchTimer: null };
const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove('show'), 2700);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) throw new Error(data.detail || `请求失败（${response.status}）`);
  return data;
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

function groupName(iso) {
  const d = new Date(iso);
  const now = new Date();
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const b = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((a - b) / 86400000);
  return days === 0 ? '今天' : days === 1 ? '昨天' : '更早';
}

function timeLabel(iso) {
  const d = new Date(iso);
  return groupName(iso) === '更早' ? `${d.getMonth() + 1}月${d.getDate()}日` : d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

async function loadHistory() {
  try {
    const q = $('history-query').value.trim();
    const rows = await api(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ''}`);
    const list = $('history-list');
    list.replaceChildren();
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'history-empty';
      empty.textContent = q ? '没有匹配的历史对话' : '还没有历史对话';
      list.append(empty);
      return;
    }
    let group = '';
    for (const row of rows) {
      const name = groupName(row.updated_at);
      if (name !== group) {
        group = name;
        const label = document.createElement('div');
        label.className = 'group-label';
        label.textContent = group;
        list.append(label);
      }
      const item = document.createElement('div');
      item.className = `history-row${row.id === state.conversationId ? ' selected' : ''}`;
      item.setAttribute('role', 'button');
      item.tabIndex = 0;
      item.append(icon('chat'));
      const copy = document.createElement('div');
      copy.className = 'row-copy';
      const title = document.createElement('strong');
      title.textContent = row.title;
      const time = document.createElement('small');
      time.textContent = timeLabel(row.updated_at);
      copy.append(title, time);
      item.append(copy);
      const menu = document.createElement('div');
      menu.className = 'row-menu';
      const menuButton = document.createElement('button');
      menuButton.setAttribute('aria-label', `${row.title} 更多操作`);
      menuButton.append(icon('more'));
      menuButton.onclick = (event) => {
        event.stopPropagation();
        document.querySelectorAll('.menu-pop').forEach(el => el.remove());
        const pop = document.createElement('div');
        pop.className = 'menu-pop';
        const rename = document.createElement('button');
        rename.textContent = '重命名';
        rename.onclick = async (e) => {
          e.stopPropagation();
          const value = window.prompt('会话名称', row.title);
          if (value && value.trim()) {
            try { await api(`/api/conversations/${row.id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({title:value.trim()}) }); await loadHistory(); if (row.id === state.conversationId) $('chat-title').textContent = value.trim(); }
            catch (error) { toast(error.message); }
          }
        };
        const remove = document.createElement('button');
        remove.className = 'danger';
        remove.textContent = '删除对话';
        remove.onclick = async (e) => {
          e.stopPropagation();
          if (!window.confirm(`删除「${row.title}」及其全部消息？`)) return;
          try { await api(`/api/conversations/${row.id}`, {method:'DELETE'}); if (row.id === state.conversationId) resetChat(); await loadHistory(); }
          catch (error) { toast(error.message); }
        };
        pop.append(rename, remove);
        menu.append(pop);
      };
      menu.append(menuButton);
      item.append(menu);
      item.onclick = () => openConversation(row.id);
      item.onkeydown = e => { if (e.key === 'Enter') openConversation(row.id); };
      list.append(item);
    }
  } catch (error) {
    $('history-list').innerHTML = '<div class="history-empty">历史对话暂时无法加载</div>';
    $('status').textContent = error.message;
  }
}

function resetChat() {
  state.conversationId = null;
  state.attachments = [];
  $('messages').replaceChildren();
  $('welcome').hidden = false;
  $('chat-title').textContent = '';
  $('prompt').value = '';
  $('status').textContent = '';
  renderAttachments();
  document.querySelectorAll('.history-row').forEach(el => el.classList.remove('selected'));
}

async function newChat() {
  if (state.busy) return;
  try {
    const created = await api('/api/conversations', {method:'POST'});
    resetChat();
    state.conversationId = created.id;
    await loadHistory();
    $('prompt').focus();
  } catch (error) { toast(error.message); }
}

function addMessage(message) {
  const el = document.createElement('div');
  el.className = `message ${message.role}`;
  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.textContent = message.role === 'user' ? '我' : 'AI';
  const body = document.createElement('div');
  body.className = 'message-body';
  const text = document.createElement('div');
  text.className = 'message-text';
  setMessageText(text, message);
  body.append(text);
  if (message.attachments?.length) {
    const files = document.createElement('div');
    files.className = 'message-files';
    for (const file of message.attachments) {
      const link = document.createElement('a');
      link.className = 'message-file';
      link.href = `/api/attachments/${file.id}`;
      link.textContent = file.filename;
      files.append(link);
    }
    body.append(files);
  }
  if (message.thinking_mode === 'deep') {
    const meta = document.createElement('div');
    meta.className = 'message-meta';
    meta.textContent = '深度思考';
    body.append(meta);
  }
  el.append(avatar, body);
  $('messages').append(el);
  $('chat-scroll').scrollTop = $('chat-scroll').scrollHeight;
  return el;
}

function setMessageText(element, message) {
  if (message.role === 'assistant' && typeof message.html === 'string') {
    element.classList.add('markdown');
    element.innerHTML = message.html;
    element.querySelectorAll('a[href]').forEach(link => {
      try {
        const protocol = new URL(link.href, location.origin).protocol;
        if (!['http:', 'https:', 'mailto:'].includes(protocol)) { link.removeAttribute('href'); return; }
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      } catch { link.removeAttribute('href'); }
    });
  } else {
    element.classList.remove('markdown');
    element.textContent = message.content || (message.attachments?.length ? '请分析上传的材料' : '');
  }
}

async function openConversation(id) {
  if (state.busy) return;
  try {
    const conversation = await api(`/api/conversations/${id}`);
    resetChat();
    state.conversationId = id;
    $('chat-title').textContent = conversation.title === '新对话' ? '' : conversation.title;
    $('welcome').hidden = conversation.messages.length > 0;
    for (const message of conversation.messages) addMessage(message);
    await loadHistory();
  } catch (error) { toast(error.message); }
}

function renderAttachments() {
  const box = $('attachments');
  box.replaceChildren();
  state.attachments.forEach((file, index) => {
    const chip = document.createElement('div');
    chip.className = 'attachment-chip';
    const name = document.createElement('span');
    name.textContent = file.filename;
    const remove = document.createElement('button');
    remove.textContent = '×';
    remove.title = '移除附件';
    remove.onclick = () => { state.attachments.splice(index, 1); renderAttachments(); };
    chip.append(name, remove);
    box.append(chip);
  });
}

async function uploadFiles(files) {
  if (state.busy || !files.length) return;
  try {
    if (!state.conversationId) {
      const created = await api('/api/conversations', {method:'POST'});
      state.conversationId = created.id;
      await loadHistory();
    }
    for (const file of files) {
      if (state.attachments.length >= 8) { toast('每次最多添加 8 个附件'); break; }
      const form = new FormData();
      form.append('file', file);
      $('status').textContent = `正在上传 ${file.name}...`;
      const saved = await api(`/api/conversations/${state.conversationId}/attachments`, {method:'POST', body:form});
      state.attachments.push(saved);
      renderAttachments();
    }
    $('status').textContent = '';
  } catch (error) { $('status').textContent = error.message; }
}

async function send() {
  if (state.busy) return;
  const content = $('prompt').value.trim();
  if (!content && !state.attachments.length) { $('status').textContent = '请输入问题或添加附件'; return; }
  state.busy = true;
  $('send').disabled = true;
  $('status').textContent = '';
  try {
    if (!state.conversationId) {
      const created = await api('/api/conversations', {method:'POST'});
      state.conversationId = created.id;
    }
    const localFiles = [...state.attachments];
    const data = {content, attachment_ids:localFiles.map(x => x.id), thinking_mode:'normal'};
    $('welcome').hidden = true;
    const userEl = addMessage({role:'user', content, attachments:localFiles, thinking_mode:data.thinking_mode});
    $('prompt').value = '';
    state.attachments = [];
    renderAttachments();
    const pending = addMessage({role:'assistant', content:'正在生成回复…'});
    try {
      const result = await api(`/api/conversations/${state.conversationId}/messages`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
      setMessageText(pending.querySelector('.message-text'), result.assistant_message);
      await loadHistory();
      $('chat-title').textContent = content.slice(0,80) || '附件对话';
    } catch (error) {
      pending.remove();
      userEl.remove();
      if (error.message.includes('提问已保存')) {
        await openConversationAfterError(state.conversationId);
      } else {
        $('prompt').value = content;
        state.attachments = localFiles;
        renderAttachments();
      }
      $('status').textContent = error.message;
    }
  } catch (error) { $('status').textContent = error.message; }
  finally { state.busy = false; $('send').disabled = false; $('prompt').focus(); }
}

async function openConversationAfterError(id) {
  try {
    const conversation = await api(`/api/conversations/${id}`);
    $('messages').replaceChildren();
    for (const message of conversation.messages) addMessage(message);
    await loadHistory();
  } catch {}
}

$('new-chat').onclick = newChat;
$('history-query').oninput = () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(loadHistory, 220); };
$('attach-file').onclick = () => $('file-input').click();
$('attach-image').onclick = () => $('image-input').click();
$('file-input').onchange = e => { uploadFiles([...e.target.files]); e.target.value = ''; };
$('image-input').onchange = e => { uploadFiles([...e.target.files]); e.target.value = ''; };
$('send').onclick = send;
$('prompt').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } };
document.querySelectorAll('[data-coming]').forEach(el => el.onclick = () => toast(`${el.dataset.coming}将在后续页面开发`));
document.addEventListener('click', e => { if (!e.target.closest('.row-menu')) document.querySelectorAll('.menu-pop').forEach(el => el.remove()); });
async function bootChat() {
  await loadHistory();
  const conversationId = new URLSearchParams(location.search).get('conversation');
  if (conversationId) await openConversation(conversationId);
  const homePrompt = sessionStorage.getItem('home-prompt');
  if (homePrompt) {
    sessionStorage.removeItem('home-prompt');
    $('prompt').value = homePrompt;
    try {
      const health = await api('/api/health');
      if (health.database === 'ready' && health.model === 'ready') await send();
      else $('status').textContent = '问题已带入对话；配置 AI 模型后可点击发送。';
    } catch { $('status').textContent = '问题已带入对话，请点击发送。'; }
  }
}
bootChat();
fetch('/api/health').then(r => r.json()).then(data => {
  if (data.database !== 'ready') $('status').textContent = 'MySQL 未连接：请检查 .env 配置';
  else if (data.model !== 'ready') $('status').textContent = 'DeepSeek 尚未配置：请填写 .env 中的 DEEPSEEK_API_KEY 并重启服务';
}).catch(() => {});
