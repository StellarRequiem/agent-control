import {spawn} from "node:child_process";
const err=code=>Object.assign(new Error(code),{code});
const METHODS=new Set(["initialize","thread/start","thread/read","turn/start","turn/interrupt"]);
const MAX=1048576;
// Private controller transport: no raw RPC tool is exposed to the model.
export class CodexStdio {
  constructor({command,cwd,env={},onFailure=()=>{},timeoutMs=20000}){
    if(!command?.startsWith("/")||!cwd?.startsWith("/")||!Number.isSafeInteger(timeoutMs)||timeoutMs<1)throw err("CODEX_CONFIG_INVALID");
    this.command=command;this.cwd=cwd;this.env=env;this.onFailure=onFailure;this.timeoutMs=timeoutMs;
    this.pending=new Map();this.next=1;this.buffer=Buffer.alloc(0);this.failed=false;this.stopping=false;
    this.notification=()=>{};this.serverRequest=()=>{};
  }
  onNotification(fn){this.notification=fn;}
  onServerRequest(fn){this.serverRequest=fn;}
  start(){
    if(this.child)throw err("CODEX_ALREADY_STARTED");
    const c=spawn(this.command,["app-server"],{cwd:this.cwd,shell:false,stdio:["pipe","pipe","pipe"],env:this.env});
    this.child=c;let stderrBytes=0;
    c.stdin.on("error",()=>this.fail("CODEX_PIPE_FAILED"));
    c.stdout.on("data",chunk=>{
      if(this.failed)return;
      this.buffer=Buffer.concat([this.buffer,chunk]);
      if(this.buffer.length>MAX)return this.fail("CODEX_OUTPUT_LIMIT");
      let i;
      while((i=this.buffer.indexOf(10))>=0){
        const line=this.buffer.subarray(0,i).toString("utf8");this.buffer=this.buffer.subarray(i+1);
        let msg;try{msg=JSON.parse(line);}catch{return this.fail("CODEX_PROTOCOL_ERROR");}
        if(!msg||typeof msg!=="object"||Array.isArray(msg))return this.fail("CODEX_PROTOCOL_ERROR");
        try{
          if(typeof msg.method==="string"){
            if(Object.hasOwn(msg,"id"))this.serverRequest(msg);else this.notification(msg);
          }else{
            const w=this.pending.get(msg.id);
            if(!w)return this.fail("CODEX_UNEXPECTED_RESPONSE");
            this.pending.delete(msg.id);clearTimeout(w.timer);
            if(Object.hasOwn(msg,"error"))w.reject(err("CODEX_RPC_ERROR"));
            else if(Object.hasOwn(msg,"result"))w.resolve(msg.result);
            else {w.reject(err("CODEX_PROTOCOL_ERROR"));return this.fail("CODEX_PROTOCOL_ERROR");}
          }
        }catch{return this.fail("CODEX_CALLBACK_FAILED");}
      }
    });
    c.stderr.on("data",chunk=>{stderrBytes+=chunk.length;if(stderrBytes>MAX)this.fail("CODEX_STDERR_LIMIT");});
    c.on("error",()=>this.fail("CODEX_SPAWN_FAILED"));
    c.on("exit",(code,signal)=>{this.exit={code,signal};this.rejectPending("CODEX_EXITED");if(!this.stopping)this.fail("CODEX_EXITED");});
  }
  rejectPending(code){for(const w of this.pending.values()){clearTimeout(w.timer);w.reject(err(code));}this.pending.clear();}
  fail(code){
    if(this.failed)return;
    this.failed=true;this.failure=code;this.rejectPending(code);
    try{this.onFailure(code);}catch{}
  }
  write(msg){
    if(!this.child||this.failed||this.child.exitCode!==null||this.child.signalCode!==null)throw err("CODEX_UNAVAILABLE");
    const line=JSON.stringify(msg)+"\n";
    if(Buffer.byteLength(line)>MAX)throw err("CODEX_INPUT_LIMIT");
    this.child.stdin.write(line,e=>{if(e)this.fail("CODEX_PIPE_FAILED");});
  }
  request(method,params={}){
    if(!METHODS.has(method))return Promise.reject(err("CODEX_METHOD_DENIED"));
    if(this.pending.size>=16)return Promise.reject(err("CODEX_PENDING_LIMIT"));
    const id=this.next++;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>this.fail("CODEX_TIMEOUT_OUTCOME_UNKNOWN"),this.timeoutMs);
      this.pending.set(id,{resolve,reject,timer});
      try{this.write({id,method,params});}catch(e){clearTimeout(timer);this.pending.delete(id);reject(e);}
    });
  }
  notify(method,params={}){
    if(method!=="initialized")throw err("CODEX_NOTIFICATION_DENIED");
    this.write({method,params});
  }
  rejectServerRequest(id,code,message){this.write({id,error:{code,message}});}
  async stopOwned(){
    const c=this.child;if(!c)return {owned_process_exit_observed:true,not_started:true,descendants:"UNVERIFIED"};
    this.stopping=true;
    if(c.exitCode===null&&c.signalCode===null){
      await new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>{c.off("exit",done);reject(err("OWNED_CODEX_DID_NOT_STOP"));},3000);
        const done=()=>{clearTimeout(timer);resolve();};
        c.once("exit",done);
        if(c.exitCode!==null||c.signalCode!==null)return done();
        // Exact owned child handle; never PID files, ports, process groups, or shared service names.
        try{if(!c.kill("SIGTERM")){clearTimeout(timer);c.off("exit",done);reject(err("OWNED_CODEX_SIGNAL_FAILED"));}}
        catch(e){clearTimeout(timer);c.off("exit",done);reject(e);}
      });
    }
    return {owned_process_exit_observed:true,exit_code:c.exitCode,signal:c.signalCode,descendants:"UNVERIFIED",remote_effects:"UNVERIFIED"};
  }
}
