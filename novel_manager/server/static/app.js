let state={books:[],groups:[],currentGroup:'',offset:0,limit:60,total:0,loading:false,hasMore:true,searchQuery:'',currentPage:'home'};
let readerState={currentBookId:null,currentTitle:'',barsVisible:true,lastScroll:0,saveThrottle:null};

// ======== UTILS ========
function eid(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
async function api(url){try{const r=await fetch(url);return r.ok?r.json():null}catch(e){return null}}
function toast(msg){const t=eid('toast');t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2000)}
function readerToast(msg){const t=eid('readerToast');t.textContent=msg;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2500)}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms)})}

// ======== DRAWER ========
function toggleDrawer(){eid('drawer').classList.toggle('open');eid('overlay').classList.toggle('open')}
function showPage(page){state.currentPage=page;eid('updatesPage').classList.toggle('open',page==='updates');eid('shelf').style.display=page==='home'?'':'none';eid('groupTabs').style.display=page==='home'?'':'none';if(page==='updates')loadUpdates()}

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
    if(contentData.encoding){eid('readerEncoding').textContent='编码：'+contentData.encoding.toUpperCase();eid('readerEncoding').style.display=''}
    if(contentData.decode_warning){eid('readerWarning').textContent='⚠ '+contentData.decode_warning;eid('readerWarning').style.display=''}
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
}

async function saveReadingProgress(){
  if(!readerState.currentBookId)return;
  updateReaderProgress();
  await fetch('/api/books/'+readerState.currentBookId+'/progress',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({progress_ratio:Math.round(readerState.lastScroll/(eid('readerContent').scrollHeight-eid('readerContent').clientHeight||1)*100)/100||0,scroll_position:readerState.lastScroll,device_id:'web'})
  }).catch(function(){})
}

function scrollToTop(){eid('readerContent').scrollTop=0;readerState.barsVisible=true;eid('reader').classList.add('bars-visible')}

// scroll tracking
eid('readerContent').addEventListener('scroll',function(){updateReaderProgress()});

// save progress on unload
window.addEventListener('beforeunload',function(){saveReadingProgress()});

// ======== UPDATES ========
async function loadUpdates(){var d=await api('/api/updates/summary');var c=eid('updatesContent');if(!d){c.innerHTML='<div class="empty-state">暂无更新数据</div>';return}var h='<p style="margin-bottom:12px;color:var(--muted)">推荐更新 '+(d.replace_recommended||0)+' 个，需复核 '+(d.manual_review||0)+' 个，已拒绝 '+(d.reject||0)+' 个</p>';for(var i=0;i<(d.candidates||[]).length;i++){var x=d.candidates[i];var cls=x.recommendation==='replace_recommended'?'replace':x.recommendation==='reject'?'reject':'review';var lb=x.recommendation==='replace_recommended'?'建议更新':x.recommendation==='reject'?'不建议':'需复核';h+='<div class="update-card"><span class="rec '+cls+'">'+lb+'</span><div><strong>'+esc(x.old_file||'')+'</strong> → '+esc(x.new_file||'')+'</div><div style="font-size:12px;color:var(--muted)">'+esc(x.reason_summary||'')+'</div></div>'}c.innerHTML=h||'<div class="empty-state">暂无更新候选</div>'}

// ======== INIT ========
async function init(){var h=await api('/api/health');if(h&&h.ok)eid('drawerStatus').textContent='仓库已连接';loadGroups();loadBooks()}
init();
