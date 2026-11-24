import type {Book} from './types';
import {booksForView} from './library-scope';
import {compareSeriesPositions} from './book-metadata';
import {normalizeReadStatus} from './reading-status';
import type {ReadingStatus} from './reading-status';

export type LibraryViewBook=Pick<Book,'format'|'media_type'|'archived'|'title'|'authors'|'author'|'series'|'series_index'|'status'>;
export interface LibraryFilterState {
 view?:string;
 query?:string;
 localQuery?:string;
 author?:string;
 series?:string;
 status?:string;
 letter?:string;
}
export interface LibraryFacets {authors:string[];series:string[];hasNoSeries:boolean;statuses:ReadingStatus[]}
export interface LibrarySeriesGroup<T> {key:string;name:string;books:T[]}

/** The same literal substring rule is used by the top search and the local filter. */
export function libraryText(value:unknown):string {
 return String(value??'').trim().toLocaleLowerCase('ru').replace(/ё/g,'е').replace(/\s+/gu,' ');
}
export function libraryAuthors(book:Pick<Book,'authors'|'author'>):string[] {
 const names=(book.authors||[]).map(name=>name.trim()).filter(Boolean);
 return [...new Set(names.length?names:[book.author?.trim()].filter(Boolean))];
}
function ordered(values:string[],selected=''):string[]{
 const names=new Map<string,string>();for(const value of values.filter(Boolean)){const key=libraryText(value);if(!names.has(key))names.set(key,value)}
 // Keep a valid existing selection visible even when imported spelling varies.
 if(selected&&names.has(libraryText(selected)))names.set(libraryText(selected),selected);
 return [...names.values()].sort((a,b)=>a.localeCompare(b,'ru',{numeric:true,sensitivity:'base'}));
}

/** Takes the whole library or an already scoped subset. It never sorts or mutates it. */
export function filterLibrary<T extends LibraryViewBook>(books:T[],filters:LibraryFilterState={}):T[] {
 const scoped=filters.view?booksForView(books,filters.view):books;
 const query=libraryText(filters.query),localQuery=libraryText(filters.localQuery),author=libraryText(filters.author),series=libraryText(filters.series),letter=libraryText(filters.letter);
 const viewStatus=['reading','planned','read'].includes(filters.view)?normalizeReadStatus(filters.view):null;
 const status=filters.status?normalizeReadStatus(filters.status):null;
 return scoped.filter(book=>{
  const normalizedStatus=normalizeReadStatus(book.status);
  if(viewStatus&&normalizedStatus!==viewStatus||status&&normalizedStatus!==status)return false;
  const names=libraryAuthors(book);
  if(author&&!names.some(name=>libraryText(name)===author))return false;
  const name=libraryText(book.series);
  if(series&&(series==='__no_series__'?!!name:name!==series))return false;
  if(letter&&!(names.length?names:[book.title]).some(name=>libraryText(name).startsWith(letter)))return false;
  if(query||localQuery){const text=libraryText([book.title,...names,book.series].filter(Boolean).join(' '));if(query&&!text.includes(query)||localQuery&&!text.includes(localQuery))return false}
  return true;
 });
}

/** A facet retains every active constraint except its own selection. */
export function libraryFacets<T extends LibraryViewBook>(books:T[],filters:LibraryFilterState={}):LibraryFacets {
 const authorBooks=filterLibrary(books,{...filters,author:''});
 const seriesBooks=filterLibrary(books,{...filters,series:''});
 const statusBooks=filterLibrary(books,{...filters,status:''});
 const availableStatuses=new Set(statusBooks.map(book=>normalizeReadStatus(book.status)));
 return {
  authors:ordered(authorBooks.flatMap(libraryAuthors),filters.author),
  series:ordered(seriesBooks.map(book=>book.series?.trim()||''),filters.series),
  hasNoSeries:seriesBooks.some(book=>!book.series?.trim()),
  statuses:(['unread','reading','planned','read'] as ReadingStatus[]).filter(status=>availableStatuses.has(status)),
 };
}

/** Call after filtering/sorting. Empty groups cannot appear; unknown numbers retain input order. */
export function groupLibraryBySeries<T extends Pick<Book,'series'|'series_index'>>(books:T[]):LibrarySeriesGroup<T>[] {
 const groups=new Map<string,LibrarySeriesGroup<T>>();
 for(const book of books){
  const name=book.series?.trim()||'',key=name?libraryText(name):'__no_series__';
  let group=groups.get(key);if(!group){group={key,name,books:[]};groups.set(key,group)}group.books.push(book);
 }
 return [...groups.values()].sort((a,b)=>!a.name||!b.name?(a.name?-1:b.name?1:0):a.name.localeCompare(b.name,'ru',{numeric:true,sensitivity:'base'}))
  .map(group=>({...group,books:group.name?[...group.books].sort((a,b)=>compareSeriesPositions(a.series_index,b.series_index)):group.books}));
}

/** Coauthored books appear under each author, as in the author directory. */
export function groupLibraryByAuthor<T extends Pick<Book,'authors'|'author'>>(books:T[],selectedAuthor=''):LibrarySeriesGroup<T>[] {
 const groups=new Map<string,LibrarySeriesGroup<T>>();
 for(const book of books){
  const authors=ordered(libraryAuthors(book)).filter(name=>!selectedAuthor||libraryText(name)===libraryText(selectedAuthor));
  for(const name of authors.length?authors:['']){
   const key=name?libraryText(name):'__no_author__';
   let group=groups.get(key);if(!group){group={key,name,books:[]};groups.set(key,group)}group.books.push(book);
  }
 }
 return [...groups.values()].sort((a,b)=>!a.name||!b.name?(a.name?-1:b.name?1:0):a.name.localeCompare(b.name,'ru',{numeric:true,sensitivity:'base'}));
}
