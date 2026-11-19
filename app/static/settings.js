(() => {
  const form = document.getElementById('settings-form');
  const status = document.getElementById('zotero-status');
  const toast = document.getElementById('toast');
  const button = document.getElementById('zotero-connect');
  const disconnect = document.getElementById('zotero-disconnect');
  const templateInput = document.getElementById('report-template-input');
  const templateCurrent = document.getElementById('template-current');
  const templateDownload = document.getElementById('template-download');
  const templateRemove = document.getElementById('template-remove');
  const templateUploadLabel = document.getElementById('template-upload-label');
  function notice(message) { toast.textContent = message; toast.classList.add('show'); clearTimeout(notice.timer); notice.timer = setTimeout(() => toast.classList.remove('show'), 4000); }
  async function api(url, options) { const response = await fetch(url, options); const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败'); return data; }
  function showTemplate(filename, format) {
    templateCurrent.textContent = filename ? `当前模板：${filename}（${String(format).toUpperCase()}）` : '尚未上传模板';
    templateCurrent.classList.toggle('has-file', Boolean(filename));
    templateUploadLabel.textContent = filename ? '更换模板' : '上传模板';
    templateDownload.hidden = !filename; templateRemove.hidden = !filename;
  }
  async function load() {
    try {
      const settings = await api('/api/settings');
      for (const [key, value] of Object.entries(settings)) {
        const control = form.elements.namedItem(key);
        if (!control) continue;
        control.value = value ?? '';
      }
      showTemplate(settings.report_template_filename, settings.report_template_format);
      if (settings.has_avatar) document.getElementById('settings-avatar').style.backgroundImage = 'url(/api/settings/avatar)';
      if (settings.has_avatar) document.getElementById('settings-avatar').textContent = '';
      document.querySelector('.profile strong').textContent = settings.user_name;
    } catch (error) { notice(error.message); }
    check();
  }
  async function check() {
    status.textContent = '检测中…'; status.className = 'connection-pill';
    try {
      const data = await api('/api/zotero/status');
      status.textContent = data.connected ? '● 已连接' : data.running ? '未授权' : '未运行';
      status.className = `connection-pill ${data.connected ? 'connected' : data.running ? '' : 'error'}`;
      button.hidden = data.connected; disconnect.hidden = !data.connected;
      button.title = data.message; status.title = data.message;
      return data;
    } catch (error) { status.textContent = '检测失败'; status.className = 'connection-pill error'; notice(error.message); }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const save = form.querySelector('[type=submit]');
    const data = Object.fromEntries(new FormData(form).entries());
    data.search_count = Number(data.search_count);
    save.disabled = true; document.getElementById('settings-error').textContent = '';
    try { await api('/api/settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}); document.querySelector('.profile strong').textContent = data.user_name; notice('设置已保存'); }
    catch (error) { document.getElementById('settings-error').textContent = error.message; }
    finally { save.disabled = false; }
  });
  document.getElementById('avatar-input').addEventListener('change', async event => {
    const file = event.target.files[0]; if (!file) return;
    const data = new FormData(); data.set('file', file);
    try { await api('/api/settings/avatar', {method:'POST',body:data}); const avatar = document.getElementById('settings-avatar'); avatar.textContent = ''; avatar.style.backgroundImage = `url(/api/settings/avatar?t=${Date.now()})`; notice('头像已更新'); }
    catch (error) { notice(error.message); }
  });
  templateUploadLabel.addEventListener('click', () => { if (!templateInput.disabled) templateInput.click(); });
  templateInput.addEventListener('change', async () => {
    const file = templateInput.files[0]; if (!file) return;
    if (!/\.(md|markdown|pdf|docx|xlsx)$/i.test(file.name)) { notice('模板仅支持 Markdown、PDF、Word（.docx）和 Excel（.xlsx）'); templateInput.value = ''; return; }
    if (file.size > 5 * 1024 * 1024) { notice('模板不能超过 5 MB'); templateInput.value = ''; return; }
    const data = new FormData(); data.set('file', file);
    templateInput.disabled = true;
    try { const result = await api('/api/settings/report-template', {method:'POST',body:data}); showTemplate(result.filename, result.format); notice('阅读报告模板已保存，新建精读任务将使用此模板'); }
    catch (error) { notice(error.message); }
    finally { templateInput.disabled = false; templateInput.value = ''; }
  });
  templateRemove.addEventListener('click', async () => {
    templateRemove.disabled = true;
    try { await api('/api/settings/report-template', {method:'DELETE'}); showTemplate(null, null); notice('模板已移除，新任务默认输出 Markdown'); }
    catch (error) { notice(error.message); }
    finally { templateRemove.disabled = false; }
  });
  button.addEventListener('click', async () => {
    button.disabled = true; button.textContent = '等待 Zotero 授权…';
    try { notice('请在 Zotero 弹窗中选择“始终允许”'); await api('/api/zotero/connect', {method:'POST'}); notice('Zotero 已连接'); await check(); }
    catch (error) { notice(error.message); }
    finally { button.disabled = false; button.textContent = '连接 Zotero'; }
  });
  document.getElementById('zotero-test').addEventListener('click', async () => { const result = await check(); if (result) notice(result.message); });
  disconnect.addEventListener('click', async () => { try { await api('/api/zotero/disconnect', {method:'POST'}); await check(); notice('本地连接已断开'); } catch (error) { notice(error.message); } });
  load();
})();
