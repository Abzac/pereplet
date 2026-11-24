import type {Entry} from './types';

export function numericSeriesPosition(value:unknown):number|null {
 if(typeof value!=='number'&&typeof value!=='string')return null;
 const text=String(value).trim();
 if(!/^\d+(?:[.,]\d+)?$/.test(text))return null;
 const number=Number(text.replace(',','.'));
 return Number.isFinite(number)&&number>=0?number:null;
}

/** Missing positions stay last in both directions. Zero is a real series position. */
export function compareSeriesPositions(a:unknown,b:unknown,direction:1|-1=1):number {
 const left=numericSeriesPosition(a),right=numericSeriesPosition(b);
 return left===null?(right===null?0:1):right===null?-1:(left-right)*direction;
}

type Acquisition=Entry['acquisitions'][number];
export function acquisitionFormat(item:Acquisition):string {
 const type=(item.type||'').split(';',1)[0].trim().toLowerCase();
 if(type.includes('epub'))return'EPUB';if(type.includes('pdf'))return'PDF';
 if(/comicbook[+-]rar|cbr|x-rar-compressed|vnd\.rar/.test(type))return'CBR';if(/comicbook\+zip|cbz/.test(type))return'CBZ';
 if(/fictionbook|fb2/.test(type))return'FB2';if(type==='text/plain')return'TXT';
 if(/zip/.test(type))return /\.fb2\.zip(?:[?#]|$)/i.test(item.url)?'FB2.zip':'ZIP';
 const extension=item.url.match(/\.(epub|pdf|fb2|txt|cbz|cbr)(?:[?#]|$)/i)?.[1];
 return extension?.toUpperCase()||item.title?.trim()||'Файл';
}
export function formatFileSize(bytes:unknown):string {
 if(typeof bytes!=='number'||!Number.isSafeInteger(bytes)||bytes<=0)return'';
 if(bytes<1024)return `${bytes} Б`;
 const unit=bytes>=1024**3?'ГБ':bytes>=1024**2?'МБ':'КБ',divisor=unit==='ГБ'?1024**3:unit==='МБ'?1024**2:1024;
 return `${(bytes/divisor).toLocaleString('ru',{maximumFractionDigits:bytes<divisor*10?1:0})} ${unit}`;
}
export function acquisitionLabel(item:Acquisition):string {
 const size=formatFileSize(item.size_bytes);
 return `${acquisitionFormat(item)}${size?` · ${size}`:''}`;
}
export function remoteSizeLabel(entry:Entry):string {
 const sizes=[...new Set((entry.acquisitions||[]).filter(item=>formatFileSize(item.size_bytes)).map(acquisitionLabel))];
 if(sizes.length)return sizes.join(' / ');
 const size=formatFileSize(entry.catalog_size?.bytes);
 return size?`${entry.catalog_size?.format||'Файл'} · ${size}`:'';
}
export function remoteSizeTitle(entry:Entry):string {
 return (entry.acquisitions||[]).some(item=>formatFileSize(item.size_bytes))?'Размер по данным каталога':'Размер исходного файла по данным каталога; архив и другие форматы могут отличаться';
}

export interface SeriesScope {url:string;title:string}
const nameKey=(value:string)=>value.trim().replace(/^["«]|["»]$/g,'').trim().toLocaleLowerCase('ru').replace(/\s+/g,' ');
function address(value:string):string {try{const url=new URL(value);url.hash='';url.searchParams.delete('page');return url.href.replace(/\/$/,'')}catch{return value}}
export function scopedSeriesPosition(entry:Entry,scope:SeriesScope):number|null {
 const title=scope.title.replace(/^(?:книги в серии|все книги серии|книги серии|books in series)\s+/i,'');
 const named=title!==scope.title?nameKey(title):'';
 const candidates=(entry.series||[]).filter(series=>series.links?.some(link=>address(link.url)===address(scope.url))||(named&&nameKey(series.name)===named));
 return candidates.length===1?numericSeriesPosition(candidates[0].position):null;
}
export function sortEntriesInSeries(entries:Entry[],scope?:SeriesScope):Entry[] {
 if(!scope)return entries;
 const positioned=entries.map((entry,index)=>({entry,index,position:scopedSeriesPosition(entry,scope)}));
 if(!positioned.some(item=>item.position!==null))return entries;
 return positioned.sort((a,b)=>compareSeriesPositions(a.position,b.position)||a.index-b.index).map(item=>item.entry);
}
