/* Shared, server-backed reading task UI. */
window.TaskUI = (() => {
  const labels = {queued: '排队中', processing: '处理中', completed: '已完成', failed: '失败'};
  const demoTasks = [
    {id:'demo-reading-1', title:'示例：大语言模型长期记忆研究综述', authors:'演示作者 A · 2024', source_label:'arXiv（模拟）', status:'completed', created_at:'2026-10-26T14:30:00', is_demo:true},
    {id:'demo-reading-2', title:'示例：长文本评测方法比较', authors:'演示作者 B · 2024', source_label:'arXiv（模拟）', status:'processing', created_at:'2026-10-25T20:12:00', is_demo:true},
    {id:'demo-reading-3', title:'示例：检索增强与记忆系统设计', authors:'演示作者 C · 2023', source_label:'会议论文（模拟）', status:'completed', created_at:'2026-10-24T16:20:00', is_demo:true},
    {id:'demo-reading-4', title:'示例：研究方法与证据链分析', authors:'演示作者 D · 2024', source_label:'DOI（模拟）', status:'queued', created_at:'2026-10-24T10:15:00', is_demo:true},
    {id:'demo-reading-5', title:'示例：模型、记忆与知识检索', authors:'演示作者 E · 2023', source_label:'PDF 上传（模拟）', status:'failed', created_at:'2026-10-23T18:40:00', is_demo:true},
  ];
  function filteredDemoTasks(query = '', status = 'all') {
    const term = query.trim().toLocaleLowerCase();
    return demoTasks.filter(task => (status === 'all' || task.status === status) &&
      (!term || `${task.title} ${task.authors} ${task.source_label}`.toLocaleLowerCase().includes(term)));
  }
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const date = value => value ? new Date(value).toLocaleString('zh-CN', {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'}) : '—';
  let toastTimer;
  function toast(message) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 4300);
  }
  async function api(path, options = {}) {
    let response;
    try { response = await fetch(path, options); }
    catch { throw new Error('无法连接本地服务，请检查服务是否运行'); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`);
    return data;
  }
  function renderRows(container, tasks, selectedId, onAction) {
    container.replaceChildren();
    if (!tasks.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-tasks';
      empty.textContent = '暂无精读任务。上传 PDF 或输入 DOI 后，任务会显示在这里。';
      container.append(empty);
      return;
    }
    for (const task of tasks) {
      const row = document.createElement('div');
      row.className = `task-row${task.id === selectedId ? ' selected' : ''}`;
      const canManage = !task.is_demo && (!task.kind || task.kind === 'reading');
      row.innerHTML = `<div class="task-info"><svg><use href="#i-file"/></svg><div><div class="task-title" title="${esc(task.title)}">${esc(task.title)}${task.is_demo ? '<span class="demo-task-tag">模拟</span>' : ''}</div><div class="task-author">${esc(task.authors || task.filename || '')}</div></div></div><div class="task-source">${esc(task.source_label)}</div><div class="task-date">${esc(date(task.created_at))}</div><div class="task-status"><span class="status-pill ${esc(task.status)}">${labels[task.status] || esc(task.status)}</span></div><div class="task-actions"><button type="button" data-action="view" aria-label="查看任务">查看</button>${canManage && ['failed','completed'].includes(task.status) ? '<button type="button" data-action="retry">重试</button>' : ''}${canManage ? '<button type="button" data-action="delete" class="remove">删除</button>' : ''}</div>`;
      row.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => onAction(button.dataset.action, task)));
      container.append(row);
    }
  }
  async function retry(id) { await api(`/api/reading-tasks/${encodeURIComponent(id)}/retry`, {method:'POST'}); toast('任务已重新加入队列'); }
  async function remove(id) { await api(`/api/reading-tasks/${encodeURIComponent(id)}`, {method:'DELETE'}); toast('任务已删除'); }
  function error(container, message) {
    container.replaceChildren();
    const el = document.createElement('div');
    el.className = 'empty-tasks result-error';
    el.textContent = message;
    container.append(el);
  }
  return {api, toast, renderRows, retry, remove, error, esc, date, demoTasks, filteredDemoTasks};
})();
