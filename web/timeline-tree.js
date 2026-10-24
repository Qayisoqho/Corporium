/* The tree describes track ownership; time containment is enforced on the server. */
const TimelineTree={
 palette:['#78bce8','#e4ad73','#8ac6a1','#b5a0de','#d88f9f','#cabd75','#7ac7c4','#aab8d9'],
 validColor(value){return typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);},
 fallbackColor(id){let hash=2166136261;for(const c of String(id))hash=Math.imul(hash^c.codePointAt(0),16777619)>>>0;return this.palette[hash%this.palette.length];},
 nextColor(tracks){const saved=tracks.filter(t=>!t.parent_id&&this.validColor(t.color)).map(t=>t.color.toLowerCase());return this.palette.find(c=>!saved.includes(c))||this.palette[saved.length%this.palette.length];},
 // Resolve each inherited colour once; never use a row index or an unbounded cache.
 colors(tracks){
  const byId=new Map(tracks.map(t=>[t.id,t])),colors=new Map();
  for(const track of tracks){
   let current=track;const path=[],seen=new Set();
   while(current&&!colors.has(current.id)&&!seen.has(current.id)){
    if(this.validColor(current.color)){colors.set(current.id,current.color.toLowerCase());break;}
    path.push(current);seen.add(current.id);
    if(!current.parent_id||!byId.has(current.parent_id))break;
    current=byId.get(current.parent_id);
   }
   const color=colors.get(current?.id)||this.fallbackColor(current?.id||track.id);
   for(const t of path)colors.set(t.id,color);
  }
  return colors;
 },
 root(tracks,id){const map=new Map(tracks.map(t=>[t.id,t])),seen=new Set();let t=map.get(id);while(t?.parent_id&&!seen.has(t.id)){seen.add(t.id);t=map.get(t.parent_id);}return t;},
 rows(tracks,speakers,collapsed=new Set()){
  const groups=new Map(),children=new Map(),result=[];
  for(const t of tracks){const map=t.parent_id?children:groups,key=t.parent_id||t.speaker_id||'';if(!map.has(key))map.set(key,[]);map.get(key).push(t);}
  function visit(t,depth){result.push({track:t,depth,children:children.get(t.id)?.length||0});if(!collapsed.has(t.id))for(const child of children.get(t.id)||[])visit(child,depth+1);}
  for(const [id,roots] of groups){const speaker=speakers.find(s=>s.id===id);result.push({group:true,id:'speaker:'+id,name:speaker?speaker.name:'未指定说话人',count:roots.length});if(!collapsed.has('speaker:'+id))for(const t of roots)visit(t,0);}
  return result;
 }
};
if(typeof module!=='undefined')module.exports=TimelineTree;
