let state={books:[],groups:[],currentGroup:'',offset:0,limit:60,total:0,loading:false,hasMore:true,searchQuery:'',currentPage:'home'};

async function api(url){try{const r=await fetch(url);return r.ok?r.json():null}catch(e){return null}}

function toggleDrawer(){document.getElementById('drawer').classList.toggle('open');document.getElementById('overlay').classList.toggle('open')}

function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2000)}

function showPage(page){state.currentPage=page;document.getElementById('updatesPage').classList.toggle('open',page==='updates');document.getElementById('shelf').style.display=page==='home'?'':'none';document.getElementById('groupTabs').style.display=page==='home'?'':'none';if(page==='updates')loadUpdates()}

async function loadGroups(){const d=await api('/api/groups');if(!d||!d.items)return;state.groups=d.items;renderGroupTabs()}

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function renderGroupTabs(){const c=document.getElementById('groupTabs');let h='<div class="group-tab'+(state.currentGroup===''?' active':'')+'" onclick="selectGroup(\'\')">📚 全部</div>';for(const g of state.groups)h+='<div class="group-tab'+(state.currentGroup===g.name?' active':'')+'" onclick="selectGroup(\''+esc(g.name)+'\')">'+esc(g.name)+' ('+g.book_count+')</div>';h+='<div class="group-tab add" onclick="showGroupModal()">+ 新建分组</div>';c.innerHTML=h}

function selectGroup(name){state.currentGroup=name;state.offset=0;state.books=[];state.hasMore=true;document.getElementById('shelf').innerHTML='';renderGroupTabs();loadBooks()}

function showGroupModal(){document.getElementById('groupModal').classList.add('open');document.getElementById('groupNameInput').value='';document.getElementById('groupNameInput').focus()}
function closeGroupModal(){document.getElementById('groupModal').classList.remove('open')}

async function createGroup(){const n=document.getElementById('groupNameInput').value.trim();if(!n){toast('请输入分组名称');return}const r=await fetch('/api/groups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});const d=await r.json();if(!r.ok){toast(d.detail||'创建失败');return}closeGroupModal();toast(d.existed?'分组已存在':'分组已创建');loadGroups()}

async function loadBooks(){if(state.loading||!state.hasMore)return;state.loading=true;const q=state.searchQuery;let url='/api/books?limit='+state.limit+'&offset='+state.offset;if(q)url+='&q='+encodeURIComponent(q);const d=await api(url);state.loading=false;if(!d)return;if(state.offset===0)state.books=d.items||[];else state.books=state.books.concat(d.items||[]);state.total=d.total||0;state.hasMore=state.books.length<state.total;state.offset+=state.limit;renderShelf()}

function onSearch(){state.searchQuery=document.getElementById('searchInput').value.trim();state.offset=0;state.books=[];state.hasMore=true;document.getElementById('shelf').innerHTML='';loadBooks()}

function renderShelf(){const s=document.getElementById('shelf');const e=document.getElementById('emptyState');if(state.books.length===0&&!state.loading){s.innerHTML='';e.style.display='block';return}e.style.display='none';let h='';for(const b of state.books){const t=esc(b.title||'未知书名');const a=esc(b.author||'');const cc=b.chapter_count||0;const qs=b.quality_score!=null?Math.round(b.quality_score):'';const tags=(b.tags||[]).slice(0,3).map(x=>'<span class="tag">'+esc(x)+'</span>').join('');const p=(b.reading_progress||0)*100;h+='<div class="book-card" onclick="openBook('+b.book_id+',\''+esc(b.title||'')+'\')"><div class="title">'+t+'</div>'+(a?'<div class="author">'+a+'</div>':'')+(tags?'<div class="tags">'+tags+'</div>':'')+'<div class="progress-bar"><div class="fill" style="width:'+p+'%"></div></div><div class="meta"><span>'+(cc?cc+'章':'')+'</span><span>'+(qs?qs+'分':'')+'</span></div></div>'}if(state.loading)h+='<div class="loading"><div class="spinner"></div></div>';s.innerHTML=h}

window.addEventListener('scroll',()=>{if(state.currentPage!=='home')return;if(window.scrollY+window.innerHeight>document.body.offsetHeight-300)loadBooks()});

async function openBook(id,title){document.getElementById('reader').classList.add('open');document.getElementById('readerTitle').textContent=title;document.getElementById('readerContent').textContent='加载中...';const d=await api('/api/books/'+id+'/content');if(d&&d.content)document.getElementById('readerContent').textContent=d.content;else if(d&&d.error)document.getElementById('readerContent').textContent='错误: '+d.error;else document.getElementById('readerContent').textContent='无法加载小说内容'}

function closeReader(){document.getElementById('reader').classList.remove('open')}

async function loadUpdates(){const d=await api('/api/updates/summary');const c=document.getElementById('updatesContent');if(!d){c.innerHTML='<div class="empty-state">暂无更新数据</div>';return}let h='<p style="margin-bottom:12px;color:var(--muted)">推荐更新 '+(d.replace_recommended||0)+' 个，需复核 '+(d.manual_review||0)+' 个，已拒绝 '+(d.reject||0)+' 个</p>';for(const x of(d.candidates||[])){const cls=x.recommendation==='replace_recommended'?'replace':(x.recommendation==='reject'?'reject':'review');const lb=x.recommendation==='replace_recommended'?'建议更新':(x.recommendation==='reject'?'不建议':'需复核');h+='<div class="update-card"><span class="rec '+cls+'">'+lb+'</span><div><strong>'+esc(x.old_file||'')+'</strong> → '+esc(x.new_file||'')+'</div><div style="font-size:12px;color:var(--muted)">'+esc(x.reason_summary||'')+'</div></div>'}c.innerHTML=h||'<div class="empty-state">暂无更新候选</div>'}

async function init(){const h=await api('/api/health');if(h&&h.ok)document.getElementById('drawerStatus').textContent='仓库已连接';loadGroups();loadBooks()}
init();
