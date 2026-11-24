<script lang="ts">
 import {Question,X} from 'phosphor-svelte';
 export let highlight=false;
 export let busy=false;
 export let onopen:()=>void;
 export let ondismiss:()=>void;
</script>
<div class="guide-help" class:highlight>
 <button class="sidebar-settings" disabled={busy} onclick={onopen} aria-label="Помощь — руководство читателя"><Question size={22}/>Помощь</button>
 {#if highlight}<div class="guide-hint" role="status"><span>Руководство всегда доступно здесь.</span><button aria-label="Закрыть подсказку" onclick={ondismiss}><X size={16}/></button></div>{/if}
</div>
<style>
 .guide-help{position:relative;margin-bottom:8px;border-radius:6px}
 .guide-help :global(.sidebar-settings){width:100%;justify-content:flex-start}
 .highlight{animation:guide-pulse 1.2s ease-out 2;background:var(--side-active)}
 .guide-hint{position:absolute;bottom:calc(100% + 10px);left:0;width:210px;max-width:calc(100vw - 40px);padding:13px 10px 13px 14px;background:var(--surface);color:var(--text);border:1px solid var(--line);border-radius:8px;box-shadow:0 5px 20px #0003;display:flex;align-items:flex-start;gap:6px;font-size:13px;line-height:1.5;z-index:30}
 .guide-hint:after{content:'';position:absolute;bottom:-6px;left:18px;width:10px;height:10px;transform:rotate(45deg);background:var(--surface);border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
 .guide-hint button{padding:2px;background:transparent;border:0;color:var(--muted)}
 @keyframes guide-pulse{50%{box-shadow:0 0 0 3px var(--gold)}}
 @media(prefers-reduced-motion:reduce){.highlight{animation:none;box-shadow:inset 2px 0 var(--gold)}}
</style>
