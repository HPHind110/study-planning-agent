/* Academic planning controls, using the dashboard's shared modal and request helpers. */
function academicFields(t){
  return field('Bắt đầu sớm nhất',input('start_at',(t.start_at||'').replace(' ','T'),'datetime-local'))+
    field('Loại hạn','<select name="deadline_type">'+option('hard','Cứng · hạn chính thức',t.deadline_type!=='soft')+
      option('soft','Mềm · mục tiêu nội bộ',t.deadline_type==='soft')+'</select>')+
    field('Ghi chú','<textarea name="notes" rows="2">'+esc(t.notes)+'</textarea>');
}

function occurrenceList(day){
  const rows=[];
  const distance=(a,b)=>(Date.parse(a+'T00:00:00Z')-Date.parse(b+'T00:00:00Z'))/86400000;
  for(const [id,ev] of Object.entries(state.events||{})){
    const first=ev.start.slice(0,10),last=ev.end.slice(0,10);
    const weekly=ev.repeat==='weekly';
    const earliest=weekly?Math.max(0,Math.floor(distance(day,last)/7)):0;
    const limit=ev.until&&ev.until<day?ev.until:day;
    const latest=weekly?Math.floor(distance(limit,first)/7):0;
    for(let i=earliest;i<=latest;i++){
      const a=offset(first,7*i)+ev.start.slice(10),b=offset(last,7*i)+ev.end.slice(10);
      if(a<day+' 24:00'&&b>day+' 00:00')rows.push([id,{...ev,start:a<day+' 00:00'?day+' 00:00':a,end:b>day+' 24:00'?day+' 24:00':b}]);
    }
  }
  return rows.sort((a,b)=>a[1].start.localeCompare(b[1].start));
}

function eventRow([id,ev]){
  return '<div class="row"><span class="tag">Cố định</span><div class="grow"><h3>'+esc(ev.name)+
    '</h3><small>'+esc(ev.start.slice(11)+' – '+ev.end.slice(11))+'</small></div>'+button('Sửa sự kiện','evEdit',id)+'</div>';
}

function eventForm(id){
  const ev=state.events?.[id]||{name:'',start:selected+' 09:00',end:selected+' 10:00',repeat:'once'};
  modal(id?'Sửa sự kiện':'Thêm sự kiện',field('Tên',input('name',ev.name,'text','required'))+
    field('Bắt đầu',input('start',ev.start.replace(' ','T'),'datetime-local','required'))+
    field('Kết thúc',input('end',ev.end.replace(' ','T'),'datetime-local','required'))+
    field('Lặp','<select name="repeat">'+option('once','Một lần',ev.repeat!=='weekly')+
      option('weekly','Hàng tuần',ev.repeat==='weekly')+'</select>')+
    field('Lặp đến hết ngày',input('until',ev.until||'','date')),f=>{
      const data=Object.fromEntries(f);
      for(const k of ['start','end'])data[k]=data[k].replace('T',' ');
      data.until=data.until||null;
      return change(id?'/events/'+encodeURIComponent(id):'/events',id?'PUT':'POST',data);
    },'Lưu sự kiện',id?button('Xóa','evRemove',id,'danger'):'');
}

function calendarConfig(){
  const cfg=state.settings,events=Object.entries(state.events||{});
  const overrides=Object.entries(cfg.overrides||{}).sort(([a],[b])=>a.localeCompare(b));
  return '<section class="panel"><div class="head"><h2>Kỳ lập lịch</h2>'+button('Chỉnh kỳ & giới hạn','horizon')+
    '</div><p>Đến hết '+esc(state.analysis.horizon_end)+(cfg.horizon_end?'':' · 90 ngày tính từ hôm nay')+
    '</p></section><section class="panel"><div class="head"><h2>Ngoại lệ theo ngày</h2>'+button('Thêm ngày / khoảng ngày','override')+
    '</div>'+ (overrides.map(([d,o])=>'<div class="row"><div class="grow">'+esc(d)+' · '+esc(o.windows??'theo tuần')+' · '+
      esc(o.cap??'kế thừa')+' phút</div>'+button('Sửa','override',d)+'</div>').join('')||empty('Đang dùng giờ rảnh hàng tuần.'))+
    '</section><section class="panel"><div class="head"><h2>Sự kiện cố định</h2>'+button('Thêm sự kiện','evNew')+'</div>'+
    (events.map(([id,ev])=>'<div class="muted">'+esc(id)+' · '+esc(ev.start.slice(0,10))+(ev.repeat==='weekly'?' · hàng tuần':'')+
      (ev.until?' · đến '+esc(ev.until):'')+'</div>'+eventRow([id,ev])).join('')||empty('Chưa thêm sự kiện.'))+'</section>';
}

function horizonForm(){
  const c=state.settings;
  modal('Kỳ lập lịch và giới hạn theo thứ',field('Ngày cuối (trống = 90 ngày)',input('end',c.horizon_end||'','date'))+
    '<p class="muted">Giới hạn phút tự học theo thứ. Để trống để dùng trần chung.</p>'+
    dayNames.map((d,i)=>field(d,input('cap'+i,c.weekday_caps?.[i]??'','number','min="0" max="720"'))).join(''),f=>
    change('/plans/replan','POST',{settings:{horizon_end:f.get('end')||null,
      weekday_caps:dayNames.map((_,i)=>f.get('cap'+i)===''?null:Number(f.get('cap'+i)))}}));
}

function overrideForm(id){
  const c=state.settings,old=c.overrides?.[id]||{};
  modal('Ngoại lệ theo ngày',field('Từ ngày',input('from',id||selected,'date','required'))+
    field('Đến hết ngày',input('to',id||selected,'date','required'))+
    field('Khung giờ mới (trống = kế thừa)',input('windows',old.windows||''))+
    field('Giới hạn phút (0 = nghỉ)',input('cap',old.cap??'','number','min="0" max="720"')),f=>{
      const a=f.get('from'),b=f.get('to'),r={};
      if(a>b)throw Error('Ngày cuối phải từ ngày đầu trở đi.');
      if(f.get('windows'))r.windows=f.get('windows');
      if(f.get('cap')!=='')r.cap=Number(f.get('cap'));
      const overrides={...c.overrides};
      for(let d=a;d<=b;d=offset(d,1)){
        if(Object.keys(r).length)overrides[d]={...r};else delete overrides[d];
        if(d===b)break;
      }
      return change('/plans/replan','POST',{settings:{overrides}});
    },'Áp dụng');
}

function matrix(head,rows){
  return '<div class="tablewrap"><table><thead><tr>'+head.map(x=>'<th>'+esc(x)+'</th>').join('')+
    '</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}

function workload(){
  const a=state.analysis;
  const opt=a.optimization;
  let diagnostics='';
  if(opt && opt.bottlenecks){
    const base=opt.baseline;
    diagnostics='<section class="panel"><h2>So sánh cách xếp lịch</h2><p>'+
      esc(opt.strategy)+' · '+opt.evaluated+' lịch hợp lệ · '+opt.seconds+' giây'+(opt.timeout?' · hết ngân sách tìm kiếm':'')+'</p>'+
      (base?matrix(['Phút','Lịch gốc','Lịch chọn'],[
        ['Xếp đúng hạn',a.remaining-base.unscheduled,a.scheduled],['Thiếu hạn cứng',base.hard_minutes,opt.selected.hard_minutes],
        ['Thiếu có trọng số',base.weighted,opt.selected.weighted],['Bị chặn bởi tiên quyết',base.blocked,opt.blocked_unique]]):
        '<p>Lịch gốc vi phạm ràng buộc.</p>')+
      '<p>Thiếu trực tiếp '+mins(opt.direct_minutes)+' · bị chặn '+mins(opt.blocked_unique)+'</p>';
    if(Object.keys(opt.impacts).length)diagnostics+=matrix(['Tiên quyết','Việc bị ảnh hưởng','Phút bị ảnh hưởng'],
      Object.entries(opt.impacts).map(([k,v])=>[state.tasks[k].name,v.tasks.map(i=>state.tasks[i].name).join(', '),v.minutes]));
    if(opt.bottlenecks.length)diagnostics+=matrix(['Từ','Đến','Cần','Tối đa','Ít nhất còn thiếu'],
      opt.bottlenecks.map(r=>[r.start,r.end,r.required,r.upper_bound,r.minimum_shortfall]));
    if(opt.idle.length)diagnostics+='<details><summary>Ngày còn giờ trống</summary>'+matrix(['Ngày','Trần còn lại','Phút chưa dùng','Việc còn lại cuối ngày'],
      opt.idle.map(r=>[r.day,r.nominal,r.unused,Object.entries(r.reasons).map(([why,n])=>why+' ('+n+')').join(', ')||'Đã xếp hết']))+'</details>';
    diagnostics+='</section>';
  }
  const groups=(rows,only)=>Object.entries(rows).sort(([x],[y])=>x.localeCompare(y))
    .filter(([,r])=>only?r.required>r.capacity:r.required||r.scheduled||r.capacity)
    .map(([key,r])=>[key,r.required,r.capacity,r.scheduled]);
  const labels=['Kỳ','Phút đến hạn','Có thể học','Đã xếp'];
  return '<section class="panel"><h2>Khả năng đáp ứng đến '+esc(a.horizon_end)+'</h2><div class="metrics">'+
    metric('Còn phải học',mins(a.remaining),'')+metric('Quỹ giờ ước tính',mins(a.capacity),'')+
    metric('Đã xếp',mins(a.scheduled),'')+metric('Chưa xếp',mins(a.unscheduled),'')+'</div>'+
    (a.risks.length?matrix(['Việc','Còn thiếu','Nguyên nhân','Gợi ý'],a.risks.map(r=>[
      (state.recent_risks?.includes(r.task)?'↑ ':'')+state.tasks[r.task].name,mins(r.minutes),r.causes.join(', '),r.recommendation])):
      empty('Mọi phút còn lại đã có chỗ trong lịch.'))+'</section><section class="panel"><h2>Trước từng hạn</h2>'+
    matrix(['Hạn','Nhu cầu lũy kế','Quỹ phút lũy kế'],a.deadlines.map(d=>[d.due,d.required,d.capacity]))+
    '</section>'+diagnostics+'<section class="panel"><h2>Khối lượng theo tuần</h2>'+matrix(labels,groups(a.weeks,false))+
    '<h3>Tuần dồn hạn</h3>'+matrix(labels,groups(a.weeks,true))+'<h3>Ngày dồn hạn</h3>'+matrix(labels,groups(a.dates,true))+
    '<p class="muted">Nhu cầu tính theo ngày đến hạn. Công việc có thể được xếp trước đó. ↑ đánh dấu rủi ro mới hoặc tăng khi xếp lại.</p></section>';
}

async function downloadJSON(url,name){
  const data=await request(url);
  const link=document.createElement('a');
  const blob=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));
  link.href=blob;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(blob),1000);
}

function exchangePage(){
  return '<section class="panel"><div class="head"><h2>Nhập và sao lưu</h2></div><div class="toolbar">'+
    button('Nhập từ JSON','import')+button('Xuất kế hoạch','export')+button('Tải bản sao đầy đủ','backup')+'</div></section>'+
    '<section class="panel"><h2>Bản sao trước thay đổi · mới nhất trước</h2>'+
    ((state.backups||[]).map(k=>'<div class="row"><a download="study-backup-'+esc(k)+'.json" href="/planning/backups/'+encodeURIComponent(k)+'">'+esc(k)+'</a></div>').join('')||empty('Chưa có lần thay thế.'))+'</section>';
}

function importForm(){
  const fields=field('Tệp JSON UTF-8','<input name="file" type="file" accept=".json" required>')+
    field('Chế độ','<select name="mode">'+option('append','Thêm mới')+option('replace','Thay trong phạm vi')+
      option('restore','Khôi phục toàn bộ')+'</select>')+
    field('Môn được thay (mỗi dòng một môn)','<textarea name="courses"></textarea>')+
    field('ID sự kiện được thay (mỗi dòng một ID)','<textarea name="event_ids"></textarea>')+
    field('Cho phép cập nhật cấu hình','<input type="checkbox" name="settings">')+
    field('Cho phép khôi phục toàn bộ dữ liệu','<input type="checkbox" name="full_restore">');
  modal('Nhập dữ liệu',fields,async f=>{
    const lines=k=>f.get(k).split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
    const body={document:JSON.parse(await f.get('file').text()),mode:f.get('mode'),scope:{
      courses:lines('courses'),event_ids:lines('event_ids'),settings:f.has('settings'),full_restore:f.has('full_restore')}};
    const result=await request('/planning/preview','POST',body);
    const taskName=k=>body.document.tasks?.find(t=>t.id===k)?.name||state.tasks[k]?.name||k;
    const details=matrix(['Thao tác','Bản ghi'],[['Thêm việc',result.added.map(taskName).join(', ')],
      ['Sửa việc',result.updated.map(taskName).join(', ')],['Xóa việc',result.deleted.map(taskName).join(', ')],
      ['Thêm / sửa / xóa sự kiện',[result.events_added,result.events_updated,result.events_deleted].map(x=>x.join(', ')||'—').join(' / ')],
      ['Trùng',result.duplicates.join(', ')],['Đổi cấu hình',result.settings_changed?'Có':'Không'],['Tổng ước lượng sau nhập',mins(result.workload)]])+
      [...result.errors,...result.warnings].map(m=>'<p>'+esc(m)+'</p>').join('');
    modal('Xem trước · '+body.mode,details,result.errors.length?null:async()=>{
      const applied=await request('/planning/import','POST',{...body,token:result.token});
      await refresh();
      if(applied.backup_id)modal('Đã lưu bản sao trước thay đổi','<p><a download="study-backup.json" href="/planning/backups/'+encodeURIComponent(applied.backup_id)+'">Tải bản sao để khôi phục</a></p>',null);
      else $('modal').close();
    },body.mode==='restore'?'Xác nhận khôi phục toàn bộ':'Xác nhận nhập');
  },'Xem trước');
}

function academicAction(action,id){
  if(action==='evNew'||action==='evEdit')return eventForm(id);
  if(action==='evRemove')return modal('Xóa sự kiện',esc(state.events[id].name),()=>change('/events/'+encodeURIComponent(id),'DELETE'),'Xóa');
  if(action==='horizon')return horizonForm();
  if(action==='override')return overrideForm(id);
  if(action==='import')return importForm();
  if(action==='export'||action==='backup')return perform(()=>downloadJSON('/planning/export'+(action==='backup'?'?backup=true':''),'study-'+action+'.json'),'Đã xuất JSON.');
}

