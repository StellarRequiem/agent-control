import {randomUUID} from "node:crypto";
import {performance} from "node:perf_hooks";
import path from "node:path";
import {Mount,handleRpc,validate} from "../vendor/plane-mount/lib/core.mjs";
import {StdioBackend} from "../vendor/plane-mount/lib/backend.mjs";
import {Journal,hash} from "../vendor/plane-mount/lib/node-state.mjs";
import {SafetySupervisor} from "./supervisor.mjs";
import {CodexSessions} from "./codex-sessions.mjs";
import {CodexStdio} from "./codex-stdio.mjs";
import {Controller} from "./controller.mjs";
import {SerialAudit,guardedBackend,candidateView} from "./bridge.mjs";
import {loadSidecarConfig,signedVerifier,privateSocketDirectory} from "./node-config.mjs";
import {listenFrames} from "./sockets.mjs";
const err=c=>Object.assign(new Error(c),{code:c});
export async function serve({configPath,configHash}){
  const config=await loadSidecarConfig(configPath,configHash);
  await privateSocketDirectory(config.socket_dir);
  const journal=await Journal.open(config.mount.state_dir);
  const audit=new SerialAudit(journal),backend=new StdioBackend(config.mount.backend),bridge=guardedBackend(backend);
  let supervisor,sessions,rpc,binding=null,controller,actionServer,controlServer,watchdog,closing=false;
  const readConfig=()=>loadSidecarConfig(configPath,configHash);
  const mount=new Mount({config:config.mount,loadConfig:async()=> (await readConfig()).mount,backend:bridge.adapter,audit,hash});
  const diagnostic={backend_ready:false,owned_process_stop:null};
  supervisor=new SafetySupervisor({
    audit,clock:()=>performance.now(),makeId:randomUUID,configHash,bootId:randomUUID(),maxConcurrent:1,
    authorize:async({tool,args})=>{
      await readConfig();
      if(tool==="codex.turn"){
        if(!sessions||typeof args.prompt!=="string"||!args.prompt||args.prompt.length>100000)return {allowed:false,code:"TURN_INVALID"};
      }else{
        const t=config.mount.tools.find(t=>t.name===tool);if(!t)return {allowed:false,code:"TOOL_NOT_CONFIGURED"};
        validate(t.inputSchema,args);
      }
      return {allowed:true}; // Admission only: Mount and host plane still authorize the actual effect.
    },
    execute:async op=>{
      if(op.tool==="codex.turn"){
        op.guard();
        const data=await sessions.start(controller.sessionId,op.args.prompt,op.guard);
        return {ok:true,data};
      }
      return bridge.execute(mount,op);
    },
    interrupt:async()=>sessions?await sessions.halt():{acknowledged:false,code:"ATTACHED_RUNTIME_HAS_NO_INTERRUPT_ADAPTER"}
  });
  if(config.codex){
    rpc=new CodexStdio({...config.codex,onFailure:code=>supervisor.halt(code)});
    sessions=new CodexSessions({rpc,onViolation:code=>supervisor.halt(code),
      onEvent:m=>{ // Record identifiers and types, not model content or credentials.
        void audit.append({kind:"sidecar",event:"codex_notification",method:m.method,thread_id:m.params?.threadId??null,
          turn_id:m.params?.turn?.id??null,status:m.params?.turn?.status??null}).catch(()=>supervisor.halt("AUDIT_UNAVAILABLE"));
      }});
  }
  controller=new Controller({
    supervisor,verify:signedVerifier(config.controller_public_key),sessions,sessionId:config.attached_session_id,config,audit,
    onGrant:b=>{binding=b;},
    onStart:prompt=>supervisor.dispatch(binding,"codex.turn",{prompt}),
    onStop:async()=>{if(!rpc)return {owned_process_exit_observed:false,code:"NO_OWNED_CODEX"};diagnostic.owned_process_stop=await rpc.stopOwned();return diagnostic.owned_process_stop;}
  });
  const view=candidateView({supervisor,config:config.mount,getBinding:()=>binding});
  const status=()=>({...controller.status(),diagnostic,clauses_fully_satisfied:false});
  const shutdown=async()=>{
    if(closing)return;closing=true;supervisor.halt("SUPERVISOR_SHUTDOWN");clearInterval(watchdog);
    const stopped=await Promise.allSettled([backend.stop(),rpc?.stopOwned(),actionServer?.close(),controlServer?.close()]);
    // An unresolved operation must leave the writer lock and journal intact for reconciliation.
    if(stopped.some(x=>x.status==="rejected")||supervisor.active.size)throw err("SHUTDOWN_UNRESOLVED");
    await audit.tail;await journal.close();
  };
  try{
    controlServer=await listenFrames(path.join(config.socket_dir,"control.sock"),()=>async request=>{
      if(request?.command==="status")return {ok:true,data:status()};
      if(request?.command!=="halt"&&(!diagnostic.backend_ready||(sessions&&!sessions.ready)))return {ok:false,code:"STARTUP_HELD"};
      try{return {ok:true,data:await controller.handle(request)};}catch(e){return {ok:false,code:e.code||"CONTROL_FAILED"};}
    });
    actionServer=await listenFrames(path.join(config.socket_dir,"actions.sock"),()=>{
      const session={ready:false,negotiated:false};
      return async message=>{const response=await handleRpc(view,message,session);if(message?.method==="initialize"&&response?.result?.serverInfo)response.result.serverInfo={name:"codex-sidecar",version:"0.3.0"};return response;};
    },{single:true,onDisconnect:()=>supervisor.halt("CANDIDATE_TRANSPORT_DISCONNECTED")});
    watchdog=setInterval(()=>supervisor.tick(),100);
    // Read-only identity preflight. No model tools admitted; startup remains HELD.
    await bridge.start(mount);diagnostic.backend_ready=true;
    if(rpc){rpc.start();await sessions.initialize();}
    const signal=()=>{void shutdown().catch(e=>{process.stderr.write(JSON.stringify({ok:false,code:e.code||"SHUTDOWN_FAILED"})+"\n");process.exitCode=1;});};
    process.once("SIGINT",signal);process.once("SIGTERM",signal);
    return {status,shutdown};
  }catch(e){supervisor.halt(e.code||"STARTUP_FAILED");try{await shutdown();}catch{}throw e;}
}
