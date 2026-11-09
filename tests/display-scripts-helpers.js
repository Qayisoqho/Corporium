const fs=require('node:fs'),vm=require('node:vm');
module.exports=function installScripts(context){
 const source=fs.readFileSync('web/app.js','utf8');
 const typography=fs.readFileSync('web/typography.js','utf8');
 for(const name of ['cssFont','rowFontCSS'])if(!context[name])vm.runInContext(typography.match(new RegExp('^function '+name+'[^\\n]+','m'))[0],context);
 vm.runInContext(source.match(/^function rich\([^\n]+/m)[0],context);
};
