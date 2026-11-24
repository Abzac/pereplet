<script lang="ts">
 import {CheckCircle,ArrowUUpLeft,X} from 'phosphor-svelte';
 import type {CompletionReason} from './reading-completion';
 export let reason:CompletionReason=null;
 export let busy=false,done=false;
 export let oncomplete:()=>void;export let onundo:()=>void;export let ondismiss:()=>void;
</script>

{#if reason||done}
 <section class="reading-completion" aria-label="Завершение чтения" data-reader-keep-controls>
  <div class="completion-copy" aria-live="polite"><strong>{done?'Отмечено как прочитанное':reason==='end'?'Вы в конце книги':'Близко к концу книги'}</strong><span>{done?'Позиция сохранена. Издание убрано из «Сейчас читаю».':'Уже дочитали? Можно завершить, даже если дальше сноски и приложения.'}</span></div>
  {#if done}<button class="text-button completion-action" disabled={busy} onclick={onundo}><ArrowUUpLeft size={17}/>Отменить</button>{:else}<button class="completion-action" disabled={busy} onclick={oncomplete}><CheckCircle size={17}/>{busy?'Сохраняем…':'Отметить прочитанным'}</button>{/if}
  <button class="icon-button completion-dismiss" disabled={busy} aria-label={done?'Закрыть сообщение о прочтении':'Не отмечать прочитанным сейчас'} title={done?'Закрыть':'Не сейчас'} onclick={ondismiss}><X size={18}/></button>
 </section>
{/if}

<style>
 .reading-completion{position:fixed;z-index:45;bottom:86px;left:50%;transform:translateX(-50%);width:max-content;max-width:calc(100vw - 40px);display:flex;align-items:center;gap:16px;padding:14px 15px 14px 18px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--text);box-shadow:0 9px 30px #0003}
 .completion-copy{min-width:0;max-width:380px}.completion-copy strong{display:block;font-size:13px;font-weight:500}.completion-copy span{display:block;margin-top:5px;font-size:11px;line-height:1.5;color:var(--muted)}
 .completion-action{min-height:36px;white-space:nowrap;gap:7px;padding:8px 11px;font-size:11px}.completion-dismiss{flex:none;width:30px;height:34px;color:var(--muted)}
 @media(max-width:720px){.reading-completion{width:calc(100vw - 32px);max-width:none;flex-wrap:wrap;gap:10px;padding:13px 42px 13px 15px;bottom:76px}.completion-copy{max-width:none;flex:1 0 100%}.completion-dismiss{position:absolute;right:8px;top:10px}}
</style>
