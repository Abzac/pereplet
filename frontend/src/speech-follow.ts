import type {SpeechPart} from './speech';

/** Locate a split audio fragment in its original paragraph, even for repeated text. */
export function speechFragmentSpan(parts:SpeechPart[],index:number,canonical:string):{start:number;end:number}|null{
 const part=parts[index];if(!part)return null;
 let cursor=0;
 for(let i=0;i<=index;i++){
  if(parts[i].id!==part.id)continue;
  const start=canonical.indexOf(parts[i].text,cursor);if(start<0)return null;
  cursor=start+parts[i].text.length;if(i===index)return{start,end:cursor};
 }
 return null;
}

/** Approximate speech position, not word alignment. Snap to whole UTF-16 characters. */
export function speechCharacterAt(text:string,span:{start:number;end:number},elapsed:number,duration:number):number|null{
 if(!Number.isFinite(duration)||duration<=0||!Number.isFinite(elapsed)||span.end<=span.start)return null;
 const ratio=Math.max(0,Math.min(.999999,elapsed/duration));
 let offset=span.start+Math.floor((span.end-span.start)*ratio);
 if(offset>span.start&&/[\uDC00-\uDFFF]/.test(text[offset]))offset--;
 return offset;
}
