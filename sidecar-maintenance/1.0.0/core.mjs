export const SOURCE_MANIFEST="0146cc4413cc7a044d3c2e4bbfc538adc144a1abe1a644355345711bd37a67a4";
export const SOURCE_ROOT="/Users/llm01/warrant/handoffs/codex-sidecar-2026-10-01";
export const OPERATOR_ROOT="/Users/llm01";
export const HOST_ROOT=OPERATOR_ROOT+"/agent-control";
export const INSTALL_ROOT=HOST_ROOT+"/sidecar/0.3.0";
export const MAINTENANCE_ROOT=HOST_ROOT+"/sidecar-maintenance/1.0.0";
export const STATE_ROOT=HOST_ROOT+"/sidecar-maintenance-state";
export const REGISTRY_PATH=HOST_ROOT+"/host/shell_handlers.py";
export const MODES=Object.freeze(["status","daily","weekly"]);
export const COMMANDS=Object.freeze({sidecar_status:"status",sidecar_test_daily:"daily",sidecar_test_weekly:"weekly"});
const bad=code=>Object.assign(new Error(code),{code});
export function modeFromArgs(args){
 if(!Array.isArray(args)||args.length!==1||!MODES.includes(args[0]))throw bad("MODE_NOT_ALLOWED");
 return args[0];
}
export function validateManifest(m){
 if(!m||m.package!=="operator-codex-sidecar"||m.version!=="0.3.0"||!Array.isArray(m.entries)||m.entries.length!==32)throw bad("MANIFEST_INVALID");
 const seen=new Set();
 for(const e of m.entries){
  if(!e||typeof e.path!=="string"||e.path.length>200||e.path.startsWith("/")||/[:\\\0\r\n]/.test(e.path)||
    e.path.split("/").some(x=>!x||x==="."||x==="..")||seen.has(e.path)||
    !/^[a-f0-9]{64}$/.test(e.sha256)||!Number.isSafeInteger(e.bytes)||e.bytes<1||e.bytes>1048576)throw bad("MANIFEST_ENTRY_INVALID");
  seen.add(e.path);
 }
 for(const p of ["package.json","lib/supervisor.mjs","lib/runtime.mjs","tests/run.mjs","tests/node.test.mjs"])if(!seen.has(p))throw bad("MANIFEST_REQUIRED_FILE_MISSING");
 return m;
}
export function runtimeMajor(version){
 const match=/^v([0-9]+)\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$/.exec(version);
 if(!match||Number(match[1])<22)throw bad("NODE_VERSION_UNSUPPORTED");
 return Number(match[1]);
}
export function cadence(name){
 if(!["daily-plus-weekly","daily","weekly"].includes(name))throw bad("CADENCE_INVALID");
 return {timezone:"America/Los_Angeles",name,jobs:[
  ...(name!=="weekly"?[{label:"local.operator.sidecar.fixtures.daily",mode:"daily",calendar:{Hour:9,Minute:0}}]:[]),
  ...(name!=="daily"?[{label:"local.operator.sidecar.fixtures.weekly",mode:"weekly",calendar:{Weekday:0,Hour:9,Minute:30}}]:[])
 ]};
}
export function patchRegistry(source,expectedHash,hash,nodePath){
 if(hash(source)!==expectedHash)throw bad("HOST_SOURCE_DRIFT");
 if(typeof nodePath!=="string"||!nodePath.startsWith("/")||/[\0\r\n]/.test(nodePath))throw bad("NODE_PATH_INVALID");
 if(Object.keys(COMMANDS).some(name=>source.includes('"'+name+'"')||source.includes("'"+name+"'")))throw bad("REGISTRY_ALREADY_HAS_COMMAND");
 const anchor="ALLOW_COMMANDS: dict[str, list[str]] = {\n";
 if(source.split(anchor).length!==2)throw bad("REGISTRY_ANCHOR_AMBIGUOUS");
 const pairs=Object.entries(COMMANDS).map(([name,mode])=>{
  const argv=["/usr/bin/env","-i","PATH=/usr/bin:/bin","LANG=C.UTF-8","HOME="+OPERATOR_ROOT,
    nodePath,MAINTENANCE_ROOT+"/maintenance.mjs",mode];
  return "    "+JSON.stringify(name)+": "+JSON.stringify(argv)+",";
 });
 const block="    # Operator sidecar maintenance: fixed argv, clean environment, pinned package only.\n"+pairs.join("\n")+"\n";
 return source.replace(anchor,anchor+block);
}
export function testPlan(mode){
 if(!["daily","weekly"].includes(mode))throw bad("TEST_MODE_REQUIRED");
 // Every command is fixed here; neither chat nor a job file can supply code or argv.
 return mode==="daily"?
  [["tests/run.mjs"],["--test","--test-reporter=tap","tests/node.test.mjs"]]:
  [["tests/run.mjs"],["--test","--test-reporter=tap","tests/node.test.mjs"],[MAINTENANCE_ROOT+"/stress-runner.mjs"]];
}
export function attentionTransition(previous,result){
 const fingerprint=JSON.stringify({ok:result.ok===true,code:result.code??null,mode:result.mode});
 const changed=previous?.fingerprint!==fingerprint;
 return {fingerprint,needs_attention:result.ok!==true,attention:result.ok!==true&&changed,notify_recovery:result.ok===true&&previous?.ok===false,
  reason:result.ok===true?"FIXTURES_PASS":"FIXTURES_REQUIRE_ATTENTION",ok:result.ok===true,
  security_enforcement:"UNKNOWN",real_model_sessions:0};
}
export function summarizeTests(stdout){
 let decoded;try{decoded=JSON.parse(stdout);}catch{throw bad("LOGIC_RESULT_INVALID");}
 if(!Array.isArray(decoded)||decoded.length!==2||decoded.some(x=>!Number.isInteger(x.passed)||!Number.isInteger(x.failed)||x.failed!==0)||
  decoded.reduce((n,x)=>n+x.passed,0)!==74)throw bad("LOGIC_RESULT_FAILED");
 return {passed:74,failed:0};
}
