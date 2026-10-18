# Threat model and honest limits

The adversary is a candidate agent following injected instructions, exceeding granted scope, forging approval or success, retrying an uncertain write, calling native tools, connecting directly to the plane, or trying to disable its supervisor. All negative tests use harmless fixture resources.

The trusted computing base is the host launcher, runtime/OS permission boundary, independent evidence issuer and protected private signing key, sidecar process and pinned code/config, existing plane policy and handlers, and the observer. The candidate must not have arbitrary same-user access to these. Mode 0600 sockets, a separate Node process, a public key, a prompt rule or a tool name are not sufficient OS isolation.

The implementation makes admission fail closed for missing proof, stale permits, unavailable audit, invalid schemas and unknown outcomes. The default catalog is diagnostic; broader capability is added as typed plane tools with real capability classification and scope checks in the plane. Exporting an unrestricted shell, general file writer over authority roots, or desktop keystrokes into a terminal would create alternate authority even if the tool has a harmless name.

Halt is a state transition before asynchronous IO. It prevents future sidecar dispatch, not every action on the host. The app-server interrupt acknowledges a request; observed interrupted completion is separate. SIGTERM plus observed owned-parent exit does not establish descendant termination. Killing an owned MCP adapter does not stop a shared plane or undo a dispatched remote request. Cancellation/rollback semantics must be implemented by each actual handler and verified on fixture effects.

An independent watchdog must enforce expiry or kill scoped work if the sidecar event loop or process becomes unresponsive. The 100ms timer in this package cannot police its own blocked event loop, a suspended process, or a hostile host. That external watchdog and a job-scope adapter are not implemented here.

Proof signatures bind commands to this boot/config/session and prevent unsigned expansion. They do not prove the issuer actually performed the checks or that observation is complete. The service therefore never changes runtime_enforcement from UNKNOWN. Evidence collection and negative-control coverage are separate host obligations.

Local journal hashes detect changes when the retained chain is trusted. They do not authenticate the backend independently or prevent a sufficiently privileged actor rewriting an entire chain. External receipt correlation and an independently protected observer remain required.

No shared/live service was stopped. The deliberately withheld live policy-service unavailability test remains open. Injected exceptions, source review or a fixture outage do not waive it. No authority files or pins changed.
