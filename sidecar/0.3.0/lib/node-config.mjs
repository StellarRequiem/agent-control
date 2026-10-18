import fs from "node:fs/promises";
import {constants} from "node:fs";
import path from "node:path";
import {createPublicKey,verify} from "node:crypto";
import {protectedPath,hash} from "../vendor/plane-mount/lib/node-state.mjs";
import {validateConfig} from "../vendor/plane-mount/lib/core.mjs";
const err=c=>Object.assign(new Error(c),{code:c});
const exact=(x,keys)=>{if(!x||typeof x!=="object"||Array.isArray(x)||Object.keys(x).some(k=>!keys.includes(k)))throw err("CONFIG_FIELDS");};
export async function loadSidecarConfig(filename,pin){
  if(!/^[a-f0-9]{64}$/.test(pin))throw err("CONFIG_PIN_REQUIRED");
  await protectedPath(filename);
  const f=await fs.open(filename,constants.O_RDONLY|constants.O_NOFOLLOW);
  let bytes;
  try{const s=await f.stat();if(s.size>131072||!s.isFile()||(s.mode&0o022)!==0)throw err("CONFIG_UNSAFE");bytes=await f.readFile("utf8");}finally{await f.close();}
  if(hash(bytes)!==pin)throw err("CONFIG_PIN_MISMATCH");
  const c=JSON.parse(bytes);
  exact(c,["version","mount","socket_dir","controller_public_key","attached_session_id","codex"]);
  if(c.version!==1)throw err("CONFIG_VERSION");
  validateConfig(c.mount);
  if(c.mount.tools.some(t=>["sidecar_status","sidecar_halt","codex.turn"].includes(t.name)))throw err("RESERVED_TOOL_NAME");
  if(typeof c.socket_dir!=="string"||!path.isAbsolute(c.socket_dir)||path.normalize(c.socket_dir)!==c.socket_dir||c.socket_dir.length>75)throw err("SOCKET_DIRECTORY_INVALID");
  if(c.socket_dir===c.mount.state_dir||c.socket_dir===path.dirname(filename))throw err("SEPARATE_SOCKET_DIRECTORY_REQUIRED");
  const key=createPublicKey(c.controller_public_key);if(key.asymmetricKeyType!=="ed25519")throw err("ED25519_PUBLIC_KEY_REQUIRED");
  if(c.codex===null){
    if(typeof c.attached_session_id!=="string"||!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(c.attached_session_id))throw err("ATTACHED_SESSION_REQUIRED");
  }else{
    if(c.attached_session_id!==null)throw err("ONE_SESSION_MODE_REQUIRED");
    exact(c.codex,["command","cwd","model","env"]);
    if(!path.isAbsolute(c.codex.command)||!path.isAbsolute(c.codex.cwd)||typeof c.codex.model!=="string"||!c.codex.model||c.codex.model.length>256)throw err("CODEX_CONFIG_INVALID");
    exact(c.codex.env,["HOME","CODEX_HOME","PATH","LANG"]);
    if(!path.isAbsolute(c.codex.env.HOME)||!path.isAbsolute(c.codex.env.CODEX_HOME)||
      Object.values(c.codex.env).some(v=>typeof v!=="string"||/[\0\r\n]/.test(v)))throw err("CODEX_ENV_INVALID");
  }
  return c;
}
export function signedVerifier(publicKey){
  const key=createPublicKey(publicKey);
  if(key.asymmetricKeyType!=="ed25519")throw err("ED25519_PUBLIC_KEY_REQUIRED");
  return async envelope=>{
    exact(envelope,["payload_json","signature_base64"]);
    if(typeof envelope.payload_json!=="string"||Buffer.byteLength(envelope.payload_json)>262144||
      typeof envelope.signature_base64!=="string"||!/^[A-Za-z0-9+/]{86}==$/.test(envelope.signature_base64))throw err("SIGNATURE_ENVELOPE_INVALID");
    const signature=Buffer.from(envelope.signature_base64,"base64");
    if(signature.length!==64||!verify(null,Buffer.from(envelope.payload_json,"utf8"),key,signature))throw err("SIGNATURE_INVALID");
    // Verify the exact UTF-8 bytes first. No reserialization/canonicalization mismatch.
    return JSON.parse(envelope.payload_json);
  };
}
export async function privateSocketDirectory(directory){
  await protectedPath(path.dirname(directory),{file:false});
  try{await fs.mkdir(directory,{mode:0o700});}catch(e){if(e.code!=="EEXIST")throw e;}
  await protectedPath(directory,{file:false});
  const st=await fs.stat(directory);
  if(st.uid!==process.getuid()||(st.mode&0o077)!==0)throw err("SOCKET_DIRECTORY_NOT_PRIVATE");
}
