/* Pure interval geometry, shared by the pointer editor and regression tests. */
const TimelineGeometry={
 edgeMode(x,left,right){
  const grip=Math.min(10,Math.max(0,(right-left)/2));
  if(x-left<=grip&&right-x<=grip)return x-left<=right-x?'left':'right';
  return x-left<=grip?'left':right-x<=grip?'right':'move';
 },
 viewport(from,span,extent=[0,60000]){
  const start=extent[0],end=extent[1]>start?extent[1]:start+60000,max=Math.max(1,end-start);
  span=Math.max(Math.min(1,max),Math.min(max,Math.round(span)));
  return [Math.round(Math.max(start,Math.min(end-span,from))),span];
 },
 follow(from,span,head,extent){
  if(head>=from&&head<from+span)return from;
  return this.viewport(head<from?head-span*.15:head,span,extent)[0];
 },
 zoom(from,span,ratio,delta,extent){
  ratio=Math.max(0,Math.min(1,ratio));
  const ceiling=extent?(extent[1]-extent[0]||60000):86400000;
  const next=Math.max(extent?Math.min(1,ceiling):500,Math.min(ceiling,Math.round(span*Math.exp(Math.max(-100,Math.min(100,delta))*.003))));
  const result=[Math.round(from+ratio*(span-next)),next];
  return extent?this.viewport(...result,extent):result;
 },
 clamp(start,end,delta,mode,previous=-Infinity,next=Infinity){
  if(mode==='left')return [Math.max(previous,Math.min(end-1,start+delta)),end];
  if(mode==='right')return [start,Math.max(start+1,Math.min(next,end+delta))];
  const d=Math.max(previous-start,Math.min(next-end,delta));return [start+d,end+d];
 },
 snap(value,targets,tolerance){let best=value,distance=tolerance;for(const t of targets){const d=Math.abs(t-value);if(d<=distance){distance=d;best=t;}}return Math.round(best);}
};
if(typeof module!=='undefined')module.exports=TimelineGeometry;
