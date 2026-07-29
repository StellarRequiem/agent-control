# Shell gating — what is covered, and the honest boundary

agent-control gates **tools that route through `AssuredPlaneHost.call`**. It cannot
intercept a model runtime's *native* tool calls from outside — so "all shell is
gated" is only true when the deployment routes shell through this host and disables
the runtime's native shell. This doc states exactly what is covered.

## The gated shell surface

| Tool | What it allows | Enforcement |
|------|----------------|-------------|
| `shell.list_dir` / `shell.read_file` / `shell.stat` | read/inspect under allowed roots | rooted paths, secret-filename refusal, size caps |
| `shell.run` | a fixed set of **named** commands (`git_status`, `git_log`, …) with fixed argv | name allowlist only |
| `shell.exec` | a **validated argv** for read/inspect work (file/test/git) | see below |

## `shell.exec` — security by construction

`shell.exec` is the covered path meant to replace Grok's native shell for
file/test/git **inspection**. It is not a general bash. Every run is `shell=False`
(argv → `execve`, so `;`, `|`, `&`, `$`, backticks are inert literals — there is no
shell to interpret them). On top of that:

- **Interpreters are refused.** `python`, `node`, `bash`, `sh`, `ruby`, `perl`,
  `awk`, `make`, `npm`, `pip`, `env`, `xargs`, `eval` are denied — allowlisting any
  of them would make `python3 -c "..."` a total bypass. An executable allowlist
  that includes an interpreter is a *false* gate.
- **Executable allowlist (deny-by-default):** only `git ls cat head tail wc rg grep
  find echo true`.
- **Per-binary escape hatches denied:** `find -exec/-execdir/-delete`, `git -c`
  (arbitrary config → code), `-e/--eval`, `-o/--output`, etc.
- **git is read-only:** only `status diff log show branch rev-parse ls-files
  describe blame shortlog tag remote` — never `push/fetch/config/commit`.
- **Path confinement:** no absolute-path args, no `..` traversal, cwd resolved
  under the allowed roots.
- Timeout + output caps.

Proof: `tests/test_shell_exec_gate.py` (interpreter denied, unlisted exe denied,
`find -exec` denied, `git -c` denied, git write subcommands denied, absolute path
denied, traversal denied, cwd-outside-roots denied, `git status` runs read-only).

## What is still NOT gated (the honest boundary)

- **Grok's native runtime shell.** If the runtime is configured with its own shell
  tool, that call never reaches this host and is **not** gated. The host provides
  the mechanism (`shell.exec` + `shell.run`); the deployment must **disable the
  native shell and route through the host** for the "all shell gated" property to
  hold. The host cannot force the runtime.
- **Code execution / editing / test-running.** `shell.exec` is read/inspect only.
  Running tests or editing files is intentionally out of its scope (running tests
  executes arbitrary test code). Use a named `shell.run` command for a fixed,
  audited test invocation instead.

`claim_ceiling` reflects this: `gated_shell_exec: true`, `ambient_shell_exec:
false`, `native_runtime_shell_gated: false`.
