(() => {
  const ui = window.TaskUI;
  const hour = new Date().getHours();
  document.getElementById('greeting').textContent = hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好';
  const form = document.getElementById('home-question-form');
  const question = document.getElementById('home-question');
  const error = document.getElementById('home-question-error');
  form.addEventListener('submit', event => {
    event.preventDefault();
    const value = question.value.trim();
    if (!value) { error.textContent = '请输入研究问题或论文主题'; question.focus(); return; }
    error.textContent = '';
    sessionStorage.setItem('home-prompt', value);
    location.href = '/chat';
  });
  question.addEventListener('input', () => { error.textContent = ''; });
  question.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); } });
  const labels = {completed:'已完成',processing:'进行中',queued:'排队中',failed:'失败'};
  function href(task) {
    if (task.kind === 'search') return `/search?task=${encodeURIComponent(task.id)}`;
    if (task.kind === 'chat') return `/chat?conversation=${encodeURIComponent(task.id)}`;
    return `/reading?task=${encodeURIComponent(task.id)}`;
  }
  function row(task) {
    const link = document.createElement('a'); link.className = 'home-recent-row'; link.href = href(task);
    const icon = document.createElement('span'); icon.className = `recent-icon ${task.kind}`;
    icon.innerHTML = `<svg><use href="#i-${task.kind === 'search' ? 'search' : task.kind === 'chat' ? 'chat' : 'file'}"/></svg>`;
    const copy = document.createElement('span'); copy.className = 'recent-copy';
    const title = document.createElement('strong'); title.textContent = task.title;
    if (task.is_demo) { const mark = document.createElement('em'); mark.className = 'home-demo-mark'; mark.textContent = '模拟'; title.append(mark); }
    const meta = document.createElement('small');
    meta.textContent = `${{search:'文献检索',reading:'文献精读',chat:'AI 对话'}[task.kind]} · ${ui.date(task.happened_at)}`;
    copy.append(title,meta);
    const status = document.createElement('span'); status.className = `recent-pill ${task.status}`; status.textContent = labels[task.status] || task.status;
    const arrow = document.createElement('svg'); arrow.className = 'recent-arrow'; arrow.innerHTML = '<use href="#i-arrow"/>';
    link.append(icon,copy,status,arrow);
    return link;
  }
  async function loadRecent() {
    const list = document.getElementById('home-recent');
    try {
      const real = await ui.api('/api/home/recent?limit=3');
      const tasks = [...real];
      for (const demo of ui.demoTasks) {
        if (tasks.length >= 3) break;
        tasks.push({...demo,kind:'reading',happened_at:demo.created_at});
      }
      list.replaceChildren(...tasks.map(row));
    } catch (err) {
      list.replaceChildren();
      const empty = document.createElement('div'); empty.className = 'home-recent-empty'; empty.textContent = err.message;
      list.append(empty);
    }
  }
  loadRecent();
})();
