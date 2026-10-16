import {INSTALL_ROOT} from "./core.mjs";
import {runStress} from "./stress.mjs";
import {pathToFileURL} from "node:url";
const {SafetySupervisor}=await import(pathToFileURL(INSTALL_ROOT+"/lib/supervisor.mjs").href);
const result=await runStress(SafetySupervisor);
process.stdout.write(JSON.stringify(result)+"\n");
process.exitCode=result.ok?0:1;
