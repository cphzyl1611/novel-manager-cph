let state={books:[],groups:[],currentGroup:'',offset:0,limit:60,total:0,loading:false,hasMore:true,searchQuery:'',currentPage:'home'};
let readerState={currentBookId:null,currentTitle:'',barsVisible:true,lastScroll:0,saveThrottle:null,chapters:[],currentChapterIndex:0,contentLength:0};

// ======== UTILS ========
function eid(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
async function api(url){try{const r=await fetch(url);return r.ok?r.json():null}catch(e){return null}}
function toast(msg){const t=eid('toast');t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2000)}
function readerToast(msg){const t=eid('readerToast');t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2500)}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms)})}

// ======== DRAWER ========
function toggleDrawer(){eid('drawer').classList.toggle('open');eid('overlay').classList.toggle('open')}
function showPage(page){state.currentPage=page;eid('updatesPage').classList.toggle('open',page==='updates');eid('uploadPage').classList.toggle('open',page==='upload');eid('shelf').style.display=(page==='home')?'':'none';eid('groupTabs').style.display=(page==='home')?'':'none';if(page==='updates')loadUpdates()}

// ======== READER SETTINGS (localStorage) ========
function loadReaderSettings(){try{return JSON.parse(localStorage.getItem('readerSettings'))||{}}catch(e){return{}}}
function saveReaderSettings(s){localStorage.setItem('readerSettings',JSON.stringify(s))}

function applyReaderSettings(){
  var s=loadReaderSettings();
  var fs=s.fontSize||18, lh=s.lineHeight||2, th=s.theme||'light';
  var content=eid('readerContent');if(content){content.style.fontSize=fs+'px';content.style.lineHeight=lh}
  var fsv=eid('fontSizeVal');if(fsv)fsv.textContent=fs+'px';
  var lhLabels={1.5:'紧凑',2:'标准',2.5:'宽松',3:'很宽'};
  var lhv=eid('lineHeightVal');if(lhv)lhv.textContent=lhLabels[lh]||lh;
  // use classList, never overwrite className
  var readerEl=eid('reader');
  readerEl.classList.remove('theme-light','theme-sepia','theme-dark');
  readerEl.classList.add('theme-'+th);
  if(readerState.barsVisible)readerEl.classList.add('bars-visible');else readerEl.classList.remove('bars-visible');
  // theme dots
  ['Light','Sepia','Dark'].forEach(function(t){
    var d=eid('theme'+t);if(d)d.classList.toggle('active',t.toLowerCase()===th)
  })
}

function changeFontSize(d){
  var s=loadReaderSettings();s.fontSize=Math.max(12,Math.min(30,(s.fontSize||18)+d*2));
  saveReaderSettings(s);applyReaderSettings()
}
function changeLineHeight(d){
  var opts=[1.5,2,2.5,3],s=loadReaderSettings();
  var i=opts.indexOf(s.lineHeight||2);if(i<0)i=1;
  i=Math.max(0,Math.min(opts.length-1,i+d));
  s.lineHeight=opts[i];saveReaderSettings(s);applyReaderSettings()
}
function setTheme(th){var s=loadReaderSettings();s.theme=th;saveReaderSettings(s);applyReaderSettings()}

function toggleSettings(){
  var panel=eid('settingsPanel'),overlay=eid('settingsOverlay');
  if(!panel||!overlay)return;
  var opening=!panel.classList.contains('open');
  panel.classList.toggle('open',opening);
  overlay.classList.toggle('open',opening)
}

// ======== TOC ========
function toggleToc(){
  var p=eid('tocPanel'),o=eid('tocOverlay');
  if(!p||!o)return;
  var op=!p.classList.contains('open');
  p.classList.toggle('open',op);o.classList.toggle('open',op)
}

async function loadChapters(id){
  var d=await api('/api/books/'+id+'/chapters');
  if(d&&d.chapters){readerState.chapters=d.chapters;renderToc()}
}

function renderToc(){
  var list=eid('tocList'),count=eid('tocCount');
  if(!list)return;
  var ch=readerState.chapters;
  if(count)count.textContent='共 '+ch.length+' 章';
  var h='';
  for(var i=0;i<ch.length;i++){
    var c=ch[i],active=i===readerState.currentChapterIndex?' active':'';
    h+='<div class="toc-item'+active+'" onclick="jumpToChapter('+i+')"><span class="toc-index">'+(c.title==='全文'?'':'第'+(i+1)+'章')+'</span><span class="toc-label">'+esc(c.title)+'</span></div>'
  }
  list.innerHTML=h;
  // scroll to current chapter
  var cur=list.querySelector('.toc-item.active');
  if(cur)cur.scrollIntoView({block:'center'})
}

function jumpToChapter(idx){
  var ch=readerState.chapters;
  if(idx<0||idx>=ch.length)return;
  readerState.currentChapterIndex=idx;
  var el=eid('readerContent'),offset=ch[idx].start_offset;
  if(offset>0&&readerState.contentLength>0){
    var ratio=offset/readerState.contentLength;
    el.scrollTop=ratio*(el.scrollHeight-el.clientHeight)
  }else{
    el.scrollTop=0
  }
  toggleToc();
  updateReaderProgress();
  saveReadingProgress();
  renderToc()
}

function findCurrentChapter(){
  var el=eid('readerContent'),scroll=el.scrollTop;
  var ratio=scroll/(el.scrollHeight-el.clientHeight||1);
  var pos=ratio*readerState.contentLength;
  var ch=readerState.chapters,found=0;
  for(var i=ch.length-1;i>=0;i--){if(ch[i].start_offset<=pos){found=i;break}}
  readerState.currentChapterIndex=found
}

// ======== GROUPS ========
async function loadGroups(){var d=await api('/api/groups');if(!d||!d.items)return;state.groups=d.items;renderGroupTabs()}
function renderGroupTabs(){var c=eid('groupTabs');var h='<div class="group-tab'+(state.currentGroup===''?' active':'')+'" onclick="selectGroup(\'\')">📚 全部</div>';for(var i=0;i<state.groups.length;i++){var g=state.groups[i];h+='<div class="group-tab'+(state.currentGroup===g.name?' active':'')+'" onclick="selectGroup(\''+esc(g.name)+'\')">'+esc(g.name)+' ('+g.book_count+')</div>'}h+='<div class="group-tab add" onclick="showGroupModal()">+ 新建分组</div>';c.innerHTML=h}
function selectGroup(name){state.currentGroup=name;state.offset=0;state.books=[];state.hasMore=true;eid('shelf').innerHTML='';renderGroupTabs();loadBooks()}
function showGroupModal(){eid('groupModal').classList.add('open');eid('groupNameInput').value='';eid('groupNameInput').focus()}
function closeGroupModal(){eid('groupModal').classList.remove('open')}
async function createGroup(){var n=eid('groupNameInput').value.trim();if(!n){toast('请输入分组名称');return}var r=await fetch('/api/groups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});var d=await r.json();if(!r.ok){toast(d.detail||'创建失败');return}closeGroupModal();toast(d.existed?'分组已存在':'分组已创建');loadGroups()}

// ======== BOOKS ========
async function loadBooks(){if(state.loading||!state.hasMore)return;state.loading=true;var url='/api/books?limit='+state.limit+'&offset='+state.offset;if(state.searchQuery)url+='&q='+encodeURIComponent(state.searchQuery);var d=await api(url);state.loading=false;if(!d)return;if(state.offset===0)state.books=d.items||[];else state.books=state.books.concat(d.items||[]);state.total=d.total||0;state.hasMore=state.books.length<state.total;state.offset+=state.limit;renderShelf()}
function onSearch(){state.searchQuery=eid('searchInput').value.trim();state.offset=0;state.books=[];state.hasMore=true;eid('shelf').innerHTML='';loadBooks()}

function renderShelf(){
  var s=eid('shelf'),e=eid('emptyState');
  if(state.books.length===0&&!state.loading){s.innerHTML='';e.style.display='block';return}
  e.style.display='none';var h='';
  for(var i=0;i<state.books.length;i++){
    var b=state.books[i];
    var t=esc(b.title||'未知书名'),a=esc(b.author||'');
    var cc=b.chapter_count||0,qs=b.quality_score!=null?Math.round(b.quality_score):'';
    var tags=(b.tags||[]).slice(0,3).map(function(x){return'<span class="tag">'+esc(x)+'</span>'}).join('');
    var prog=b.reading_progress||0,pct=Math.round(prog*100);
    h+='<div class="book-card" onclick="openBook('+b.book_id+',\''+esc(b.title||'')+'\')">'
      +'<div class="title">'+t+'</div>'
      +(a?'<div class="author">'+a+'</div>':'')
      +(tags?'<div class="tags">'+tags+'</div>':'')
      +(pct>0?'<div class="progress-bar"><div class="fill" style="width:'+pct+'%"></div></div><div class="meta" style="margin-top:2px"><span>已读 '+pct+'%</span></div>':'<div class="meta"><span>'+(cc?cc+'章':'')+'</span><span>'+(qs?qs+'分':'')+'</span></div>')
      +'</div>'
  }
  if(state.loading)h+='<div class="loading"><div class="spinner"></div></div>';s.innerHTML=h
}
window.addEventListener('scroll',function(){if(state.currentPage!=='home')return;if(window.scrollY+window.innerHeight>document.body.offsetHeight-300)loadBooks()});

// ======== READER CORE ========
async function openBook(id,title){
  readerState.currentBookId=id;readerState.currentTitle=title;readerState.barsVisible=true;
  var readerEl=eid('reader');
  readerEl.classList.add('open');
  // close settings panel when opening a book
  eid('settingsPanel').classList.remove('open');
  eid('settingsOverlay').classList.remove('open');
  // title + encoding + warning
  eid('readerTitle').textContent=title;
  eid('readerContent').textContent='加载中...';
  eid('readerEncoding').style.display='none';
  eid('readerWarning').style.display='none';
  applyReaderSettings();

  var results=await Promise.all([api('/api/books/'+id+'/content'),api('/api/books/'+id+'/progress')]);
  var contentData=results[0],progressData=results[1];

  if(contentData&&contentData.content){
    var text=contentData.content;
    if(text.length>500000){
      eid('readerContent').textContent='长篇小说加载中...';
      await sleep(50);
      eid('readerContent').textContent=text.slice(0,300000);
      await sleep(100);
      eid('readerContent').textContent=text;
    }else{
      eid('readerContent').textContent=text;
    }
    readerState.contentLength=text.length;
    if(contentData.encoding){eid('readerEncoding').textContent='编码：'+contentData.encoding.toUpperCase();eid('readerEncoding').style.display=''}
    if(contentData.decode_warning){eid('readerWarning').textContent='⚠ '+contentData.decode_warning;eid('readerWarning').style.display=''}
    loadChapters(id);
  }else if(contentData&&contentData.error){
    eid('readerContent').textContent='错误: '+contentData.error;
  }else{
    eid('readerContent').textContent='无法加载小说内容';
  }

  if(progressData&&progressData.has_progress&&progressData.scroll_position>0){
    setTimeout(function(){eid('readerContent').scrollTop=progressData.scroll_position},200);
    readerToast('已恢复到上次阅读位置');
  }
  updateReaderProgress();
  readerState.saveThrottle=setInterval(saveReadingProgress,4000);
}

function closeReader(){
  saveReadingProgress();
  if(readerState.saveThrottle){clearInterval(readerState.saveThrottle);readerState.saveThrottle=null}
  eid('reader').classList.remove('open');
  eid('tocPanel').classList.remove('open');
  eid('tocOverlay').classList.remove('open');
  eid('settingsPanel').classList.remove('open');
  eid('settingsOverlay').classList.remove('open');
  state.offset=0;state.books=[];state.hasMore=true;
  eid('shelf').innerHTML='';
  loadBooks();
}

function onReaderTap(){
  readerState.barsVisible=!readerState.barsVisible;
  var r=eid('reader');
  if(readerState.barsVisible)r.classList.add('bars-visible');else r.classList.remove('bars-visible')
}

function updateReaderProgress(){
  var el=eid('readerContent'),scroll=el.scrollTop,height=el.scrollHeight-el.clientHeight;
  var ratio=height>0?Math.min(1,scroll/height):0;
  var pct=Math.round(ratio*100);
  eid('readerProgressText').textContent=pct+'%';
  readerState.lastScroll=scroll;
  findCurrentChapter();
}

async function saveReadingProgress(){
  if(!readerState.currentBookId)return;
  updateReaderProgress();
  await fetch('/api/books/'+readerState.currentBookId+'/progress',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({progress_ratio:Math.round(readerState.lastScroll/(eid('readerContent').scrollHeight-eid('readerContent').clientHeight||1)*100)/100||0,scroll_position:readerState.lastScroll,device_id:'web',current_chapter_index:readerState.currentChapterIndex})
  }).catch(function(){})
}

function scrollToTop(){eid('readerContent').scrollTop=0;readerState.barsVisible=true;eid('reader').classList.add('bars-visible')}

// scroll tracking
eid('readerContent').addEventListener('scroll',function(){updateReaderProgress()});

// save progress on unload
window.addEventListener('beforeunload',function(){saveReadingProgress()});

// ======== UPDATES ========
var analysisResult=null;

async function postApi(url){try{var r=await fetch(url,{method:'POST'});return r.ok?r.json():null}catch(e){return null}}

async function doScanIncoming(){
  var btn=eid('btnScanIncoming');btn.disabled=true;btn.textContent='扫描中...';
  var d=await postApi('/api/tasks/scan-incoming');
  btn.disabled=false;btn.textContent='🔍 扫描新下载区';
  if(!d){toast('扫描失败，请查看服务端日志');return}
  toast('扫描完成: 发现 '+d.found+' 个, 已扫描 '+d.scanned+' 个')
}

async function doAnalyzeIncoming(){
  var btn=eid('btnAnalyzeIncoming');btn.disabled=true;btn.textContent='检测中...';
  var d=await postApi('/api/tasks/analyze-incoming');
  btn.disabled=false;btn.textContent='📊 检测新下载小说';
  if(!d){toast('检测失败，请查看服务端日志');return}
  analysisResult=d;renderAnalysis()
}

function renderAnalysis(){
  var d=analysisResult,c=eid('updatesContent'),s=eid('updatesSummary');
  if(!d||!d.items||d.items.length===0){c.innerHTML='<div class="empty-state">暂无检测结果，请先上传小说或扫描新下载区。</div>';s.style.display='none';return}
  s.style.display='';
  var sum=d.summary;
  s.innerHTML='<div class="sum-cards">'
    +'<div class="sum-card"><span>'+sum.incoming_count+'</span>新下载区</div>'
    +'<div class="sum-card sum-new"><span>'+sum.new_book+'</span>新书</div>'
    +'<div class="sum-card sum-dup"><span>'+sum.exact_duplicate+'</span>简单重复</div>'
    +'<div class="sum-card sum-upd"><span>'+sum.update_candidate+'</span>可能是新版</div>'
    +'<div class="sum-card sum-near"><span>'+sum.near_duplicate+'</span>近似重复</div>'
    +'<div class="sum-card sum-rev"><span>'+sum.manual_review+'</span>需人工确认</div>'
    +'</div>';
  var cm={new_book:'new',exact_duplicate:'dup',update_candidate:'upd',near_duplicate:'near',manual_review:'rev',risky:'risk',reject:'reject'};
  var h='';
  for(var i=0;i<d.items.length;i++){
    var it=d.items[i],cls=cm[it.classification]||'';
    h+='<div class="analysis-card '+cls+'">'
      +'<div class="ac-head"><span class="ac-badge '+cls+'">'+esc(it.classification_label)+'</span><span class="ac-title">'+esc(it.incoming_title)+'</span></div>'
      +'<div class="ac-meta">文件: '+esc(it.incoming_file)+'</div>';
    if(it.matched_title)h+='<div class="ac-match">匹配: '+esc(it.matched_title)+'</div>';
    h+='<div class="ac-reason">'+esc(it.reason)+'</div>';
    if(it.risks&&it.risks.length>0)h+='<div class="ac-risks">风险: '+it.risks.map(function(r){return'<span class="risk-tag">'+esc(r)+'</span>'}).join(' ')+'</div>';
    h+='<div class="ac-actions"><button class="btn-sm" onclick="openBook('+it.incoming_book_id+',\''+esc(it.incoming_title)+'\')">打开新书</button>';
    if(it.matched_book_id)h+='<button class="btn-sm" onclick="openBook('+it.matched_book_id+',\''+esc(it.matched_title||'')+'\')">打开旧书</button>';
    h+='</div></div>'
  }
  c.innerHTML=h
}

function loadUpdates(){doAnalyzeIncoming()}

// ======== UPLOAD ========
var selectedFiles=[];

function onFilesSelected(){
  var inp=eid('uploadInput');selectedFiles=Array.from(inp.files);
  var list=eid('uploadList'),actions=eid('uploadActions');
  if(selectedFiles.length===0){list.innerHTML='';actions.style.display='none';return}
  var h='<div style="padding:0 16px;font-size:14px;margin-bottom:8px">已选择 '+selectedFiles.length+' 个文件:</div>';
  for(var i=0;i<selectedFiles.length;i++){
    var f=selectedFiles[i],cls=f.name.toLowerCase().endsWith('.txt')?'':' style="color:#c0392b"';
    h+='<div class="upload-item"'+cls+'>'+esc(f.name)+' <span style="font-size:11px;color:var(--muted)">'+formatSize(f.size)+'</span></div>'
  }
  list.innerHTML=h;
  actions.style.display=''
}

function formatSize(bytes){
  if(bytes<1024)return bytes+' B';
  if(bytes<1024*1024)return (bytes/1024).toFixed(1)+' KB';
  return (bytes/1024/1024).toFixed(1)+' MB'
}

async function doUpload(){
  var inp=eid('uploadInput');
  if(!inp.files||inp.files.length===0){toast('请先选择文件');return}
  var btn=eid('uploadBtn');btn.disabled=true;btn.textContent='上传中...';
  var form=new FormData();
  for(var i=0;i<inp.files.length;i++)form.append('files',inp.files[i]);
  var r=await fetch('/api/books/upload',{method:'POST',body:form});
  var d=await r.json();btn.disabled=false;btn.textContent='上传到新下载区';
  var result=eid('uploadResult'),next=eid('uploadNext');
  var h='';
  if(d.uploaded&&d.uploaded.length>0){
    h+='<div class="upload-success">✅ 成功上传 '+d.uploaded.length+' 本:</div>';
    for(var i=0;i<d.uploaded.length;i++){
      var u=d.uploaded[i],renamed=u.original_name!==u.saved_name?' (已自动改名: '+esc(u.saved_name)+')':'';
      h+='<div class="upload-item success">'+esc(u.original_name)+renamed+'</div>'
    }
  }
  if(d.skipped&&d.skipped.length>0){
    h+='<div class="upload-skipped">⏭ 跳过 '+d.skipped.length+' 个:</div>';
    for(var i=0;i<d.skipped.length;i++){
      h+='<div class="upload-item skipped">'+esc(d.skipped[i].original_name)+' — '+esc(d.skipped[i].reason)+'</div>'
    }
  }
  result.innerHTML=h;next.style.display='';
  inp.value='';selectedFiles=[];eid('uploadList').innerHTML='';eid('uploadActions').style.display='none'
}

async function scanIncoming(){
  toast('正在扫描新下载区...');
  var d=await api('/api/tasks/scan-incoming',{method:'POST'});
  if(!d){toast('扫描失败');return}
  var el=eid('scanResult');
  el.innerHTML='<div class="upload-success">🔍 新下载区发现 '+d.found+' 个 TXT 文件</div>';
  if(d.files&&d.files.length>0){
    var h='<div style="font-size:13px;color:var(--muted);padding:4px 16px">';
    for(var i=0;i<Math.min(d.files.length,10);i++)h+=esc(d.files[i].name)+' ('+formatSize(d.files[i].size)+')<br>';
    if(d.files.length>10)h+='…… 等 '+(d.files.length-10)+' 个文件';
    h+='</div>';el.innerHTML+=h
  }
  toast('扫描完成，发现 '+d.found+' 个文件')
}

// Make upload zone clickable
eid('uploadZone').addEventListener('click',function(){eid('uploadInput').click()});

// ======== INIT ========
async function init(){var h=await api('/api/health');if(h&&h.ok)eid('drawerStatus').textContent='仓库已连接';loadGroups();loadBooks()}
init();
