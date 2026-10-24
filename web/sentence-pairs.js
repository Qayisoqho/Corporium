/* Legacy Tab editor, shared by text and independent examples. */
(()=>{
function parse(text){return text.split('\n').filter(line=>line.trim()).map((line,i)=>{const parts=line.split('\t');if(parts.length!==2)throw Error(`第 ${i+1} 行需要一个 Tab 分隔语素和标注；标注可以留空。`);return {form:parts[0],gloss:parts[1]};});}
window.CorporiumPairs={parse};
})();
