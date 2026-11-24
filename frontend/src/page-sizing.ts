/** Fits complete images. Ratios are height/width; proportional scaling never crops artwork. */
export function spreadWidths(width:number,height:number,ratios:number[],gap:number,equalHeight=false):number[] {
 const aspects=ratios.map(value=>Number.isFinite(value)&&value>0?value:Math.SQRT2);
 if(!aspects.length)return[];
 const available=Math.max(1,width-Math.max(0,gap)*(aspects.length-1)),maxHeight=Math.max(1,height);
 if(equalHeight){const commonHeight=Math.min(maxHeight,available/aspects.reduce((sum,ratio)=>sum+1/ratio,0));return aspects.map(ratio=>commonHeight/ratio)}
 const commonWidth=Math.min(available/aspects.length,maxHeight/Math.max(...aspects));return aspects.map(()=>commonWidth);
}
