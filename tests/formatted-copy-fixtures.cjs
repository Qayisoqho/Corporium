(function(root, factory) {
  const data = factory();
  if (typeof module === 'object' && module.exports) module.exports = data;
  else root.copyFixtures = data;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  const metadata = {ipa_font:'IPAPANNEW',annotation_font:'Junicode',gloss_font:'Junicode',translation_font:'Microsoft YaHei',glossary:{SG:'单数',PST:'过去时',Q:'疑问',NEG:'否定',TOP:'话题'}};
  const group = {key:'group-contrast',number:'(18)',name:'问答与合法性对比',context:'调查语境：有人刚刚到来。'};
  const members = [
    {key:'group-contrast:member-q',sourceId:'sentence-q',label:'a.',role:'Q',group,metadata,judgment:{symbol:''},body:{ipa:'mĩra na-tu#super[55]?',words:[{form:'mira',gloss:'谁'},{form:'na-tu',gloss:'来-Q'}],translation:'谁来了？'}},
    {key:'group-contrast:member-a',sourceId:'sentence-a',label:'b.',role:'A',group,metadata,judgment:{symbol:''},body:{ipa:'luma na#super[21].',words:[{form:'luma#sub[1]',gloss:'露玛'},{form:'na',gloss:'来.PST'}],translation:'露玛来了。',notes:'仅用于原型的默认不复制备注。'}},
    {key:'group-contrast:member-bad',sourceId:'sentence-bad',label:'c.',role:'A',group,metadata,judgment:{symbol:'*'},body:{ipa:'na luma.',words:[{form:'na',gloss:'来.PST'},{form:'luma',gloss:'露玛'}],translation:'想表达“露玛来了”。'},localJudgment:'此语境中不接受这个词序。'},
    {key:'group-contrast:member-uncertain',sourceId:'sentence-uncertain',label:'d.',role:'A',group,metadata,judgment:{symbol:'?'},body:{ipa:'luma se-na.',words:[{form:'luma',gloss:'露玛'},{form:'se-na',gloss:'NEG-来'}],translation:'露玛没有来。'}}
  ];
  const rows = [{key:'corpus:text-a:3',sourceId:'corpus-3',label:'(3)',metadata,body:{ipa:'soro#super[55] urtu na.',words:[{form:'soro',gloss:'山'},{form:'urtu',gloss:'高'},{form:'na',gloss:'COP.PST'}],translation:'那座山很高。'}},...members,
    {key:'other-group:same-q',sourceId:'sentence-q',label:'b.',role:'Q',group:{key:'other-group',number:'(22)',name:'只摘取原组中的 b 句',context:''},metadata,judgment:{symbol:''},body:members[0].body},
    {key:'long:one-strip',sourceId:'long',label:'(24)',metadata,body:{ipa:'长句单行词格测试；不会按预览窗口宽度拆分。',words:Array.from({length:24},(_,i)=>({form:i%3===0?'na#super[55]':'morpheme'+(i+1),gloss:i%3===0?'PST':'第'+(i+1)+'词标注'})),translation:'这条例句用来检查所有词格是否仍在同一张表、同一行中。'}},
    {key:'empty:slots',sourceId:'empty',label:'(25)',metadata,body:{ipa:'空标注、标点与附加层',words:[{form:'luma',gloss:''},{form:',',gloss:''},{form:'na',gloss:'来'}],translation:'露玛，来了。'},layers:[{name:'本字',visible:true,values:['露玛','，','来']}]}
  ];
  return {metadata,rows};
});
