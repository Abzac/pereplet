<script lang="ts">
 export let book:any;export let className='';export let lazy=true;
 let failed=false;
 $: template=!book.cover_url||book.cover_kind==='template'||failed;
 $: hue=[0,155,285][Array.from(String(book.title||'')).reduce((n,c)=>n+c.charCodeAt(0),0)%3];
 $: title=book.title||'Без названия';
 $: author=book.authors?.join(', ')||book.author||'';
</script>
{#if template}
 <span class={`cover-art ${className}`}>
  <img src={failed||!book.cover_url?'/assets/cover-fallback.png':book.cover_url} alt={`Обложка ${title}`} loading={lazy?'lazy':'eager'} style:filter={`hue-rotate(${hue}deg)`}/>
  <span class="cover-lettering" aria-hidden="true"><span class="cover-author">{author}</span><strong class:long-title={title.length>35}>{title}</strong><span class="cover-edition">П Е Р Е П Л Ё Т</span></span>
 </span>
{:else}
 <img class={className} src={book.cover_url} alt={`Обложка ${title}`} loading={lazy?'lazy':'eager'} onerror={()=>failed=true}/>
{/if}
