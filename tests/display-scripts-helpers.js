const fs=require('node:fs'),vm=require('node:vm');
module.exports=function installScripts(context){
 const source=fs.readFileSync('web/app.js','utf8');
 vm.runInContext(source.match(/^function rich\([^\n]+/m)[0],context);
};
