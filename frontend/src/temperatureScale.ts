// Keep labels readable while never using intervals below half a degree.
export function temperatureScale(values:number[]) {
  const finite=values.filter(Number.isFinite);
  const min=finite.length?Math.min(...finite):0;
  const max=finite.length?Math.max(...finite):1;
  const step=Math.max(0.5,Math.ceil((max-min)/4*2)/2);
  let first=Math.floor(min/step)*step;
  let last=Math.ceil(max/step)*step;
  if(first===last){first-=step;last+=step}
  const ticks=Array.from({length:Math.round((last-first)/step)+1},(_,i)=>first+i*step);
  return {ticks,domain:[first,last] as [number,number]};
}
