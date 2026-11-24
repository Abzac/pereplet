export type ReadingStatus='unread'|'reading'|'planned'|'read';

/** Old imports may use the earlier aliases; position never determines completion. */
export function normalizeReadStatus(value:unknown):ReadingStatus {
 if(value==='finished')return'read';
 if(value==='want')return'planned';
 return value==='reading'||value==='planned'||value==='read'?value:'unread';
}

export function plannedReturnStatus(book:{planned_previous_status?:unknown;progress?:number;last_opened?:string}):ReadingStatus {
 const previous=book.planned_previous_status;
 if(previous==='unread'||previous==='reading'||previous==='read'||previous==='finished')return normalizeReadStatus(previous);
 // A legacy queued book may lack its old status. Even 100% is only a position.
 return book.last_opened||Number(book.progress)>0?'reading':'unread';
}
