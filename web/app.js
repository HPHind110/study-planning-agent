'use strict';
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pages = {overview:'Tổng quan',tasks:'Việc học',courses:'Môn học',history:'Nhật ký'};
const dayNames = ['Thứ 2','Thứ 3','Thứ 4','Thứ 5','Thứ 6','Thứ 7','CN'];
const pad = v => String(v).padStart(2,'0');
const iso = d => [d.getFullYear(),pad(d.getMonth()+1),pad(d.getDate())].join('-');
const local = d => new Date(d+'T12:00:00');
const offset = (d,n) => {const t=local(d);t.setDate(t.getDate()+n);return iso(t)};
const today = () => iso(new Date());
const monday = d => offset(d,-((local(d).getDay()+6)%7));
const short = d => local(d).toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit'});
const mins = n => n<60 ? n+' phút' : Math.floor(n/60)+' giờ'+(n%60?' '+n%60+'′':'');
const sum = (xs,fn) => xs.reduce((n,x)=>n+fn(x),0);
const button = (text,action,id='',cls='') => '<button type="button" class="'+cls+'" data-action="'+action+'" data-id="'+esc(id)+'">'+esc(text)+'</button>';
const empty = text => '<p class="empty">'+esc(text)+'</p>';
const option = (v,label=v,selected=false) => '<option value="'+esc(v)+'"'+(selected?' selected':'')+'>'+esc(label)+'</option>';
const tag = t => '<span class="tag '+(t.priority>=4?'high':'')+'">Ưu tiên '+t.priority+'/5</span>';
const field = (title,html) => '<label>'+esc(title)+html+'</label>';
const input = (name,value,type='text',attrs='') => '<input name="'+name+'" type="'+type+'" value="'+esc(value)+'" '+attrs+'>';
const num = (name,value,min,max) => input(name,value,'number','required min="'+min+'" max="'+max+'"');
let state=null,page='overview',selected=today(),busy=false,submit=null,filter='open',courseFilter='';
function note(text,bad=false){$('notice').className=bad?'bad':'';$('notice').textContent=text}
async function request(url,method='GET',body){
  const opts={method,cache:'no-store'};
  if(body!==undefined){opts.headers={'Content-Type':'application/json'};opts.body=JSON.stringify(body)}
  const r=await fetch(url,opts);
  if(!r.ok){let msg='HTTP '+r.status;try{const {detail}=await r.json();msg=Array.isArray(detail)?detail.map(x=>x.loc.slice(1).join('.')+' — '+x.msg).join('; '):detail||msg}catch{}throw Error(msg)}
  return r.json();
}
async function refresh(){state=await request('/dashboard');render()}
async function perform(fn,success=''){
  if(busy)return;
  busy=true;$('view').setAttribute('aria-busy','true');note('Đang xử lý…');$('error').textContent='';
  try{await fn();note(success)}catch(e){
    if($('modal').open)$('error').textContent=e.message;
    note('Không thể hoàn tất. '+e.message,true);
    if(!state)$('view').innerHTML=button('Thử tải lại','refresh');
  }finally{busy=false;$('view').setAttribute('aria-busy','false')}
}
async function change(url,method,body){await request(url,method,body);$('modal').close();await refresh()}
function modal(title,fields,save,label='Lưu',extra=''){
  $('dialogTitle').textContent=title;$('fields').innerHTML=fields;$('error').textContent='';
  $('actions').innerHTML=extra+(save?'<button class="primary" type="submit">'+esc(label)+'</button>':'');
  submit=save;if(!$('modal').open)$('modal').showModal();
}
$('form').addEventListener('submit',e=>{
  e.preventDefault();const data=new FormData(e.target);if(submit)perform(()=>submit(data),'Đã lưu thay đổi.');
});
const entries=()=>Object.entries(state.tasks);
const metric=(title,value,symbol)=>'<div class="metric"><span class="symbol">'+symbol+'</span><small>'+title+'</small><strong>'+value+'</strong></div>';
function deadline(t){const late=t.left>0 && new Date(t.due.replace(' ','T'))<new Date();return (late?'Quá hạn · ':'Hạn ')+short(t.due.slice(0,10))+' '+t.due.slice(11)}
function taskRow([id,t]){
 return '<div class="row"><div class="grow"><h3>'+esc(t.name)+'</h3><small>'+esc(t.course)+' · '+esc(deadline(t))+'</small></div>'+tag(t)+'<span class="status">'+(t.left?mins(t.left):'Hoàn thành')+'</span>'+button('Chi tiết','edit',id)+'</div>';
}
function calendar(){
 const first=monday(selected),last=offset(first,6);
 const days=Array.from({length:7},(_,i)=>offset(first,i));
 const sessions=state.sessions.filter(h=>h.start.slice(0,10)===selected);
 const grid=days.map((d,i)=>{
   const hours=sum(state.sessions.filter(h=>h.start.startsWith(d)),h=>h.minutes);
   return '<button type="button" aria-pressed="'+(d===selected)+'" data-action="day" data-id="'+d+'" class="day '+(d===selected?'active ':'')+(d===today()?'today':'')+'">'+dayNames[i]+'<strong>'+d.slice(-2)+'</strong><div class="track"><div class="fill" style="width:'+Math.min(100,hours/state.settings.cap*100)+'%"></div></div><small>'+hours+' phút</small></button>';
 }).join('');
 const agenda=sessions.map(h=>'<div class="row"><span class="time">'+h.start.slice(11)+' – '+h.end.slice(11)+'</span><div class="grow"><h3>'+esc(state.tasks[h.task].name)+'</h3><small>'+esc(state.tasks[h.task].course)+'</small></div>'+button('Xem buổi','session',h.start)+'</div>').join('');
 return '<section class="panel"><div class="head"><div><h2>Lịch học tuần</h2><small>'+short(first)+' – '+short(last)+' / '+last.slice(0,4)+'</small></div><div class="toolbar">'+button('←','prev')+button('Hôm nay','today')+button('→','next')+'</div></div><div class="week">'+grid+'</div><div class="head section-title"><h3>Buổi học ngày '+short(selected)+'</h3>'+button(state.sessions.length?'Xếp lại lịch':'Tạo lịch',state.sessions.length?'replan':'generate')+'</div>'+(agenda||empty('Chưa có buổi học trong ngày này.'))+'</section>';
}
function overview(){
 const tasks=entries(),open=tasks.filter(([,t])=>t.left),done=tasks.length-open.length;
 const actual=sum(state.history,h=>h.actual),left=sum(open,([,t])=>t.left);
 const upcoming=open.sort((a,b)=>a[1].due.localeCompare(b[1].due)).slice(0,5);
 const workloads=state.courses.map(c=>[c,sum(open.filter(([,t])=>t.course===c),([,t])=>t.left)]).sort((a,b)=>b[1]-a[1]);
 const alerts=state.warnings.length?'<section class="panel"><h2>Cần lưu ý</h2><ul>'+state.warnings.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></section>':'';
 return '<div class="metrics">'+metric('Khối lượng còn lại',mins(left),'◷')+metric('Việc đang mở',open.length,'☷')+metric('Việc hoàn thành',done+' / '+tasks.length,'✓')+metric('Đã thực học',mins(actual),'◴')+'</div>'+calendar()+alerts+'<div class="split"><section class="panel"><h2>Hạn gần nhất</h2>'+(upcoming.map(taskRow).join('')||empty('Các việc đang mở sẽ xuất hiện ở đây.'))+'</section><section class="panel"><h2>Khối lượng theo môn</h2>'+(workloads.map(([c,n])=>'<div class="row"><div class="grow">'+esc(c)+'<div class="track"><div class="fill" style="width:'+(left?n/left*100:0)+'%"></div></div></div><small>'+mins(n)+'</small></div>').join('')||empty('Thêm môn hoặc việc học để theo dõi khối lượng.'))+'</section></div>';
}
function tasksPage(){
 const visible=entries().filter(([,t])=>(!courseFilter||t.course===courseFilter)&&(filter==='all'||(filter==='open'?t.left>0:t.left===0))).sort((a,b)=>a[1].due.localeCompare(b[1].due));
 return '<section class="panel"><div class="head"><h2>Danh sách việc</h2><div class="toolbar"><select aria-label="Trạng thái" id="filter">'+[['open','Đang mở'],['done','Hoàn thành'],['all','Tất cả trạng thái']].map(([v,l])=>option(v,l,filter===v)).join('')+'</select><select aria-label="Lọc theo môn" id="courseFilter">'+option('','Mọi môn')+state.courses.map(c=>option(c,c,c===courseFilter)).join('')+'</select></div></div>'+(visible.map(taskRow).join('')||empty('Chưa có việc phù hợp với bộ lọc.'))+'</section>';
}
function render(){
 $('today').textContent=new Date().toLocaleDateString('vi-VN',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
 $('title').textContent=pages[page];document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
 let html;
 if(page==='overview')html=overview();
 if(page==='tasks')html=tasksPage();
 if(page==='courses')html='<section class="panel"><div class="head"><h2>Danh sách môn</h2>'+button('＋ Thêm môn','courseNew')+'</div><div class="cards">'+(state.courses.map(c=>{
  const group=entries().filter(([,t])=>t.course===c);return '<article class="course"><h3>'+esc(c)+'</h3><p>'+group.length+' việc · '+mins(sum(group,([,t])=>t.left))+' còn lại</p>'+button('Quản lý','courseEdit',c)+'</article>';
 }).join('')||empty('Thêm môn học đầu tiên.'))+'</div></section>';
 if(page==='history')html='<section class="panel"><h2>Nhật ký học tập</h2>'+(state.history.slice().reverse().map(h=>'<div class="row"><div class="grow"><h3>'+esc(h.name)+'</h3><small>'+esc(h.at)+' · '+esc(h.status)+'</small></div><span>'+mins(h.actual)+' thực học</span><small>Còn '+mins(h.remaining)+'</small></div>').join('')||empty('Kết quả đã ghi và buổi bị bỏ sẽ xuất hiện ở đây.'))+'</section>';
 $('view').innerHTML=html;
}
function taskForm(id){
 const t=state.tasks[id]||{name:'',course:state.courses[0]||'',kind:'Bài tập',due:offset(today(),7)+' 22:00',estimate:60,priority:3,difficulty:3,deps:[]};
 const fields=field('Tên việc',input('name',t.name,'text','required maxlength="250"'))+field('Môn học',input('course',t.course,'text','required list="courses" maxlength="250"')+'<datalist id="courses">'+state.courses.map(c=>option(c)).join('')+'</datalist>')+
 field('Loại việc','<select name="kind">'+['Bài tập','Kỳ thi','Mục tiêu'].map(k=>option(k,k,k===t.kind)).join('')+'</select>')+
 field('Hạn hoàn thành',input('due',t.due.replace(' ','T'),'datetime-local','required'))+field('Khối lượng dự kiến (phút)',num('estimate',t.estimate,1,100000))+
 (id?field('Khối lượng còn lại (phút)',num('left',t.left,0,100000)):'')+field('Ưu tiên (1–5)',num('priority',t.priority,1,5))+field('Độ khó (1–5)',num('difficulty',t.difficulty,1,5))+
 field('Việc tiên quyết (có thể chọn nhiều)','<select multiple name="deps">'+entries().filter(([k])=>k!==id).map(([k,v])=>option(k,v.name,t.deps.includes(k))).join('')+'</select>');
 modal(id?'Chi tiết việc học':'Thêm việc học',fields,async f=>{
   const body=Object.fromEntries(f);body.due=body.due.replace('T',' ');body.deps=f.getAll('deps');
   for(const k of ['estimate','difficulty','priority','left'])if(k in body)body[k]=Number(body[k]);
   await change(id?'/tasks/'+encodeURIComponent(id):'/tasks',id?'PUT':'POST',body);
 },'Lưu việc',id?button('Ghi tiến độ','log',id)+button('Xóa','taskDelete',id,'danger'):'');
}
function progress(id,start){
 const t=state.tasks[id],s=start&&state.sessions.find(h=>h.start===start);
 modal('Ghi tiến độ · '+t.name,field('Phút thực học',num('actual',s?s.minutes:0,0,1440))+field('Phút còn lại (0 = hoàn thành)',num('remaining',s?Math.max(0,t.left-s.minutes):t.left,0,100000)),f=>
 change('/progress','POST',{task:id,actual:Number(f.get('actual')),remaining:Number(f.get('remaining')),...(start?{start}:{})}));
}
function settings(){
 const c=state.settings;
 modal('Giờ rảnh & giới hạn','<p class="muted">Nhập khung giờ như 08:00-10:00, 19:00-21:00. Để trống ngày nghỉ.</p>'+dayNames.map((d,i)=>field(d,input('day'+i,c.windows[i]))).join('')+field('Ngày bận (YYYY-MM-DD, cách bằng dấu phẩy)',input('off',c.off.join(', ')))+field('Tối đa phút/ngày',num('cap',c.cap,1,720))+field('Tối đa phút/buổi',num('block',c.block,5,120))+field('Nghỉ giữa buổi (phút)',num('rest',c.rest,1,60)),f=>change('/plans/replan','POST',{settings:{windows:dayNames.map((_,i)=>f.get('day'+i)),off:f.get('off').split(',').map(x=>x.trim()).filter(Boolean),cap:+f.get('cap'),block:+f.get('block'),rest:+f.get('rest')}}),'Lưu và xếp lại lịch');
}
document.addEventListener('change',e=>{if(e.target.id==='filter'){filter=e.target.value;render()}if(e.target.id==='courseFilter'){courseFilter=e.target.value;render()}});
document.addEventListener('click',e=>{
 const b=e.target.closest('button');if(!b||busy)return;
 const {action:a,id,page:p}=b.dataset;
 if(a==='refresh')return perform(refresh);
 if(!state)return;
 if(p){page=p;render();return}
 if(a==='close')return $('modal').close();
 if(a==='new'||a==='edit')return taskForm(id||'');
 if(a==='settings')return settings();
 if(a==='today'||a==='day'||a==='prev'||a==='next'){selected=a==='today'?today():a==='day'?id:offset(selected,a==='prev'?-7:7);return render()}
 if(a==='generate'||a==='replan')return perform(async()=>{await request('/plans/'+a,'POST',a==='replan'?{}:undefined);await refresh()},'Đã cập nhật lịch học.');
 if(a==='courseNew'||a==='courseEdit'){
   const edit=a==='courseEdit';return modal(edit?'Quản lý môn học':'Thêm môn học',field('Tên môn',input('name',id,'text','required maxlength="250"')),async f=>{
     courseFilter='';await change('/courses',edit?'PATCH':'POST',edit?{name:id,new_name:f.get('name')}:{name:f.get('name')});
   },'Lưu môn',edit?button('Xóa môn','courseDelete',id,'danger'):'');
 }
 if(a==='courseDelete'||a==='taskDelete'){
   const course=a==='courseDelete';return modal('Xác nhận xóa','<p>'+esc(course?id:state.tasks[id].name)+'</p>',()=>change(course?'/courses':'/tasks/'+encodeURIComponent(id),'DELETE',course?{name:id}:undefined),'Xóa');
 }
 if(a==='log')return progress(id);
 if(a==='session'){
   const h=state.sessions.find(x=>x.start===id);if(!h)return;
   const active=new Date(h.start.replace(' ','T'))<=new Date();
   return modal(state.tasks[h.task].name,'<p>'+esc(h.start)+' – '+esc(h.end.slice(11))+'</p><p class="muted">'+esc(h.reason)+'</p>',null,'',button('Bỏ buổi và xếp lại','skip',id)+(active?button('Ghi kết quả','sessionLog',id):''));
 }
 if(a==='sessionLog'||a==='skip'){
   const h=state.sessions.find(x=>x.start===id);if(!h)return;
   if(a==='sessionLog')return progress(h.task,id);
   return perform(()=>change('/plans/replan','POST',{skip:[{task:h.task,start:id}]}),'Đã bỏ buổi và xếp lại lịch.');
 }
});
perform(refresh);
setInterval(()=>{if(!document.hidden&&!busy&&!$('modal').open)perform(refresh)},60000);

