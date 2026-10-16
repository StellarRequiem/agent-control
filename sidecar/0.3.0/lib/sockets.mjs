import net from "node:net";
import fs from "node:fs/promises";
const MAX=1048576;
const code=e=>e?.code||"REQUEST_FAILED";
export async function listenFrames(socketPath,makeHandler,{single=false,onDisconnect=()=>{}}={}){
  const clients=new Set();let st;
  // Never unlink an existing path or "recover" a socket based on a PID.
  try{await fs.lstat(socketPath);throw Object.assign(new Error("SOCKET_EXISTS"),{code:"SOCKET_EXISTS"});}catch(e){if(e.code!=="ENOENT")throw e;}
  const server=net.createServer(socket=>{
    if(clients.size>=(single?1:16)){socket.destroy();return;}
    clients.add(socket);
    let buffer=Buffer.alloc(0),pending=0;const handle=makeHandler();
    socket.setTimeout(120000,()=>socket.destroy());
    socket.on("error",()=>{});
    socket.on("close",()=>{clients.delete(socket);onDisconnect();});
    socket.on("data",chunk=>{
      buffer=Buffer.concat([buffer,chunk]);
      if(buffer.length>MAX){socket.destroy();return;}
      let at;
      while((at=buffer.indexOf(10))>=0){
        const line=buffer.subarray(0,at).toString("utf8");buffer=buffer.subarray(at+1);
        let request;try{request=JSON.parse(line);}catch{socket.end(JSON.stringify({ok:false,code:"INVALID_JSON"})+"\n");return;}
        if(++pending>16){socket.destroy();return;}
        Promise.resolve().then(()=>handle(request)).then(
          response=>{if(response!==null&&!socket.destroyed){const data=JSON.stringify(response)+"\n";if(Buffer.byteLength(data)>MAX)socket.destroy();else socket.write(data);}},
          e=>{if(!socket.destroyed)socket.write(JSON.stringify({ok:false,code:code(e)})+"\n");}
        ).finally(()=>{pending--;});
      }
    });
  });
  await new Promise((resolve,reject)=>{server.once("error",reject);server.listen(socketPath,resolve);});
  await fs.chmod(socketPath,0o600);st=await fs.lstat(socketPath);
  return {
    async close(){
      for(const s of clients)s.destroy();
      await new Promise((resolve,reject)=>server.close(e=>e?reject(e):resolve()));
      // Node may already remove its own Unix socket; never unlink a replacement.
      try{const now=await fs.lstat(socketPath);if(now.isSocket()&&now.dev===st.dev&&now.ino===st.ino)await fs.unlink(socketPath);}
      catch(e){if(e.code!=="ENOENT")throw e;}
    }
  };
}
export async function requestSocket(socketPath,request,{timeoutMs=120000}={}){
  const frame=JSON.stringify(request)+"\n";
  if(Buffer.byteLength(frame)>MAX)throw new Error("INPUT_LIMIT");
  return new Promise((resolve,reject)=>{
    const socket=net.createConnection(socketPath);let buffer=Buffer.alloc(0),done=false;
    const finish=(e,value)=>{if(done)return;done=true;socket.destroy();if(e)reject(e);else resolve(value);};
    socket.setTimeout(timeoutMs,()=>finish(new Error("CONTROL_TIMEOUT_OUTCOME_UNKNOWN")));
    socket.on("connect",()=>socket.write(frame));
    socket.on("error",e=>finish(e));
    socket.on("end",()=>finish(new Error("CONTROL_TRUNCATED_RESPONSE")));
    socket.on("data",chunk=>{
      buffer=Buffer.concat([buffer,chunk]);
      if(buffer.length>MAX)return finish(new Error("OUTPUT_LIMIT"));
      const at=buffer.indexOf(10);if(at<0)return;
      try{finish(null,JSON.parse(buffer.subarray(0,at).toString("utf8")));}catch(e){finish(e);}
    });
  });
}
