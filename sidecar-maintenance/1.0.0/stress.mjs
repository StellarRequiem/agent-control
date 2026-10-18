// Seeded fixture-only state machine checks. No IO, model calls or host effects.
export async function runStress(SafetySupervisor){
 const traces=[];let checks=0;
 const assert=(x,message)=>{checks++;if(!x)throw new Error(message);};
 for(let seed=1;seed<=128;seed++){
  let rng=seed,now=1,ids=0,effects=0,expected=0,closed=false,budget=8;const events=[];
  const next=()=>{rng=(Math.imul(rng,1664525)+1013904223)>>>0;return rng;};
  const audit={append:async event=>{events.push(event);return {id:"receipt-"+events.length};}};
  const s=new SafetySupervisor({audit,authorize:async()=>({allowed:true}),
   execute:async op=>{op.guard();effects++;return {ok:true};},interrupt:async()=>({acknowledged:true}),
   clock:()=>now,makeId:()=>"fixture-"+(++ids),configHash:"a".repeat(64),bootId:"fixture-boot"});
  await s.arm({valid:true,id:"fixture-proof",boot_id:"fixture-boot",config_sha256:"a".repeat(64),
   native_routes_denied:true,scope_isolation_verified:true,ttl_ms:1000},async x=>x);
  const binding=await s.grant({session:"fixture-session",actor:"codex",tools:["fixture.read"],maxCalls:8,ttlMs:2000});
  for(let step=0;step<48;step++){
   const action=step===0?0:next()%7;
   if(action===4){s.halt("FIXTURE_HALT");closed=true;}
   else if(action===5){now+=1001;s.tick();closed=true;}
   else{
    const allowed=action===0||action===1||action===6;
    const tool=allowed?"fixture.read":"fixture.forbidden";
    const selected=action===3?{...binding,session:"peer"}:binding;
    const canExecute=!closed&&allowed&&budget>0;
    const result=await s.dispatch(selected,tool,{});
    if(canExecute){expected++;budget--;assert(result.ok===true,"allowed fixture did not execute");}
    else assert(result.ok===false,"ungranted fixture executed");
    if(!closed&&allowed&&budget===0&&result.ok===false)closed=true;
   }
   assert(effects===expected,"unexpected effect count");
   if(closed)assert(!s.status().admission_open,"closed admission reopened");
   assert(s.status().runtime_enforcement==="UNKNOWN","fixture promoted enforcement");
  }
  const permitted=events.filter(x=>x.kind==="authorization"&&x.decision==="ALLOW").length;
  assert(effects===permitted,"effect lacks authorization event");
  traces.push({seed,effects,closed});
 }
 return {ok:true,fixture_traces:traces.length,assertions:checks,seeds:{first:1,last:128},
  real_model_sessions:0,live_effects:0,classification:"SYNTHETIC_STATE_MACHINE_ONLY",traces};
}
