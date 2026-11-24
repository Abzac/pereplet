let token='';
let refreshing:Promise<void>|null=null;
function refreshSession():Promise<void>{
 if(!refreshing)refreshing=(async()=>{const response=await fetch('/api/session',{cache:'no-store'});if(!response.ok)throw new Error('Не удалось восстановить соединение с приложением. Обновите вкладку.');const data=await response.json();if(!data.token)throw new Error('Сервер не выдал ключ приложения');token=data.token;})().finally(()=>refreshing=null);
 return refreshing;
}
function awaitSession(pending:Promise<void>,signal?:AbortSignal):Promise<void>{
 if(!signal)return pending;
 return new Promise((resolve,reject)=>{
  let settled=false;
  const finish=(complete:()=>void)=>{if(settled)return;settled=true;signal.removeEventListener('abort',abort);complete()};
  const abort=()=>finish(()=>reject(new DOMException('Запрос отменён','AbortError')));
  signal.addEventListener('abort',abort,{once:true});
  // Keep the shared refresh alive for other callers, including after this abort.
  pending.then(()=>finish(resolve),error=>finish(()=>reject(error)));
  if(signal.aborted)abort();
 });
}
export async function initApi(){try{await refreshSession()}catch{}}
export async function api<T=any>(path:string,method='GET',body?:any,signal?:AbortSignal):Promise<T>{
 const send=()=>{const headers:Record<string,string>={'X-Pereplet':'1'};if(token)headers['X-Pereplet-Token']=token;if(body!==undefined&&!(body instanceof FormData))headers['Content-Type']='application/json';return fetch(path,{method,headers,signal,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)});};
 const usedToken=token;let response=await send();
 // This exact rejection occurs before the operation runs. Never replay arbitrary failures.
 if(response.status===403){let detail='';try{detail=(await response.clone().json()).detail}catch{}
  if(detail==='Запрос должен выполняться из приложения'){
   if(token===usedToken)await awaitSession(refreshSession(),signal);
   if(signal?.aborted)throw new DOMException('Запрос отменён','AbortError');
   response=await send();
  }
 }
 if(!response.ok){let message=`Ошибка ${response.status}`;try{const data=await response.json();message=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data)}catch{}throw new Error(message)}
 return response.status===204?undefined:await response.json();
}
