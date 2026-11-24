import {api} from './api';

export type SpeechPart = {id:string,text:string};
let cancellation:Promise<void> = Promise.resolve();

// Shared across Reader instances: reopening a book must wait for the previous
// reader's stop request, otherwise a late cancellation can kill the new voice.
export function cancelLocalSpeech():Promise<void>{
 cancellation=cancellation.then(()=>api('/api/tts/cancel','POST')).then(()=>undefined,()=>undefined);
 return cancellation;
}
export function waitForSpeechCancellation(){return cancellation;}

export function splitSpeech(paragraphs:SpeechPart[],limit=1200):SpeechPart[]{
 const result:SpeechPart[]=[];
 for(const paragraph of paragraphs){
  let remaining=paragraph.text||'';
  while(remaining.length){
   let end=Math.min(limit,remaining.length);
   if(end<remaining.length){
    const prefix=remaining.slice(0,end);
    const sentence=Array.from(prefix.matchAll(/[.!?…][»”"']?\s+/g)).at(-1);
    const boundary=sentence?sentence.index+sentence[0].length:prefix.lastIndexOf(' ')+1;
    if(boundary>end*.45)end=boundary;
    // Do not split a surrogate pair in an unusual long token.
    if(/[\uD800-\uDBFF]/.test(remaining[end-1]))end--;
   }
   const text=remaining.slice(0,end).trim();
   if(text)result.push({id:paragraph.id,text});
   remaining=remaining.slice(end);
  }
 }
 return result;
}
