export type CompletionReason='near-end'|'end';
export type CompletionSource='forward'|'scroll'|'speech'|'jump'|'restore';

/** Navigation position is never proof of completion. This only offers a choice. */
export function completionOffer(position:number,source:CompletionSource,atEnd=false,dismissed=false,alreadyRead=false):CompletionReason|null {
 if(dismissed||alreadyRead||!['forward','scroll','speech'].includes(source))return null;
 if(atEnd)return'end';
 return Number.isFinite(position)&&position>=.9?'near-end':null;
}

/** Queue position/status writes so a delayed autosave cannot undo an explicit status. */
export function serialReadingWriter<T>(read:()=>T,write:(patch:Record<string,unknown>)=>Promise<T>,commit:(book:T)=>void){
 let tail:Promise<unknown>=Promise.resolve();
 return (patch:(book:T)=>Record<string,unknown>):Promise<T>=>{
  const result=tail.then(async()=>{const updated=await write(patch(read()));commit(updated);return updated});
  tail=result.catch(()=>{});return result;
 };
}
