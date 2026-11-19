(() => {
  const $ = id => document.getElementById(id);
  const state = {category:'all',topicId:null,papers:[],topics:[],selectedId:null};
  const toast = message => { const box=$('toast'); box.textContent=message; box.classList.add('show'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>box.classList.remove('show'),3500); };
  async function api(url, options) { const response=await fetch(url,options); const data=await response.json().catch(()=>({})); if(!response.ok) throw new Error(data.detail || `请求失败（${response.status}）`); return data; }
  const text = (tag, value, className='') => { const node=document.createElement(tag); node.textContent=value ?? ''; node.className=className; return node; };
  const label = (name, value, asLink=false) => { const row=text('p',`${name}：`,'library-detail-meta'); if(asLink && value){const a=text('a',value); a.href=value; a.target='_blank'; a.rel='noopener noreferrer'; row.append(a);} else row.append(document.createTextNode(value || '未提供')); return row; };
  function section(name,value) { const box=text('section','','library-section'); box.append(text('h3',name),text('p',value || '未提供')); return box; }
  function showDetail() {
    const detail=$('library-detail-content'); detail.replaceChildren();
    const paper=state.papers.find(p=>p.id===state.selectedId);
    if(!paper){ detail.append(text('div','选择一篇文献查看详情','result-placeholder')); return; }
    detail.append(text('h3',paper.title,'library-detail-title'));
    const tags=text('div','','library-badges');
    tags.append(text('span',paper.category==='reading'?'精读文献':paper.topic_name || '主题文献','library-tag'));
    if(paper.is_mock) tags.append(text('span','模拟数据 · 不可正式引用','library-tag mock'));
    detail.append(tags,label('来源',paper.source_name),label('作者',paper.authors),label('发表年份',paper.publication_year || '未提供'),label('DOI',paper.doi));
    if(paper.source_url) detail.append(label('来源链接',paper.source_url,true));
    detail.append(section('摘要',paper.abstract_text || (paper.is_mock?'模拟摘要未提供':'暂无摘要')));
    if(paper.analysis?.purpose) detail.append(section('研究目的',paper.analysis.purpose));
    if(paper.analysis?.method) detail.append(section('研究方法',paper.analysis.method));
    if(paper.report_text) detail.append(section('精读报告',paper.report_text));
    const files=text('div','','library-file-tabs');
    for(const [kind,title,available] of [['original','原文 PDF',paper.has_original_pdf],['chinese','中文 PDF',paper.has_chinese_pdf]]) {
      if(available){const a=text('a',title); a.href=`/api/library/${encodeURIComponent(paper.id)}/files/${kind}`; a.target='_blank'; a.rel='noopener'; a.onclick=event=>{event.preventDefault(); const frame=$('library-pdf-preview'); frame.src=a.href; frame.hidden=false;}; files.append(a);}
      else files.append(text('span',`${title} 暂无`));
    }
    detail.append(files);
    const preview=document.createElement('iframe'); preview.id='library-pdf-preview'; preview.className='library-pdf-preview'; preview.title='文献 PDF 预览'; preview.hidden=true; detail.append(preview);
    const remove=text('button','从文献库删除','library-remove'); remove.type='button'; remove.onclick=async()=>{if(!confirm(`从文献库删除“${paper.title}”？`))return;try{await api(`/api/library/${encodeURIComponent(paper.id)}`,{method:'DELETE'});state.selectedId=null;toast('文献已删除');await load();}catch(error){toast(error.message);}}; detail.append(remove);
  }
  function renderTopics() {
    const chips=$('topic-chips'); chips.replaceChildren(); chips.hidden=state.category!=='theme';
    const all=text('button','全部主题',state.topicId===null?'active':''); all.type='button'; all.onclick=()=>{state.topicId=null;load();}; chips.append(all);
    for(const topic of state.topics){const chip=text('button',`${topic.name} · ${topic.paper_count}`,state.topicId===topic.id?'active':'');chip.type='button';chip.onclick=()=>{state.topicId=topic.id;load();};chips.append(chip);}
    const create=text('button','＋ 新建主题');create.type='button';create.onclick=openTopicDialog;chips.append(create);
  }
  function render() {
    const list=$('library-list'); list.replaceChildren();
    $('library-heading').textContent=state.category==='all'?'全部文献':state.category==='reading'?'精读文献库':'主题文献库';
    $('library-count').textContent=`${state.papers.length} 篇`;
    renderTopics();
    if(!state.papers.length){const empty=text('div','当前没有符合条件的文献。','library-empty');if(state.category==='theme'){const a=text('a','前往文献检索');a.href='/search';empty.append(document.createElement('br'),a);}list.append(empty);}
    for(const paper of state.papers){const card=text('button','','library-item'+(paper.id===state.selectedId?' active':''));card.type='button';const top=text('div','','library-item-top');top.append(text('div',paper.title,'library-item-title'));card.append(top,text('div',`${paper.authors || '作者未提供'} · ${paper.publication_year || '年份未提供'} · ${paper.source_name}`,'library-item-meta'));const badges=text('div','','library-badges');badges.append(text('span',paper.category==='reading'?'精读文献':paper.topic_name || '主题文献','library-tag'));if(paper.is_mock)badges.append(text('span','模拟','library-tag mock'));if(paper.has_original_pdf)badges.append(text('span','原文 PDF','library-tag pdf'));if(paper.has_chinese_pdf)badges.append(text('span','中文 PDF','library-tag pdf'));card.append(badges,text('div',paper.abstract_text || '暂无摘要','library-item-abstract'));card.onclick=()=>{state.selectedId=paper.id;render();};list.append(card);}
    showDetail();
  }
  async function load() {
    try {const params=new URLSearchParams({q:$('library-query').value.trim(),source:$('library-source').value,category:state.category});if(state.topicId && state.category==='theme')params.set('topic_id',state.topicId);state.papers=await api(`/api/library?${params}`);if(state.selectedId && !state.papers.some(p=>p.id===state.selectedId))state.selectedId=null;render();}
    catch(error){$('library-list').replaceChildren(text('div',error.message,'library-empty'));toast(error.message);}
  }
  async function loadTopics(){state.topics=await api('/api/library/topics');renderTopics();const select=$('upload-topic');select.replaceChildren();for(const topic of state.topics){const option=new Option(topic.name,topic.id);select.append(option);}}
  document.querySelectorAll('[data-category]').forEach(button=>button.onclick=()=>{state.category=button.dataset.category;state.topicId=null;document.querySelectorAll('[data-category]').forEach(item=>item.classList.toggle('active',item===button));load();});
  let timer; $('library-query').oninput=()=>{clearTimeout(timer);timer=setTimeout(load,250);}; $('library-source').onchange=load;
  $('upload-open').onclick=async()=>{try{await loadTopics();$('upload-category').value=state.category==='reading'?'reading':'theme';$('upload-topic-wrap').hidden=$('upload-category').value!=='theme';$('upload-error').textContent='';$('upload-dialog').showModal();}catch(error){toast(error.message);}};
  $('upload-close').onclick=$('upload-cancel').onclick=()=>$('upload-dialog').close();
  let resumeUpload=false;
  function openTopicDialog(){resumeUpload=$('upload-dialog').open;if(resumeUpload)$('upload-dialog').close();$('topic-name').value='';$('topic-error').textContent='';$('topic-dialog').showModal();}
  $('upload-create-topic').onclick=openTopicDialog;
  $('topic-cancel').onclick=()=>{$('topic-dialog').close();if(resumeUpload)$('upload-dialog').showModal();};
  $('topic-form').onsubmit=async event=>{event.preventDefault();const name=$('topic-name').value.trim();if(!name)return;try{const topic=await api('/api/library/topics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});$('topic-dialog').close();await loadTopics();state.category='theme';state.topicId=topic.id;document.querySelectorAll('[data-category]').forEach(item=>item.classList.toggle('active',item.dataset.category==='theme'));$('upload-topic').value=topic.id;await load();if(resumeUpload)$('upload-dialog').showModal();toast(`已创建主题「${name}」`);}catch(error){$('topic-error').textContent=error.message;}};
  $('upload-category').onchange=()=>{$('upload-topic-wrap').hidden=$('upload-category').value!=='theme';};
  $('upload-form').onsubmit=async event=>{event.preventDefault();const button=$('upload-submit');button.disabled=true;button.textContent='正在导入…';$('upload-error').textContent='';try{const data=new FormData(event.target);if(data.get('category')==='reading')data.delete('topic_id');if(!data.get('chinese')?.size)data.delete('chinese');const result=await api('/api/library/upload',{method:'POST',body:data});$('upload-dialog').close();event.target.reset();state.category=result.category;state.topicId=null;state.selectedId=result.id;document.querySelectorAll('[data-category]').forEach(item=>item.classList.toggle('active',item.dataset.category===state.category));await loadTopics();await load();toast('文献已导入');}catch(error){$('upload-error').textContent=error.message;}finally{button.disabled=false;button.textContent='确认导入';}};
  Promise.all([loadTopics(),load()]).catch(error=>toast(error.message));
})();
