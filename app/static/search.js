const el = id => document.getElementById(id);
const PAGE_SIZE = 10;
const state = { items: [], selected: new Set(), total: 0, page: 1, loading: false, zoteroReady: false };

function showToast(message) {
  const box = el('toast');
  box.textContent = message;
  box.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => box.classList.remove('show'), 2800);
}

function svg(name) {
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  icon.append(use);
  return icon;
}

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function updateSelected() {
  const visible = pageItems();
  el('selected-count').textContent = `已选择 ${state.selected.size} 篇`;
  el('select-all').checked = visible.length > 0 && visible.every(item => state.selected.has(item.id));
  el('select-all').indeterminate = visible.some(item => state.selected.has(item.id)) && !el('select-all').checked;
  el('archive-button').disabled = state.selected.size === 0 || state.loading;
  el('zotero-button').disabled = state.selected.size === 0 || state.loading || !state.zoteroReady;
  el('reading-button').disabled = state.selected.size === 0 || state.loading;
  el('reading-button').title = state.selected.size > 1 ? '一次只能选择一篇文献精读' : '选择一篇文献创建精读任务';
}

function filteredItems() {
  const keyword = el('filter-results').value.trim().toLocaleLowerCase();
  if (!keyword) return state.items;
  return state.items.filter(item => `${item.title} ${item.authors} ${item.abstract}`.toLocaleLowerCase().includes(keyword));
}

function pageItems() {
  return filteredItems().slice((state.page - 1) * PAGE_SIZE, state.page * PAGE_SIZE);
}

function setPage(page) {
  const pageCount = Math.max(1, Math.ceil(filteredItems().length / PAGE_SIZE));
  state.page = Math.min(Math.max(page, 1), pageCount);
  render();
  el('results').scrollIntoView({block: 'start', behavior: 'smooth'});
}

function renderPagination(total) {
  const pagination = el('results-pagination');
  pagination.replaceChildren();
  if (total <= PAGE_SIZE) return;
  const count = Math.ceil(total / PAGE_SIZE);
  const summary = node('span', 'page-summary', `第 ${state.page} / ${count} 页 · 显示 ${(state.page - 1) * PAGE_SIZE + 1}–${Math.min(state.page * PAGE_SIZE, total)} 篇，共 ${total} 篇`);
  const controls = node('div', 'page-controls');
  const button = (text, page, disabled = false, current = false) => {
    const item = node('button', current ? 'current' : '', text);
    item.type = 'button';
    item.disabled = disabled;
    if (current) item.setAttribute('aria-current', 'page');
    item.setAttribute('aria-label', text === '上一页' || text === '下一页' ? text : `第 ${page} 页`);
    item.onclick = () => setPage(page);
    controls.append(item);
  };
  button('上一页', state.page - 1, state.page === 1);
  for (let page = 1; page <= count; page++) button(String(page), page, false, page === state.page);
  button('下一页', state.page + 1, state.page === count);
  pagination.append(summary, controls);
}

function makeBadge(text, extra = '') { return node('span', `paper-badge ${extra}`, text); }

function makeAction(label, icon, className, handler, disabled = false, title = '') {
  const button = node('button', className);
  button.type = 'button';
  button.append(svg(icon), document.createTextNode(label));
  button.disabled = disabled;
  button.title = title || label;
  if (handler) button.onclick = handler;
  return button;
}

function makePaper(item, index) {
  const outer = node('article', 'paper');
  const row = node('div', 'paper-row');
  const check = node('input');
  check.type = 'checkbox';
  check.checked = state.selected.has(item.id);
  check.setAttribute('aria-label', `选择 ${item.title}`);
  check.onchange = () => { check.checked ? state.selected.add(item.id) : state.selected.delete(item.id); updateSelected(); };
  const number = node('span', 'paper-index', String(index + 1));
  const main = node('div', 'paper-main');
  main.append(node('div', 'paper-title', item.title));
  const badges = node('div', 'paper-badges');
  badges.append(makeBadge(item.year ? String(item.year) : '年份未注明'), makeBadge(item.source), makeBadge(item.document_type, 'blue'));
  if (item.is_mock) badges.append(makeBadge('模拟数据', 'amber'));
  main.append(badges, node('div', 'paper-meta', `${item.authors} · ${item.venue} · ${item.year}`));
  const actions = node('div', 'paper-actions');
  actions.append(makeAction('查看原文', 'link', '', () => window.open(item.url, '_blank', 'noopener,noreferrer'), !item.url, item.url ? '打开来源页面' : '暂无原文链接'));
  actions.append(makeAction('PDF下载', 'file', '', () => window.open(item.pdf_url, '_blank', 'noopener,noreferrer'), !item.pdf_url, item.pdf_url ? '打开 PDF 资源链接' : '暂无公开 PDF 链接'));
  actions.append(makeAction('引用', 'quote', 'cite', async () => {
    const citation = `${item.is_mock ? '[模拟数据，不能用于正式引用] ' : '[检索记录，请核对原文] '}${item.authors}. ${item.title}. ${item.venue}, ${item.year || '年份未注明'}. ${item.doi ? `DOI: ${item.doi}.` : ''}`;
    try { await navigator.clipboard.writeText(citation); showToast(item.is_mock ? '已复制模拟引用（不可用于正式论文）' : '已复制检索记录，请核对原文信息'); }
    catch { showToast(citation); }
  }));
  const expand = makeAction('展开分析', 'down', 'expand', () => {
    const open = outer.classList.toggle('expanded');
    expand.lastChild.textContent = open ? '收起分析' : '展开分析';
    expand.setAttribute('aria-expanded', String(open));
  });
  expand.setAttribute('aria-expanded', 'false');
  actions.append(expand);
  row.append(check, number, main, actions);
  const panel = node('div', 'analysis-panel');
  panel.append(node('div', 'analysis-note', `分析依据：${item.analysis.basis}。${item.is_mock ? '以下内容仅用于演示，不可作为真实文献结论。' : '未读取全文的栏目会明确标注信息不足。'}`));
  const grid = node('div', 'analysis-grid');
  for (const [title, value] of [
    ['简要摘要', item.analysis.summary],
    ['研究目的', item.analysis.purpose],
    ['研究方法', item.analysis.method],
    ['实证过程', item.analysis.empirical_process],
  ]) {
    const block = node('div', 'analysis-block');
    block.append(node('h3', '', title), node('p', '', value));
    grid.append(block);
  }
  panel.append(grid);
  outer.append(row, panel);
  return outer;
}

function render() {
  const list = el('results');
  list.replaceChildren();
  const filtered = filteredItems();
  state.page = Math.min(state.page, Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)));
  const items = pageItems();
  el('result-count').textContent = `（${filtered.length} 篇）`;
  if (!filtered.length) {
    const empty = node('div', 'empty-results');
    empty.append(node('strong', '', state.items.length ? '当前结果中没有匹配项' : '没有找到匹配的文献'), node('span', '', '可调整关键词、年份或文献类型后重试。'));
    list.append(empty);
  } else {
    items.forEach((item, index) => list.append(makePaper(item, (state.page - 1) * PAGE_SIZE + index)));
  }
  renderPagination(filtered.length);
  updateSelected();
}

function applySearchResult(data, language, restored = false) {
  state.items = data.items || [];
  state.total = data.total || state.items.length;
  state.page = 1;
  state.selected.clear();
  el('filter-results').value = '';
  const typeLabel = language === 'zh' ? '中文' : language === 'en' ? '英文' : '历史检索';
  el('result-summary').textContent = data.mock
    ? `历史模拟数据匹配 ${data.total} 篇，展示 ${data.returned} 篇${restored ? ' · 历史任务' : ''}`
    : `${typeLabel}文献 · ${data.provider || '检索服务'} 返回 ${data.returned} 篇（估计总量 ${data.total} 篇）${restored === 'latest' ? ' · 最近一次检索' : restored ? ' · 历史任务快照' : ''}${data.warning ? ` · ${data.warning}` : ''}`;
  el('source-mode-title').textContent = data.mock ? '模拟数据模式' : '实时检索模式';
  el('source-mode-text').textContent = data.mock ? '这是旧任务的本地模拟记录，不可正式引用。' : '优先使用 OpenAlex，结果不足或服务不可用时由 SerpApi 补充。分析仅根据检索元数据与摘要，需以原文核实。';
  el('sort-note').textContent = el('sort').selectedOptions[0].textContent;
  render();
}

async function search(event) {
  if (event) event.preventDefault();
  if (state.loading) return;
  const query = el('query').value.trim();
  const language = document.querySelector('input[name="language"]:checked')?.value;
  const yearFrom = Number(el('year-from').value);
  const yearTo = Number(el('year-to').value);
  if (query.length < 2) { showToast('请至少输入 2 个字符'); el('query').focus(); return; }
  if (!language) { showToast('请选择中文或英文文献'); return; }
  if (yearFrom > yearTo) { showToast('起始年份不能晚于结束年份'); return; }
  state.loading = true;
  el('search-button').disabled = true;
  el('search-button').lastChild.textContent = '检索中...';
  try {
    const response = await fetch('/api/search', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({query, language, year_from:yearFrom, year_to:yearTo, count:Number(el('count').value), sort:el('sort').value, record:Boolean(event)}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '检索失败');
    applySearchResult(data, language);
    if (data.search_task_id) history.replaceState({}, '', `/search?task=${encodeURIComponent(data.search_task_id)}`);
  } catch (error) {
    showToast(error.message);
  } finally {
    state.loading = false;
    el('search-button').disabled = false;
    el('search-button').lastChild.textContent = '开始检索';
  }
}

for (let year = 2015; year <= new Date().getFullYear(); year++) {
  for (const id of ['year-from', 'year-to']) {
    const option = node('option', '', String(year));
    option.value = String(year);
    el(id).append(option);
  }
}
el('year-from').value = '2020';
el('year-to').value = String(new Date().getFullYear());
el('query-count').textContent = `${el('query').value.length}/200`;
el('query').oninput = () => { el('query-count').textContent = `${el('query').value.length}/200`; };
el('search-form').onsubmit = search;
el('filter-results').oninput = () => { state.page = 1; render(); };
el('select-all').onchange = event => {
  for (const item of pageItems()) event.target.checked ? state.selected.add(item.id) : state.selected.delete(item.id);
  render();
};
el('archive-button').onclick = async () => {
  if (!state.selected.size || state.loading) return;
  const dialog = el('import-dialog');
  el('import-summary').textContent = `已选择 ${state.selected.size} 篇文献，请指定保存主题。${state.items.some(item => state.selected.has(item.id) && item.is_mock) ? '模拟数据仍会明确标记。' : '检索元数据请以原文核对。'}`;
  el('import-error').textContent = '';
  try {
    const response = await fetch('/api/library/topics');
    const topics = await response.json();
    if (!response.ok) throw new Error(topics.detail || '无法读取主题');
    const container = el('existing-topics'); container.replaceChildren();
    topics.forEach((topic, index) => {
      const label = node('label', 'topic-option');
      const input = node('input'); input.type = 'radio'; input.name = 'topic_id'; input.value = topic.id; input.checked = index === 0;
      label.append(input, node('span', '', topic.name), node('small', '', `${topic.paper_count} 篇`));
      container.append(label);
    });
    setImportTab('existing');
    dialog.showModal();
  } catch (error) { showToast(error.message); }
};
let importTab = 'existing';
function setImportTab(tab) {
  importTab = tab;
  document.querySelectorAll('[data-import-tab]').forEach(button => button.classList.toggle('active', button.dataset.importTab === tab));
  el('existing-topics').hidden = tab !== 'existing';
  el('new-topic').hidden = tab !== 'new';
  el('import-error').textContent = '';
}
document.querySelectorAll('[data-import-tab]').forEach(button => button.onclick = () => setImportTab(button.dataset.importTab));
el('import-close').onclick = el('import-cancel').onclick = () => el('import-dialog').close();
el('import-form').onsubmit = async event => {
  event.preventDefault();
  const button = el('import-confirm'); button.disabled = true; button.textContent = '正在导入…';
  try {
    let topicId = document.querySelector('input[name="topic_id"]:checked')?.value;
    if (importTab === 'new') {
      const name = el('new-topic-name').value.trim();
      if (!name) throw new Error('请输入新主题名称');
      const response = await fetch('/api/library/topics', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      const topic = await response.json();
      if (!response.ok) throw new Error(topic.detail || '创建主题失败');
      topicId = topic.id;
    }
    if (!topicId) throw new Error('请选择一个主题');
    const response = await fetch('/api/library/import', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[...state.selected],topic_id:topicId})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '导入失败');
    state.selected.clear(); render(); el('import-dialog').close();
    showToast(`已导入 ${data.imported} 篇，${data.already_exists} 篇已存在并归入所选主题`);
  } catch (error) { el('import-error').textContent = error.message; }
  finally { button.disabled = false; button.textContent = '确认导入'; }
};
el('zotero-button').onclick = async () => {
  if (!state.selected.size || !state.zoteroReady) return;
  const button = el('zotero-button');
  button.disabled = true; button.textContent = '正在导入…';
  try {
    const response = await fetch('/api/zotero/search/import', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[...state.selected]})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '导入 Zotero 失败');
    showToast(`已保存 ${data.imported} 篇到 Zotero「${data.collection}」，${data.already_exists} 篇已存在`);
  } catch (error) { showToast(error.message); }
  finally { button.textContent = '导入 Zotero'; updateSelected(); }
};
el('reading-button').onclick = async () => {
  if (state.selected.size !== 1) { showToast('每次只能选择一篇文献进行精读'); return; }
  const paper = state.items.find(item => state.selected.has(item.id));
  if (!paper) { showToast('请重新选择文献'); return; }
  if (paper.is_mock) { showToast('模拟文献没有真实原文，请在文献精读页上传 PDF'); return; }
  if (!paper.doi && !paper.pdf_url) { showToast('这篇文献没有可获取的 DOI 或 PDF 链接，请上传原文 PDF'); return; }
  const button = el('reading-button');
  button.disabled = true; button.textContent = '正在创建…';
  try {
    const response = await fetch('/api/reading/from-search', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id:paper.id}),
    });
    const task = await response.json();
    if (!response.ok) throw new Error(task.detail || '创建精读任务失败');
    location.href = `/reading?task=${encodeURIComponent(task.id)}`;
  } catch (error) { showToast(error.message); button.textContent = '精读文献'; updateSelected(); }
};
document.querySelectorAll('[data-coming]').forEach(item => item.onclick = () => showToast(`${item.dataset.coming}将在后续页面开发`));
async function startSearchPage() {
  try {
    const settings = await fetch('/api/settings').then(response => response.json());
    if (settings.search_count) el('count').value = String(settings.search_count);
    if (settings.literature_language === 'en') document.querySelector('input[name="language"][value="en"]').checked = true;
    const response = await fetch('/api/zotero/status');
    const zotero = await response.json();
    state.zoteroReady = Boolean(zotero.connected);
    el('zotero-button').title = zotero.connected ? '保存选中文献到 Zotero；模拟条目会标注不可正式引用' : '请先在设置中连接 Zotero';
    updateSelected();
  } catch { /* Settings remain at their page defaults. */ }
  const taskId = new URLSearchParams(location.search).get('task');
  try {
      const response = await fetch(taskId ? `/api/search-history/${encodeURIComponent(taskId)}` : '/api/search-history/latest');
      const task = await response.json();
      if (!response.ok) throw new Error(task.detail || '无法恢复检索结果');
      if (!task) return;
      el('query').value = task.query_text;
      el('query-count').textContent = `${task.query_text.length}/200`;
      const language = task.sources.includes('en') ? 'en' : task.sources.includes('zh') ? 'zh' : task.result?.language || 'zh';
      document.querySelector(`input[name="language"][value="${language}"]`).checked = true;
      el('year-from').value = String(task.year_from);
      el('year-to').value = String(task.year_to);
      el('count').value = String(task.requested_count);
      el('sort').value = task.sort_order;
      if (task.result) {
        applySearchResult(task.result, language, taskId ? 'history' : 'latest');
        return;
      }
      el('result-summary').textContent = '此检索任务创建时尚未保存结果，请点击“开始检索”重新获取。';
      return;
  } catch (error) { showToast(error.message); }
}
startSearchPage();
