// Wrap an existing Mount without exposing its recovery methods to candidate tools.
export class SerialAudit {
  constructor(inner){this.inner=inner;this.tail=Promise.resolve();this.broken=false;this.queued=0;}
  append(event){
    if(this.queued>=2048){this.broken=true;return Promise.reject(Object.assign(new Error("AUDIT_QUEUE_LIMIT"),{code:"AUDIT_QUEUE_LIMIT"}));}
    this.queued++;
    const job=this.tail.then(()=>{if(this.broken)throw Object.assign(new Error("AUDIT_UNAVAILABLE"),{code:"AUDIT_UNAVAILABLE"});return this.inner.append(event);});
    this.tail=job.catch(()=>{this.broken=true;});
    return job.finally(()=>{this.queued--;});
  }
}
const err=c=>Object.assign(new Error(c),{code:c});
const empty={type:"object",properties:{},required:[],additionalProperties:false};
export function guardedBackend(backend){
  let preflight=false,current=null;
  return {
    adapter:{
      initialize:()=>backend.initialize(),list:()=>backend.list(),
      call:(name,args)=>{
        if(preflight){if(name!=="plane_status")throw err("PREFLIGHT_READ_ONLY");}
        else {if(!current)throw err("FINAL_GUARD_MISSING");current.guard();}
        // No await between final guard and submission to the actual adapter.
        return backend.call(name,args);
      },
      canReconnect:()=>false,reconnect:()=>{throw err("RECOVERY_NOT_EXPOSED");}
    },
    async start(mount){if(preflight||current)throw err("BRIDGE_BUSY");preflight=true;try{return await mount.start();}finally{preflight=false;}},
    async execute(mount,op){
      if(preflight||current)throw err("BRIDGE_BUSY");current=op;
      try{
        op.guard();
        op.setCancel(async()=>{await backend.stop();return {acknowledged:true,scope:"OWNED_ADAPTER_ONLY",remote_effects:"UNVERIFIED"};});
        return await mount.call(op.tool,op.args);
      }finally{current=null;}
    }
  };
}
export function candidateView({supervisor,config,getBinding}){
  const allowed=config.tools.map(({name,description,inputSchema})=>({name,description,inputSchema}));
  if(allowed.some(t=>["sidecar_status","sidecar_halt","codex.turn"].includes(t.name)))throw err("RESERVED_TOOL_NAME");
  return {
    inventory:()=>[
      {name:"sidecar_status",description:"Read local admission and uncertainty state.",inputSchema:empty},
      {name:"sidecar_halt",description:"Revoke this sidecar's task permits. Does not claim all running effects stopped.",inputSchema:empty},
      ...allowed
    ],
    async call(name,args={}){
      if(["sidecar_status","sidecar_halt"].includes(name)){
        if(!args||typeof args!=="object"||Array.isArray(args)||Object.keys(args).length)return {ok:false,code:"ARGUMENT_FIELDS",executed:false};
        return {ok:true,data:name==="sidecar_status"?supervisor.status():supervisor.halt("CANDIDATE_HALT")};
      }
      if(!allowed.some(t=>t.name===name))return {ok:false,code:"TOOL_NOT_EXPOSED",executed:false};
      return supervisor.dispatch(getBinding(),name,args);
    }
  };
}
