export async function runCoreTests(api,manifest,registrySource,registryHash,hash){
 const rows=[],assert=(x,m="assertion")=>{if(!x)throw new Error(m);};
 const same=(a,b)=>assert(JSON.stringify(a)===JSON.stringify(b));
 const test=(name,fn)=>{try{fn();rows.push({name,pass:true});}catch(e){rows.push({name,pass:false,error:e.message});}};
 const rejects=(fn,code)=>{try{fn();}catch(e){assert(e.code===code,"unexpected "+e.code);return;}throw new Error("not rejected");};
 const copy=x=>JSON.parse(JSON.stringify(x));
 for(const args of [[],["daily","extra"],["eval"],["install"],["--help"],["status;id"]])
  test("closed command surface rejects "+JSON.stringify(args),()=>rejects(()=>api.modeFromArgs(args),"MODE_NOT_ALLOWED"));
 for(const mode of ["status","daily","weekly"])test("fixed mode "+mode,()=>same(api.modeFromArgs([mode]),mode));
 test("real package manifest accepted",()=>assert(api.validateManifest(manifest)===manifest));
 for(const bad of ["/absolute","../escape","sub/../escape","sub//file","C:/file","sub\\file","sub/\0file","./file"]){
  test("manifest rejects unsafe path "+JSON.stringify(bad),()=>{const m=copy(manifest);m.entries[0].path=bad;rejects(()=>api.validateManifest(m),"MANIFEST_ENTRY_INVALID");});
 }
 test("duplicate manifest path refused",()=>{const m=copy(manifest);m.entries[1].path=m.entries[0].path;rejects(()=>api.validateManifest(m),"MANIFEST_ENTRY_INVALID");});
 test("oversized manifest file refused",()=>{const m=copy(manifest);m.entries[0].bytes=1048577;rejects(()=>api.validateManifest(m),"MANIFEST_ENTRY_INVALID");});
 test("different package version refused",()=>rejects(()=>api.validateManifest({...manifest,version:"0.4.0"}),"MANIFEST_INVALID"));
 test("missing payload list refused",()=>rejects(()=>api.validateManifest({...manifest,entries:[]}),"MANIFEST_INVALID"));
 for(const version of ["v20.18.0","22.1.0","v22","garbage"])
  test("unsupported Node "+version,()=>rejects(()=>api.runtimeMajor(version),"NODE_VERSION_UNSUPPORTED"));
 test("supported Node syntax",()=>same(api.runtimeMajor("v22.12.0"),22));
 test("daily and weekly calendar times are explicit",()=>same(api.cadence("daily-plus-weekly").jobs.map(x=>x.calendar),[{Hour:9,Minute:0},{Weekday:0,Hour:9,Minute:30}]));
 test("weekly-only cannot accidentally add a daily job",()=>same(api.cadence("weekly").jobs.map(x=>x.mode),["weekly"]));
 test("daily-only cannot accidentally add a weekly job",()=>same(api.cadence("daily").jobs.map(x=>x.mode),["daily"]));
 test("arbitrary schedule refused",()=>rejects(()=>api.cadence("* * * * *"),"CADENCE_INVALID"));
 test("registry drift stops patch",()=>rejects(()=>api.patchRegistry(registrySource+" ",registryHash,hash,"/verified/node"),"HOST_SOURCE_DRIFT"));
 test("registry patch preserves everything outside one allowlist insertion",()=>{
  const out=api.patchRegistry(registrySource,registryHash,hash,"/verified/node"),anchor="ALLOW_COMMANDS: dict[str, list[str]] = {\n";
  assert(out.startsWith(registrySource.slice(0,registrySource.indexOf(anchor)+anchor.length)));
  const rest=registrySource.slice(registrySource.indexOf(anchor)+anchor.length);
  assert(out.endsWith(rest));
  for(const n of Object.keys(api.COMMANDS))assert(out.includes(JSON.stringify(n)));
  const line=out.split("\n").find(x=>x.trimStart().startsWith('"sidecar_status":'));
  const argv=JSON.parse(line.slice(line.indexOf(":")+1).trim().slice(0,-1));
  same(argv.slice(0,2),["/usr/bin/env","-i"]);assert(!out.includes('"sidecar_exec"'));
 });
 test("registry duplicate registration refused",()=>{
  const out=api.patchRegistry(registrySource,registryHash,hash,"/verified/node");
  rejects(()=>api.patchRegistry(out,hash(out),hash,"/verified/node"),"REGISTRY_ALREADY_HAS_COMMAND");
 });
 test("ambiguous registry anchor refused",()=>{
  const source=registrySource+"\nALLOW_COMMANDS: dict[str, list[str]] = {\n}\n";
  rejects(()=>api.patchRegistry(source,hash(source),hash,"/verified/node"),"REGISTRY_ANCHOR_AMBIGUOUS");
 });
 test("daily plan has only supplied package fixtures",()=>same(api.testPlan("daily"),[["tests/run.mjs"],["--test","--test-reporter=tap","tests/node.test.mjs"]]));
 test("weekly plan adds only the fixed seeded stress runner",()=>same(api.testPlan("weekly").slice(-1),[[api.MAINTENANCE_ROOT+"/stress-runner.mjs"]]));
 test("no status command runs a fixture plan",()=>rejects(()=>api.testPlan("status"),"TEST_MODE_REQUIRED"));
 test("healthy checks do not request attention",()=>{const r=api.attentionTransition(null,{ok:true,mode:"daily"});assert(!r.attention&&!r.needs_attention);});
 test("new failure requests attention without promoting enforcement",()=>{const r=api.attentionTransition(null,{ok:false,mode:"daily",code:"TEST_FAILED"});assert(r.attention&&r.needs_attention);same(r.security_enforcement,"UNKNOWN");});
 test("unchanged failure stays recorded but does not request a new alert",()=>{const r={ok:false,mode:"daily",code:"FAILED"},p=api.attentionTransition(null,r),n=api.attentionTransition(p,r);assert(!n.attention&&n.needs_attention);});
 test("recovery produces a transition",()=>{const p=api.attentionTransition(null,{ok:false,mode:"daily",code:"FAILED"});assert(api.attentionTransition(p,{ok:true,mode:"daily"}).notify_recovery);});
 test("missing logic result cannot count as pass",()=>rejects(()=>api.summarizeTests("{}"),"LOGIC_RESULT_FAILED"));
 test("child process exit zero with incomplete test counts cannot count as pass",()=>rejects(()=>api.summarizeTests('[{"passed":1,"failed":0},{"passed":1,"failed":0}]'),"LOGIC_RESULT_FAILED"));
 test("expected logic result accepted",()=>same(api.summarizeTests('[{"passed":45,"failed":0},{"passed":29,"failed":0}]'),{passed:74,failed:0}));
 return {ok:rows.every(x=>x.pass),passed:rows.filter(x=>x.pass).length,failed:rows.filter(x=>!x.pass).length,tests:rows,environment:"PURE_LOGIC_ONLY"};
}
