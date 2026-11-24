<script lang="ts">
 import {X,Stack,WarningCircle} from 'phosphor-svelte';
 import {api} from './api';
 import {dialogFocus} from './dialog-focus';
 import type {Book} from './types';

 export let books:Book[];
 export let selectedIds:string[];
 export let onclose:()=>void;
 export let onupdated:(books:Book[])=>void;
 export let notify:(message:string)=>void;

 const selectedBooks=books.filter(book=>selectedIds.includes(book.id));
 const commonSeries=selectedBooks.length&&selectedBooks.every(book=>book.series===selectedBooks[0].series)?selectedBooks[0].series:'';
 let choice=commonSeries?`series:${commonSeries}`:'new',newName='',busy=false,completed=0,attempted=0;
 let pendingIds=selectedBooks.map(book=>book.id),failures:{id:string;title:string;error:string}[]=[];
 $: existing=[...new Set(books.map(book=>book.series).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ru',{numeric:true}));
 $: name=choice==='new'?newName.trim():choice==='none'?'':choice.slice(7);
 $: valid=choice==='none'||name.length>0&&name.length<=300&&!/[\u0000-\u001f]/.test(name);

 function close(){if(!busy)onclose()}
 function keydown(event:KeyboardEvent){if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close()}}
 async function save(){
  if(busy||!valid||!pendingIds.length)return;
  busy=true;failures=[];attempted=0;
  const targets=books.filter(book=>pendingIds.includes(book.id)),saved:Book[]=[],errors:typeof failures=[];
  for(const book of targets){
   try{
    const updated=await api<Book>(`/api/books/${book.id}`,'PATCH',{series:name,...(book.series!==name?{series_index:null}:{})});
    saved.push(updated);completed++;
   }catch(error){errors.push({id:book.id,title:book.title,error:error instanceof Error?error.message:'Не удалось сохранить серию'})}
   attempted++;
  }
  if(saved.length)onupdated(saved);
  failures=errors;pendingIds=errors.map(item=>item.id);busy=false;
  if(!failures.length){notify(name?`Серия «${name}»: сохранено ${completed}.`:`Из серии убрано: ${completed}.`);onclose()}
  else notify(`Серия сохранена: ${completed}. Не удалось: ${failures.length}.`);
 }
</script>

<div class="modal-backdrop">
 <div class="small-modal series-assignment" role="dialog" aria-modal="true" aria-labelledby="series-assignment-title" tabindex="-1" use:dialogFocus onkeydown={keydown}>
  <div class="panel-heading"><h2 id="series-assignment-title">Назначить серию</h2><button class="icon-button" aria-label="Закрыть выбор серии" disabled={busy} onclick={close}><X size={22}/></button></div>
  <p class="series-selection-count">Выбрано изданий: <strong>{selectedBooks.length}</strong></p>
  <form onsubmit={event=>{event.preventDefault();void save()}}>
   <label for="series-assignment-choice">Серия</label>
   <select id="series-assignment-choice" bind:value={choice} disabled={busy||completed>0}>
    <option value="new">Создать новую серию…</option>
    {#each existing as series}<option value={`series:${series}`}>{series}</option>{/each}
    <option value="none">Без серии</option>
   </select>
   {#if choice==='new'}<label for="series-assignment-name">Название новой серии</label><input id="series-assignment-name" bind:value={newName} placeholder="Например, Мир воров" maxlength="300" required disabled={busy||completed>0}/>{/if}
   <p class="series-assignment-hint">{choice==='none'?'Издания останутся в библиотеке. Удалится только их связь с серией.':'Номера уже в этой серии сохранятся. У перенесённых из другой серии номер будет пустым. Новые номера не назначаются автоматически.'}</p>
   {#if busy}<p class="series-assignment-progress" role="status" aria-live="polite">Сохраняем: {attempted} из {pendingIds.length}…</p>{/if}
   {#if failures.length}<div class="series-assignment-errors" role="alert"><p><WarningCircle size={18}/>Не удалось сохранить: {failures.length}. Успешно: {completed}.</p><ul>{#each failures as failure}<li><strong>{failure.title}</strong><span>{failure.error}</span></li>{/each}</ul><p>Повторная попытка затронет только эти издания.</p></div>{/if}
   <div class="modal-actions"><button type="button" disabled={busy} onclick={close}>{failures.length?'Закрыть':'Отмена'}</button><button class="primary" type="submit" disabled={busy||!valid||!pendingIds.length}><Stack size={18}/>{busy?'Сохраняем…':failures.length?'Повторить':choice==='none'?'Убрать из серии':'Сохранить серию'}</button></div>
  </form>
 </div>
</div>

<style>
 .series-assignment{width:500px;max-width:100%;outline:none}.series-selection-count{margin:0 0 18px}.series-selection-count strong{color:var(--text);font-weight:500}
 .series-assignment form{gap:9px}.series-assignment select,.series-assignment input{width:100%;min-height:40px}.series-assignment .series-assignment-hint{font-size:11px;line-height:1.7;margin:7px 0 0}
 .series-assignment .modal-actions{margin-top:18px}.series-assignment .modal-actions .primary{margin-top:0}.series-assignment-progress{font-size:12px;margin:10px 0 0;min-height:20px}
 .series-assignment-errors{padding:12px;border:1px solid var(--line);border-radius:6px;background:var(--surface-alt);font-size:12px}.series-assignment-errors p{font-size:12px;margin:0;display:flex;gap:8px;align-items:center}.series-assignment-errors p:last-child{font-size:11px}
 .series-assignment-errors ul{margin:10px 0;padding-left:18px;max-height:160px;overflow-y:auto}.series-assignment-errors li{margin:8px 0}.series-assignment-errors strong,.series-assignment-errors span{display:block;overflow-wrap:anywhere}.series-assignment-errors strong{font-weight:500}.series-assignment-errors span{font-size:11px;color:var(--muted);margin-top:3px}
</style>
