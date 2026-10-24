/* Paired colors add no characters and preserve the existing rich/script markup. */
(()=>{
 const allowed=new Set(['base','affix','clitic','infix','circumfix','connector','multipart','reduplication']);
 const labels={affix:'已关联词典 · 词缀',clitic:'已关联词典 · 附着成分',infix:'已关联词典 · 中缀',circumfix:'已关联词典 · 环缀',connector:'已关联词典 · 连接成分',multipart:'已关联词典 · 多部分语素',reduplication:'重叠部分 · 已关联基底'};
 const components=w=>[...(w.morph_colors||[]),...(w.redup_colors||[])];
 const entities={amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"};
 function decode(s){if(s[0]!=='&')return s;const name=s.slice(1,-1);if(name in entities)return entities[name];if(/^#x[0-9a-f]+$/i.test(name))return String.fromCodePoint(parseInt(name.slice(2),16));if(/^#\d+$/.test(name))return String.fromCodePoint(Number(name.slice(1)));return s;}
 function htmlTokens(html){return [...html.matchAll(/<[^>]*>|&(?:#\d+|#x[\da-f]+|[a-z]+);|[^<&]+|[<&]/giu)].map(m=>m[0]);}
 function glyphs(raw,gloss){
  const chars=Array.from(raw),pattern=gloss?/#(?:sub|sup|super)\[([^\[\]]*)\]/g:/#sub\[([^\[\]]*)\]/g;
  const glyph=[];let at=0,cp=0;
  for(const m of raw.matchAll(pattern)){
   const start=cp+Array.from(raw.slice(at,m.index)).length,end=start+Array.from(m[0]).length;
   for(;cp<start;cp++)glyph.push({text:chars[cp],start:cp,end:cp+1});
   for(const text of Array.from(m[1]))glyph.push({text,start,end});cp=end;at=m.index+m[0].length;
  }
  for(;cp<chars.length;cp++)glyph.push({text:chars[cp],start:cp,end:cp+1});
  const out=[];
  for(let i=0;i<glyph.length;i++){
   if(glyph[i].text==='\\'&&glyph[i+1]&&/[~?\[\]#]/.test(glyph[i+1].text)){out.push({...glyph[i+1],start:glyph[i].start});i++;}
   else out.push(glyph[i]);
  }
  return out;
 }
 function decorate(raw,html,components,field){
  const source=glyphs(String(raw||''),field==='gloss'),tokens=htmlTokens(html),visible=tokens.filter(t=>t[0]!=='<').map(decode).join('');
  if(source.map(g=>g.text).join('')!==visible)return html;
  const ranges=components.flatMap(m=>(m[field]||[]).filter(r=>Array.isArray(r)&&r.length===2&&Number.isInteger(r[0])&&Number.isInteger(r[1])&&r[0]<r[1]).map(([start,end])=>({start,end,tone:allowed.has(m.tone)?m.tone:'base'}))).sort((a,b)=>a.start-b.start||a.end-b.end);
  const ordinary=ranges.filter(r=>r.tone!=='reduplication'),overlays=[];
  for(const r of ranges.filter(r=>r.tone==='reduplication')){const last=overlays.at(-1);if(last&&r.start<=last.end)last.end=Math.max(last.end,r.end);else overlays.push({...r});}
  let ri=0,oi=0;const colors=source.map(g=>{
   while(ri<ordinary.length&&ordinary[ri].end<=g.start)ri++;while(oi<overlays.length&&overlays[oi].end<=g.start)oi++;
   const range=ordinary[ri],overlay=overlays[oi];return overlay&&overlay.start<=g.start&&g.end<=overlay.end?'reduplication':range&&range.start<=g.start&&g.end<=range.end?range.tone:'base';
  });
  let cursor=0,out='';
  for(const token of tokens){
   if(token[0]==='<'){out+=token;continue;}
   const pieces=token[0]==='&'&&token.endsWith(';')?[token]:Array.from(token);let tone=null;
   for(const piece of pieces){const next=colors[cursor++]||'base';if(next!==tone){if(tone!==null)out+='</span>';out+='<span class="morph-tone morph-tone-'+next+'"'+(field==='form'&&labels[next]?' title="'+labels[next]+'"':'')+'>';tone=next;}out+=piece;}
   if(tone!==null)out+='</span>';
  }
  return out;
 }
 function pair(w,lid){const form=rich(w.form),gloss=richGloss(w.gloss,lid),colors=components(w);if(!colors.length)return {form:'<span class="morph-unclassified">'+form+'</span>',gloss:'<span class="morph-unclassified">'+gloss+'</span>'};return {form:decorate(w.form,form,colors,'form'),gloss:decorate(w.gloss,gloss,colors,'gloss')};}
 // Only matching morphological boundaries become shared columns; dots remain tags.
 function aligned(w,lid){
  function parts(text){
   const base=glossEditParts(text,false);
   if(w.infix_ambiguous||!w.morphemes?.some(m=>m.kind==='infix'))return base;
   return base.flatMap((value,index)=>{
    if(index%2)return [value];
    const out=[];let start=0;
    for(const match of value.matchAll(/<[^<>]*>/g)){out.push(value.slice(start,match.index),'<',match[0].slice(1,-1),'>');start=match.index+match[0].length;}
    out.push(value.slice(start));return out;
   });
  }
  const forms=parts(w.form),glosses=parts(w.gloss);
  if(forms.length<3||forms.length>129||forms.length!==glosses.length||forms.some((v,i)=>i%2&&v!==glosses[i]))return pair(w,lid);
  function line(parts,field){
   let offset=0;
   return parts.map((value,index)=>{
    const length=Array.from(value).length,start=offset;offset+=length;
    const ranges=components(w).map(m=>({...m,[field]:(m[field]||[]).map(([a,z])=>[Math.max(0,a-start),Math.min(length,z-start)]).filter(([a,z])=>z>a)}));
    const html=field==='form'?rich(value):index%2?esc(value):richGloss(value,lid,index>0&&parts[index-1]==='<');
    return '<span class="interlinear-part">'+(ranges.length?decorate(value,html,ranges,field):'<span class="morph-unclassified">'+html+'</span>')+'</span>';
   }).join('');
  }
  return {form:line(forms,'form'),gloss:line(glosses,'gloss'),columns:forms.length};
 }
 // Inspector units use the sentence's actual color role, never the tag spelling
 // or the currently previewed dictionary candidate. Group members inherit their group.
 function unitOverlay(u,overlay,field,value){
  if(!overlay[field]?.length)return [];
  const length=Array.from(value).length,fragments=u[field==='form'?'fragments':'gloss_fragments']||[],sources=overlay[field==='form'?'fragments':'gloss_fragments']||[];
  if(overlay.key===u.key||overlay.key==='@word'||fragments.length&&fragments.every(f=>sources.some(s=>s.start<=f.start&&f.end<=s.end)))return [[0,length]];
  // A custom group gloss has no positional correspondence to its member labels.
  // Only project fragments whose concatenation is the actually displayed value.
  const joiner=['','…'].find(j=>fragments.map(f=>f.text).join(j)===value);if(joiner===undefined)return [];
  let at=0;const out=[];
  for(const f of fragments){for(const s of sources){const a=Math.max(f.start,s.start),z=Math.min(f.end,s.end);if(a<z)out.push([at+a-f.start,at+z-f.start]);}at+=Array.from(f.text).length+Array.from(joiner).length;}
  return out;
 }
 function unit(w,u,lid){
  if(!u||u===w)return pair(w,lid);
  if(!w.morph_colors?.length&&!w.redup_colors?.length)return pair({...u,gloss:u.display_gloss??u.gloss},lid);
  const owner=w.morphemes?.find(m=>m.key===u.key||m.members?.includes(u.key)),color=w.morph_colors?.find(c=>c.key===(owner?.key||u.key)),tone=color?.tone||'base';
  const form=String(u.form||''),gloss=String(u.display_gloss??u.gloss??''),ranges=[{tone,form:[[0,Array.from(form).length]],gloss:[[0,Array.from(gloss).length]]}];
  for(const overlay of w.redup_colors||[])ranges.push({tone:'reduplication',form:unitOverlay(u,overlay,'form',form),gloss:unitOverlay(u,overlay,'gloss',gloss)});
  return {form:decorate(form,rich(form),ranges,'form'),gloss:decorate(gloss,richGloss(gloss,lid),ranges,'gloss')};
 }
 window.CorporiumMorphColors={decorate,pair,aligned,unit,components};
})();
