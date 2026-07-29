"""Re-runnable proof for the gated shell.exec — the covered path meant to
replace Grok's ungated NATIVE shell for file/test/git inspection.

The security model is by construction, and these tests assert each pillar:
  - interpreters are refused (python/node/bash would make `-c '...'` a bypass);
  - only allowlisted read/inspect binaries run; everything else is denied;
  - per-binary escape hatches are denied (find -exec, git -c);
  - git may only READ (status/diff/log/...), never push/config/fetch;
  - paths are confined: no absolute paths, no parent traversal, cwd rooted;
  - an allowlisted read command actually runs.

subprocess uses shell=False throughout, so these run real commands but cannot
spawn a shell. The allow-case runs `git status` in the repo itself (read-only).
"""

from __future__ import annotations

from pathlib import Path

from host.shell_handlers import ShellHandlers

REPO = Path(__file__).resolve().parent.parent
sh = ShellHandlers()


# ---- interpreters are never allowlisted (the key insight) -----------------

def test_python_interpreter_denied():
    out = sh.exec({"argv": ["python3", "-c", "import os; os.system('id')"]})
    assert out["ok"] is False and out["code"] == "INTERPRETER_DENIED"


def test_bash_and_node_denied():
    for exe in ("bash", "sh", "node", "ruby", "perl", "awk", "make", "npm", "pip3"):
        out = sh.exec({"argv": [exe, "-c", "whatever"]})
        assert out["ok"] is False and out["code"] == "INTERPRETER_DENIED", exe


# ---- executable allowlist (deny-by-default) -------------------------------

def test_unlisted_executable_denied():
    for exe in ("rm", "curl", "wget", "chmod", "dd", "mv", "kill"):
        out = sh.exec({"argv": [exe, "x"]})
        assert out["ok"] is False and out["code"] == "EXECUTABLE_NOT_ALLOWLISTED", exe


def test_empty_or_bad_argv_denied():
    assert sh.exec({"argv": []})["code"] == "ARGV_REQUIRED"
    assert sh.exec({"argv": "git status"})["code"] == "ARGV_REQUIRED"
    assert sh.exec({})["code"] == "ARGV_REQUIRED"


# ---- per-binary escape hatches --------------------------------------------

def test_find_exec_flag_denied():
    out = sh.exec({"argv": ["find", ".", "-exec", "rm", "{}", ";"]})
    assert out["ok"] is False and out["code"] == "DANGEROUS_FLAG"


def test_find_delete_flag_denied():
    out = sh.exec({"argv": ["find", ".", "-delete"]})
    assert out["ok"] is False and out["code"] == "DANGEROUS_FLAG"


def test_git_dash_c_denied():
    # git -c core.pager=... / -c core.sshCommand=... can run arbitrary code
    out = sh.exec({"argv": ["git", "-c", "core.pager=sh -c id", "log"]})
    assert out["ok"] is False and out["code"] == "DANGEROUS_FLAG"


# ---- git is read-only -----------------------------------------------------

def test_git_write_subcommands_denied():
    for sub in ("push", "fetch", "config", "commit", "reset", "clean", "checkout"):
        out = sh.exec({"argv": ["git", sub]})
        assert out["ok"] is False and out["code"] == "GIT_SUBCOMMAND_DENIED", sub


# ---- path confinement -----------------------------------------------------

def test_absolute_path_arg_denied():
    out = sh.exec({"argv": ["cat", "/etc/passwd"]})
    assert out["ok"] is False and out["code"] == "ABSOLUTE_PATH_DENIED"


def test_parent_traversal_arg_denied():
    out = sh.exec({"argv": ["cat", "../../../../etc/passwd"]})
    assert out["ok"] is False and out["code"] == "PATH_TRAVERSAL"


def test_cwd_outside_roots_denied():
    out = sh.exec({"argv": ["ls"], "cwd": "/etc"})
    assert out["ok"] is False and out["code"] == "PATH_OUTSIDE_ROOTS"


# ---- the allow case actually runs (read-only) -----------------------------

def test_git_status_runs_readonly():
    out = sh.exec({"argv": ["git", "status", "--short"], "cwd": str(REPO)})
    assert out["ok"] is True and out["code"] == "RAN"
    assert out["data"]["returncode"] == 0


def test_echo_runs():
    out = sh.exec({"argv": ["echo", "gated-ok"], "cwd": str(REPO)})
    assert out["ok"] is True and "gated-ok" in out["data"]["stdout"]
