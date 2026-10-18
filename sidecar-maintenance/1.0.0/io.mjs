import fs from "node:fs/promises";
import {constants,createReadStream} from "node:fs";
import path from "node:path";
import {createHash,randomUUID} from "node:crypto";
import {spawn} from "node:child_process";
export const fail=code=>Object.assign(new Error(code),{code});
export const hash=text=>createHash("sha256").update(text).digest("hex");
export async function protectedFile(filename,max=1048576){
 if(!path.isAbsolute(filename)||path.normalize(filename)!==filename)throw fail("PATH_NOT_CANONICAL");
 const chain=[];for(let p=filename;;p=path.dirname(p)){chain.push(p);if(path.dirname(p)===p)break;}
 for(const p of chain.reverse()){
  const st=await fs.lstat(p);
  if(st.isSymbolicLink()||![0,process.getuid()].includes(st.uid)||(st.mode&0o022)!==0)throw fail("PATH_NOT_PROTECTED");
  if(p!==filename&&!st.isDirectory())throw fail("PARENT_NOT_DIRECTORY");
 }
 const f=await fs.open(filename,constants.O_RDONLY|constants.O_NOFOLLOW);
 try{const st=await f.stat();if(!st.isFile()||st.nlink!==1||st.size>max)throw fail("FILE_NOT_SAFE");return await f.readFile();}
 finally{await f.close();}
}
export async function privateDir(directory,{exclusive=false}={}){
 if(!path.isAbsolute(directory)||path.normalize(directory)!==directory)throw fail("PATH_NOT_CANONICAL");
 const parent=path.dirname(directory),parentSt=await fs.lstat(parent);
 if(parentSt.isSymbolicLink()||!parentSt.isDirectory()||(parentSt.mode&0o022)!==0||![0,process.getuid()].includes(parentSt.uid))throw fail("PARENT_NOT_PROTECTED");
 try{await fs.mkdir(directory,{mode:0o700});}catch(e){if(exclusive||e.code!=="EEXIST")throw e;}
 const st=await fs.lstat(directory);
 if(st.isSymbolicLink()||!st.isDirectory()||st.uid!==process.getuid()||(st.mode&0o077)!==0)throw fail("DIRECTORY_NOT_PRIVATE");
}
export async function atomicJson(filename,value){
 const tmp=filename+".new-"+randomUUID(),f=await fs.open(tmp,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600);
 try{await f.writeFile(JSON.stringify(value,null,2)+"\n");await f.sync();}finally{await f.close();}
 try{const st=await fs.lstat(filename);if(st.isSymbolicLink()||!st.isFile()||st.uid!==process.getuid())throw fail("STATE_TARGET_UNSAFE");}
 catch(e){if(e.code!=="ENOENT")throw e;}
 await fs.rename(tmp,filename);
}
export async function exclusiveText(filename,text,mode=0o600){
 const f=await fs.open(filename,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,mode);
 try{await f.writeFile(text);await f.sync();}finally{await f.close();}
}
export async function binaryHash(filename){
 const h=createHash("sha256");
 for await(const chunk of createReadStream(filename))h.update(chunk);
 return h.digest("hex");
}
export async function runFixed(command,args,{cwd,env,timeoutMs=30000,maxBytes=100000,group=false}={}){
 if(!path.isAbsolute(command)||!Array.isArray(args)||args.some(x=>typeof x!=="string"||x.includes("\0")))throw fail("FIXED_COMMAND_INVALID");
 return new Promise((resolve,reject)=>{
  let total=0,stdout="",stderr="",fault=null,spawned=false;
  const c=spawn(command,args,{cwd,env,shell:false,stdio:["ignore","pipe","pipe"],detached:group});
  const stop=code=>{
   if(fault)return;fault=code;
   // Group was created by this call for this fixed test job. Never inspect or kill an unrelated PID.
   if(spawned&&c.exitCode===null&&c.signalCode===null){try{if(group)process.kill(-c.pid,"SIGTERM");else c.kill("SIGTERM");}catch{}}
  };
  const timer=setTimeout(()=>stop("JOB_TIMEOUT"),timeoutMs);
  const deadline=setTimeout(()=>{
   stop("JOB_DID_NOT_EXIT");clearTimeout(timer);c.stdout.destroy();c.stderr.destroy();c.unref();
   reject(fail("JOB_TERMINATION_UNVERIFIED"));
  },timeoutMs+4000);
  c.on("spawn",()=>{spawned=true;});
  c.stdout.on("data",b=>{total+=b.length;if(total>maxBytes)stop("JOB_OUTPUT_LIMIT");else stdout+=b.toString("utf8");});
  c.stderr.on("data",b=>{total+=b.length;if(total>maxBytes)stop("JOB_OUTPUT_LIMIT");else stderr+=b.toString("utf8");});
  c.on("error",e=>{clearTimeout(timer);clearTimeout(deadline);reject(e);});
  c.on("close",(exitCode,signal)=>{
   clearTimeout(timer);clearTimeout(deadline);
   resolve({ok:!fault&&exitCode===0,exit_code:exitCode,signal,fault,stdout,stderr,
    parent_exit_observed:true,descendants:"NOT_INDEPENDENTLY_OBSERVED"});
  });
 });
}
