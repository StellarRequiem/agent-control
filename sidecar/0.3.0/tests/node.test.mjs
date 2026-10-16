import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {generateKeyPairSync,sign} from "node:crypto";
import {signedVerifier} from "../lib/node-config.mjs";
import {validateControlPayload,Controller} from "../lib/controller.mjs";
import {SafetySupervisor} from "../lib/supervisor.mjs";
import {CodexStdio} from "../lib/codex-stdio.mjs";
import {CodexSessions} from "../lib/codex-sessions.mjs";
import {listenFrames,requestSocket} from "../lib/sockets.mjs";
const parent=path.dirname(fileURLToPath(import.meta.url));
async function directory(t){
  const dir=await fs.mkdtemp(path.join(parent,".node-fixture-"));await fs.chmod(dir,0o700);
  t.after(async()=>{await fs.rm(dir,{recursive:true,force:true});});return dir;
}
test("Ed25519 exact-byte envelope: accepts signed bytes, rejects tampering and wrong signer",async()=>{
  const {publicKey,privateKey}=generateKeyPairSync("ed25519");
  const verify=signedVerifier(publicKey.export({type:"spki",format:"pem"}));
  const payload_json=JSON.stringify({schema:1,purpose:"codex-sidecar-control",id:"test-cmd",boot_id:"test-boot",
    config_sha256:"a".repeat(64),expires_at_ms:2000,action:"prepare",params:{}});
  const envelope={payload_json,signature_base64:sign(null,Buffer.from(payload_json),privateKey).toString("base64")};
  const p=await verify(envelope);validateControlPayload(p,{bootId:"test-boot",configHash:"a".repeat(64),now:1000});
  await assert.rejects(()=>verify({...envelope,payload_json:payload_json+" "}),{code:"SIGNATURE_INVALID"});
  const wrong=generateKeyPairSync("ed25519").privateKey;
  await assert.rejects(()=>verify({...envelope,signature_base64:sign(null,Buffer.from(payload_json),wrong).toString("base64")}),{code:"SIGNATURE_INVALID"});
  assert.throws(()=>validateControlPayload(p,{bootId:"different-boot",configHash:"a".repeat(64),now:1000}),{code:"CONTROL_BINDING_INVALID"});
});
test("separate local socket delivers halt while an action promise is unresolved",{timeout:10000},async t=>{
  const dir=await directory(t),socketPath=path.join(dir,"c.sock");let release,entered;
  const pending=new Promise(r=>{release=r;}),started=new Promise(r=>{entered=r;});let seq=0;
  const audit={append:async()=>({id:"r"+(++seq)})};
  const s=new SafetySupervisor({audit,authorize:async()=>({allowed:true}),execute:async op=>{op.guard();entered();await pending;return {ok:true};},
    interrupt:async()=>({acknowledged:true}),clock:()=>1,makeId:()=>"id"+(++seq),configHash:"a".repeat(64),bootId:"fixture-boot"});
  await s.arm({valid:true,id:"proof",boot_id:"fixture-boot",config_sha256:"a".repeat(64),native_routes_denied:true,scope_isolation_verified:true,ttl_ms:10000},async x=>x);
  const binding=await s.grant({session:"fixture-session",actor:"codex",tools:["fixture.read"]});
  const c=new Controller({supervisor:s,verify:async()=>{throw new Error("unused");},sessionId:"fixture-session",config:{},audit});
  const server=await listenFrames(socketPath,()=>request=>c.handle(request));
  t.after(()=>server.close());t.after(()=>release());
  const action=s.dispatch(binding,"fixture.read",{});await started;
  const response=await requestSocket(socketPath,{command:"halt"},{timeoutMs:1000});
  assert.equal(response.supervisor.mode,"HALTED");assert.equal(response.supervisor.admission_open,false);
  release();assert.equal((await action).ok,false);
});
test("owned fake app-server exercises headerless stdio, interrupt notification and observed parent exit",{timeout:10000},async t=>{
  const dir=await directory(t);
  const fixture=String.raw`let buf="";
process.stdin.setEncoding("utf8");
process.stdin.on("data",chunk=>{
 buf+=chunk;let at;
 while((at=buf.indexOf("\n"))>=0){
  const m=JSON.parse(buf.slice(0,at));buf=buf.slice(at+1);
  if(m.jsonrpc){process.exit(3);return;}
  if(!Object.hasOwn(m,"id"))continue;
  let result={};
  if(m.method==="initialize")result={userAgent:"fixture-only"};
  else if(m.method==="thread/start")result={thread:{id:"fixture-thread",sessionId:"fixture-thread"}};
  else if(m.method==="thread/read")result={thread:{id:"fixture-thread",turns:[]}};
  else if(m.method==="turn/start")result={turn:{id:"fixture-turn",status:"inProgress"}};
  else if(m.method!=="turn/interrupt"){process.exit(4);return;}
  process.stdout.write(JSON.stringify({id:m.id,result})+"\n");
  if(m.method==="turn/interrupt")process.stdout.write(JSON.stringify({method:"turn/completed",params:{threadId:"fixture-thread",turn:{id:"fixture-turn",status:"interrupted"}}})+"\n");
 }
});
`;
  await fs.writeFile(path.join(dir,"app-server"),fixture,{mode:0o600});
  const rpc=new CodexStdio({command:process.execPath,cwd:dir,env:{PATH:"/usr/bin:/bin"},timeoutMs:2000});
  t.after(()=>rpc.stopOwned());let completed;
  const completion=new Promise(r=>{completed=r;});
  const sessions=new CodexSessions({rpc,onEvent:m=>{if(m.method==="turn/completed")completed();}});
  rpc.start();await sessions.initialize();
  const prepared=await sessions.prepare({model:"fixture-model",cwd:dir});
  await sessions.start(prepared.thread_id,"fixture task",()=>{});
  const halted=await sessions.halt();assert.equal(halted.physical_stop,"UNVERIFIED");
  await completion;assert.equal(sessions.status().threads[0].completed[0].status,"interrupted");
  await assert.rejects(()=>rpc.request("thread/shellCommand",{}),{code:"CODEX_METHOD_DENIED"});
  const stopped=await rpc.stopOwned();assert.equal(stopped.owned_process_exit_observed,true);assert.equal(stopped.descendants,"UNVERIFIED");
});
