import {spawn} from "node:child_process";
import {PROTOCOL} from "./core.mjs";
const err=code=>Object.assign(new Error(code),{code});
const MAX=1024*1024;
export class StdioBackend {
  constructor(config){this.config=config;this.next=1;this.pending=new Map();this.poisoned=false;this.stopping=false;this.child=null;}
  spawn(){
    if(this.child)throw err("BACKEND_ALREADY_STARTED");
    this.poisoned=false;this.stopping=false;this.buffer=Buffer.alloc(0);this.stderrBytes=0;
    const c=spawn(this.config.command,this.config.args,{
      cwd:this.config.cwd,shell:false,stdio:["pipe","pipe","pipe"],windowsHide:true,
      env:{PATH:process.env.PATH||"/usr/bin:/bin",LANG:process.env.LANG||"C.UTF-8"}
    });
    this.child=c;
    c.stdout.on("data",chunk=>{
      this.buffer=Buffer.concat([this.buffer,chunk]);
      if(this.buffer.length>MAX){this.abort("BACKEND_OUTPUT_LIMIT");return;}
      let at;
      while((at=this.buffer.indexOf(10))>=0){
        const line=this.buffer.subarray(0,at).toString("utf8");this.buffer=this.buffer.subarray(at+1);
        let msg;try{msg=JSON.parse(line);}catch{this.abort("BACKEND_PROTOCOL_ERROR");return;}
        if(msg?.jsonrpc!=="2.0"){this.abort("BACKEND_PROTOCOL_ERROR");return;}
        if(typeof msg.method==="string"){ // No sampling, elicitation, roots, or reverse client authority.
          if(msg.id!==undefined)c.stdin.write(JSON.stringify({jsonrpc:"2.0",id:msg.id,error:{code:-32601,message:"Reverse requests unsupported"}})+"\n");
          continue;
        }
        const waiter=this.pending.get(msg.id);
        if(!waiter){this.abort("BACKEND_UNEXPECTED_RESPONSE");return;}
        this.pending.delete(msg.id);clearTimeout(waiter.timer);
        if(msg.error)waiter.reject(err("BACKEND_RPC_ERROR"));else if(msg.result!==undefined)waiter.resolve(msg.result);else waiter.reject(err("BACKEND_PROTOCOL_ERROR"));
      }
    });
    c.stderr.on("data",chunk=>{this.stderrBytes+=chunk.length;if(this.stderrBytes>MAX)this.abort("BACKEND_STDERR_LIMIT");});
    c.on("error",()=>this.abort("BACKEND_SPAWN_FAILED"));
    c.on("exit",()=>{for(const w of this.pending.values()){clearTimeout(w.timer);w.reject(err("BACKEND_EXITED"));}this.pending.clear();if(!this.stopping)this.poisoned=true;});
    c.stdin.on("error",()=>this.abort("BACKEND_PIPE_FAILED"));
  }
  abort(code){
    this.poisoned=true;this.buffer=Buffer.alloc(0);this.child?.stdout.pause();this.child?.stderr.pause();
    for(const w of this.pending.values()){clearTimeout(w.timer);w.reject(err(code));}this.pending.clear();
    // Do not restart or kill after an uncertain action; operator reconciliation is required.
  }
  request(method,params={},timeout=20000){
    if(!this.child||this.poisoned||this.child.exitCode!==null||this.child.signalCode!==null)return Promise.reject(err("BACKEND_UNAVAILABLE"));
    const id=this.next++;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>this.abort("BACKEND_TIMEOUT_OUTCOME_UNKNOWN"),timeout);
      this.pending.set(id,{resolve,reject,timer});
      this.child.stdin.write(JSON.stringify({jsonrpc:"2.0",id,method,params})+"\n",e=>{if(e)this.abort("BACKEND_PIPE_FAILED");});
    });
  }
  async initialize(){
    if(!this.child)this.spawn();
    const r=await this.request("initialize",{protocolVersion:PROTOCOL,capabilities:{},clientInfo:{name:"plane-mount",version:"0.2.0"}});
    this.child.stdin.write(JSON.stringify({jsonrpc:"2.0",method:"notifications/initialized"})+"\n");
    return r;
  }
  list(){return this.request("tools/list");}
  call(name,args){return this.request("tools/call",{name,arguments:args},105000);}
  canReconnect(){return !!this.child&&!this.poisoned&&this.pending.size===0&&this.child.exitCode===null&&this.child.signalCode===null;}
  async stop(){
    const c=this.child;if(!c)return;
    this.stopping=true;
    if(c.exitCode===null&&c.signalCode===null){
      // ChildProcess handle only: no PID files, port scans, process groups, or SIGKILL escalation.
      c.kill("SIGTERM");
      await new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>{reject(err("OWNED_CHILD_DID_NOT_STOP"));},3000);
        c.once("exit",()=>{clearTimeout(timer);resolve();});
        if(c.exitCode!==null||c.signalCode!==null){clearTimeout(timer);resolve();}
      });
    }
    this.child=null;
  }
  async reconnect(){if(!this.canReconnect())throw err("RECONNECT_UNSAFE");await this.stop();this.poisoned=false;}
}
