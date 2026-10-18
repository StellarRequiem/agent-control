// Codex app-server wire contract checked against official documentation 2026-10-01.
// This client is controller-only; none of these methods is exposed as an agent tool.
const error=code=>Object.assign(new Error(code),{code});
const id=x=>typeof x==="string"&&x.length>0&&x.length<=256;
export class CodexSessions {
  constructor({rpc,onViolation=()=>{},onEvent=()=>{}}){
    this.rpc=rpc;this.onViolation=onViolation;this.onEvent=onEvent;this.ready=false;this.halted=false;this.threads=new Map();
    rpc.onNotification(message=>this.notification(message));
    rpc.onServerRequest(message=>{
      // Never grant native approvals, permissions, credentials or reverse access.
      rpc.rejectServerRequest(message.id,-32601,"Unsupported by operator sidecar");
      this.halted=true;this.onViolation("SERVER_INITIATED_REQUEST_REJECTED");
    });
  }
  async initialize(){
    if(this.ready||this.halted)throw error("CODEX_NOT_INITIALIZABLE");
    const result=await this.rpc.request("initialize",{clientInfo:{name:"operator_sidecar",title:"Operator Sidecar",version:"0.3.0"}});
    this.rpc.notify("initialized",{});
    this.ready=true;return {initialized:true,server:result};
  }
  check(){if(!this.ready||this.halted)throw error("CODEX_ADMISSION_CLOSED");}
  async prepare({model,cwd}){
    this.check();
    if(!id(model)||typeof cwd!=="string"||!cwd.startsWith("/")||/[\0\r\n]/.test(cwd))throw error("PRESET_INVALID");
    const result=await this.rpc.request("thread/start",{model,cwd,approvalPolicy:"never",sandbox:"readOnly",serviceName:"operator_sidecar"});
    const t=result?.thread;
    if(!id(t?.id)||!id(t?.sessionId)||t.sessionId!==t.id||t.forkedFromId)throw error("FRESH_THREAD_UNPROVEN");
    if(this.threads.has(t.id))throw error("THREAD_ID_REUSED");
    const entry={id:t.id,sessionId:t.sessionId,model,cwd,active:null,starting:false,completed:new Map(),fresh:false};
    this.threads.set(t.id,entry);
    const read=await this.rpc.request("thread/read",{threadId:t.id,includeTurns:true});
    if(read?.thread?.id!==t.id||!Array.isArray(read.thread.turns)||read.thread.turns.length!==0)throw error("THREAD_HISTORY_NOT_EMPTY");
    entry.fresh=true;
    if(this.halted)throw error("CODEX_ADMISSION_CLOSED");
    return {thread_id:t.id,session_id:t.sessionId,state:"PREPARED_HELD",instruction_sources:result.instructionSources??null};
  }
  async start(threadId,prompt,guard){
    this.check();const t=this.threads.get(threadId);
    if(!t?.fresh||t.active||t.starting||typeof prompt!=="string"||!prompt||prompt.length>100000||typeof guard!=="function")throw error("TURN_START_INVALID");
    guard();t.starting=true;
    try{
      // Native dispatch must separately be disabled/denied in this exact runtime.
      // Read-only and approvalPolicy never do NOT establish that boundary.
      const r=await this.rpc.request("turn/start",{threadId,input:[{type:"text",text:prompt}],cwd:t.cwd,
        approvalPolicy:"never",sandboxPolicy:{type:"readOnly",access:{type:"restricted",includePlatformDefaults:true,readableRoots:[t.cwd]}}});
      const turn=r?.turn;
      if(!id(turn?.id))throw error("TURN_ID_MISSING");
      if(t.active&&t.active!==turn.id)throw error("TURN_ID_MISMATCH");
      if(!t.completed.has(turn.id))t.active=turn.id;
      if(this.halted&&t.active)await this.interruptOne(t);
      return {thread_id:threadId,turn_id:turn.id,state:t.completed.get(turn.id)??(this.halted?"INTERRUPT_REQUESTED":"RUNNING")};
    }catch(e){this.halted=true;this.onViolation(e.code||"TURN_START_FAILED");throw e;}
    finally{t.starting=false;}
  }
  notification(message){
    this.onEvent(message);
    const p=message?.params;
    if(!p)return;
    if(message.method==="turn/started"||message.method==="turn/completed"){
      const t=this.threads.get(p.threadId);if(!t)return;
      if(!id(p.turn?.id)){this.halted=true;this.onViolation("INVALID_TURN_NOTIFICATION");return;}
      if(message.method==="turn/started"){
        if(!t.completed.has(p.turn.id))t.active=p.turn.id;
        if(this.halted)void this.interruptOne(t);
      }else{
        if(!["completed","interrupted","failed"].includes(p.turn.status)){this.halted=true;this.onViolation("INVALID_TURN_STATUS");return;}
        t.completed.set(p.turn.id,p.turn.status);if(t.active===p.turn.id)t.active=null;
      }
    }
  }
  async interruptOne(t){
    const turnId=t.active;if(!turnId)return {acknowledged:false,reason:"NO_KNOWN_TURN"};
    try{
      await this.rpc.request("turn/interrupt",{threadId:t.id,turnId});
      return {acknowledged:true,thread_id:t.id,turn_id:turnId,completion_observed:t.completed.get(turnId)==="interrupted"};
    }catch(e){return {acknowledged:false,thread_id:t.id,turn_id:turnId,code:e.code||"INTERRUPT_FAILED"};}
  }
  async halt(){
    this.halted=true;
    const results=await Promise.all([...this.threads.values()].filter(t=>t.active).map(t=>this.interruptOne(t)));
    return {acknowledged:results.every(r=>r.acknowledged),requests:results,physical_stop:"UNVERIFIED",
      pending_start:[...this.threads.values()].filter(t=>t.starting).map(t=>t.id)};
  }
  status(){return {ready:this.ready,halted:this.halted,threads:[...this.threads.values()].map(t=>({
    id:t.id,session_id:t.sessionId,active_turn:t.active,starting:t.starting,fresh:t.fresh,completed:[...t.completed].map(([id,status])=>({id,status}))})),native_route_enforcement:"UNKNOWN"};}
}
