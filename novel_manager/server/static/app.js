// NovelHub app.js shelfpaging1
console.log('[NovelHub] app.js shelfpaging1 loaded');

let state={books:[],groups:[],currentGroup:'',page:1,pageSize:40,total:0,totalPages:0,loading:false,searchQuery:'',currentPage:'shelf'};
let readerState={currentBookId:null,currentTitle:'',barsVisible:true,lastScroll:0,saveThrottle:null,chapters:[],currentChapterIndex:0,contentLength:0};

// ======== AUTH STATE ========
var authState={
  deviceId:'',
  deviceToken:'',
  isPaired:false,
  needsPairing:false
};

// ======== PAGE REGISTRY ========
const PAGES={
  shelf:{id:'shelfPage',onShow:null},
  upload:{id:'uploadPage',onShow:null},
  updates:{id:'updatesPage',onShow:function(){loadUpdates()}},
  operations:{id:'opsPage',onShow:function(){loadOps('')}},
  health:{id:'healthPage',onShow:loadHealth},
  settings:{id:'settingsPage',onShow:updateSettingsDisplay},
  pairing:{id:'pairingMgmtPage',onShow:loadPairedDevices}
};

// ======== UTILS ========
function eid(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function getAuthHeaders(){
  var headers={};
  if(authState.deviceId)headers['X-Device-ID']=authState.deviceId;
  if(authState.deviceToken)headers['X-Device-Token']=authState.deviceToken;
  return headers;
}

async function api(url){
  try{
    var r=await fetch(url,{headers:getAuthHeaders()});
    if(r.status===401){
      var d=await r.json();
      if(d.error_code==='unauthorized_device'||d.error_code==='device_revoked'){
        showPairingPage(d.error);
        return null;
      }
    }
    return r.ok?r.json():null;
  }catch(e){return null}
}

async function postApi(url,body){
  try{
    var r=await fetch(url,{
      method:'POST',
      headers:getAuthHeaders(),
      body:body?JSON.stringify(body):undefined
    });
    if(r.status===401){
      var d=await r.json();
      if(d.error_code==='unauthorized_device'||d.error_code==='device_revoked'){
        showPairingPage(d.error);
        return null;
      }
    }
    return r.ok?r.json():null;
  }catch(e){return null}
}

function toast(msg){const t=eid('toast');if(t){t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2000)}}
function readerToast(msg){const t=eid('readerToast');if(t){t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2500)}}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms)})}

// ======== NAVIGATION ========
function initNavigation(){
  document.addEventListener('click',function(e){
    // Handle overlay click to close drawer
    if(e.target.id==='overlay'){
      toggleDrawer();
      return;
    }

    // Handle data-toggle="drawer" (menu button)
    var toggleBtn=e.target.closest('[data-toggle="drawer"]');
    if(toggleBtn){
      e.preventDefault();
      toggleDrawer();
      return;
    }

    // Handle data-page (navigation items)
    var nav=e.target.closest('[data-page]');
    if(!nav)return;
    e.preventDefault();
    var page=nav.dataset.page;
    showPage(page);
    var drawer=eid('drawer');
    if(drawer&&drawer.classList.contains('open')){
      toggleDrawer();
    }
  });
  console.log('[NovelHub] navigation initialized');
}

function showPage(pageName){
  console.log('[NovelHub] showPage',pageName);

  // Handle legacy 'home' -> 'shelf'
  if(pageName==='home')pageName='shelf';

  var cfg=PAGES[pageName];
  if(!cfg){
    console.warn('[NovelHub] unknown page:',pageName);
    pageName='shelf';
    cfg=PAGES[pageName];
  }

  state.currentPage=pageName;

  // Hide all pages first
  Object.entries(PAGES).forEach(function(entry){
    var name=entry[0],page=entry[1];
    var el=eid(page.id);
    if(!el){
      console.warn('[NovelHub] missing page element:',page.id);
      return;
    }
    el.classList.remove('open');
    el.classList.remove('active');
    el.style.display='none';
  });

  // Show selected page
  var activeEl=eid(cfg.id);
  if(activeEl){
    activeEl.classList.add('open');
    activeEl.style.display='';
  }

  // Toggle shelf and groupTabs visibility
  var shelf=eid('shelf');
  var groupTabs=eid('groupTabs');
  if(shelf)shelf.style.display=(pageName==='shelf')?'':'none';
  if(groupTabs)groupTabs.style.display=(pageName==='shelf')?'':'none';

  // Update nav active state
  document.querySelectorAll('[data-page]').forEach(function(btn){
    btn.classList.toggle('active',btn.dataset.page===pageName||btn.dataset.page==='home'&&pageName==='shelf');
  });

  // Call onShow if defined
  if(cfg&&typeof cfg.onShow==='function'){
    try{
      cfg.onShow();
    }catch(e){
      console.error('[NovelHub] page onShow failed:',pageName,e);
      toast('页面加载失败');
    }
  }
}

// ======== DRAWER ========
function toggleDrawer(){
  var drawer=eid('drawer');
  var overlay=eid('overlay');
  if(drawer)drawer.classList.toggle('open');
  if(overlay)overlay.classList.toggle('open');
}

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
function selectGroup(name){state.currentGroup=name;state.page=1;state.books=[];eid('shelf').innerHTML='';renderGroupTabs();loadBooks()}
function showGroupModal(){eid('groupModal').classList.add('open');eid('groupNameInput').value='';eid('groupNameInput').focus()}
function closeGroupModal(){eid('groupModal').classList.remove('open')}
async function createGroup(){var n=eid('groupNameInput').value.trim();if(!n){toast('请输入分组名称');return}var r=await fetch('/api/groups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});var d=await r.json();if(!r.ok){toast(d.detail||'创建失败');return}closeGroupModal();toast(d.existed?'分组已存在':'分组已创建');loadGroups()}

// ======== BOOKS ========
async function loadBooks(){if(state.loading)return;state.loading=true;var url='/api/books?page='+state.page+'&page_size='+state.pageSize;if(state.searchQuery)url+='&q='+encodeURIComponent(state.searchQuery);var d=await api(url);state.loading=false;if(!d){state.books=[];state.total=0;state.totalPages=0;renderShelf();return}state.books=d.items||[];state.total=d.total||0;if(d.pagination){state.totalPages=d.pagination.total_pages||0;state.page=d.pagination.page||1}else{state.totalPages=Math.ceil(state.total/state.pageSize)||1}renderShelf()}
function onSearch(){state.searchQuery=eid('searchInput').value.trim();state.page=1;state.books=[];eid('shelf').innerHTML='';loadBooks()}

function renderShelf(){
  var s=eid('shelf'),e=eid('emptyState');
  if(state.books.length===0&&!state.loading){
    s.innerHTML='<div class="empty-state">当前书架没有可读小说。<br>请先上传或扫描 library 文件夹。</div>';
    e.style.display='none';return
  }
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
  if(state.loading)h+='<div class="loading"><div class="spinner"></div></div>';
  // Pagination controls
  if(state.totalPages>1){
    h+='<div class="pagination-bar">';
    h+='<span class="pagination-info">共 '+state.total+' 本，每页 '+state.pageSize+' 本</span>';
    h+='<div class="pagination-btns">';
    if(state.page>1)h+='<button class="page-btn" onclick="goToPage('+(state.page-1)+')">上一页</button>';
    h+='<span class="page-indicator">'+state.page+' / '+state.totalPages+'</span>';
    if(state.page<state.totalPages)h+='<button class="page-btn" onclick="goToPage('+(state.page+1)+')">下一页</button>';
    h+='</div></div>';
  }
  s.innerHTML=h
}

function goToPage(p){
  state.page=p;state.books=[];eid('shelf').innerHTML='';window.scrollTo(0,0);loadBooks();
}

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
  }else if(contentData&&contentData.error){
    eid('readerContent').textContent='错误: '+contentData.error;
  }else{
    eid('readerContent').textContent='无法加载小说内容';
  }

  await loadChapters(id);

  if(progressData&&progressData.has_progress){
    var restored=false;
    if(progressData.current_chapter_index>0&&readerState.chapters&&readerState.chapters.length>progressData.current_chapter_index){
      jumpToChapter(progressData.current_chapter_index);
      restored=true;
    }else if(progressData.progress_ratio>0){
      var el=eid('readerContent');
      el.scrollTop=progressData.progress_ratio*(el.scrollHeight-el.clientHeight);
      restored=true;
    }else if(progressData.scroll_position>0){
      setTimeout(function(){eid('readerContent').scrollTop=progressData.scroll_position},200);
      restored=true;
    }
    if(restored)readerToast('已恢复到上次阅读位置');
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
  state.page=1;state.books=[];
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

async function postApiSimple(url){try{var r=await fetch(url,{method:'POST',headers:getAuthHeaders()});return r.ok?r.json():null}catch(e){return null}}

async function doScanIncoming(){
  var btn=eid('btnScanIncoming');btn.disabled=true;btn.textContent='扫描中...';
  var d=await postApiSimple('/api/tasks/scan-incoming');
  btn.disabled=false;btn.textContent='🔍 扫描新下载区';
  if(!d){toast('扫描失败，请查看服务端日志');return}
  toast('扫描完成: 发现 '+d.found+' 个, 已扫描 '+d.scanned+' 个')
}

async function doAnalyzeIncoming(){
  var btn=eid('btnAnalyzeIncoming');btn.disabled=true;btn.textContent='检测中...';
  var d=await postApiSimple('/api/tasks/analyze-incoming');
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
  var safeCount=0;
  for(var i=0;i<d.items.length;i++){var aa=d.items[i].available_actions||[];if(aa.indexOf('import_to_library')>=0||aa.indexOf('move_to_review_duplicates')>=0)safeCount++}
  if(safeCount>0)s.innerHTML+='<button class="btn-primary" style="margin:8px 0" onclick="doBatchSafe()">一键处理安全项 ('+safeCount+'项)</button>';
  var cm={new_book:'new',exact_duplicate:'dup',update_candidate:'upd',near_duplicate:'near',manual_review:'rev',risky:'risk',reject:'reject'};
  var h='';
  for(var i=0;i<d.items.length;i++){
    var it=d.items[i],cls=cm[it.classification]||'';
    var aa=it.available_actions||[];
    h+='<div class="analysis-card '+cls+'" data-incoming-id="'+it.incoming_book_id+'">'
      +'<div class="ac-head"><span class="ac-badge '+cls+'">'+esc(it.classification_label)+'</span><span class="ac-title">'+esc(it.incoming_title)+'</span></div>'
      +'<div class="ac-meta">文件: '+esc(it.incoming_file)+'</div>';
    if(it.matched_title)h+='<div class="ac-match">匹配: '+esc(it.matched_title)+'</div>';
    h+='<div class="ac-reason">'+esc(it.reason)+'</div>';
    if(it.risks&&it.risks.length>0)h+='<div class="ac-risks">风险: '+it.risks.map(function(r){return'<span class="risk-tag">'+esc(r)+'</span>'}).join(' ')+'</div>';
    h+='<div class="ac-actions"><button class="btn-sm" onclick="openBook('+it.incoming_book_id+',\''+esc(it.incoming_title)+'\')">打开</button>';
    if(aa.indexOf('import_to_library')>=0)h+='<button class="btn-sm btn-action" onclick="doImport('+it.incoming_book_id+')">加入书架</button>';
    if(aa.indexOf('move_to_review_duplicates')>=0)h+='<button class="btn-sm btn-action" onclick="doMoveReview('+it.incoming_book_id+')">移入重复复核区</button>';
    if(aa.indexOf('replace_library_version')>=0)h+='<button class="btn-sm btn-action replace-btn" data-incoming-id="'+it.incoming_book_id+'" data-matched-id="'+it.matched_book_id+'">确认替换旧版</button>';
    if(aa.indexOf('compare')>=0&&it.matched_book_id)h+='<button class="btn-sm" onclick="showCompare('+it.incoming_book_id+','+it.matched_book_id+')">对比</button>';
    if(aa.length===0)h+='<span class="btn-sm" style="color:#888">已处理/不可操作</span>';
    h+='</div></div>'
  }
  c.innerHTML=h
}

async function doImport(bookId){
  if(!confirm('加入书架？\n\n将把这本新书从新下载区加入小说库。\n不会覆盖已有文件，也不会修改 TXT 内容。'))return;
  var r=await postApiSimple('/api/incoming/'+bookId+'/import-to-library');
  if(!r||!r.ok){
    if(r&&r.error_code==='incoming_item_stale'){toast('该项目已经被处理，正在刷新检测结果。');doAnalyzeIncoming();return}
    toast(r&&r.error||'操作失败');return
  }
  _removeAnalysisCard(bookId);
  toast('已加入书架');
  doAnalyzeIncoming();
  state.page=1;state.books=[];eid('shelf').innerHTML='';loadBooks()
}
async function doMoveReview(bookId){
  if(!confirm('移入重复复核区？\n\n将只把新下载区的这份文件移入重复复核区，\n不会删除任何文件，也不会影响小说库中已有版本。'))return;
  var r=await postApiSimple('/api/incoming/'+bookId+'/move-to-review-duplicates');
  if(!r||!r.ok){
    if(r&&r.error_code==='incoming_item_stale'){toast('该项目已经被处理，正在刷新检测结果。');doAnalyzeIncoming();return}
    toast(r&&r.error||'操作失败');return
  }
  _removeAnalysisCard(bookId);
  toast('已移入重复复核区');
  doAnalyzeIncoming()
}
async function showCompare(b1,b2){
  var d=await api('/api/incoming/'+b1+'/compare/'+b2);if(!d||!d.ok){toast('获取对比失败');return}
  var h='<h3 style="margin-bottom:8px">新旧对比</h3>';
  h+='<div class="cmp-row"><div><strong>新下载:</strong> '+esc(d.incoming.title)+'</div><div>'+d.incoming.chapter_count+'章 | '+formatSize(d.incoming.char_count_clean||0)+' | '+d.incoming.quality_score+'分</div></div>';
  h+='<div class="cmp-row"><div><strong>已有书:</strong> '+esc(d.matched.title)+'</div><div>'+d.matched.chapter_count+'章 | '+formatSize(d.matched.char_count_clean||0)+' | '+d.matched.quality_score+'分</div></div>';
  h+='<div class="cmp-diff">章节差: '+(d.diff.chapter_delta>0?'+':'')+d.diff.chapter_delta+' | 字数差: '+(d.diff.char_count_delta>0?'+':'')+formatSize(d.diff.char_count_delta||0)+' | 质量差: '+(d.diff.quality_delta>0?'+':'')+d.diff.quality_delta+'</div>';
  h+='<div class="cmp-msg">'+esc(d.recommendation.message)+'</div>';
  h+='<button class="btn-primary" onclick="closeCompare()" style="margin-top:12px">关闭</button>';
  eid('compareContent').innerHTML=h;eid('compareModal').classList.add('open')
}
function closeCompare(){eid('compareModal').classList.remove('open')}

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
  var d=await postApiSimple('/api/tasks/scan-incoming');
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

// ======== OPERATIONS ========
async function loadOps(filter){
  var url='/api/operations?limit=50';if(filter)url+='&'+filter;
  var d=await api(url);var el=eid('opsContent');
  if(!d||!d.items||d.items.length===0){el.innerHTML='<div class="empty-state">暂无操作记录</div>';return}
  var h='';
  for(var i=0;i<d.items.length;i++){
    var it=d.items[i],rev=it.reversible&&!it.restored;
    var isReplace=it.operation_type==='replace_library_version';
    h+='<div class="analysis-card'+(it.restored?' reject':'')+'">'
      +'<div class="ac-head"><span class="ac-badge'+(it.restored?' reject':' new')+'">'+esc(it.operation_label)+'</span>'
      +(it.restored?'<span class="ac-badge reject" style="margin-left:4px">已恢复</span>':'')
      +'</div>'
      +'<div class="ac-title">'+esc(it.title||it.file_name||'')+'</div>';
    if(isReplace){
      h+='<div class="ac-meta">新下载区 → 小说库</div><div class="ac-meta">旧版：小说库 → 已归档</div>';
    }else{
      h+='<div class="ac-meta">'+esc(it.source_area)+' → '+esc(it.target_area)+'</div>';
    }
    h+='<div class="ac-meta">'+esc(it.created_at||'')+'</div>'
      +'<div class="ac-actions">';
    if(rev){
      var btnLabel=isReplace?'恢复替换':'恢复到新下载区';
      var isRepVal=isReplace?'true':'false';
      h+='<button class="btn-sm btn-action" data-op-id="'+esc(it.operation_id)+'" data-is-replace="'+isRepVal+'" onclick="doRestore(this.dataset.opId,this.dataset.isReplace===\'true\')">'+btnLabel+'</button>';
    }
    h+='</div></div>'
  }
  el.innerHTML=h
}

async function doRestore(opId,isReplace){
  var msg;
  if(isReplace){
    msg=['确认恢复替换？','','这会把新版移回新下载区，并把旧版恢复到小说库。','不会删除文件。','不会覆盖已有文件。'].join('\n');
  }else{
    msg=['确认恢复？','','这会把该小说从当前区域移回新下载区。','不会删除文件，也不会覆盖已有文件。','如果新下载区已有同名文件，会自动改名。'].join('\n');
  }
  if(!confirm(msg))return;
  var r=await postApiSimple('/api/operations/'+opId+'/restore');
  if(!r||!r.ok){toast(r&&r.error||'恢复失败');return}
  toast(isReplace?'已恢复替换操作':'已恢复到新下载区');loadOps('')
}

// ======== REPLACE LIBRARY VERSION ========
async function doReplaceLibrary(incomingId,matchedId){
  var msg=['确认替换旧版？','','这会执行以下操作：','','1. 将书架中的旧版移动到 archive/replaced；','2. 将新下载区中的新版加入书架；','3. 不会删除任何文件；','4. 不会覆盖已有文件；','5. 可在"操作记录"中恢复。'].join('\n');
  if(!confirm(msg))return;
  var r=await postApiSimple('/api/incoming/'+incomingId+'/replace-library/'+matchedId);
  if(!r||!r.ok){
    if(r&&r.error_code==='incoming_item_stale'){toast('该项目已经被处理，正在刷新检测结果。');doAnalyzeIncoming();return}
    if(r&&r.error_code==='matched_not_in_library'){toast('匹配的小说已不在书架中，请刷新检测结果。');doAnalyzeIncoming();return}
    toast(r&&r.error||'替换失败');return
  }
  _removeAnalysisCard(incomingId);
  var pt=r.progress_transfer;
  if(pt&&pt.copied>0){
    toast('已将新版加入书架，旧版已归档。新版已继承旧版阅读进度。');
  }else{
    toast('已替换旧版。旧版没有可继承的阅读进度。');
  }
  doAnalyzeIncoming();
  state.page=1;state.books=[];
  eid('shelf').innerHTML='';
  loadBooks();
}

// Event delegation for replace button
document.addEventListener('click',function(e){
  var btn=e.target.closest('.replace-btn');
  if(!btn)return;
  var incomingId=btn.getAttribute('data-incoming-id');
  var matchedId=btn.getAttribute('data-matched-id');
  if(incomingId&&matchedId)doReplaceLibrary(incomingId,matchedId);
});

function _removeAnalysisCard(bookId){
  var card=document.querySelector('.analysis-card[data-incoming-id="'+bookId+'"]');
  if(card)card.remove();
  if(analysisResult&&analysisResult.items){
    analysisResult.items=analysisResult.items.filter(function(it){return it.incoming_book_id!==bookId})
  }
}

async function doBatchSafe(){
  if(!analysisResult||!analysisResult.items)return;
  var items=analysisResult.items.filter(function(it){
    var aa=it.available_actions||[];
    return aa.indexOf('import_to_library')>=0||aa.indexOf('move_to_review_duplicates')>=0
  });
  if(items.length===0){toast('没有可处理的安全项');return}
  if(!confirm('一键处理 '+items.length+' 项安全操作？\n\n只会处理新书和简单重复项。\n不会处理可能是新版、需人工确认等项目。'))return;
  var imported=0,moved=0,failed=0;
  for(var i=0;i<items.length;i++){
    var it=items[i],aa=it.available_actions||[];
    var r;
    if(aa.indexOf('import_to_library')>=0){
      r=await postApiSimple('/api/incoming/'+it.incoming_book_id+'/import-to-library');
      if(r&&r.ok){imported++;_removeAnalysisCard(it.incoming_book_id)}else{failed++}
    }else if(aa.indexOf('move_to_review_duplicates')>=0){
      r=await postApiSimple('/api/incoming/'+it.incoming_book_id+'/move-to-review-duplicates');
      if(r&&r.ok){moved++;_removeAnalysisCard(it.incoming_book_id)}else{failed++}
    }
  }
  toast('完成：加入书架 '+imported+' 本，移入重复复核区 '+moved+' 本，失败 '+failed+' 本');
  doAnalyzeIncoming();
  state.page=1;state.books=[];eid('shelf').innerHTML='';loadBooks()
}

// ======== HEALTH CENTER ========
async function loadHealth(){
  var sumEl=eid('healthSummary'),issEl=eid('healthIssues');
  sumEl.innerHTML='<div class="loading"><div class="spinner"></div></div>';
  issEl.innerHTML='';

  var sum=await api('/api/health/summary');
  var issues=await api('/api/health/issues');

  if(!sum){sumEl.innerHTML='<div class="empty-state">无法获取健康状态</div>';return}

  var b=sum.books||{},p=sum.pending||{},o=sum.operations||{},i=sum.integrity||{};
  var statusClass=sum.status==='ok'?'health-ok':(sum.status==='warning'?'health-warn':'health-error');
  var statusLabel=sum.status==='ok'?'正常':(sum.status==='warning'?'有警告':'有错误');

  var h='<div class="health-status '+statusClass+'">仓库状态：'+statusLabel+'</div>';

  h+='<div class="health-section"><h3>📊 书库统计</h3><div class="health-cards">';
  h+='<div class="h-card"><span class="h-num">'+b.total+'</span><span class="h-label">小说总数</span></div>';
  h+='<div class="h-card"><span class="h-num">'+b.library+'</span><span class="h-label">书架</span></div>';
  h+='<div class="h-card"><span class="h-num">'+b.incoming+'</span><span class="h-label">新下载区</span></div>';
  h+='<div class="h-card"><span class="h-num">'+(b.review_duplicates||0)+'</span><span class="h-label">重复复核区</span></div>';
  h+='<div class="h-card"><span class="h-num">'+(b.archive||0)+'</span><span class="h-label">已归档</span></div>';
  h+='</div></div>';

  h+='<div class="health-section"><h3>⏳ 待处理项</h3><div class="health-cards">';
  h+='<div class="h-card"><span class="h-num">'+p.incoming_unprocessed+'</span><span class="h-label">新下载待处理</span></div>';
  h+='<div class="h-card"><span class="h-num">'+p.safe_new_books+'</span><span class="h-label">新书待入库</span></div>';
  h+='<div class="h-card"><span class="h-num">'+(p.safe_duplicates||0)+'</span><span class="h-label">简单重复待处理</span></div>';
  h+='<div class="h-card"><span class="h-num">'+(p.update_candidates||0)+'</span><span class="h-label">更新候选</span></div>';
  h+='<div class="h-card"><span class="h-num">'+(p.manual_review||0)+'</span><span class="h-label">人工确认</span></div>';
  h+='</div></div>';

  h+='<div class="health-section"><h3>📋 操作安全</h3><div class="health-cards">';
  h+='<div class="h-card"><span class="h-num">'+o.recent_total+'</span><span class="h-label">最近操作</span></div>';
  h+='<div class="h-card"><span class="h-num">'+o.reversible+'</span><span class="h-label">可恢复</span></div>';
  h+='<div class="h-card"><span class="h-num">'+o.restored+'</span><span class="h-label">已恢复</span></div>';
  h+='<div class="h-card"><span class="h-num">'+o.failed+'</span><span class="h-label">失败</span></div>';
  h+='</div></div>';

  h+='<div class="health-section"><h3>🔍 一致性检查</h3><div class="health-cards">';
  // missing_files is no longer shown as warning - user deletions are normal
  if(i.ignored_missing_files_count>0){
    h+='<div class="h-card h-info"><span class="h-num">'+i.ignored_missing_files_count+'</span><span class="h-label">已忽略缺失文件</span></div>';
  }
  h+='<div class="h-card '+(i.path_area_mismatch>0?'h-warn':'')+'"><span class="h-num">'+i.path_area_mismatch+'</span><span class="h-label">路径区域不一致</span></div>';
  h+='<div class="h-card '+(i.stale_incoming_records>0?'h-warn':'')+'"><span class="h-num">'+i.stale_incoming_records+'</span><span class="h-label">stale incoming</span></div>';
  if(i.external_removed_count>0){
    h+='<div class="h-card"><span class="h-num">'+i.external_removed_count+'</span><span class="h-label">已确认移除</span></div>';
  }
  if(i.ignored_missing_count>0){
    h+='<div class="h-card"><span class="h-num">'+i.ignored_missing_count+'</span><span class="h-label">已忽略缺失</span></div>';
  }
  h+='</div></div>';

  // Add info message about ignored missing files
  if(i.ignored_missing_files_count>0){
    h+='<div class="health-info-box">💡 已忽略本地缺失文件。若你手动删除了 TXT，健康中心不会将其视为错误。</div>';
  }

  if(sum.warnings&&sum.warnings.length>0){
    h+='<div class="health-warnings">';
    for(var w=0;w<sum.warnings.length;w++)h+='<div class="health-warn-item">⚠ '+esc(sum.warnings[w])+'</div>';
    h+='</div>';
  }

  sumEl.innerHTML=h;

  if(issues&&issues.items&&issues.items.length>0){
    var ih='<div class="health-section"><h3>🚨 问题列表</h3>';
    for(var j=0;j<issues.items.length;j++){
      var it=issues.items[j];
      var sev=it.severity==='error'?'issue-error':(it.severity==='warning'?'issue-warn':'issue-info');
      ih+='<div class="issue-card '+sev+'">';
      ih+='<div class="issue-head"><span class="issue-code">'+esc(it.code)+'</span>';
      if(it.book_id)ih+='<span class="issue-book-id">book_id: '+it.book_id+'</span>';
      ih+='</div>';
      ih+='<div class="issue-file">'+esc(it.file_name||it.current_path||'')+'</div>';
      ih+='<div class="issue-msg">'+esc(it.message)+'</div>';
      ih+='</div>';
    }
    ih+='</div>';
    issEl.innerHTML=ih;
  }
}

// ======== SYNC CLIENT ========
var syncState={
  deviceId:'',
  repoId:'',
  lastSyncedRevision:0,
  syncEnabled:false
};

function getOrCreateDeviceId(){
  var id=localStorage.getItem('novelhub_device_id');
  if(!id){
    id='mobile-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);
    localStorage.setItem('novelhub_device_id',id);
  }
  return id;
}

function loadSyncState(){
  syncState.deviceId=getOrCreateDeviceId();
  syncState.repoId=localStorage.getItem('novelhub_repo_id')||'';
  syncState.lastSyncedRevision=parseInt(localStorage.getItem('novelhub_last_revision')||'0',10);
}

function saveSyncState(){
  if(syncState.repoId)localStorage.setItem('novelhub_repo_id',syncState.repoId);
  localStorage.setItem('novelhub_last_revision',String(syncState.lastSyncedRevision));
}

async function checkSyncManifest(){
  try{
    var manifest=await api('/api/sync/manifest');
    if(!manifest)return null;
    if(syncState.repoId&&syncState.repoId!==manifest.repo_id){
      // Repo changed, reset local cache
      localStorage.removeItem('novelhub_last_revision');
      syncState.lastSyncedRevision=0;
    }
    syncState.repoId=manifest.repo_id;
    saveSyncState();
    return manifest;
  }catch(e){
    console.error('[NovelHub] checkSyncManifest failed:',e);
    return null;
  }
}

async function syncPullChanges(){
  var manifest=await checkSyncManifest();
  if(!manifest)return{ok:false,error:'无法获取同步清单'};

  if(manifest.server_revision<=syncState.lastSyncedRevision){
    return{ok:true,changes:0,message:'已是最新'};
  }

  var changes=await api('/api/sync/changes?since='+syncState.lastSyncedRevision);
  if(!changes)return{ok:false,error:'无法获取变更'};

  // Apply changes to local cache (placeholder - actual implementation would use IndexedDB)
  // For now, just refresh the book list
  if(changes.changes&&changes.changes.length>0){
    syncState.lastSyncedRevision=manifest.server_revision;
    saveSyncState();
    state.page=1;state.books=[];
    eid('shelf').innerHTML='';
    await loadBooks();
    return{ok:true,changes:changes.changes.length,message:'已同步 '+changes.changes.length+' 条变更'};
  }

  return{ok:true,changes:0,message:'无变更'};
}

async function syncPushProgress(){
  if(!syncState.deviceId)return{ok:false,error:'无设备ID'};

  // Collect pending progress from localStorage (placeholder)
  // In a full implementation, this would read from IndexedDB
  var pendingProgress=[];
  var progressKey='novelhub_pending_progress';
  try{
    var stored=localStorage.getItem(progressKey);
    if(stored)pendingProgress=JSON.parse(stored);
  }catch(e){}

  if(pendingProgress.length===0)return{ok:true,uploaded:0,message:'无待上传进度'};

  var r=await fetch('/api/sync/progress',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({device_id:syncState.deviceId,progress:pendingProgress})
  });

  if(!r.ok)return{ok:false,error:'上传失败'};

  var d=await r.json();
  if(d.ok&&d.accepted>0){
    localStorage.removeItem(progressKey);
    return{ok:true,uploaded:d.accepted,message:'已上传 '+d.accepted+' 条阅读进度'};
  }

  return{ok:true,uploaded:0,message:'无新进度上传'};
}

async function doFullSync(){
  toast('开始同步...');

  // Pull changes first
  var pullResult=await syncPullChanges();

  // Then push progress
  var pushResult=await syncPushProgress();

  var messages=[];
  if(pullResult.message)messages.push(pullResult.message);
  if(pushResult.message)messages.push(pushResult.message);

  toast(messages.join(' | '));
}

function updateSyncStatusUI(manifest){
  var el=eid('drawerStatus');
  if(!el)return;
  if(manifest){
    var rev=manifest.server_revision||0;
    el.textContent='已连接 r'+rev;
    el.title='repo_id: '+manifest.repo_id+'\nrevision: '+rev;
  }else{
    el.textContent='未连接';
  }
}

// ======== PAIRING ========
function loadAuthState(){
  authState.deviceId=localStorage.getItem('novelhub_device_id')||'';
  authState.deviceToken=localStorage.getItem('novelhub_device_token')||'';
  authState.isPaired=authState.deviceId&&authState.deviceToken;
}

function saveAuthState(){
  if(authState.deviceId)localStorage.setItem('novelhub_device_id',authState.deviceId);
  if(authState.deviceToken)localStorage.setItem('novelhub_device_token',authState.deviceToken);
}

function clearAuthState(){
  localStorage.removeItem('novelhub_device_token');
  authState.deviceToken='';
  authState.isPaired=false;
}

function showPairingPage(errorMsg){
  authState.needsPairing=true;
  var pp=eid('pairingPage');
  if(!pp)return;
  pp.classList.add('open');
  pp.style.display='';
  var shelf=eid('shelf');
  var groupTabs=eid('groupTabs');
  if(shelf)shelf.style.display='none';
  if(groupTabs)groupTabs.style.display='none';
  var errEl=eid('pairingError');
  if(errEl)errEl.textContent=errorMsg||'该设备尚未配对，请先在电脑端完成配对。';
  var codeInput=eid('pairingCodeInput');
  var nameInput=eid('deviceNameInput');
  if(codeInput)codeInput.value='';
  if(nameInput)nameInput.value='';
}

function hidePairingPage(){
  authState.needsPairing=false;
  var pp=eid('pairingPage');
  if(pp){
    pp.classList.remove('open');
    pp.style.display='none';
  }
  var shelf=eid('shelf');
  var groupTabs=eid('groupTabs');
  if(shelf)shelf.style.display='';
  if(groupTabs)groupTabs.style.display='';
}

async function doPairing(){
  var code=eid('pairingCodeInput').value.trim();
  var name=eid('deviceNameInput').value.trim();
  if(!code){
    toast('请输入配对码');
    return;
  }
  if(!authState.deviceId){
    authState.deviceId='mobile-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);
  }
  var btn=eid('pairingBtn');
  btn.disabled=true;
  btn.textContent='配对中...';
  try{
    var r=await fetch('/api/pairing/confirm',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({pairing_code:code,device_id:authState.deviceId,device_name:name||'Mobile Device'})
    });
    var d=await r.json();
    btn.disabled=false;
    btn.textContent='完成配对';
    if(!r.ok||!d.ok){
      var errEl=eid('pairingError');
      if(errEl)errEl.textContent=d.error||'配对失败';
      return;
    }
    authState.deviceToken=d.device_token;
    authState.isPaired=true;
    saveAuthState();
    toast('配对成功');
    hidePairingPage();
    init();
  }catch(e){
    btn.disabled=false;
    btn.textContent='完成配对';
    var errEl=eid('pairingError');
    if(errEl)errEl.textContent='网络错误，请重试';
  }
}

function checkPairUrl(){
  var hash=window.location.hash||'';
  if(hash.indexOf('pair=')>=0){
    var code=hash.split('pair=')[1].split('&')[0];
    if(code){
      var input=eid('pairingCodeInput');
      if(input)input.value=code;
      showPairingPage('');
    }
  }
}

// ======== SETTINGS PAGE ========
function showSettingsPage(){
  var sp=eid('settingsPage');
  if(sp){
    sp.classList.add('open');
    sp.style.display='';
  }
  var shelf=eid('shelf');
  var groupTabs=eid('groupTabs');
  if(shelf)shelf.style.display='none';
  if(groupTabs)groupTabs.style.display='none';
  updateSettingsDisplay();
}

function hideSettingsPage(){
  var sp=eid('settingsPage');
  if(sp){
    sp.classList.remove('open');
    sp.style.display='none';
  }
  var shelf=eid('shelf');
  var groupTabs=eid('groupTabs');
  if(shelf)shelf.style.display='';
  if(groupTabs)groupTabs.style.display='';
}

function updateSettingsDisplay(){
  var info=eid('deviceInfo');
  if(!info)return;
  var h='<div class="settings-row"><span>设备 ID</span><span style="color:var(--muted)">'+esc(authState.deviceId||'未生成')+'</span></div>';
  h+='<div class="settings-row"><span>配对状态</span><span style="color:'+((authState.isPaired)?'var(--accent)':'var(--error)')+'">'+((authState.isPaired)?'已配对':'未配对')+'</span></div>';
  if(authState.isPaired){
    h+='<div class="settings-row"><button class="btn-cancel" onclick="clearPairing()">清除配对</button></div>';
  }
  info.innerHTML=h;
}

function clearPairing(){
  if(!confirm('确认清除配对？\n\n清除后需要重新配对才能访问书库。'))return;
  clearAuthState();
  showPairingPage('配对已清除，请重新配对。');
  hideSettingsPage();
}

// ======== DESKTOP PAIRING CODE GENERATION ========
async function createPairingCode(){
  var btn=eid('createPairingBtn');
  if(btn){
    btn.disabled=true;
    btn.textContent='生成中...';
  }
  try{
    var r=await fetch('/api/pairing/create',{method:'POST'});
    var d=await r.json();
    if(btn){
      btn.disabled=false;
      btn.textContent='生成配对码';
    }
    if(!r.ok||!d.pairing_code){
      toast('生成配对码失败');
      return;
    }
    var display=eid('pairingCodeDisplay');
    if(display){
      display.innerHTML='<div class="pairing-code-box"><div class="pairing-code">'+esc(d.pairing_code)+'</div><div class="pairing-expires">有效期 5 分钟</div><div class="pairing-url">'+esc(d.pair_url||'')+'</div></div>';
    }
    toast('配对码: '+d.pairing_code);
  }catch(e){
    if(btn){
      btn.disabled=false;
      btn.textContent='生成配对码';
    }
    toast('网络错误');
  }
}

async function loadPairedDevices(){
  var list=eid('pairedDevicesList');
  if(!list)return;
  list.innerHTML='<div class="loading"><div class="spinner"></div></div>';
  try{
    var r=await fetch('/api/pairing/devices');
    var d=await r.json();
    if(!r.ok||!d.ok){
      list.innerHTML='<div class="empty-state">无法获取设备列表</div>';
      return;
    }
    var devices=d.devices||[];
    if(devices.length===0){
      list.innerHTML='<div class="empty-state">暂无已配对设备</div>';
      return;
    }
    var h='<div class="device-list">';
    for(var i=0;i<devices.length;i++){
      var dev=devices[i];
      var status=dev.revoked?'已撤销':'已配对';
      var statusClass=dev.revoked?'device-revoked':'device-active';
      h+='<div class="device-card '+statusClass+'">';
      h+='<div class="device-head"><span class="device-name">'+esc(dev.device_name||dev.device_id)+'</span><span class="device-status">'+status+'</span></div>';
      h+='<div class="device-meta">ID: '+esc(dev.device_id)+'</div>';
      h+='<div class="device-meta">创建: '+esc(dev.created_at||'')+'</div>';
      if(dev.last_seen_at)h+='<div class="device-meta">最后访问: '+esc(dev.last_seen_at)+'</div>';
      if(!dev.revoked){
        h+='<div class="device-actions"><button class="btn-sm btn-cancel" onclick="revokeDevice(\''+esc(dev.device_id)+'\')">撤销授权</button></div>';
      }
      h+='</div>';
    }
    h+='</div>';
    list.innerHTML=h;
  }catch(e){
    list.innerHTML='<div class="empty-state">网络错误</div>';
  }
}

async function revokeDevice(deviceId){
  if(!confirm('确认撤销该设备的授权？\n\n撤销后该设备将无法继续访问书库。'))return;
  try{
    var r=await fetch('/api/pairing/devices/'+encodeURIComponent(deviceId)+'/revoke',{method:'POST'});
    var d=await r.json();
    if(!r.ok||!d.ok){
      toast(d.error||'撤销失败');
      return;
    }
    toast('已撤销授权');
    loadPairedDevices();
  }catch(e){
    toast('网络错误');
  }
}

// ======== INIT ========
async function init(){
  console.log('[NovelHub] init start');

  // Initialize navigation first (must work even if API fails)
  initNavigation();

  // Initialize sync state
  loadSyncState();

  // Load auth state
  loadAuthState();

  // Check pairing URL
  checkPairUrl();

  // Try to connect to server
  try{
    var h=await api('/api/health');
    if(h&&h.ok){
      if(!authState.needsPairing){
        try{
          var manifest=await checkSyncManifest();
          updateSyncStatusUI(manifest);
        }catch(e){
          console.error('[NovelHub] sync manifest check failed:',e);
        }
      }
    }
  }catch(e){
    console.error('[NovelHub] health check failed:',e);
  }

  // Load data if not in pairing mode
  if(!authState.needsPairing){
    try{
      loadGroups();
      loadBooks();
    }catch(e){
      console.error('[NovelHub] load data failed:',e);
    }
  }

  console.log('[NovelHub] init complete');
}

// Initialize auth state on load
loadAuthState();

// Start init
init();
