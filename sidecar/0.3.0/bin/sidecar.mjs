#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import net from "node:net";
import {serve} from "../lib/runtime.mjs";
import {requestSocket} from "../lib/sockets.mjs";
import {protectedPath} from "../vendor/plane-mount/lib/node-state.mjs";
const fail=c=>Object.assign(new Error(c),{code:c});
function parse(argv){
  const mode=argv.shift(),opts={};
  if(!["serve","status","halt","signed","mcp-proxy"].includes(mode))throw fail("USAGE_REQUIRED");
  for(let i=0;i<argv.length;i+=2){
    const k=argv[i];if(!["--config","--sha256","--socket","--envelope"].includes(k)||opts[k]||!argv[i+1])throw fail("OPTION_INVALID");
    opts[k]=argv[i+1];
  }
  const expected=mode==="serve"?["--config","--sha256"]:mode==="signed"?["--socket","--envelope"]:["--socket"];
  if(Object.keys(opts).length!==expected.length||expected.some(k=>!opts[k]))throw fail("OPTION_INVALID");
  return {mode,opts};
}
async function checkedSocket(p){
  if(!path.isAbsolute(p)||path.normalize(p)!==p)throw fail("SOCKET_PATH_INVALID");
  await protectedPath(path.dirname(p),{file:false});
  const parent=await fs.stat(path.dirname(p)),st=await fs.lstat(p);
  if(parent.uid!==process.getuid()||(parent.mode&0o077)!==0||!st.isSocket()||st.uid!==process.getuid()||(st.mode&0o077)!==0)throw fail("SOCKET_NOT_PRIVATE");
}
try{
  const {mode,opts}=parse(process.argv.slice(2));
  if(mode==="serve"){
    const daemon=await serve({configPath:opts["--config"],configHash:opts["--sha256"]});
    process.stdout.write(JSON.stringify({ok:true,data:daemon.status()})+"\n");
  }else{
    const socketPath=opts["--socket"];await checkedSocket(socketPath);
    if(mode==="mcp-proxy"){
      // Byte transport only. The daemon parses, authenticates the mount and gates every action.
      const socket=net.createConnection(socketPath);
      socket.on("error",e=>{process.stderr.write(JSON.stringify({ok:false,code:e.code||"PROXY_FAILED"})+"\n");process.exitCode=1;process.stdin.pause();});
      socket.on("connect",()=>{process.stdin.pipe(socket);socket.pipe(process.stdout);});
      socket.on("end",()=>process.stdin.pause());
      process.stdin.on("end",()=>socket.end());
      process.once("SIGTERM",()=>{socket.destroy();process.stdin.pause();});
    }else{
      let request={command:mode};
      if(mode==="signed"){
        // Signed envelope is operator input, not a private signing key. The service holds only a public key.
        await protectedPath(opts["--envelope"]);
        const st=await fs.stat(opts["--envelope"]);if(st.size>524288)throw fail("ENVELOPE_LIMIT");
        request={command:"signed",envelope:JSON.parse(await fs.readFile(opts["--envelope"],"utf8"))};
      }
      const result=await requestSocket(socketPath,request,{timeoutMs:mode==="halt"?5000:120000});
      process.stdout.write(JSON.stringify(result,null,2)+"\n");process.exitCode=result.ok===false?1:0;
    }
  }
}catch(e){
  process.stderr.write(JSON.stringify({ok:false,code:e.code||"SIDECAR_FAILED",detail:String(e.message).slice(0,200)})+"\n");
  process.exitCode=1;
}
