export type SearchHit = {chapter:number; chapter_title:string; id:string; start:number; end:number; before:string; match:string; after:string};
export type SearchResponse = {query:string; scope:'book'|'chapter'; total:number; offset:number; next_offset:number|null; results:SearchHit[]};

// The importer collapses whitespace. Keep a UTF-16 map back to the original DOM,
// including inline elements, NBSP, surrogate pairs and repeated words.
export function canonicalOffsets(raw:string, canonical:string, start:number, end:number):[number,number]|null {
 let text='', offsets:number[]=[]; let pending=-1;
 for(let i=0;i<raw.length;i++) {
  if(/[\s\u001c-\u001f\u0085]/u.test(raw[i])) {if(text&&pending<0)pending=i;continue;}
  if(pending>=0){text+=' ';offsets.push(pending);pending=-1;}
  text+=raw[i];offsets.push(i);
 }
 if(text!==canonical||start<0||end<=start||end>text.length)return null;
 return [offsets[start],offsets[end-1]+1];
}

export function textRange(element:HTMLElement, canonical:string, start:number, end:number):Range|null {
 const doc=element.ownerDocument, walker=doc.createTreeWalker(element,4), nodes:Text[]=[];
 let node:Node, raw='';
 while((node=walker.nextNode())){nodes.push(node as Text);raw+=node.textContent||'';}
 const span=canonicalOffsets(raw,canonical,start,end);if(!span)return null;
 let offset=0,startNode:Text=null,endNode:Text=null,startOffset=0,endOffset=0;
 for(const text of nodes){const length=text.data.length;
  if(!startNode&&span[0]<offset+length){startNode=text;startOffset=span[0]-offset;}
  if(span[1]>offset&&span[1]<=offset+length){endNode=text;endOffset=span[1]-offset;break;}
  offset+=length;
 }
 if(!startNode||!endNode)return null;
 const range=doc.createRange();range.setStart(startNode,startOffset);range.setEnd(endNode,endOffset);return range;
}

export function literalMatches(text:string,query:string,limit=2000):{start:number;end:number}[] {
 if(!query)return [];
 const escaped=query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
 const pattern=new RegExp(escaped,'giu'), found:{start:number;end:number}[]=[];
 let match:RegExpExecArray;
 while(found.length<limit&&(match=pattern.exec(text)))found.push({start:match.index,end:match.index+match[0].length});
 return found;
}
