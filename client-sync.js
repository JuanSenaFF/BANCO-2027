(function(root){
  'use strict';
  function createSession({url,key,onChange=()=>{},onExpired=()=>{},fetcher=globalThis.fetch,now=Date.now,schedule=setTimeout,cancel=clearTimeout}){
    let session=null,timer=null,refreshing=null,generation=0;
    function clear(){
      generation++;
      cancel(timer);
      timer=null;
      session=null;
      refreshing=null;
      onChange(null);
    }
    function set(data){
      if(!data?.access_token||!data?.refresh_token)throw Error('Resposta de autenticação inválida.');
      generation++;
      cancel(timer);
      const expiresAt=Number(data.expires_at)||now()/1000+(Number(data.expires_in)||3600);
      session={...data,expires_at:expiresAt};
      onChange(session);
      const remaining=expiresAt*1000-now();
      timer=schedule(()=>{refresh().catch(()=>{});},Math.max(1000,remaining-Math.min(120000,remaining/2)));
      return session;
    }
    async function refresh(){
      if(refreshing)return refreshing;
      if(!session)throw Error('Entre na sua conta.');
      const version=generation,refreshToken=session.refresh_token;
      const task=(async()=>{
        try{
          const response=await fetcher(url.replace(/\/$/,'')+'/auth/v1/token?grant_type=refresh_token',{
            method:'POST',headers:{apikey:key,'Content-Type':'application/json'},
            body:JSON.stringify({refresh_token:refreshToken}),signal:AbortSignal.timeout(15000)
          });
          if(!response.ok)throw Error('Sessão expirada. Entre novamente.');
          const data=await response.json();
          // A response from a previous account must never revive a closed session.
          if(version!==generation)return session;
          return set(data);
        }catch(error){
          if(version===generation){clear();onExpired(error);}
          throw error;
        }
      })();
      refreshing=task;
      try{return await task;}finally{if(refreshing===task)refreshing=null;}
    }
    async function token(){
      const before=session;
      if(!before)throw Error('Entre na sua conta.');
      if(before.expires_at*1000-now()<=30000){
        const data=await refresh();
        if(!data)throw Error('Sessão encerrada. Entre novamente.');
        return data.access_token;
      }
      return before.access_token;
    }
    return {set,clear,refresh,token};
  }
  function createSaveQueue({send,onSaved=()=>{},onError=()=>{}}){
    let pending=null,running=null,generation=0;
    function reset(){generation++;pending=null;}
    function start(){
      if(running)return running;
      running=(async()=>{
        while(pending){
          const item=pending;
          pending=null;
          try{
            await send(item.state);
            if(item.generation===generation)onSaved(item.revision);
          }catch(error){
            if(item.generation===generation)onError(error);
          }
        }
      })().finally(()=>{running=null;if(pending)start();});
      return running;
    }
    function save(state,revision){
      pending={state:JSON.parse(JSON.stringify(state)),revision,generation};
      return start();
    }
    return {save,reset};
  }
  const api={createSession,createSaveQueue};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.BancoSync=api;
})(typeof window!=='undefined'?window:globalThis);
