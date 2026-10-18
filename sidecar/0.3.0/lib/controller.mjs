const err=c=>Object.assign(new Error(c),{code:c});
const object=x=>x&&typeof x==="object"&&!Array.isArray(x);
const label=x=>typeof x==="string"&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(x);
export function validateControlPayload(p,{bootId,configHash,now}){
  const keys=["schema","purpose","id","boot_id","config_sha256","expires_at_ms","action","params"];
  if(!object(p)||Object.keys(p).some(k=>!keys.includes(k))||p.schema!==1||p.purpose!=="codex-sidecar-control"||
    !label(p.id)||p.boot_id!==bootId||p.config_sha256!==configHash||!object(p.params)||
    !Number.isSafeInteger(p.expires_at_ms)||p.expires_at_ms<=now||p.expires_at_ms-now>60000||
    !["prepare","arm","renew","grant","start","stop_owned"].includes(p.action))throw err("CONTROL_BINDING_INVALID");
  return p;
}
export class Controller {
  constructor({supervisor,verify,sessions,sessionId,config,onGrant,onStart,onStop,audit,now=()=>Date.now()}){
    Object.assign(this,{supervisor,verify,sessions,sessionId,config,onGrant,onStart,onStop,audit,now});this.seen=new Set();this.busy=false;
  }
  status(){return {supervisor:this.supervisor.status(),codex:this.sessions?.status()??null,
    session_id:this.sessionId??null,controller_busy:this.busy,halt_scope:"ADMISSION_AND_OWNED_REQUESTS",enforcement:"UNKNOWN"};}
  // Each connection invokes this independently; status/halt do not join the action queue.
  async handle(request){
    if(!object(request))throw err("CONTROL_REQUEST_INVALID");
    if(request.command==="status"||request.command==="halt"){
      if(Object.keys(request).some(k=>k!=="command"))throw err("CONTROL_FIELDS");
      if(request.command==="halt")this.supervisor.halt("OPERATOR_HALT");
      return this.status();
    }
    if(request.command!=="signed"||Object.keys(request).some(k=>!["command","envelope"].includes(k)))throw err("CONTROL_REQUEST_INVALID");
    if(this.busy)throw err("CONTROLLER_BUSY");
    this.busy=true;
    try{
      const p=await this.verify(request.envelope);
      validateControlPayload(p,{bootId:this.supervisor.bootId,configHash:this.supervisor.configHash,now:this.now()});
      if(this.seen.has(p.id))throw err("CONTROL_REPLAY");
      this.seen.add(p.id);
      if(this.seen.size>10000){this.supervisor.halt("CONTROLLER_REPLAY_CAPACITY");throw err("CONTROLLER_REPLAY_CAPACITY");}
      try{await this.audit.append({kind:"sidecar",event:"controller_request",id:p.id,action:p.action});}
      catch{this.supervisor.halt("AUDIT_UNAVAILABLE");throw err("AUDIT_UNAVAILABLE");}
      if(this.now()>=p.expires_at_ms)throw err("CONTROL_EXPIRED");
      const params=p.params;
      const exact=keys=>{if(Object.keys(params).some(k=>!keys.includes(k)))throw err("CONTROL_FIELDS");};
      if(p.action==="prepare"){
        exact([]);
        if(!this.sessions||this.sessionId||this.supervisor.mode!=="HELD")throw err("PREPARE_NOT_ALLOWED");
        const result=await this.sessions.prepare(this.config.codex);
        this.sessionId=result.session_id;
        return result;
      }
      if(p.action==="arm"||p.action==="renew"){
        exact(["evidence"]);const e=params.evidence;
        if(!object(e)||!label(this.sessionId)||e.session_id!==this.sessionId||
          typeof e.runtime_version!=="string"||!e.runtime_version||!/^[a-f0-9]{64}$/.test(e.effective_config_sha256??"")||
          !Array.isArray(e.allowed_receipt_ids)||e.allowed_receipt_ids.length<2||e.allowed_receipt_ids.some(x=>!label(x))||
          !Array.isArray(e.denied_receipt_ids)||!e.denied_receipt_ids.length||e.denied_receipt_ids.some(x=>!label(x))||
          e.native_routes_denied!==true||e.scope_isolation_verified!==true)throw err("HOST_EVIDENCE_REQUIRED");
        // Signed assertions remain assertions: independent host collection is a deployment prerequisite.
        const ttl=p.expires_at_ms-this.now();
        const proof={valid:true,id:p.id,boot_id:p.boot_id,config_sha256:p.config_sha256,
          native_routes_denied:true,scope_isolation_verified:true,ttl_ms:ttl};
        return await this.supervisor[p.action](proof,async x=>x);
      }
      if(p.action==="grant"){
        exact(["tools","maxCalls","ttlMs"]);
        if(!this.sessionId||!Array.isArray(params.tools))throw err("GRANT_INVALID");
        const permitted=new Set(this.config.mount.tools.map(t=>t.name));if(this.sessions)permitted.add("codex.turn");
        if(params.tools.some(t=>!permitted.has(t)))throw err("GRANT_TOOL_INVALID");
        const binding=await this.supervisor.grant({...params,session:this.sessionId,actor:this.config.mount.identity.actor});
        this.onGrant(binding);
        return {granted:true,session_id:this.sessionId,lease_id_withheld:true};
      }
      if(p.action==="start"){
        exact(["prompt"]);
        if(!this.sessions||!this.sessionId||typeof params.prompt!=="string"||!params.prompt||params.prompt.length>100000)throw err("START_INVALID");
        return await this.onStart(params.prompt);
      }
      exact([]);
      // Signed stop is explicit and limited to the app-server child this instance spawned.
      this.supervisor.halt("OPERATOR_STOP_OWNED");
      return await this.onStop();
    }finally{this.busy=false;}
  }
}
