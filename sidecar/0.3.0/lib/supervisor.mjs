// No host IO. Effects, clocks, audit and cancellation adapters are injected.
export class SidecarError extends Error {constructor(code){super(code);this.code=code;}}
const err=c=>new SidecarError(c);
const text=x=>typeof x==="string"&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(x);
const finite=x=>Number.isFinite(x)&&x>=0;
export class SafetySupervisor {
  constructor({audit,authorize,execute,interrupt,clock,makeId,configHash,bootId,maxConcurrent=1}) {
    if(!audit||typeof audit.append!=="function"||![authorize,execute,interrupt,clock,makeId].every(x=>typeof x==="function")||
      !/^[a-f0-9]{64}$/.test(configHash)||!text(bootId)||!Number.isSafeInteger(maxConcurrent)||maxConcurrent<1||maxConcurrent>16)throw err("SUPERVISOR_CONFIG_INVALID");
    Object.assign(this,{audit,authorize,execute,interrupt,clock,makeId,configHash,bootId,maxConcurrent});
    this.mode="HELD";this.epoch=1;this.reason="STARTUP_HELD";this.leases=new Map();this.active=new Map();this.usedProofs=new Set();
    this.lastClock=clock();if(!finite(this.lastClock))throw err("CLOCK_INVALID");
    this.lastHalt=null;this.arming=false;this.closed=false;
  }
  status(){if(this.mode==="READY"){try{this.checkReady();}catch{}}
    return {mode:this.mode,epoch:this.epoch,reason:this.reason,boot_id:this.bootId,
    admission_open:this.mode==="READY",active:[...this.active.values()].map(x=>({id:x.id,session:x.session,stage:x.stage})),
    runtime_enforcement:"UNKNOWN",physical_stop:"NOT_ESTABLISHED",last_halt:this.lastHalt};}
  time(){
    const n=this.clock();
    if(!finite(n)||n<this.lastClock){this.halt("CLOCK_INVALID");throw err("CLOCK_INVALID");}
    this.lastClock=n;return n;
  }
  async writeAudit(event){try{return await this.audit.append(event);}catch(e){this.halt("AUDIT_UNAVAILABLE");throw err("AUDIT_UNAVAILABLE");}}
  async arm(proof,verifyProof){
    if(this.closed||this.mode!=="HELD"||this.arming||this.active.size)throw err("ARM_NOT_ALLOWED");
    this.arming=true;const epoch=this.epoch;
    try{
      // Verifier must be a protected host capability, never a field in an agent tool call.
      const p=await verifyProof(proof,{bootId:this.bootId,configHash:this.configHash});
      if(!p||p.valid!==true||!text(p.id)||this.usedProofs.has(p.id)||p.boot_id!==this.bootId||p.config_sha256!==this.configHash||
        p.native_routes_denied!==true||p.scope_isolation_verified!==true||!Number.isSafeInteger(p.ttl_ms)||p.ttl_ms<1||p.ttl_ms>60000)throw err("HOST_PROOF_REQUIRED");
      if(epoch!==this.epoch||this.mode!=="HELD")throw err("ARM_REVOKED");
      const expires=this.time()+p.ttl_ms;
      await this.writeAudit({kind:"sidecar",event:"arm",boot_id:this.bootId,epoch,proof_id:p.id,ttl_ms:p.ttl_ms});
      if(epoch!==this.epoch||this.mode!=="HELD"||this.time()>=expires)throw err("ARM_REVOKED");
      this.usedProofs.add(p.id);this.proofExpires=expires;this.mode="READY";this.reason=null;
      return this.status();
    }catch(e){this.halt(e.code||"ARM_FAILED");throw e;}finally{this.arming=false;}
  }
  async renew(proof,verifyProof){
    this.checkReady();const epoch=this.epoch;
    try{
      const p=await verifyProof(proof,{bootId:this.bootId,configHash:this.configHash});
      if(!p||p.valid!==true||!text(p.id)||this.usedProofs.has(p.id)||p.boot_id!==this.bootId||p.config_sha256!==this.configHash||
        p.native_routes_denied!==true||p.scope_isolation_verified!==true||!Number.isSafeInteger(p.ttl_ms)||p.ttl_ms<1||p.ttl_ms>60000)throw err("HOST_PROOF_REQUIRED");
      const expires=this.time()+p.ttl_ms;
      await this.writeAudit({kind:"sidecar",event:"renew",proof_id:p.id,epoch,ttl_ms:p.ttl_ms});
      this.checkReady();if(epoch!==this.epoch||this.time()>=expires)throw err("RENEW_REVOKED");
      this.proofExpires=expires;this.usedProofs.add(p.id);return this.status();
    }catch(e){this.halt(e.code||"RENEW_FAILED");throw e;}
  }
  // Only the protected controller receives this method. No MCP tool exposes it.
  async grant({session,actor,tools,maxCalls=40,ttlMs=30000}){
    this.checkReady();
    if(!text(session)||!text(actor)||!Array.isArray(tools)||!tools.length||tools.length>100||tools.some(t=>!text(t))||
      !Number.isSafeInteger(maxCalls)||maxCalls<1||maxCalls>1000||!Number.isSafeInteger(ttlMs)||ttlMs<1||ttlMs>900000)throw err("LEASE_INVALID");
    const id=this.makeId();if(!text(id)||this.leases.has(id))throw err("LEASE_ID_INVALID");
    const lease={id,session,actor,tools:new Set(tools),remaining:maxCalls,epoch:this.epoch,expires:this.time()+ttlMs};
    await this.writeAudit({kind:"sidecar",event:"grant",session,actor,tools:[...lease.tools],max_calls:maxCalls,ttl_ms:ttlMs,epoch:lease.epoch});
    this.checkReady();if(lease.epoch!==this.epoch)throw err("PERMIT_REVOKED");
    this.leases.set(id,lease);
    // Kept by a trusted adapter; never returned as a model tool result.
    return Object.freeze({id,epoch:lease.epoch,session});
  }
  checkReady(){
    if(this.mode!=="READY"||this.closed)throw err("ADMISSION_CLOSED");
    if(this.time()>=this.proofExpires){this.halt("HOST_PROOF_EXPIRED");throw err("HOST_PROOF_EXPIRED");}
  }
  guard(lease){
    this.checkReady();
    if(lease.epoch!==this.epoch||this.leases.get(lease.id)!==lease)throw err("PERMIT_REVOKED");
    if(this.time()>=lease.expires){this.halt("LEASE_EXPIRED");throw err("LEASE_EXPIRED");}
  }
  async dispatch(binding,tool,args){
    let op=null,lease=null,dispatched=false,authorization=null,executionRecorded=false;
    try{
      this.checkReady();
      lease=this.leases.get(binding?.id);
      if(!lease||binding.epoch!==lease.epoch||binding.session!==lease.session)throw err("LEASE_UNKNOWN");
      this.guard(lease);
      if(!lease.tools.has(tool))throw err("TOOL_OUTSIDE_LEASE");
      if(lease.remaining<=0){this.halt("CALL_BUDGET_EXHAUSTED");throw err("CALL_BUDGET_EXHAUSTED");}
      if(this.active.size>=this.maxConcurrent)throw err("CONCURRENCY_LIMIT");
      if(args===null||typeof args!=="object"||Array.isArray(args))throw err("ARGUMENT_OBJECT_REQUIRED");
      const id=this.makeId();if(!text(id)||this.active.has(id))throw err("OPERATION_ID_INVALID");
      op={id,session:lease.session,actor:lease.actor,tool,stage:"AUTHORIZING",cancel:null,epoch:this.epoch};
      this.active.set(id,op);lease.remaining--;
      const decision=await this.authorize({id,actor:lease.actor,session:lease.session,tool,args,epoch:op.epoch});
      this.guard(lease);
      if(decision?.allowed!==true)throw err(decision?.code||"POLICY_DENIED");
      authorization=await this.writeAudit({kind:"authorization",decision:"ALLOW",tool,session:lease.session,actor:lease.actor,operation_id:id,epoch:op.epoch});
      this.guard(lease);
      op.stage="DISPATCHED";dispatched=true;
      // Executor must invoke guard again immediately before its final actual dispatch
      // if it has awaited configuration/audit work since entering this callback.
      const result=await this.execute({id,tool,args,actor:lease.actor,session:lease.session,
        guard:()=>this.guard(lease),setCancel:fn=>{if(typeof fn!=="function")throw err("CANCEL_INVALID");op.cancel=fn;if(op.epoch!==this.epoch)void this.requestCancel(op);}});
      this.guard(lease);
      if(result?.ok!==true)throw err(result?.code||"DOWNSTREAM_FAILURE");
      await this.writeAudit({kind:"execution",authorization_id:authorization.id,operation_id:id,tool,session:lease.session,executed:true,ok:true,epoch:op.epoch});
      executionRecorded=true;this.guard(lease);
      return {ok:true,code:"COMPLETED",operation_id:id,result,authorization_receipt:authorization};
    }catch(e){
      const code=e.code||"OPERATION_FAILED";
      if(dispatched)this.halt(code);
      try{await this.writeAudit(executionRecorded?{kind:"sidecar",event:"result_suppressed_after_halt",operation_id:op?.id,code}:authorization?
        {kind:"execution",authorization_id:authorization.id,operation_id:op?.id,tool,session:lease?.session,executed:dispatched?"UNKNOWN":false,ok:false,code}:
        {kind:"authorization",decision:"DENY",tool,session:lease?.session,code,executed:false});}
      catch{this.halt("AUDIT_UNAVAILABLE");}
      return {ok:false,code,executed:dispatched?"UNKNOWN":false,operation_id:op?.id??null};
    }finally{if(op)this.active.delete(op.id);}
  }
  async requestCancel(op){
    if(!op.cancel||op.cancelRequested)return;
    op.cancelRequested=true;op.stage="CANCEL_REQUESTED";
    try{const r=await op.cancel();op.cancelAcknowledged=r?.acknowledged===true;}
    catch{op.cancelAcknowledged=false;}
    // Acknowledgement is not independent proof that effects ceased.
  }
  halt(reason="OPERATOR_HALT"){
    if(this.mode==="HALTED")return this.lastHalt;
    // This transition is synchronous and precedes audit IO and any awaited interrupt.
    this.mode="HALTED";this.reason=String(reason).slice(0,128);this.epoch++;this.leases.clear();
    const ids=[...this.active.keys()];
    const report={admission:"CLOSED",epoch:this.epoch,reason:this.reason,active_at_halt:ids,
      cancellation:"REQUESTED",physical_stop:"UNVERIFIED",audit:"PENDING"};
    this.lastHalt=report;
    for(const op of this.active.values())void this.requestCancel(op);
    try{Promise.resolve(this.interrupt({reason:this.reason,active:ids,epoch:this.epoch})).then(
      r=>{report.interrupt_acknowledged=r?.acknowledged===true;},
      ()=>{report.interrupt_acknowledged=false;});}catch{report.interrupt_acknowledged=false;}
    Promise.resolve().then(()=>this.audit.append({kind:"sidecar",event:"halt",epoch:this.epoch,reason:this.reason,active_at_halt:ids}))
      .then(()=>{report.audit="RECORDED";},()=>{report.audit="FAILED";});
    return report;
  }
  tick(){
    if(this.mode==="READY"){
      try{this.checkReady();for(const l of this.leases.values())if(this.time()>=l.expires){this.halt("LEASE_EXPIRED");break;}}
      catch{}
    }
    return this.status();
  }
  close(){this.closed=true;return this.halt("SUPERVISOR_CLOSED");}
}
