(() => {
  const ui = window.TaskUI;
  const list = document.getElementById('reading-tasks');
  const search = document.getElementById('task-search');
  const status = document.getElementById('task-status');
  let tasks = [], busy = false;
  async function action(kind, task) {
    try {
      if (kind === 'view') {
        if (task.kind === 'search') location.href = `/search?task=${encodeURIComponent(task.id)}`;
        else if (task.kind === 'chat') location.href = `/chat?conversation=${encodeURIComponent(task.id)}`;
        else location.href = `/reading?task=${encodeURIComponent(task.id)}`;
        return;
      }
      if (kind === 'retry') await ui.retry(task.id);
      if (kind === 'delete') {
        if (!confirm(`删除“${task.title}”及其精读结果？`)) return;
        await ui.remove(task.id);
      }
      await refresh();
    } catch (error) { ui.toast(error.message); }
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const recent = await ui.api('/api/home/recent?limit=100');
      const all = recent.map(task => ({...task, source_label:{search:'文献检索',reading:'文献精读',chat:'AI 对话'}[task.kind], created_at:task.happened_at}));
      const q = search.value.trim().toLocaleLowerCase();
      const filtered = all.filter(task => (status.value === 'all' || task.status === status.value) &&
        (!q || `${task.title} ${task.source_label}`.toLocaleLowerCase().includes(q)));
      const demo = ui.filteredDemoTasks(search.value, status.value);
      const allDemo = ui.demoTasks;
      tasks = [...filtered, ...demo];
      ui.renderRows(list, tasks, null, action);
      document.getElementById('task-count').textContent = `共 ${tasks.length} 条（含 ${demo.length} 条模拟）`;
      const combined = [...all, ...allDemo];
      document.getElementById('all-count').textContent = combined.length;
      document.getElementById('done-count').textContent = combined.filter(task => task.status === 'completed').length;
      document.getElementById('active-count').textContent = combined.filter(task => ['queued','processing'].includes(task.status)).length;
      document.getElementById('failed-count').textContent = combined.filter(task => task.status === 'failed').length;
    } catch (error) {
      ui.error(list, error.message);
      document.getElementById('task-count').textContent = '无法读取任务';
      ['all-count','done-count','active-count','failed-count'].forEach(id => { document.getElementById(id).textContent = '—'; });
    }
    finally { busy = false; }
  }
  let timer;
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(refresh, 250); });
  status.addEventListener('change', refresh);
  document.querySelectorAll('[data-coming]').forEach(button => button.addEventListener('click', () => ui.toast(`${button.dataset.coming}页面尚未开发`)));
  refresh();
  setInterval(() => { if (tasks.some(task => !task.is_demo && task.kind === 'reading' && ['queued','processing'].includes(task.status))) refresh(); }, 4000);
})();
