const fs=require('node:fs'),vm=require('node:vm');
module.exports=function installWriting(context){
 require('./display-scripts-helpers.js')(context);
 if(!context.orthographyStyle)context.orthographyStyle=v=>String(v);
 vm.runInContext(fs.readFileSync('web/line-spacing.js','utf8'),context);
 const source=fs.readFileSync('web/lexicon-extra.js','utf8');
 vm.runInContext(source.slice(source.indexOf('function writingDisplayAttrs'),source.indexOf('function addOrthography')),context);
};
