# Host deployment and commands

This is the remaining integration work, not a claim that it was completed. The current agent-control route refuses writes under its protected installation tree and has no approved Node runner for this candidate. Do not route around those controls. The operator has already authorized the build; a host installer/runner with appropriately bounded capability is the missing mechanism.

1. Have a non-author review the candidate and manifest. Install it into a host-controlled directory unreadable for modification by candidate processes. Preserve the staged evidence package.
2. In an isolated test runtime, run `node tests/run.mjs` and `node --test tests/node.test.mjs`. These are the supplied 74 logic checks and 3 Node fixture tests. They do not count as native-dispatch enforcement checks.
3. Supply a validated receipt-bearing operator-plane MCP backend. The readable legacy Grok adapter omits actor/receipt fields and fails this mount's identity checks. The current exposed Codex plane does return those fields, but its startup adapter was not accessible in this session. Do not replace the checks with compatibility defaults.
4. Render `examples/config.template.json` with exact paths, verified model identifier and a protected Ed25519 issuer public key. The template is deliberately non-runnable. Pin the exact UTF-8 bytes with SHA-256 in the trusted launcher. Keep config, private sockets and journal in separate protected directories. Unix socket paths must remain short (directory <=75 characters). This implementation targets macOS/Linux only.
5. The independent issuer must collect real runtime version, effective tool and permission configuration, allowed authorization/execution receipt IDs, denied native-route receipt IDs and process/resource isolation evidence. Neither this service nor the model can certify its own isolation. The issuer must keep private signing material inaccessible to candidate and peer agents.
6. Choose one instance per candidate. Owned mode uses `codex` in the config and `attached_session_id: null`; it creates a fresh app-server process using the isolated HOME/CODEX_HOME. Attached mode uses `codex: null` and an externally verified actual session ID. Attached mode can block mediated actions but has no parent-runtime interrupt adapter. Do not promise it stops the desktop chat.
7. Install the MCP snippet into the isolated Codex configuration before preparing a model. Independently deny native and unrelated tools, direct resource access, alternative connections to the plane, peer sockets and controller files. No unsupported "disable all tools" switch is invented here.
8. Start the supervisor through the protected host launcher. Startup reads plane status for backend identity; action admission remains HELD. Configured app-server initialization creates a process but starts no turn.
9. Read status and obtain its boot ID and configuration pin. In owned mode, send a signed `prepare` command. It requests a new root thread and verifies returned history is empty. Record instruction sources, exact effective config and tool inventory externally; an empty thread alone is not blind isolation.
10. Only after independent checks succeed, sign `arm` evidence for the exact session, then a `grant` with permitted tools, maxCalls and ttlMs. Include the reserved `codex.turn` capability only in a controller grant for owned inference. It is never an MCP tool. Sign `start` with the candidate prompt. Do not give an agent the controller key.
11. The issuer must renew the proof before its maximum 60-second expiry. Missing or invalid evidence must not produce a renewal. Task leases expire separately (default 30 seconds, maximum 15 minutes); assign a bounded duration for the task. Halt is latched until a separately reviewed new instance starts HELD.

Commands below use installed paths supplied by the host operator; they were not run in this session:

```sh
node /APPROVED/sidecar/bin/sidecar.mjs serve --config /PRIVATE/sidecar.json --sha256 EXACT_SHA256
node /APPROVED/sidecar/bin/sidecar.mjs status --socket /PRIVATE/RUN/control.sock
node /APPROVED/sidecar/bin/sidecar.mjs halt --socket /PRIVATE/RUN/control.sock
node /APPROVED/sidecar/bin/sidecar.mjs signed --socket /PRIVATE/RUN/control.sock --envelope /PRIVATE/issued-command.json
```

The MCP proxy command is `node /APPROVED/sidecar/bin/sidecar.mjs mcp-proxy --socket /PRIVATE/RUN/actions.sock`. Candidate chats can call `sidecar_status` and `sidecar_halt`.

A signed envelope is `{"payload_json":"EXACT_JSON_STRING","signature_base64":"ED25519_SIGNATURE"}`. Sign the exact UTF-8 bytes of payload_json, not a reserialized object. Payload fields are schema=1, purpose=codex-sidecar-control, unique id, boot_id, config_sha256, expires_at_ms no more than 60 seconds ahead, action and params. The example arm payload is a schema template, not evidence and not a valid command.

Actions and params:
- prepare: {} (owned instance, no prior prepared session, HELD only).
- arm / renew: {evidence:{session_id,runtime_version,effective_config_sha256,allowed_receipt_ids,denied_receipt_ids,native_routes_denied:true,scope_isolation_verified:true}}.
- grant: {tools:[configured tool names],maxCalls:integer,ttlMs:integer}.
- start: {prompt:"candidate-only task text"}.
- stop_owned: {}. First halts admission, then SIGTERM of only this instance's owned app-server child; no process groups or shared services.

Do not delete a writer lock or change a journal to restart. A crash, truncated audit, pending authorization or unknown effect requires explicit reconciliation outside the candidate. Halt does not roll back a remote write already accepted. A process group/job cancellation adapter and an independent watchdog remain deployment gaps.

Do not point Node tests or deployment commands at the denied legacy workspace. Use a host-approved isolated installation and harmless fixtures.
