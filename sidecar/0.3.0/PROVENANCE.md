# Provenance

Authority: /Users/llm01/OPERATOR_PROTOCOL.md and full /Users/llm01/ops/10.00-AGENT-INDEX.md were read through the operator plane during this build. Index SHA-256 matched a44275dfb5617c4a676b53dcd39947c0f1029050443c71573bfad11e633f7120. No authority-root change was made.

Scope was recorded before this package's source writes in AUTHORIZATION-SCOPE.json, authorization e723ff2d-9608-4dd0-a134-06199b1b6629, execution 0bc4fbc1-62c4-47bc-8756-fdcf5d188b79 at chain position 642.

Official API source retrieved 2026-10-01 via approved browser: [Codex App Server](https://learn.chatgpt.com/docs/app-server). The requested developers.openai.com/codex/app-server/ URL redirected there. Snapshot receipt 18e39355-f8db-482a-a7a1-cc43d8e3645f, position 646. Exact turn/interrupt example obtained with browser.find receipt f94c40dd-b485-4b7c-b0f8-395b71863349, position 652.

Verified documentary facts: headerless newline JSON on stdio; initialize/initialized handshake; fresh thread/start and thread/read; turn/start; turn/interrupt takes threadId and turnId and acknowledges with {}; interrupted terminal status arrives separately. The documented thread/shellCommand and experimental process/spawn run outside the thread sandbox and are not exposed here. No live version-specific schema was generated and no real app-server compatibility test ran.

Vendored Plane Mount 0.2.0 source is copied unchanged from the staged, previously read-back package:
 /Users/llm01/warrant/handoffs/plane-mount-2026-09-30
 source manifest SHA-256 d91b19dc0c8ae87472d04b1aab8fcf9b405663eec628de12cc75df773c63bafc.
This sidecar wraps its backend with a final guard and wraps its journal with serialized appends; it exposes no mount reconnect method. The vendor's own 58 logic tests were run in the earlier build, not counted as new sidecar tests.

Existing host install refusal: OPERATOR_CONTROL_PATH_READ_ONLY, executed=false, handler_executed=false, authorization 870c5be3-e43a-4d3e-ab94-b8d88bd7e080, execution 9c2d8304-7a4a-4c20-9e8c-558dbe31d121 position 454. This was operator-plane policy, not an automatic approval-review rejection. No alternative write/runner route was used.

All sidecar logic test verifiers and app-server fixtures are explicitly synthetic. The new live-status evidence is from the existing plane, not the new sidecar. No external independent reviewer, observer, signing issuer, model run or published release is claimed.
