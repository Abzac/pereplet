export type PageMode='single'|'spread'|'scroll';
export type PagePlace={page:number;ratio:number};
export const clamp=(value:number,min:number,max:number)=>Math.max(min,Math.min(max,value));
export function spreadStart(page:number,count:number,coverFirst=false){const current=clamp(Math.floor(page),0,Math.max(0,count-1));return coverFirst?(current===0?0:1+2*Math.floor((current-1)/2)):2*Math.floor(current/2)}
export function visibleSpread(page:number,count:number,coverFirst=false){const first=spreadStart(page,count,coverFirst);return coverFirst&&first===0?[0]:[first,...(first+1<count?[first+1]:[])]}
export function adjacentPage(page:number,direction:number,count:number,mode:PageMode,coverFirst=false):number|null {
 const first=mode==='spread'?spreadStart(page,count,coverFirst):page;
 const target=mode==='spread'?(direction>0?first+(coverFirst&&first===0?1:2):first-(coverFirst&&first===1?1:2)):first+direction;
 return target>=0&&target<count?target:null;
}
/** Unknown sizes have a fixed estimate; decoded neighbors refine it lazily. */
export function pageOffsets(count:number,width:number,aspects:Record<number,number>,gap=24){const offsets=[0];for(let index=0;index<count;index++)offsets.push(offsets[index]+Math.max(40,width*(aspects[index]||Math.SQRT2))+gap);return offsets}
export function pageAtOffset(offsets:number[],offset:number){let low=0,high=offsets.length-2;while(low<high){const middle=Math.ceil((low+high)/2);if(offsets[middle]<=offset)low=middle;else high=middle-1}return low}
export function placeAtOffset(offsets:number[],offset:number,gap=24):PagePlace {const page=pageAtOffset(offsets,Math.max(0,offset));return{page,ratio:clamp((offset-offsets[page])/Math.max(1,offsets[page+1]-offsets[page]-gap),0,1)}}
export function offsetForPlace(offsets:number[],place:PagePlace,gap=24){const page=clamp(place.page,0,offsets.length-2);return offsets[page]+clamp(place.ratio,0,1)*Math.max(1,offsets[page+1]-offsets[page]-gap)}
export function windowForOffset(offsets:number[],top:number,height:number,max=8){const first=pageAtOffset(offsets,Math.max(0,top)),last=pageAtOffset(offsets,top+height);const start=Math.max(0,first-1),end=Math.min(offsets.length-2,Math.max(last+2,start+3),start+max-1);return Array.from({length:end-start+1},(_,index)=>start+index)}
