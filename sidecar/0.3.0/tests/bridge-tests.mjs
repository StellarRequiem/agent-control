export async function runIntegrationTests({SafetySupervisor,Controller,validateControlPayload,SerialAudit,guardedBackend,candidateView}){
 const results=[],assert=(x,m="assertion")=>{if(!x)throw new Error(m);};
 const eq=(a,b)=>assert(JSON.stringify(a)===JSON.stringify(b),JSON.stringify({a,b}));
 const test=async(name,fn)=>{try{await fn();results.push({name,pass:true});}catch(e){results.push({name,pass:false,error:e.message});}};
 const reject=async(fn,code)=>{try{await fn();}catch(e){assert(!code||e.code===code,"expected "+code+" got "+e.code);return;}throw new Error("not rejected");};
 const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
 await test("journal appends serialize while halt can enqueue independently",async()=>{
   const d=defer(),events=[];let active=0,max=0;
   const a=new SerialAudit({append:async e=>{active++;max=Math.max(max,active);if(e===1)await d.promise;events.push(e);active--;return {id:String(e)};}});
   const first=a.append(1),second=a.append(2);await Promise.resolve();eq(max,1);d.resolve();await Promise.all([first,second]);eq(events,[1,2]);eq(max,1);
 });
 await test("journal failure poisons later appends",async()=>{
   let n=0;const a=new SerialAudit({append:async()=>{n++;throw new Error("disk");}});
   await reject(()=>a.append({}));await reject(()=>a.append({}),"AUDIT_UNAVAILABLE");eq(n,1);
 });
 await test("journal queue is bounded",async()=>{
   const d=defer(),a=new SerialAudit({append:()=>d.promise});
   const jobs=Array.from({length:2048},()=>a.append({}));jobs.forEach(p=>p.catch(()=>{}));
   await reject(()=>a.append({}),"AUDIT_QUEUE_LIMIT");d.resolve({id:"fixture"});await Promise.allSettled(jobs);assert(a.broken);
 });
 await test("backend final guard follows asynchronous mount work",async()=>{
   const gate=defer(),entered=defer();let revoked=false,calls=0;
   const b=guardedBackend({call:async()=>{calls++;return {};},stop:async()=>{}});
   const mount={call:async()=>{entered.resolve();await gate.promise;return b.adapter.call("fixture",{});}};
   const task=b.execute(mount,{tool:"fixture",args:{},guard:()=>{if(revoked)throw Object.assign(new Error("halt"),{code:"REVOKED"});},setCancel:()=>{}});
   await entered.promise;revoked=true;gate.resolve();await reject(()=>task,"REVOKED");eq(calls,0);
 });
 await test("backend refuses calls outside guarded executor",async()=>{
   const b=guardedBackend({call:()=>{throw new Error("effect");}});
   await reject(()=>b.adapter.call("fixture",{}),"FINAL_GUARD_MISSING");
 });
 await test("preflight can call only read-only plane status",async()=>{
   const calls=[],b=guardedBackend({call:async n=>{calls.push(n);return {};}});
   await b.start({start:async()=>{await b.adapter.call("plane_status",{});await reject(()=>b.adapter.call("shell_exec",{}),"PREFLIGHT_READ_ONLY");}});
   eq(calls,["plane_status"]);await reject(()=>b.adapter.call("plane_status",{}),"FINAL_GUARD_MISSING");
 });
 await test("backend reconnect is never exposed",async()=>{
   const b=guardedBackend({});eq(b.adapter.canReconnect(),false);await reject(()=>b.adapter.reconnect(),"RECOVERY_NOT_EXPOSED");
 });
 await test("candidate catalog has no arm grant renew or reconnect",async()=>{
   const v=candidateView({supervisor:{},config:{tools:[{name:"fixture.read"}]},getBinding:()=>null});
   eq(v.inventory().map(t=>t.name),["sidecar_status","sidecar_halt","fixture.read"]);
   for(const n of ["arm","grant","renew","mount_reconnect","codex.turn"])eq((await v.call(n,{})).code,"TOOL_NOT_EXPOSED");
 });
 await test("candidate cannot smuggle parameters into local halt",async()=>{
   let halts=0;const v=candidateView({supervisor:{halt:()=>{halts++;}},config:{tools:[]},getBinding:()=>null});
   eq((await v.call("sidecar_halt",{scope:"all"})).ok,false);eq(halts,0);
 });
 await test("candidate binding comes from trusted adapter rather than arguments",async()=>{
   const expected={id:"trusted"};let seen;
   const v=candidateView({supervisor:{dispatch:async(...x)=>{seen=x;return {ok:true};}},config:{tools:[{name:"fixture.read"}]},getBinding:()=>expected});
   await v.call("fixture.read",{binding:"forged"});eq(seen[0],expected);
 });
 function payload(action="arm",params={}){
   return {schema:1,purpose:"codex-sidecar-control",id:"cmd-1",boot_id:"boot-a",config_sha256:"a".repeat(64),expires_at_ms:11000,action,params};
 }
 function controlFixture(){
   const state={now:1000,events:[],halts:[],grants:[],starts:[],sessionPrepares:0};
   let seq=0;
   const audit={append:async e=>{state.events.push(e);return {id:"receipt-"+state.events.length};}};
   const s=new SafetySupervisor({audit,authorize:async()=>({allowed:true}),execute:async op=>{op.guard();return {ok:true};},interrupt:async()=>({acknowledged:true}),
     clock:()=>state.now,makeId:()=>"lease-"+(++seq),configHash:"a".repeat(64),bootId:"boot-a"});
   const original=s.halt.bind(s);s.halt=reason=>{state.halts.push(reason);return original(reason);};
   const c=new Controller({supervisor:s,verify:async p=>p,sessionId:"session-a",config:{mount:{identity:{actor:"codex"},tools:[{name:"fixture.read"}]}},audit,now:()=>state.now,
     onGrant:b=>state.grants.push(b),onStart:async p=>state.starts.push(p),onStop:async()=>({stopped:"fixture"})});
   const evidence={session_id:"session-a",runtime_version:"fixture-runtime",effective_config_sha256:"b".repeat(64),
     allowed_receipt_ids:["fixture-auth","fixture-exec"],denied_receipt_ids:["fixture-denied"],native_routes_denied:true,scope_isolation_verified:true};
   return {s,c,state,evidence,audit};
 }
 for(const [field,value] of [["purpose","other"],["boot_id","other"],["config_sha256","c".repeat(64)],["expires_at_ms",1000],["expires_at_ms",1000000],["action","exec"],["extra",true]])
  await test("signed control binding rejects "+field+"="+String(value).slice(0,12),async()=>{await reject(()=>validateControlPayload({...payload(),[field]:value},{bootId:"boot-a",configHash:"a".repeat(64),now:1000}),"CONTROL_BINDING_INVALID");});
 await test("unsigned arm command is rejected",async()=>{const {c,s}=controlFixture();await reject(()=>c.handle({command:"arm"}),"CONTROL_REQUEST_INVALID");eq(s.mode,"HELD");});
 await test("signature verifier refusal precedes controller audit and arming",async()=>{
   const {c,s,state}=controlFixture();c.verify=async()=>{throw Object.assign(new Error("signature"),{code:"SIGNATURE_INVALID"});};
   await reject(()=>c.handle({command:"signed",envelope:payload()}),"SIGNATURE_INVALID");eq(s.mode,"HELD");eq(state.events.length,0);
 });
 await test("session-mismatched evidence cannot arm",async()=>{const {c,s,evidence}=controlFixture();await reject(()=>c.handle({command:"signed",envelope:payload("arm",{evidence:{...evidence,session_id:"other"}})}),"HOST_EVIDENCE_REQUIRED");eq(s.mode,"HELD");});
 await test("arm evidence needs allowed and denied receipt identifiers",async()=>{
   for(const k of ["allowed_receipt_ids","denied_receipt_ids"]){const {c,s,evidence}=controlFixture();await reject(()=>c.handle({command:"signed",envelope:payload("arm",{evidence:{...evidence,[k]:[]}})}),"HOST_EVIDENCE_REQUIRED");eq(s.mode,"HELD");}
 });
 await test("signed fixture arm does not promote runtime enforcement",async()=>{
   const {c,evidence}=controlFixture();await c.handle({command:"signed",envelope:payload("arm",{evidence})});eq(c.status().supervisor.mode,"READY");eq(c.status().enforcement,"UNKNOWN");
 });
 await test("controller rejects replay within boot",async()=>{
   const {c,evidence}=controlFixture(),p=payload("arm",{evidence});await c.handle({command:"signed",envelope:p});await reject(()=>c.handle({command:"signed",envelope:p}),"CONTROL_REPLAY");
 });
 await test("grant cannot expand beyond configured capability catalog",async()=>{
   const {c,evidence}=controlFixture();await c.handle({command:"signed",envelope:payload("arm",{evidence})});
   await reject(()=>c.handle({command:"signed",envelope:{...payload("grant",{tools:["native.exec"]}),id:"cmd-2"}}),"GRANT_TOOL_INVALID");
 });
 await test("grant binds server-side session and withholds lease handle",async()=>{
   const {c,state,evidence}=controlFixture();await c.handle({command:"signed",envelope:payload("arm",{evidence})});
   const r=await c.handle({command:"signed",envelope:{...payload("grant",{tools:["fixture.read"]}),id:"cmd-2"}});
   eq(state.grants[0].session,"session-a");eq(r.lease_id_withheld,true);assert(!("id" in r));
 });
 await test("halt remains callable while signed verifier is hanging",async()=>{
   const {c,s}=controlFixture(),d=defer();c.verify=()=>d.promise;
   const pending=c.handle({command:"signed",envelope:{}});eq(c.busy,true);
   await c.handle({command:"halt"});eq(s.mode,"HALTED");d.resolve(payload("prepare",{}));await reject(()=>pending,"PREPARE_NOT_ALLOWED");
 });
 await test("halt during controller audit cannot reopen admission",async()=>{
   const {c,s,evidence,audit}=controlFixture(),d=defer(),entered=defer();audit.append=async()=>{entered.resolve();return d.promise;};
   const pending=c.handle({command:"signed",envelope:payload("arm",{evidence})});await entered.promise;await c.handle({command:"halt"});
   d.resolve({id:"late"});await reject(()=>pending,"ARM_NOT_ALLOWED");eq(s.mode,"HALTED");
 });
 await test("controller audit failure closes admission",async()=>{
   const {c,s,evidence,audit}=controlFixture();audit.append=async()=>{throw new Error("disk");};
   await reject(()=>c.handle({command:"signed",envelope:payload("arm",{evidence})}),"AUDIT_UNAVAILABLE");eq(s.mode,"HALTED");
 });
 await test("attached-runtime controller cannot pretend to start or interrupt Codex",async()=>{
   const {c}=controlFixture();await reject(()=>c.handle({command:"signed",envelope:payload("start",{prompt:"fixture"})}),"START_INVALID");eq(c.status().codex,null);
 });
 return {passed:results.filter(r=>r.pass).length,failed:results.filter(r=>!r.pass).length,total:results.length,results,
   environment:"pure JavaScript with injected fixtures; signature/Node/OS not exercised"};
}
