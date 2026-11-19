(() => {
  const ui = window.TaskUI;
  const list = document.getElementById('reading-tasks');
  const count = document.getElementById('task-count');
  const search = document.getElementById('task-search');
  const status = document.getElementById('task-status');
  const content = document.getElementById('result-content');
  const label = document.getElementById('result-task-label');
  const form = document.getElementById('reading-form');
  const formError = document.getElementById('form-error');
  const templateRequired = document.getElementById('template-required');
  const doiInput = document.getElementById('doi-input');
  const fileInput = document.getElementById('pdf-input');
  const fileName = document.getElementById('file-name');
  const submit = form.querySelector('[type=submit]');
  let mode = 'reference', selectedId = new URLSearchParams(location.search).get('task'), selectedTab = 'original';
  let tasks = [], busy = false, detailRequest = 0;
  const zoteroButton = document.getElementById('reading-zotero');
  let zoteroReady = false;
  fetch('/api/settings').then(response => response.json()).then(data => {
    templateRequired.hidden = Boolean(data.report_template_filename);
  }).catch(() => {});
  fetch('/api/zotero/status').then(response => response.json()).then(data => { zoteroReady = Boolean(data.connected); }).catch(() => {});
  zoteroButton.addEventListener('click', async () => {
    if (!selectedId) return;
    zoteroButton.disabled = true; zoteroButton.textContent = '正在归档精读文件…';
    try {
      const response = await fetch(`/api/zotero/reading/${encodeURIComponent(selectedId)}/import`, {method:'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '归档失败');
      ui.toast(`已归档至 Zotero「${data.collection}」，新增 ${data.uploaded} 份 PDF`);
    } catch (error) { ui.toast(error.message); }
    finally { zoteroButton.disabled = false; zoteroButton.textContent = '归档至 Zotero 每周精读文献'; }
  });

  function setMode(next) {
    mode = next;
    document.getElementById('doi-tab').classList.toggle('active', mode === 'reference');
    document.getElementById('file-tab').classList.toggle('active', mode === 'file');
    doiInput.hidden = mode !== 'reference';
    document.getElementById('upload-zone').hidden = mode !== 'file';
    formError.textContent = '';
  }
  document.getElementById('doi-tab').addEventListener('click', () => setMode('reference'));
  document.getElementById('file-tab').addEventListener('click', () => setMode('file'));
  fileInput.addEventListener('change', () => { fileName.textContent = fileInput.files[0]?.name || '选择 PDF 文件（最大 10 MB）'; });
  document.querySelectorAll('[data-result-tab]').forEach(button => button.addEventListener('click', () => {
    selectedTab = button.dataset.resultTab;
    document.querySelectorAll('[data-result-tab]').forEach(tab => tab.classList.toggle('active', tab === button));
    loadDetail();
  }));

  function placeholder(message, error = false) {
    content.replaceChildren();
    const el = document.createElement('div');
    el.className = `result-placeholder${error ? ' result-error' : ''}`;
    el.textContent = message;
    content.append(el);
  }
  function showPdf(name, url, downloadUrl, frameTitle) {
    const toolbar = document.createElement('div'); toolbar.className = 'pdf-toolbar';
    const title = document.createElement('span'); title.textContent = name;
    const view = document.createElement('a'); view.href = url; view.target = '_blank'; view.rel = 'noopener'; view.textContent = '新窗口查看';
    const download = document.createElement('a'); download.href = downloadUrl; download.textContent = '下载 PDF';
    toolbar.append(title, view, download);
    const frame = document.createElement('iframe'); frame.className = 'pdf-frame'; frame.title = frameTitle; frame.src = url;
    content.append(toolbar, frame);
  }
  async function loadDetail() {
    const request = ++detailRequest;
    zoteroButton.hidden = true;
    if (!selectedId) { label.textContent = ''; placeholder('选择一条任务查看精读结果'); return; }
    const demo = ui.demoTasks.find(task => task.id === selectedId);
    if (demo) {
      label.textContent = demo.title;
      placeholder('这是模拟任务记录，仅用于展示列表和状态。没有真实原文 PDF、中文翻译或阅读报告。上传 PDF 或输入 DOI 后可创建真实任务。');
      return;
    }
    placeholder('正在加载任务…');
    try {
      const task = await ui.api(`/api/reading-tasks/${encodeURIComponent(selectedId)}`);
      if (request !== detailRequest) return;
      label.textContent = task.title || '';
      content.replaceChildren();
      const translationTab = document.querySelector('[data-result-tab="translation"]');
      translationTab.hidden = task.document_language === 'zh';
      if (translationTab.hidden && selectedTab === 'translation') {
        selectedTab = 'report';
        document.querySelectorAll('[data-result-tab]').forEach(tab => tab.classList.toggle('active', tab.dataset.resultTab === selectedTab));
      }
      zoteroButton.hidden = task.status !== 'completed';
      zoteroButton.title = zoteroReady ? (task.document_language === 'zh' ? '保存原文与阅读报告 PDF' : '保存原文、中文版与阅读报告 PDF') : '请先在设置中连接 Zotero';
      if (selectedTab === 'original' && task.has_original_pdf) {
        const url = `/api/reading-tasks/${encodeURIComponent(task.id)}/pdf`;
        showPdf(`${task.title}.pdf`, url, `${url}?download=true`, '论文原文 PDF');
      } else if (selectedTab === 'translation' && (task.has_translation_pdf || task.translation)) {
        const url = `/api/reading-tasks/${encodeURIComponent(task.id)}/translation.pdf`;
        showPdf(`${task.translated_title || task.title}.pdf`, url, `${url}?download=true`, '中文版 PDF');
      } else if (task.status === 'queued' || task.status === 'processing') {
        const stages = {acquiring:'正在获取 PDF', extracting:'正在提取全文', translating:`正在逐段翻译（${task.completed_segments || 0}/${task.total_segments || 0}）`, reporting:'正在递进阅读并生成报告'};
        placeholder(task.status === 'queued' ? '任务正在排队，页面会自动更新。' : `${stages[task.stage] || '正在提取论文文字'}，页面会自动更新。`);
      } else if (task.status === 'failed') {
        const box = document.createElement('div');
        box.className = 'result-error';
        box.textContent = task.error_message || '任务处理失败';
        const button = document.createElement('button');
        button.type = 'button'; button.textContent = '重试任务'; button.className = 'inline-action';
        button.addEventListener('click', async () => { try { await ui.retry(task.id); await refresh(); } catch (error) { ui.toast(error.message); } });
        box.append(document.createElement('br'), button);
        content.append(box);
      } else if (selectedTab === 'original') {
        placeholder('原文 PDF 尚未取得。');
      } else if (selectedTab === 'translation') {
        placeholder(task.document_language === 'zh' ? '这篇论文为中文，无需翻译。' : '中文版 PDF 尚未生成。');
      } else {
        const isPdf = task.output_format === 'pdf';
        const extension = ({markdown:'md',pdf:'pdf',docx:'docx',xlsx:'xlsx'})[task.output_format] || 'md';
        const formatLabel = ({md:'Markdown',pdf:'PDF',docx:'Word',xlsx:'Excel'})[extension];
        const download = document.createElement('a');
        download.className = 'generated-download';
        const reportUrl = `/api/reading-tasks/${encodeURIComponent(task.id)}/report.${extension}`;
        download.href = isPdf ? `${reportUrl}?download=true` : reportUrl;
        download.textContent = `下载阅读报告 ${formatLabel}`;
        content.append(download);
        if (isPdf) {
          const frame = document.createElement('iframe'); frame.className = 'pdf-frame';
          frame.title = '阅读报告 PDF';
          frame.src = reportUrl; content.append(frame);
        } else {
          const text = document.createElement('div'); text.className = 'text-result markdown-body';
          text.innerHTML = task.report_html || '';
          content.append(text);
        }
      }
    } catch (error) { if (request === detailRequest) placeholder(error.message, true); }
  }
  async function action(kind, task) {
    try {
      if (kind === 'view') {
        selectedId = task.id;
        history.replaceState({}, '', `/reading?task=${encodeURIComponent(selectedId)}`);
        ui.renderRows(list, tasks, selectedId, action);
        await loadDetail();
      } else if (kind === 'retry') { await ui.retry(task.id); await refresh(); }
      else if (kind === 'delete' && confirm(`删除“${task.title}”及其精读结果？`)) {
        await ui.remove(task.id);
        if (selectedId === task.id) { selectedId = null; history.replaceState({}, '', '/reading'); loadDetail(); }
        await refresh();
      }
    } catch (error) { ui.toast(error.message); }
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const params = new URLSearchParams({q:search.value.trim(), status:status.value});
      const realTasks = await ui.api(`/api/reading-tasks?${params}`);
      const demo = ui.filteredDemoTasks(search.value, status.value);
      tasks = [...realTasks, ...demo];
      count.textContent = `共 ${tasks.length} 条（含 ${demo.length} 条模拟）`;
      ui.renderRows(list, tasks, selectedId, action);
      if (selectedId) await loadDetail();
    } catch (error) { ui.error(list, error.message); count.textContent = '无法读取任务'; if (selectedId) placeholder(error.message, true); }
    finally { busy = false; }
  }
  let searchTimer;
  search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(refresh, 250); });
  status.addEventListener('change', refresh);
  form.addEventListener('submit', async event => {
    event.preventDefault(); formError.textContent = '';
    const data = new FormData();
    if (mode === 'file') {
      const file = fileInput.files[0];
      if (!file) { formError.textContent = '请选择 PDF 文件'; return; }
      if (!file.name.toLowerCase().endsWith('.pdf')) { formError.textContent = '仅支持 PDF 文件'; return; }
      if (file.size > 10 * 1024 * 1024) { formError.textContent = 'PDF 不能超过 10 MB'; return; }
      data.set('file', file);
    } else {
      const reference = doiInput.value.trim();
      if (!reference) { formError.textContent = '请输入 DOI 或论文链接'; return; }
      data.set('reference', reference);
    }
    submit.disabled = true; submit.textContent = '正在创建…';
    try {
      const task = await ui.api('/api/reading-tasks', {method:'POST', body:data});
      selectedId = task.id; history.replaceState({}, '', `/reading?task=${encodeURIComponent(task.id)}`);
      templateRequired.hidden = true;
      ui.toast('任务已创建');
      await refresh();
    } catch (error) { formError.textContent = error.message; }
    finally { submit.disabled = false; submit.textContent = '开始精读'; }
  });
  document.querySelectorAll('[data-coming]').forEach(button => button.addEventListener('click', () => ui.toast(`${button.dataset.coming}页面尚未开发`)));
  refresh();
  setInterval(() => { if (tasks.some(task => !task.is_demo && ['queued','processing'].includes(task.status))) refresh(); }, 4000);
})();
