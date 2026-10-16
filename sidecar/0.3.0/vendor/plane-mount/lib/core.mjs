// Plane Mount 0.2.0: pure broker. IO is injected and must be host-controlled.
export const VERSION = "0.2.0";
export const PROTOCOL = "2024-11-05";
const obj = x => x !== null && typeof x === "object" && !Array.isArray(x);
const own = (x,k) => Object.prototype.hasOwnProperty.call(x,k);
const fail = (code, detail = code) => Object.assign(new Error(detail), {code});
const fields = (x, allowed) => { if (!obj(x) || Object.keys(x).some(k=>!allowed.includes(k))) throw fail("UNSUPPORTED_FIELDS"); };
const label = x => typeof x === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/.test(x);
const abs = x => typeof x === "string" && (x.startsWith("/") || /^[A-Za-z]:[\\/]/.test(x)) && !/[\0\r\n]/.test(x);
export function schemaCheck(s, depth=0) {
  if (depth>12) throw fail("SCHEMA_TOO_DEEP");
  fields(s,["type","properties","required","additionalProperties","items","maxItems","maxLength","minimum","maximum","enum","description"]);
  if (!["object","array","string","boolean","integer","number"].includes(s.type)) throw fail("SCHEMA_TYPE_UNSUPPORTED");
  if (s.type==="object") {
    if (!obj(s.properties) || s.additionalProperties!==false || !Array.isArray(s.required) ||
        s.required.some(k=>!own(s.properties,k)) || new Set(s.required).size!==s.required.length) throw fail("SCHEMA_MUST_BE_CLOSED");
    for (const [k,v] of Object.entries(s.properties)) {
      if (!label(k) || ["__proto__","constructor","prototype"].includes(k)) throw fail("SCHEMA_KEY_INVALID");
      schemaCheck(v,depth+1);
    }
  }
  if (s.type==="array") {
    if (!Number.isSafeInteger(s.maxItems) || s.maxItems<0 || s.maxItems>1000) throw fail("ARRAY_BOUND_REQUIRED");
    schemaCheck(s.items,depth+1);
  }
  if(s.type==="string" && (!Number.isSafeInteger(s.maxLength)||s.maxLength<0||s.maxLength>65536)) throw fail("STRING_BOUND_REQUIRED");
  for(const k of ["minimum","maximum"]) if(own(s,k)&&!Number.isFinite(s[k])) throw fail("INVALID_BOUND");
  if(own(s,"minimum")&&own(s,"maximum")&&s.minimum>s.maximum) throw fail("INVALID_BOUND");
  if(own(s,"enum")&&(!Array.isArray(s.enum)||!s.enum.length||s.enum.some(v=>!["string","number","boolean"].includes(typeof v)))) throw fail("INVALID_ENUM");
}
export function validate(s,v,depth=0) {
  if(depth>12) throw fail("ARGUMENT_DEPTH");
  let ok = s.type==="object"?obj(v):s.type==="array"?Array.isArray(v):s.type==="integer"?Number.isSafeInteger(v):s.type==="number"?Number.isFinite(v):typeof v===s.type;
  if(!ok) throw fail("ARGUMENT_TYPE");
  if(own(s,"enum")&&!s.enum.some(x=>x===v)) throw fail("ARGUMENT_ENUM");
  if(s.type==="object") {
    if(Object.keys(v).some(k=>!own(s.properties,k))||s.required.some(k=>!own(v,k))) throw fail("ARGUMENT_FIELDS");
    for(const [k,x] of Object.entries(v)) validate(s.properties[k],x,depth+1);
  }
  if(s.type==="array") { if(v.length>s.maxItems) throw fail("ARGUMENT_SIZE"); for(const x of v)validate(s.items,x,depth+1); }
  if(s.type==="string"&&(v.length>s.maxLength||v.includes("\0"))) throw fail("ARGUMENT_SIZE");
  if(typeof v==="number"&&((own(s,"minimum")&&v<s.minimum)||(own(s,"maximum")&&v>s.maximum)))throw fail("ARGUMENT_RANGE");
}
export function validateConfig(c) {
  fields(c,["version","identity","backend","tools","state_dir"]);
  if(c.version!==1)throw fail("CONFIG_VERSION");
  fields(c.identity,["actor","runtime","instance"]);
  if(!["actor","runtime","instance"].every(k=>label(c.identity[k])))throw fail("IDENTITY_REQUIRED");
  fields(c.backend,["command","args","cwd"]);
  if(!abs(c.backend.command)||!abs(c.backend.cwd)||!Array.isArray(c.backend.args)||c.backend.args.length>40||
     c.backend.args.some(v=>typeof v!=="string"||v.length>4096||/[\0\r\n]/.test(v)))throw fail("BACKEND_CONFIG_INVALID");
  if(!abs(c.state_dir))throw fail("STATE_PATH_REQUIRED");
  if(!Array.isArray(c.tools)||!c.tools.length||c.tools.length>100)throw fail("TOOLS_REQUIRED");
  const seen=new Set();
  for(const t of c.tools) {
    fields(t,["name","backend_name","capability","description","inputSchema"]);
    if(!label(t.name)||!label(t.backend_name)||seen.has(t.name)||["mount_status","mount_reconnect"].includes(t.name))throw fail("TOOL_NAME_INVALID");
    seen.add(t.name);
    if(!["read","write","execute","network","desktop"].includes(t.capability))throw fail("CAPABILITY_REQUIRED");
    if(typeof t.description!=="string"||t.description.length>1000)throw fail("DESCRIPTION_INVALID");
    schemaCheck(t.inputSchema);
  }
  const status=c.tools.find(t=>t.name==="status");
  if(!status||status.capability!=="read"||status.backend_name!=="plane_status"||
    JSON.stringify(status.inputSchema)!==JSON.stringify({type:"object",properties:{},required:[],additionalProperties:false}))throw fail("IDENTITY_PREFLIGHT_REQUIRED");
  return c;
}
export function unwrapMcp(r) {
  if(!obj(r)||r.isError===true)throw fail("BACKEND_TOOL_ERROR");
  if(obj(r.structuredContent))return r.structuredContent;
  const xs=Array.isArray(r.content)?r.content.filter(x=>x.type==="text"):[];
  if(xs.length!==1||typeof xs[0].text!=="string")throw fail("BACKEND_ENVELOPE_MISSING");
  try {const d=JSON.parse(xs[0].text);if(!obj(d))throw 0;return d;}catch{throw fail("BACKEND_JSON_INVALID");}
}
export function verifyEnvelope(d,actor) {
  if(!obj(d)||d.actor!==actor)throw fail("BACKEND_IDENTITY_MISMATCH");
  if(d.verdict?.decision!=="ALLOW"||d.verdict?.allowed!==true)throw fail(d.verdict?.code||"BACKEND_DENIED");
  if(d.executed!==true||d.execution_receipt?.handler_executed!==true)throw fail("BACKEND_NOT_EXECUTED");
  for(const k of ["authorization_receipt","execution_receipt"]) {
    const r=d[k];
    if(!obj(r)||!label(r.id)||typeof r.hash!=="string"||!/^[a-f0-9]{64}$/.test(r.hash)||
      !Number.isSafeInteger(r.chain_position)||r.chain_position<1)throw fail("BACKEND_RECEIPT_MISSING");
  }
  if(d.result?.ok!==true)throw fail(d.result?.code||"BACKEND_OPERATION_FAILED");
  return d;
}
const emptySchema={type:"object",properties:{},required:[],additionalProperties:false};
export class Mount {
  constructor({config,loadConfig,backend,audit,hash}) {
    this.config=validateConfig(config);this.loadConfig=loadConfig;this.backend=backend;this.audit=audit;this.hash=hash;
    this.uncertain=false;this.busy=false;this.initialized=false;this.catalog=null;this.last=null;
  }
  inventory() {
    return [
      {name:"mount_status",description:"Local mount status; runtime enforcement is not established.",inputSchema:emptySchema},
      {name:"mount_reconnect",description:"Reconnect only this mount's owned stdio child when idle; never restarts shared bridges.",inputSchema:emptySchema},
      ...this.config.tools.map(t=>({name:t.name,description:t.description,inputSchema:t.inputSchema}))
    ];
  }
  async record(kind,body) {return await this.audit.append({kind,identity:this.config.identity,...body});}
  async start() {
    await this.assertPolicy();
    const authorization=await this.record("authorization",{decision:"ALLOW",tool:"mount_connect",purpose:"owned_child_and_identity_preflight",arguments_hash:this.hash("{}")});
    try {
      const h=await this.backend.initialize();
      if(h.protocolVersion!==PROTOCOL||!obj(h.capabilities?.tools))throw fail("BACKEND_PROTOCOL_UNSUPPORTED");
      const list=await this.backend.list();
      if(!Array.isArray(list.tools)||list.nextCursor)throw fail("BACKEND_CATALOG_INCOMPLETE");
      for(const t of this.config.tools) {
        if(list.tools.filter(x=>x.name===t.backend_name).length!==1)throw fail("BACKEND_TOOL_UNAVAILABLE",t.backend_name);
      }
      this.catalog=list.tools.map(x=>x.name);
      const d=verifyEnvelope(unwrapMcp(await this.backend.call("plane_status",{})),this.config.identity.actor);
      await this.record("execution",{authorization_id:authorization.id,tool:"mount_connect",executed:true,ok:true,backend_authorization_id:d.authorization_receipt.id,backend_execution_id:d.execution_receipt.id});
      this.initialized=true;
    } catch(e) {
      this.uncertain=true;this.initialized=false;
      try{await this.record("execution",{authorization_id:authorization.id,tool:"mount_connect",executed:"UNKNOWN",ok:false,code:e.code||"CONNECT_FAILED"});}catch{}
      throw e;
    }
  }
  async assertPolicy() {
    const latest=validateConfig(await this.loadConfig());
    if(JSON.stringify(latest)!==JSON.stringify(this.config))throw fail("CONFIG_CHANGED");
  }
  async call(name,args={}) {
    if(this.busy)return {ok:false,code:"MOUNT_BUSY",executed:false};
    this.busy=true;
    let auth=null, dispatched=false;
    try {
      await this.assertPolicy();
      if(name==="mount_status") {
        validate(emptySchema,args);
        auth=await this.record("authorization",{decision:"ALLOW",tool:name,arguments_hash:this.hash(JSON.stringify(args))});
        const data={version:VERSION,identity:this.config.identity,connected:this.initialized,
          uncertain:this.uncertain,runtime_enforcement:"UNKNOWN",registration_is_enforcement:false,
          local_audit_authenticates_backend:false,shared_service_recovery:false};
        const execution=await this.record("execution",{authorization_id:auth.id,tool:name,executed:true,ok:true});
        return {ok:true,code:"MOUNT_STATUS",data,authorization_receipt:auth,execution_receipt:execution};
      }
      if(this.uncertain)throw fail("OUTCOME_UNKNOWN_RECONCILE_REQUIRED");
      if(name==="mount_reconnect") {
        validate(emptySchema,args);
        if(!this.initialized||!this.backend.canReconnect())throw fail("RECONNECT_UNSAFE");
        auth=await this.record("authorization",{decision:"ALLOW",tool:name,arguments_hash:this.hash(JSON.stringify(args))});
        dispatched=true;this.initialized=false;
        await this.backend.reconnect();await this.start();
        const execution=await this.record("execution",{authorization_id:auth.id,tool:name,executed:true,ok:true});
        return {ok:true,code:"OWNED_CONNECTION_RECONNECTED",authorization_receipt:auth,execution_receipt:execution};
      }
      const t=this.config.tools.find(t=>t.name===name);
      if(!t)throw fail("TOOL_NOT_ALLOWLISTED");
      validate(t.inputSchema,args);
      if(!this.initialized)throw fail("BACKEND_NOT_READY");
      auth=await this.record("authorization",{decision:"ALLOW",tool:name,capability:t.capability,arguments_hash:this.hash(JSON.stringify(args))});
      dispatched=true;
      const envelope=verifyEnvelope(unwrapMcp(await this.backend.call(t.backend_name,args)),this.config.identity.actor);
      const execution=await this.record("execution",{authorization_id:auth.id,tool:name,executed:true,ok:true,
        backend_authorization_id:envelope.authorization_receipt.id,backend_execution_id:envelope.execution_receipt.id,
        result_hash:this.hash(JSON.stringify(envelope.result))});
      this.last={tool:name,execution_id:execution.id};
      return {ok:true,code:"FORWARDED",backend:envelope,authorization_receipt:auth,execution_receipt:execution};
    }catch(e){
      const code=typeof e?.code==="string"?e.code:"MOUNT_FAILURE";
      // Any failure after dispatch has an unresolved effect until reconciled by the operator.
      if(dispatched)this.uncertain=true;
      let execution=null;
      try {execution=await this.record(auth?"execution":"authorization",{
        authorization_id:auth?.id??null,tool:typeof name==="string"?name.slice(0,96):"invalid",
        decision:auth?undefined:"DENY",ok:false,code,executed:dispatched?"UNKNOWN":false});}catch{this.uncertain=true;}
      return {ok:false,code,executed:dispatched?"UNKNOWN":false,authorization_receipt:auth??execution,execution_receipt:auth?execution:null};
    }finally{this.busy=false;}
  }
}
export async function handleRpc(mount,msg,session) {
  const error=(code,message)=>({jsonrpc:"2.0",id:obj(msg)&&own(msg,"id")?msg.id:null,error:{code,message}});
  if(!obj(msg)||msg.jsonrpc!=="2.0"||typeof msg.method!=="string"||
    (own(msg,"id")&&!(typeof msg.id==="string"||Number.isSafeInteger(msg.id))))return error(-32600,"Invalid Request");
  if(msg.method==="notifications/initialized"&&!own(msg,"id")){if(session.negotiated)session.ready=true;return null;}
  if(!own(msg,"id"))return null;
  if(msg.method==="initialize"){
    if(session.negotiated)return error(-32600,"Already initialized");
    if(!obj(msg.params)||typeof msg.params.protocolVersion!=="string")return error(-32602,"Protocol version required");
    session.negotiated=true;
    return {jsonrpc:"2.0",id:msg.id,result:{protocolVersion:PROTOCOL,capabilities:{tools:{}},serverInfo:{name:"plane-mount",version:VERSION}}};
  }
  if(msg.method==="ping")return {jsonrpc:"2.0",id:msg.id,result:{}};
  if(!session.ready)return error(-32002,"Initialization required");
  if(msg.method==="tools/list")return {jsonrpc:"2.0",id:msg.id,result:{tools:mount.inventory()}};
  if(msg.method==="tools/call") {
    if(!obj(msg.params)||typeof msg.params.name!=="string"||!obj(msg.params.arguments??{}))return error(-32602,"Invalid tool arguments");
    const out=await mount.call(msg.params.name,msg.params.arguments??{});
    return {jsonrpc:"2.0",id:msg.id,result:{isError:!out.ok,content:[{type:"text",text:JSON.stringify(out)}]}};
  }
  return error(-32601,"Method not found");
}

export function nextAudit(previous, position, event, id, timestamp, hash) {
  const body={version:1,id,chain_position:position,timestamp,previous,event};
  return {...body,hash:hash(JSON.stringify(body))};
}
export function verifyAudit(records,hash) {
  let previous="0".repeat(64),position=0;
  for(const r of records) {
    if(!obj(r))throw fail("AUDIT_CORRUPT");
    const {hash:actual,...body}=r;
    if(body.version!==1||body.previous!==previous||body.chain_position!==++position||
      typeof actual!=="string"||hash(JSON.stringify(body))!==actual)throw fail("AUDIT_CORRUPT");
    previous=actual;
  }
  return {previous,position};
}

export function auditHealth(records) {
  const pending=new Map(),uncertain=[];
  for(const r of records){
    const e=r.event;
    if(!e||typeof e!=="object")throw fail("AUDIT_EVENT_INVALID");
    if(e.kind==="authorization"&&e.decision==="ALLOW")pending.set(r.id,{id:r.id,tool:e.tool});
    if(e.kind==="execution"&&e.authorization_id){
      if(!pending.has(e.authorization_id))throw fail("AUDIT_ORPHAN_EXECUTION");
      pending.delete(e.authorization_id);
      if(e.executed==="UNKNOWN")uncertain.push({id:r.id,tool:e.tool,code:e.code});
    }
  }
  return {ready:pending.size===0&&uncertain.length===0,pending:[...pending.values()],uncertain};
}
