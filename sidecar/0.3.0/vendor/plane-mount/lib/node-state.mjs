import fs from "node:fs/promises";
import {constants} from "node:fs";
import path from "node:path";
import {createHash,randomUUID} from "node:crypto";
import {validateConfig,nextAudit,verifyAudit,auditHealth} from "./core.mjs";
export const hash = s => createHash("sha256").update(s,"utf8").digest("hex");
const err=code=>Object.assign(new Error(code),{code});
export async function protectedPath(p,{file=true}={}) {
  if(!["darwin","linux"].includes(process.platform))throw err("OS_ADAPTER_UNTESTED");
  if(!path.isAbsolute(p)||path.normalize(p)!==p)throw err("ABSOLUTE_CANONICAL_PATH_REQUIRED");
  const parts=[];for(let q=p;;q=path.dirname(q)){parts.push(q);if(path.dirname(q)===q)break;}
  for(const q of parts.reverse()){
    const st=await fs.lstat(q);
    if(st.isSymbolicLink()||(st.mode&0o022)!==0||![0,process.getuid()].includes(st.uid))throw err("UNPROTECTED_PATH");
    if(q!==p&&!st.isDirectory())throw err("INVALID_PARENT");
    if(q===p&&(file?!st.isFile():!st.isDirectory()))throw err("INVALID_FILE_TYPE");
  }
}
export async function loadPinnedConfig(filename,pin) {
  if(!/^[a-f0-9]{64}$/.test(pin))throw err("CONFIG_PIN_REQUIRED");
  await protectedPath(filename);
  const handle=await fs.open(filename,constants.O_RDONLY|constants.O_NOFOLLOW);
  try {
    const st=await handle.stat();
    if(!st.isFile()||st.size>131072||(st.mode&0o022)!==0||![0,process.getuid()].includes(st.uid))throw err("CONFIG_UNSAFE");
    const text=await handle.readFile("utf8");
    if(hash(text)!==pin)throw err("CONFIG_PIN_MISMATCH");
    const config=validateConfig(JSON.parse(text));
    if(path.resolve(config.state_dir)===path.dirname(filename))throw err("SEPARATE_STATE_DIRECTORY_REQUIRED");
    return config;
  }finally{await handle.close();}
}
export class Journal {
  static async open(directory) {
    await protectedPath(path.dirname(directory),{file:false});
    try {await fs.mkdir(directory,{mode:0o700});}catch(e){if(e.code!=="EEXIST")throw e;}
    await protectedPath(directory,{file:false});
    const st=await fs.stat(directory);
    if((st.mode&0o077)!==0||st.uid!==process.getuid())throw err("PRIVATE_STATE_REQUIRED");
    const j=new Journal();j.dir=directory;j.lockpath=path.join(directory,"writer.lock");
    j.lock=await fs.open(j.lockpath,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600);
    try {
      await j.lock.writeFile(JSON.stringify({pid:process.pid,id:randomUUID()})+"\n");await j.lock.sync();
      j.log=await fs.open(path.join(directory,"audit.jsonl"),constants.O_RDWR|constants.O_CREAT|constants.O_APPEND|constants.O_NOFOLLOW,0o600);
      const s=await j.log.stat();if(!s.isFile()||s.uid!==process.getuid()||(s.mode&0o077)!==0||s.size>16777216)throw err("AUDIT_UNSAFE");
      const text=await j.log.readFile("utf8");if(text&&!text.endsWith("\n"))throw err("AUDIT_TRUNCATED");
      const records=text?text.trimEnd().split("\n").map(line=>JSON.parse(line)):[];
      const verified=verifyAudit(records,hash);
      if(!auditHealth(records).ready)throw err("PRIOR_OUTCOME_UNRESOLVED");
      j.previous=verified.previous;j.position=verified.position;j.bytes=s.size;
      return j;
    }catch(e){await j.log?.close();await j.lock.close();await fs.unlink(j.lockpath);throw e;}
  }
  async append(event) {
    if(this.broken)throw err("AUDIT_UNAVAILABLE");
    const rec=nextAudit(this.previous,this.position+1,event,randomUUID(),new Date().toISOString(),hash);
    const text=JSON.stringify(rec)+"\n";
    if(this.bytes+Buffer.byteLength(text)>16777216)throw err("AUDIT_CAPACITY_REACHED");
    try {await this.log.writeFile(text);await this.log.sync();}
    catch(e){this.broken=true;throw err("AUDIT_WRITE_FAILED");}
    this.previous=rec.hash;this.position=rec.chain_position;this.bytes+=Buffer.byteLength(text);
    return {id:rec.id,hash:rec.hash,chain_position:rec.chain_position};
  }
  async close(){await this.log?.close();await this.lock?.close();await fs.unlink(this.lockpath);}
}

export async function inspectJournal(directory) {
  const p=path.join(directory,"audit.jsonl");
  await protectedPath(p);
  const st=await fs.stat(p);
  if(st.size>16777216||(st.mode&0o077)!==0)throw err("AUDIT_UNSAFE");
  const f=await fs.open(p,constants.O_RDONLY|constants.O_NOFOLLOW);
  try{
    const text=await f.readFile("utf8");if(text&&!text.endsWith("\n"))throw err("AUDIT_TRUNCATED");
    const records=text?text.trimEnd().split("\n").map(x=>JSON.parse(x)):[];
    return {chain:verifyAudit(records,hash),health:auditHealth(records),authenticated:false};
  }finally{await f.close();}
}
