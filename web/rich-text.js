/* Shared survey / lexical notes editor: whitelisted text runs and local editing history. */
(()=>{
const editors=new WeakMap();
function remapRuns(runs,replacements){return runs.map(run=>{if(!Object.hasOwn(replacements,run.type_id))return run;const next={...run};if(replacements[run.type_id])next.type_id=replacements[run.type_id];else delete next.type_id;return next;});}
function updateTypes(root,types,replacements={}){for(const box of root.querySelectorAll('.survey-rich-box'))editors.get(box)?.update(types,replacements);}
function markup(runs=[],types=[],scripts=true){return runs.map(r=>{const t=types.find(x=>x.id===r.type_id);return `<span${r.type_id?` data-writing-type="${esc(r.type_id)}"`:''}${t?' '+writingDisplayAttrs(t):''}>${r.bold?'<b>':''}${r.italic?'<i>':''}${r.highlight?'<mark>':''}${scripts?rich(r.text):esc(r.text)}${r.highlight?'</mark>':''}${r.italic?'</i>':''}${r.bold?'</b>':''}</span>`;}).join('');}
// Rich text is serialized as whitelisted text runs; pasted HTML is never stored.
function richBox(id,title,runs=[],types=[]){return (globalThis.CorporiumI18n?.f("9e151335bc8425",()=>[title,id,title,types.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join(''),id,title,markup(runs,types,false)])??`<label>${title}</label><div class="survey-rich-box"><div class="survey-rich-tools" data-for="${id}"><button type="button" data-format="bold" title="粗体"><b>B</b></button><button type="button" data-format="italic" title="斜体"><i>I</i></button><button type="button" data-format="highlight" title="高亮">高亮</button><button type="button" data-format="plain" title="清除所选格式">清除格式</button><button type="button" data-list title="插入列表项目">• 列表</button><button type="button" data-rich-undo title="撤销文字编辑">↶</button><button type="button" data-rich-redo title="重做文字编辑">↷</button><select data-writing aria-label="${title}书写类型"><option value="">正文文字</option>${types.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')}</select><button type="button" data-apply-writing>应用书写类型</button></div><div class="survey-rich survey-rich-input" id="${id}" role="textbox" aria-label="${title}" aria-multiline="true" contenteditable="true">${markup(runs,types,false)}</div></div>`);}
function readRich(el){const out=[];function walk(node,attrs={}){if(node.nodeType===3){if(node.textContent)out.push({...attrs,text:node.textContent});return;}if(node.nodeType!==1)return;const next={...attrs};if(['B','STRONG'].includes(node.tagName))next.bold=true;if(['I','EM'].includes(node.tagName))next.italic=true;if(node.tagName==='MARK')next.highlight=true;if(node.dataset.writingType)next.type_id=node.dataset.writingType;if(node.tagName==='BR'){out.push({text:'\n'});return;}if(['DIV','P','LI'].includes(node.tagName)&&out.length&&!out.at(-1).text.endsWith('\n'))out.push({text:'\n'});for(const child of node.childNodes)walk(child,next);}for(const child of el.childNodes)walk(child);return out;}
function bindRich(root,types=[]){for(const box of root.querySelectorAll('.survey-rich-box')){const ed=box.querySelector('[contenteditable]');let range=null,writingTypes=types;
 ed.addEventListener('keyup',remember);ed.addEventListener('mouseup',remember);ed.addEventListener('input',remember);
 function remember(){const s=getSelection();if(s.rangeCount&&ed.contains(s.anchorNode)&&ed.contains(s.focusNode))range=s.getRangeAt(0).cloneRange();}
 box.querySelector('.survey-rich-tools').addEventListener('mousedown',e=>{if(e.target.closest('button'))e.preventDefault();});
 function textSize(fragment){const temp=document.createElement('div');temp.append(fragment);return readRich(temp).reduce((n,r)=>n+r.text.length,0);}
 function selectOffsets(start,end){const nodes=[],walker=document.createTreeWalker(ed,NodeFilter.SHOW_TEXT);let node;while(node=walker.nextNode())nodes.push(node);if(!nodes.length){range=document.createRange();range.selectNodeContents(ed);range.collapse(false);return;}const r=document.createRange();let offset=0,started=false;for(const n of nodes){const next=offset+n.length;if(!started&&start<=next){r.setStart(n,Math.max(0,start-offset));started=true;}if(end<=next){r.setEnd(n,Math.max(0,end-offset));break;}offset=next;}range=r;const selection=getSelection();selection.removeAllRanges();selection.addRange(r);ed.focus();}
 function change(kind,type){if(!range||!ed.contains(range.commonAncestorContainer)){ed.focus();return;}const prefix=document.createRange();prefix.selectNodeContents(ed);prefix.setEnd(range.startContainer,range.startOffset);const start=textSize(prefix.cloneContents());prefix.setEnd(range.endContainer,range.endOffset);const end=textSize(prefix.cloneContents());if(start===end&&kind!=='list')return;const runs=readRich(ed),out=[];let pos=0,inserted=false;const selected=runs.filter(r=>{const hit=pos<end&&pos+r.text.length>start;pos+=r.text.length;return hit;});const toggle=['bold','italic','highlight'].includes(kind)&&!selected.every(r=>r[kind]);pos=0;
 for(const run of runs){const next=pos+run.text.length;if(pos<start&&next>start)out.push({...run,text:run.text.slice(0,start-pos)});else if(next<=start){out.push(run);pos=next;continue;}
 if(kind==='list'&&!inserted){out.push({text:'\n• '});inserted=true;}
 const a=Math.max(pos,start),b=Math.min(next,end);if(a<b&&kind!=='list'){const r={...run,text:run.text.slice(a-pos,b-pos)};if(kind==='plain'){for(const k of ['bold','italic','highlight','type_id'])delete r[k];}else if(kind==='writing'){if(type)r.type_id=type;else delete r.type_id;}else if(toggle)r[kind]=true;else delete r[kind];out.push(r);}
 if(next>end)out.push({...run,text:run.text.slice(Math.max(0,end-pos))});pos=next;}
 if(kind==='list'&&!inserted)out.push({text:'\n• '});ed.innerHTML=markup(out,writingTypes,false);selectOffsets(kind==='list'?start+3:start,kind==='list'?start+3:end);ed.dispatchEvent(new Event('input',{bubbles:true}));}
 let history=[JSON.stringify(readRich(ed))],historyIndex=0,restoring=false;
 ed.addEventListener('input',e=>{if(restoring||e.isComposing)return;const snapshot=JSON.stringify(readRich(ed));if(snapshot===history[historyIndex])return;history=history.slice(0,historyIndex+1);history.push(snapshot);if(history.length>50)history.shift();historyIndex=history.length-1;});
 function historyStep(direction){const next=historyIndex+direction;if(next<0||next>=history.length)return;historyIndex=next;ed.innerHTML=markup(JSON.parse(history[next]),writingTypes,false);const size=readRich(ed).reduce((n,r)=>n+r.text.length,0);selectOffsets(size,size);restoring=true;ed.dispatchEvent(new Event('input',{bubbles:true}));restoring=false;}
 editors.set(box,{update(nextTypes,replacements){
  writingTypes=nextTypes;
  const select=box.querySelector('[data-writing]'),selected=Object.hasOwn(replacements,select.value)?replacements[select.value]:select.value;
  const plain=select.options[0].cloneNode(true);select.replaceChildren(plain,...nextTypes.map(t=>new Option(t.name,t.id)));select.value=nextTypes.some(t=>t.id===selected)?selected:'';
  const definitions=new Map(nextTypes.map(t=>[t.id,t])),sample=document.createElement('div');
  // Change attributes only: keep text nodes, caret, selection, scroll and undo history.
  for(const span of ed.querySelectorAll('[data-writing-type]')){
   const id=span.dataset.writingType,next=Object.hasOwn(replacements,id)?replacements[id]:id;
   if(next)span.dataset.writingType=next;else span.removeAttribute('data-writing-type');
   const type=definitions.get(next);
   if(type){sample.innerHTML='<span '+writingDisplayAttrs(type)+'></span>';span.style.cssText=sample.firstElementChild.style.cssText;span.dataset.lineWriting=next;}
   else{span.removeAttribute('style');span.removeAttribute('data-line-writing');}
  }
  history=history.map(value=>JSON.stringify(remapRuns(JSON.parse(value),replacements)));
 }});
 box.querySelector('[data-rich-undo]').onclick=()=>historyStep(-1);box.querySelector('[data-rich-redo]').onclick=()=>historyStep(1);
 ed.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();historyStep(e.shiftKey?1:-1);}});

 box.querySelectorAll('[data-format]').forEach(b=>b.onclick=()=>change(b.dataset.format));box.querySelector('[data-list]').onclick=()=>{if(!range){range=document.createRange();range.selectNodeContents(ed);range.collapse(false);}change('list');};box.querySelector('[data-apply-writing]').onclick=()=>change('writing',box.querySelector('[data-writing]').value);
 ed.addEventListener('paste',e=>{e.preventDefault();const text=e.clipboardData.getData('text/plain'),s=getSelection();if(!s.rangeCount||!ed.contains(s.anchorNode))return;const r=s.getRangeAt(0);r.deleteContents();const n=document.createTextNode(text);r.insertNode(n);r.setStartAfter(n);r.collapse(true);s.removeAllRanges();s.addRange(r);ed.dispatchEvent(new Event('input',{bubbles:true}));});ed.addEventListener('drop',e=>e.preventDefault());
 }}
window.CorporiumRichText={markup,box:richBox,read:readRich,bind:bindRich,updateTypes,remapRuns};
})();
