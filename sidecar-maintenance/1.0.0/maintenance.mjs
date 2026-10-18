import fs from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {randomUUID} from "node:crypto";
import {SOURCE_MANIFEST,INSTALL_ROOT,MAINTENANCE_ROOT,STATE_ROOT,OPERATOR_ROOT,modeFromArgs,validateManifest,
 runtimeMajor,cadence,testPlan,attentionTransition,summarizeTests} from "./core.mjs";
import {protectedFile,hash,privateDir,atomicJson,exclusiveText,binaryHash,runFixed,fail} from "./io.mjs";
const CONFIG=MAINTENANCE_ROOT+"/installed.json";
async function readOptional(name){
 try{return JSON.parse((await protectedFile(STATE_ROOT+"/"+name)).toString("utf8"));}
 catch(e){if(e.code==="ENOENT")return null;throw e;}
}
async function verifyInstalled(){
 const c=JSON.parse((await protectedFile(CONFIG)).toString("utf8"));
 if(c.version!==1||c.node!==process.execPath||c.package_manifest!==SOURCE_MANIFEST||
   !/^[a-f0-9]{64}$/.test(c.node_sha256??"")||!Array.isArray(c.maintenance_files)||c.maintenance_files.length!==6)throw fail("INSTALL_RECORD_INVALID");
 runtimeMajor(process.version);
 if(await binaryHash(process.execPath)!==c.node_sha256)throw fail("NODE_BINARY_DRIFT");
 if(JSON.stringify(c.schedule)!==JSON.stringify(cadence(c.schedule?.name)))throw fail("INSTALL_SCHEDULE_INVALID");
 const required=new Set(["core.mjs","io.mjs","maintenance.mjs","stress.mjs","stress-runner.mjs","selftest.mjs"]);
 for(const entry of c.maintenance_files){
  if(!entry||!required.delete(entry.path)||!/^[a-f0-9]{64}$/.test(entry.sha256)||!Number.isSafeInteger(entry.bytes)||entry.bytes<1||entry.bytes>1048576)throw fail("INSTALL_RECORD_INVALID");
  const payload=await protectedFile(MAINTENANCE_ROOT+"/"+entry.path);
  if(payload.length!==entry.bytes||hash(payload)!==entry.sha256)throw fail("MAINTENANCE_CODE_DRIFT");
 }
 const manifestBytes=await protectedFile(INSTALL_ROOT+"/MANIFEST.json");
 if(hash(manifestBytes)!==SOURCE_MANIFEST)throw fail("PACKAGE_MANIFEST_DRIFT");
 const manifest=validateManifest(JSON.parse(manifestBytes.toString("utf8")));
 for(const e of manifest.entries){
  const b=await protectedFile(INSTALL_ROOT+"/"+e.path);
  if(b.length!==e.bytes||hash(b)!==e.sha256)throw fail("PACKAGE_FILE_DRIFT");
 }
 return c;
}
export async function maintenance(mode,{bootstrap=false}={}){
 const c=await verifyInstalled();
 const base={version:"1.0.0",package_version:"0.3.0",installed:true,node:process.version,package_integrity:"MATCH",
  runtime_enforcement:"UNKNOWN",sidecar_action_mediation:"NOT_ESTABLISHED",sidecar_service:"NOT_OBSERVED",admission:"UNKNOWN",
  real_model_sessions:0,scope:"FIXED_FIXTURE_MAINTENANCE_ONLY"};
 await privateDir(STATE_ROOT);
 if(mode==="status"){
  const last=await readOptional("latest.json"),attention={daily:await readOptional("attention-daily.json"),weekly:await readOptional("attention-weekly.json")},activation=await readOptional("activation.json");
  const schedules=[];
  for(const job of c.schedule.jobs){
   const out=await runFixed("/bin/launchctl",["print","gui/"+process.getuid()+"/"+job.label],
    {cwd:MAINTENANCE_ROOT,env:{PATH:"/usr/bin:/bin",LANG:"C.UTF-8"},timeoutMs:5000,maxBytes:40000});
   schedules.push({label:job.label,loaded:out.ok,exit_code:out.exit_code,calendar:job.calendar});
  }
  return {ok:true,...base,last_result:last,attention,activation,schedules,uncertain:await readOptional("UNCERTAIN.json")};
 }
 if(!["daily","weekly"].includes(mode))throw fail("MODE_NOT_ALLOWED");
 const activation=await readOptional("activation.json");
 if(!bootstrap&&activation?.ready!==true)throw fail("MAINTENANCE_NOT_ACTIVATED");
 if(await readOptional("UNCERTAIN.json"))throw fail("PRIOR_JOB_OUTCOME_UNKNOWN");
 const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;
 if(!["America/Los_Angeles","US/Pacific"].includes(timezone))throw fail("SCHEDULE_TIMEZONE_CHANGED");
 const runId=randomUUID(),lock=STATE_ROOT+"/run.lock";
 try{await exclusiveText(lock,JSON.stringify({run_id:runId,pid:process.pid,started:new Date().toISOString()})+"\n");}
 catch(e){if(e.code==="EEXIST")return {ok:false,...base,code:"JOB_ALREADY_RUNNING_OR_UNRECONCILED",skipped:true};throw e;}
 const started=Date.now(),steps=[];let outcome;
 try{
  for(const argv of testPlan(mode)){
   const remaining=90000-(Date.now()-started);
   if(remaining<1000)throw fail("TOTAL_JOB_BUDGET_EXHAUSTED");
   const result=await runFixed(c.node,argv,{cwd:INSTALL_ROOT,
    env:{PATH:"/usr/bin:/bin",LANG:"C.UTF-8",HOME:OPERATOR_ROOT},
    timeoutMs:Math.min(30000,remaining),maxBytes:100000,group:true});
   const detail={argv,ok:result.ok,exit_code:result.exit_code,signal:result.signal,fault:result.fault,
    stdout_sha256:hash(result.stdout),stderr_sha256:hash(result.stderr),stderr_tail:result.stderr.slice(-1000),
    parent_exit_observed:result.parent_exit_observed,descendants:result.descendants};
   steps.push(detail);
   if(result.fault)await atomicJson(STATE_ROOT+"/UNCERTAIN.json",{run_id:runId,reason:result.fault,operator_reconciliation_required:true});
   if(!result.ok){throw fail(result.fault||"FIXTURE_PROCESS_FAILED");}
   if(argv[0]==="tests/run.mjs")detail.logic=summarizeTests(result.stdout);
   else if(argv[0]==="--test"){
    if(!/# tests 3(?:\r?\n|$)/.test(result.stdout)||!/# pass 3(?:\r?\n|$)/.test(result.stdout)||!/# fail 0(?:\r?\n|$)/.test(result.stdout))throw fail("NODE_TEST_RESULT_INCOMPLETE");
    detail.node_fixtures={passed:3,failed:0};
   }else{
    let report;try{report=JSON.parse(result.stdout);}catch{throw fail("STRESS_RESULT_INVALID");}
    if(report.ok!==true||report.fixture_traces!==128||report.real_model_sessions!==0||report.live_effects!==0)throw fail("STRESS_RESULT_INCOMPLETE");
    detail.stress={fixture_traces:report.fixture_traces,assertions:report.assertions,real_model_sessions:0};
   }
  }
  outcome={ok:true,...base,run_id:runId,mode,code:"FIXTURES_PASS",steps,finished:new Date().toISOString(),duration_ms:Date.now()-started};
 }catch(e){
  if(e.code==="JOB_TERMINATION_UNVERIFIED")await atomicJson(STATE_ROOT+"/UNCERTAIN.json",{run_id:runId,reason:e.code,operator_reconciliation_required:true});
  outcome={ok:false,...base,run_id:runId,mode,code:e.code||"FIXTURE_CHECK_FAILED",steps,finished:new Date().toISOString(),duration_ms:Date.now()-started};
 }

 const previous=await readOptional("attention-"+mode+".json"),attention=attentionTransition(previous,outcome);
 await privateDir(STATE_ROOT+"/runs");
 await exclusiveText(STATE_ROOT+"/runs/"+runId+".json",JSON.stringify(outcome,null,2)+"\n");
 await atomicJson(STATE_ROOT+"/latest.json",outcome);
 await atomicJson(STATE_ROOT+"/attention-"+mode+".json",{...attention,run_id:runId,mode,recorded:new Date().toISOString(),delivery:"LOCAL_STATUS_ONLY_NO_CHAT_CONNECTOR"});
 // Release only after result and attention state are durable. Failed persistence leaves a reconciliation lock.
 const current=JSON.parse((await protectedFile(lock)).toString("utf8"));
 if(current.run_id!==runId)throw fail("RUN_LOCK_RECONCILIATION_REQUIRED");
 await fs.unlink(lock);
 return outcome;
}
const invoked=process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url;
if(invoked){
 try{
  const mode=modeFromArgs(process.argv.slice(2)),result=await maintenance(mode);
  process.stdout.write(JSON.stringify(result)+"\n");process.exitCode=result.ok?0:1;
 }catch(e){process.stderr.write(JSON.stringify({ok:false,code:e.code||"MAINTENANCE_FAILED",runtime_enforcement:"UNKNOWN"})+"\n");process.exitCode=1;}
}
