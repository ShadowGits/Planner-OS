/* A local 24-hour field: select common values or type an exact time. */
(() => {
  'use strict';
  const canonical=document.getElementById('new-time'),host=document.getElementById('task-time-control');
  if(!canonical||!host)return;
  const pad=n=>String(n).padStart(2,'0');
  let opened=null,lastValue=canonical.value;
  const fields={};
  const help=document.createElement('p');help.className='time-entry-help';help.id='task-time-help';help.setAttribute('aria-live','polite');
  const row=document.createElement('div');row.className='time-entry-fields';host.append(row);
  function number(field){const s=field.input.value;return /^\d{1,2}$/.test(s)&&Number(s)<=field.max?Number(s):null;}
  function close(){
    if(!opened)return;
    opened.popup.hidden=true;opened.input.setAttribute('aria-expanded','false');opened.input.removeAttribute('aria-activedescendant');opened=null;
  }
  function position(field){
    const rect=field.box.getBoundingClientRect(),view=window.visualViewport;
    const top=view?.offsetTop||0,bottom=top+(view?.height||window.innerHeight),below=bottom-rect.bottom-8,above=rect.top-top-8;
    const up=below<180&&above>below;
    const height=Math.max(44,Math.min(240,up?above:below));
    Object.assign(field.popup.style,{left:`${rect.left}px`,width:`${rect.width}px`,maxHeight:`${height}px`,top:up?'auto':`${rect.bottom+4}px`,bottom:up?`${window.innerHeight-rect.top+4}px`:'auto'});
  }
  function highlight(field,index){
    field.active=(index+field.values.length)%field.values.length;
    [...field.popup.children].forEach((node,i)=>node.setAttribute('aria-selected',String(i===field.active)));
    const option=field.popup.children[field.active];field.input.setAttribute('aria-activedescendant',option.id);
    option.scrollIntoView?.({block:'nearest'});
  }
  function choose(field,value){
    field.input.value=pad(value);
    if(field.kind==='hour'&&!fields.minute.input.value)fields.minute.input.value='00';
    write();close();
  }
  function open(field){
    close();opened=field;
    const exact=number(field);
    field.values=field.kind==='hour'?Array.from({length:24},(_,i)=>i):[...new Set([...Array.from({length:12},(_,i)=>i*5),...(exact===null?[]:[exact])])].sort((a,b)=>a-b);
    field.popup.replaceChildren(...field.values.map(value=>{
      const button=document.createElement('button');button.type='button';button.tabIndex=-1;button.setAttribute('role','option');button.id=`task-time-${field.kind}-${value}`;button.textContent=pad(value);
      button.addEventListener('pointerdown',event=>event.preventDefault());
      button.addEventListener('click',()=>{choose(field,value);field.input.focus();});
      return button;
    }));
    field.popup.hidden=false;field.input.setAttribute('aria-expanded','true');position(field);
    highlight(field,Math.max(0,field.values.indexOf(exact)));
  }
  function write(){
    const h=number(fields.hour),m=number(fields.minute);
    canonical.value=h!==null&&m!==null?`${pad(h)}:${pad(m)}`:'';
    lastValue=canonical.value;
    for(const field of Object.values(fields))field.input.removeAttribute('aria-invalid');
    help.classList.remove('time-entry-error');
    help.textContent=!fields.hour.input.value&&!fields.minute.input.value?'No start time · stays in Inbox':'24-hour time · type any minute or choose a 5-minute step';
    clear.disabled=!fields.hour.input.value&&!fields.minute.input.value;
    canonical.dispatchEvent(new Event('input',{bubbles:true}));
  }
  for(const [kind,max] of [['hour',23],['minute',59]]){
    const box=document.createElement('div');box.className='time-entry-segment';
    const label=document.createElement('label');label.htmlFor=`task-time-${kind}`;label.textContent=kind==='hour'?'Hour':'Minute';
    const line=document.createElement('div');line.className='time-entry-input';
    const input=document.createElement('input');input.id=label.htmlFor;input.type='text';input.inputMode='numeric';input.maxLength=2;input.placeholder='—';input.autocomplete='off';
    input.setAttribute('role','combobox');input.setAttribute('aria-expanded','false');input.setAttribute('aria-autocomplete','none');input.setAttribute('aria-describedby',help.id);
    const arrow=document.createElement('button');arrow.type='button';arrow.tabIndex=-1;arrow.textContent='⌄';arrow.setAttribute('aria-label',kind==='hour'?'Choose hour':'Choose minute');
    const popup=document.createElement('div');popup.className='time-entry-options';popup.id=`task-time-${kind}-options`;popup.hidden=true;popup.setAttribute('role','listbox');popup.setAttribute('aria-label',kind==='hour'?'Hours, 00 to 23':'Minutes, five-minute choices');document.body.append(popup);
    input.setAttribute('aria-controls',popup.id);
    const field={kind,max,box,input,popup,values:[],active:0};fields[kind]=field;
    arrow.addEventListener('click',()=>{const wasOpen=opened===field;input.focus();if(wasOpen)close();else open(field);});
    input.addEventListener('focus',()=>input.select());
    input.addEventListener('click',()=>{if(opened!==field)open(field);});
    input.addEventListener('input',()=>{
      close();
      if(kind==='hour'&&number(field)!==null&&!fields.minute.input.value)fields.minute.input.value='00';
      write();
    });
    input.addEventListener('blur',()=>{const n=number(field);if(n!==null)input.value=pad(n);if(opened===field)close();});
    input.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&opened){event.preventDefault();event.stopPropagation();close();return;}
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){
        event.preventDefault();if(opened!==field)open(field);else highlight(field,field.active+(event.key==='ArrowDown'?1:-1));
      }else if(event.key==='Enter'&&opened===field){event.preventDefault();choose(field,field.values[field.active]);}
      else if(event.key==='Tab')close();
    });
    line.append(input,arrow);box.append(label,line);row.append(box);
  }
  const clear=document.createElement('button');clear.type='button';clear.className='time-entry-clear';clear.textContent='Clear time';
  clear.addEventListener('click',()=>{close();fields.hour.input.value='';fields.minute.input.value='';write();fields.hour.input.focus();});
  host.append(clear,help);
  function sync(){
    close();const [hour='',minute='']=canonical.value.split(':');fields.hour.input.value=hour;fields.minute.input.value=minute;lastValue=canonical.value;
    help.classList.remove('time-entry-error');help.textContent=canonical.value?'24-hour time · type any minute or choose a 5-minute step':'No start time · stays in Inbox';
    clear.disabled=!canonical.value;Object.values(fields).forEach(f=>f.input.removeAttribute('aria-invalid'));
  }
  function validate(){
    // Preserve callers that assign the canonical field directly (cached edits and restore paths).
    if(canonical.value!==lastValue)sync();
    if(!fields.hour.input.value&&!fields.minute.input.value){write();return true;}
    const invalid=Object.values(fields).find(field=>number(field)===null);
    if(invalid){close();invalid.input.setAttribute('aria-invalid','true');help.classList.add('time-entry-error');help.textContent='Choose an hour 00–23 and minute 00–59, or clear the time.';invalid.input.focus();return false;}
    write();sync();return true;
  }
  document.addEventListener('pointerdown',event=>{if(opened&&!opened.box.contains(event.target)&&!opened.popup.contains(event.target))close();});
  window.addEventListener('resize',close);document.addEventListener('scroll',event=>{if(opened&&!opened.popup.contains(event.target))close();},true);
  window.visualViewport?.addEventListener('resize',close);
  window.PlannerTimeEntry={sync,validate,close,focus(){fields.hour.input.focus();},set(value){canonical.value=value||'';sync();}};
  sync();
})();
