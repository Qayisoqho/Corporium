/* Display numbering and stable multi-slot ordering; never rewrite stored titles or IDs. */
const CorporiumOrder={
 numbers(nodes){
  const children=new Map(),result=new Map();
  for(const node of nodes){const key=node.parent_id||null;if(!children.has(key))children.set(key,[]);children.get(key).push(node);}
  function visit(parent,prefix){(children.get(parent)||[]).forEach((node,i)=>{if(result.has(node.id))return;const number=prefix?prefix+'.'+(i+1):String(i+1);result.set(node.id,number);visit(node.id,number);});}
  visit(null,'');return result;
 },
 move(ids,selected,target,after=false){
  const moving=new Set(selected);if(moving.has(target)||!ids.includes(target))return [...ids];
  const kept=ids.filter(id=>!moving.has(id)),batch=ids.filter(id=>moving.has(id));
  kept.splice(kept.indexOf(target)+(after?1:0),0,...batch);return kept;
 }
};
if(typeof module!=='undefined')module.exports=CorporiumOrder;
