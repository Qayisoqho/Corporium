/* Unicode characters and descriptive lookup terms; chart reference:
   https://www.internationalphoneticassociation.org/content/ipa-chart */
const CorporiumIPA=(()=>{
 // Chinese labels follow the user's reviewed workbook; blank revisions retain the original.
 const reviewedNames={
 "p": "双唇爆发音（清）",
 "b": "双唇爆发音（浊）",
 "t": "龈爆发音（清）",
 "d": "龈爆发音（浊）",
 "ʈ": "卷舌爆发音（清）",
 "ɖ": "卷舌爆发音（浊）",
 "c": "硬腭爆发音（清）",
 "ɟ": "硬腭爆发音（浊）",
 "k": "软腭爆发音（清）",
 "ɡ": "软腭爆发音（浊）",
 "q": "小舌爆发音（清）",
 "ɢ": "小舌爆发音（浊）",
 "ʔ": "声门爆发音",
 "n": "龈鼻音",
 "r": "龈鼻音",
 "ⱱ": "唇齿闪/拍音",
 "ɾ": "龈闪/拍音",
 "ɽ": "卷舌闪/拍音",
 "s": "龈擦音（清）",
 "z": "龈擦音（浊）",
 "ɬ": "龈边擦音（清）",
 "ɮ": "龈边擦音（浊）",
 "ɹ": "龈近音",
 "l": "龈边近音",
 "i": "高前不圆唇元音",
 "y": "高前圆唇元音",
 "ɨ": "高央不圆唇元音",
 "ʉ": "高央圆唇元音",
 "ɯ": "高后不圆唇元音",
 "u": "高后圆唇元音",
 "ɪ": "高前不圆唇元音（央化）",
 "ʏ": "高前圆唇元音（央化）",
 "ʊ": "高后圆唇元音（央化）",
 "e": "半高前不圆唇元音",
 "ø": "半高前圆唇元音",
 "ɘ": "半高央不圆唇元音",
 "ɵ": "半高央圆唇元音",
 "ɤ": "半高后不圆唇元音",
 "o": "半高后圆唇元音",
 "ɛ": "半低前不圆唇元音",
 "œ": "半低前圆唇元音",
 "ɜ": "半低央不圆唇元音",
 "ɞ": "半低央圆唇元音",
 "ʌ": "半低后不圆唇元音",
 "ɔ": "半低后圆唇元音",
 "æ": "次低前不圆唇元音",
 "ɐ": "次低央元音",
 "a": "低前不圆唇元音",
 "ɶ": "低前圆唇元音",
 "ɑ": "低后不圆唇元音",
 "ɒ": "低后圆唇元音",
 "ʘ": "双唇倒吸气音",
 "ǀ": "齿倒吸气音",
 "ǃ": "龈倒吸气音",
 "ǂ": "腭龈倒吸气音",
 "ǁ": "龈边倒吸气音",
 "ɗ": "龈内爆音",
 "ʼ": "外挤气音符号",
 "ʍ": "唇软腭擦音（清）",
 "w": "唇软腭擦音（浊）",
 "ɥ": "唇硬腭近音（浊）",
 "ʜ": "会厌擦音（清）",
 "ʢ": "会厌擦音（浊）",
 "ʡ": "会厌爆发音",
 "ɕ": "龈腭擦音（清）",
 "ʑ": "龈腭擦音（浊）",
 "ɺ": "龈边闪音（浊）",
 "ɧ": "龈后软腭双部位擦音（清）",
 "̹": "偏圆唇",
 "̜": "欠圆唇",
 "̟": "偏前",
 "̠": "偏后",
 "̯": "不成音节",
 "̤": "气嗓声",
 "ʲ": "硬腭化",
 "̝": "偏高",
 "̞": "偏低",
 "̘": "舌根前伸",
 "̙": "舌根后缩",
 "̺": "舌尖化",
 "̻": "舌叶化",
 "̚": "无听感除阻",
 "ˈ": "主重读",
 "ˌ": "次重读",
 ".": "音节边界",
 "|": "小音系单位（音步）",
 "‖": "大音系单位（语调）"
};
 const removed=new Set(["˩˥","˥˩","˧˥","˩˧","˥˩˥"]);
 const symbols=[];
 function add(category,text,zh,en){if(removed.has(text))return;const name=reviewedNames[text]??zh,english=en.replace(/\p{Script=Han}+/gu,' ');symbols.push({text,category,name,search:(text+' '+name+' '+english).toLowerCase(),display:/^\p{M}/u.test(text)?'◌'+text:text});}
 const places=['双唇 bilabial','唇齿 labiodental','齿 dental','齿龈 alveolar','龈后 postalveolar','卷舌 retroflex','硬腭 palatal','软腭 velar','小舌 uvular','咽 pharyngeal','声门 glottal'];
 const rows=[['塞音 plosive',['p b','','','t d','','ʈ ɖ','c ɟ','k ɡ','q ɢ','','ʔ']],['鼻音 nasal',['m','ɱ','','n','','ɳ','ɲ','ŋ','ɴ','','']],['颤音 trill',['ʙ','','','r','','','','','ʀ','','']],['闪音 tap flap',['','ⱱ','','ɾ','','ɽ','','','','','']],['擦音 fricative',['ɸ β','f v','θ ð','s z','ʃ ʒ','ʂ ʐ','ç ʝ','x ɣ','χ ʁ','ħ ʕ','h ɦ']],['边擦音 lateral fricative',['','','','ɬ ɮ','','','','','','','']],['近音 approximant',['','ʋ','','ɹ','','ɻ','j','ɰ','','','']],['边近音 lateral approximant',['','','','l','','ɭ','ʎ','ʟ','','','']]];
 for(const [manner,cells] of rows)cells.forEach((cell,i)=>cell.split(' ').filter(Boolean).forEach((s,j,a)=>add('consonants',s,places[i].split(' ')[0]+manner.split(' ')[0]+(a.length===2?(j?'（浊）':'（清）'):''),places[i]+' '+manner+' '+(a.length===2?(j?'voiced':'voiceless'):''))));
 for(const [s,zh,en] of [['ʘ','双唇吸气音','bilabial click'],['ǀ','齿吸气音','dental click'],['ǃ','齿龈吸气音','alveolar click'],['ǂ','腭龈吸气音','palatoalveolar click'],['ǁ','齿龈边吸气音','alveolar lateral click'],['ɓ','双唇内爆音','bilabial implosive'],['ɗ','齿龈内爆音','alveolar implosive'],['ʄ','硬腭内爆音','palatal implosive'],['ɠ','软腭内爆音','velar implosive'],['ʛ','小舌内爆音','uvular implosive'],['ʼ','挤喉音符号','ejective'],['ʍ','清唇软腭擦音','voiceless labial velar fricative'],['w','浊唇软腭近音','voiced labial velar approximant'],['ɥ','浊唇硬腭近音','voiced labial palatal approximant'],['ʜ','清会厌擦音','voiceless epiglottal fricative'],['ʢ','浊会厌擦音','voiced epiglottal fricative'],['ʡ','会厌塞音','epiglottal plosive'],['ɕ','清龈腭擦音','voiceless alveolopalatal fricative'],['ʑ','浊龈腭擦音','voiced alveolopalatal fricative'],['ɺ','齿龈边闪音','alveolar lateral flap'],['ɧ','同时发ʃ与x的擦音','simultaneous sh x fricative']])add('other',s,zh,en);
 for(const [height,front,central,back] of [['闭','i y','ɨ ʉ','ɯ u'],['次闭','ɪ ʏ','','ʊ'],['半闭','e ø','ɘ ɵ','ɤ o'],['中','','ə',''],['半开','ɛ œ','ɜ ɞ','ʌ ɔ'],['次开','æ','ɐ',''],['开','a ɶ','','ɑ ɒ']])for(const [place,pair] of [['前',front],['央',central],['后',back]])pair.split(' ').filter(Boolean).forEach((s,i,a)=>add('vowels',s,height+place+(a.length===2?(i?'圆唇':'不圆唇'):'')+'元音',({'闭':'close','次闭':'near close','半闭':'close mid','中':'mid','半开':'open mid','次开':'near open','开':'open'}[height])+' '+({'前':'front','央':'central','后':'back'}[place])+' vowel '+(a.length===2?(i?'rounded':'unrounded'):'')));
 for(const [s,zh,en] of [['\u0325','清化（下置）','voiceless'],['\u030a','清化（上置）','voiceless above'],['\u032c','浊化','voiced'],['ʰ','送气','aspirated aspiration'],['\u0339','较圆唇','more rounded'],['\u031c','较少圆唇','less rounded'],['\u031f','前移','advanced'],['\u0320','后移','retracted'],['\u0308','央化','centralized'],['\u033d','中央化','mid centralized'],['\u0329','成音节','syllabic'],['\u032f','非音节','non syllabic'],['˞','卷舌化','rhoticity'],['\u0324','气声','breathy voiced'],['\u0330','嘎裂声','creaky voiced'],['\u033c','舌唇音','linguolabial'],['ʷ','唇化','labialized'],['ʲ','腭化','palatalized'],['ˠ','软腭化','velarized'],['ˤ','咽化','pharyngealized'],['\u0334','软腭化或咽化','velarized pharyngealized'],['\u031d','升高','raised'],['\u031e','降低','lowered'],['\u0318','舌根前移','advanced tongue root ATR'],['\u0319','舌根后移','retracted tongue root RTR'],['\u032a','齿化','dental'],['\u033a','舌尖音','apical'],['\u033b','舌叶音','laminal'],['\u0303','鼻化','nasalized'],['ⁿ','鼻音除阻','nasal release'],['ˡ','边音除阻','lateral release'],['\u031a','无可闻除阻','no audible release'],['\u0361','上连音符','tie bar above affricate'],['\u035c','下连音符','tie bar below affricate']])add('marks',s,zh,en);
 for(const [s,zh,en] of [['ˈ','主重音','primary stress'],['ˌ','次重音','secondary stress'],['ː','长音','long length'],['ˑ','半长音','half long'],['\u0306','超短音','extra short'],['.','音节界限','syllable break'],['|','小语调群','minor group'],['‖','大语调群','major group'],['‿','连读','linking'],['˥','最高调','extra high tone'],['˦','高调','high tone'],['˧','中调','mid tone'],['˨','低调','low tone'],['˩','最低调','extra low tone'],['˩˥','升调','rising tone'],['˥˩','降调','falling tone'],['˧˥','高升调','high rising'],['˩˧','低升调','low rising'],['˥˩˥','降升调','rising falling contour'],['ꜜ','降阶','downstep'],['ꜛ','升阶','upstep'],['↗','整体上升','global rise'],['↘','整体下降','global fall'],['\u030b','最高调附加符','extra high tone diacritic'],['\u0301','高调附加符','high tone acute'],['\u0304','中调附加符','mid tone macron'],['\u0300','低调附加符','low tone grave'],['\u030f','最低调附加符','extra low tone'],['\u030c','升调附加符','rising tone caron'],['\u0302','降调附加符','falling tone circumflex'],['¹','上标1','superscript tone 1'],['²','上标2','superscript tone 2'],['³','上标3','superscript tone 3'],['⁴','上标4','superscript tone 4'],['⁵','上标5','superscript tone 5'],['⁰','上标0','superscript tone 0']])add('prosody',s,zh,en);
 // Additional Chinese-linguistics symbols use the actual characters, including ȶ U+0236.
 for(const [s,zh,en] of [["ȶ","龈腭爆发音（清）","voiceless alveolo-palatal plosive"],["ȡ","龈腭爆发音（浊）","voiced alveolo-palatal plosive"],["ȵ","龈腭鼻音","voiced alveolopalatal nasal"],["ȴ","龈腭边近音（浊）","voiced alveopalatal lateral approximant"],["ɿ","舌尖龈不圆唇元音","apical alveolar unrounded vowel"],["ʮ","舌尖龈圆唇元音","apical alveolar rounded vowel"],["ʅ","舌尖卷舌不圆唇元音","apical retroflex unrounded vowel"],["ʯ","舌尖卷舌圆唇元音","apical retroflex rounded vowel"],["ᴇ","中前不圆唇元音","mid front unrounded vowel"],["ᴀ","低央不圆唇元音","open central unrounded vowel"]])add('sinitic',s,zh,en);
 const categories={consonants:'辅音',vowels:'元音',other:'其他辅音',marks:'附加符号',prosody:'声调与超音段',sinitic:'汉语语言学符号'};
 function find(query,category=''){const q=query.trim().toLowerCase();return symbols.filter(s=>(!category||s.category===category)&&(!q||q.split(/\s+/u).every(term=>s.search.includes(term))||[...s.text].some(c=>('u+'+c.codePointAt(0).toString(16).padStart(4,'0')).includes(q))))}
 return {symbols,categories,find};
})();
if(typeof module!=='undefined')module.exports=CorporiumIPA;
