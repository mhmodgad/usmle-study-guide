"""Cross-platform launcher: self-update from the public repo, then serve the app.

    python -m tempu.launch [--port 5000] [--host 127.0.0.1]
                           [--no-update] [--no-browser] [--update-only]

Before serving, the launcher fetches main from the public GitHub repo - pulling
a public repo needs no account, login or SSH key - and applies it only when
the repo is strictly ahead of this copy:

  behind, with nothing of its own           -> fast-forwarded to the repo's version
  behind, with local edits the update doesn't touch
                                            -> fast-forwarded, edits kept
  commits the repo doesn't have, or local edits in the way of the update
                                            -> nothing is changed, the app just runs

A folder that was copied rather than cloned has no history to compare. On
its first run the launcher links it to the release its files came from,
without touching a file, and from then on treats it like any other copy.

Offline, no git, or any other failure just prints a notice and starts the
installed version. User data (data/, local/assets/media/, local/content/,
.venv/) is gitignored and never touched. Disable with --no-update or
TEMPU_NO_UPDATE=1.
"""
import argparse
import os
import re
import subprocess
import sys

REPO_URL = os.environ.get(
    "TEMPU_REPO_URL", "https://github.com/mhmodgad/usmle-study-guide.git")
BRANCH = os.environ.get("TEMPU_UPDATE_BRANCH", "main")
FETCH_TIMEOUT = 90    # seconds before we give up on the network
PIP_TIMEOUT = 300
ADOPT_SCAN = 200      # how far back a copied folder is matched to a release

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTE_REF = "refs/remotes/origin/" + BRANCH
FETCH = ("fetch", "--quiet", "origin",
         "+refs/heads/%s:%s" % (BRANCH, REMOTE_REF))


def _find_git():
    from shutil import which
    found = which("git")
    if found:
        return found
    for path in (r"C:\Program Files\Git\cmd\git.exe",
                 r"C:\Program Files (x86)\Git\cmd\git.exe",
                 os.path.expanduser(r"~\AppData\Local\Programs\Git\cmd\git.exe"),
                 "/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git"):
        if os.path.isfile(path):
            return path
    return None


def _run(git, *args, timeout=60):
    """Run a git command in the project folder; returns (exit code, output)."""
    cmd = [git, "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=20",
           *args]
    # never wait for a password or pop up a login dialog
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        p = subprocess.run(cmd, cwd=PROJECT, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=timeout,
                           text=True, encoding="utf-8", errors="replace", env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def _names(out):
    """The paths in a `git diff --name-only -z` listing."""
    return [p for p in out.split("\0") if p]


def _reason(out):
    """The first error line git printed, to show why an update was skipped."""
    for line in out.splitlines():
        if line.startswith(("fatal:", "error:")):
            return line.strip()[:200]
    return out.strip().splitlines()[0][:200] if out.strip() else ""


def _blocked_files(out):
    """The files git lists when it refuses to overwrite local edits."""
    files, listing = [], False
    for line in out.splitlines():
        if listing:
            if line.strip() and not line.startswith("Please"):
                files.append(line.strip())
                continue
            break
        listing = line.rstrip().endswith("overwritten by merge:")
    return files


# The start/setup scripts are app code, not your data. A hand-edited copy (for
# example a workaround for a bug the update fixes) would otherwise block every
# future update, so it is kept next to the original and replaced.
SCRIPTS = ("run-windows.bat", "setup-windows.bat", "setup-windows.ps1", "run.sh", "setup.sh")


def _set_aside_scripts(git, blocked, say):
    """Keep a copy of locally edited launcher scripts (<name>.local-edit) and
    reset them to the committed version. True if every blocked file was one."""
    if not blocked or any(f not in SCRIPTS for f in blocked):
        return False
    import shutil
    for f in blocked:
        src = os.path.join(PROJECT, f)
        try:
            shutil.copy2(src, src + ".local-edit")
        except OSError:
            return False
        rc, _ = _run(git, "checkout", "--", f)
        if rc != 0:
            return False
        say("[update] your edited %s was saved as %s.local-edit; "
            "the updated version replaces it" % (f, f))
    return True


def _link(git):
    """Make a copied folder (no .git) a repository that tracks the public repo."""
    rc, out = _run(git, "init", "--quiet", "--branch", BRANCH)
    if rc != 0:  # git older than 2.28 has no --branch, but the branch is unborn
        rc, out = _run(git, "init", "--quiet")
        if rc == 0:
            _run(git, "symbolic-ref", "HEAD", "refs/heads/" + BRANCH)
    if rc != 0:
        raise RuntimeError("git init failed: " + _reason(out))
    rc, _ = _run(git, "remote", "get-url", "origin")
    if rc != 0:
        rc, out = _run(git, "remote", "add", "origin", REPO_URL)
        if rc != 0:
            raise RuntimeError("could not add the repo: " + _reason(out))


def _fetch(git):
    """Fetch the repo's BRANCH into origin/BRANCH; returns (ok, output).

    The whole history is fetched (no --depth): deciding whether this copy is
    ahead or behind needs real ancestry, and a shallow fetch makes both sides
    look unrelated. The repo is code only, so the pack is small."""
    rc, out = _run(git, *FETCH, timeout=FETCH_TIMEOUT)
    if rc == 0:
        return True, out
    if "dubious ownership" in out:
        # git refuses a folder owned by another Windows account; trust just this one
        m = re.search(r"at '([^']+)'", out)
        _run(git, "config", "--global", "--add", "safe.directory",
             m.group(1) if m else PROJECT)
        rc, out = _run(git, *FETCH, timeout=FETCH_TIMEOUT)
    return rc == 0, out


def _adopt(git, latest):
    """Link a folder without history to the release its files came from,
    without touching a file. Returns (commit, number of locally changed files).

    The index is pointed at a release while the files stay as they are, so a
    plain diff lists what the folder changed relative to that release. A clean
    copy matches one release exactly; an edited one differs least from the
    release it was taken from."""
    rc, out = _run(git, "reset", "--quiet", "--mixed", latest)
    if rc != 0:
        raise RuntimeError("could not link the folder: " + _reason(out))
    _, out = _run(git, "diff", "--name-only", "-z", latest)
    best, fewest = latest, len(_names(out))
    if fewest:
        _, out = _run(git, "rev-list", "--max-count=%d" % ADOPT_SCAN, latest)
        for commit in out.split():
            _, diffs = _run(git, "diff", "--name-only", "-z", commit)
            n = len(_names(diffs))
            if n < fewest:
                best, fewest = commit, n
            if n == 0:
                break
        if best != latest:
            _run(git, "reset", "--quiet", "--mixed", best)
    return best, fewest


def _install_deps():
    p = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r",
         os.path.join(PROJECT, "requirements.txt")],
        cwd=PROJECT, stdin=subprocess.DEVNULL, capture_output=True,
        timeout=PIP_TIMEOUT, text=True, encoding="utf-8", errors="replace")
    return p.returncode == 0, (p.stderr or p.stdout or "").strip()[-300:]


def selfupdate(verbose=True):
    """Bring this copy up to date with the repo. Returns True if files changed."""
    def say(msg):
        if verbose:
            print(msg, flush=True)

    if os.environ.get("TEMPU_NO_UPDATE"):
        say("[update] disabled via TEMPU_NO_UPDATE - using the current version")
        return False

    git = _find_git()
    if not git:
        say("[update] git not found - skipping the update check "
            "(run the setup script to install it)")
        return False

    try:
        if not os.path.exists(os.path.join(PROJECT, ".git")):
            say("[update] first run - linking this folder to the repo...")
            _link(git)

        ok, out = _fetch(git)
        if not ok:
            if "couldn't find remote ref" in out:
                say("[update] the repo has no '%s' branch - using the current version"
                    % BRANCH)
            else:
                why = _reason(out)
                say("[update] could not reach the repo - using the current version"
                    + (" (%s)" % why if why else ""))
            return False

        _, latest = _run(git, "rev-parse", "--verify", "--quiet", REMOTE_REF)
        latest = latest.strip()

        rc, _ = _run(git, "rev-parse", "--verify", "--quiet", "HEAD")
        if rc != 0:
            # No history: a folder that was copied rather than cloned.
            base, local = _adopt(git, latest)
            say("[update] linked to the repo at release %s" % base[:8]
                + (" - %d locally changed file(s) kept as they are" % local
                   if local else ""))

        # Update only when the repo is strictly ahead (a fast-forward). A copy
        # with commits of its own, or diverged from the repo, is left alone.
        rc, counts = _run(git, "rev-list", "--left-right", "--count",
                          "HEAD..." + latest)
        try:
            ahead, behind = (int(x) for x in counts.split())
        except ValueError:
            say("[update] could not compare with the repo - using the current version")
            return False
        if ahead > 0:
            say("[update] this copy has %d commit(s) the repo doesn't - "
                "leaving everything as it is" % ahead)
            return False
        if behind == 0:
            say("[update] already up to date")
            return False

        # Local edits survive unless a file they touch changes in the update;
        # then git refuses to touch anything at all.
        _, diff = _run(git, "diff", "--name-only", "HEAD", latest, "--",
                       "requirements.txt")
        rc, out = _run(git, "merge", "--ff-only", "--quiet", latest)
        if rc != 0 and _set_aside_scripts(git, _blocked_files(out), say):
            rc, out = _run(git, "merge", "--ff-only", "--quiet", latest)
        if rc != 0:
            blocked = _blocked_files(out)
            if blocked:
                why = ("the repo is %d commit(s) ahead, but local edits to %s are in "
                       "the way. Commit or discard those edits to get the update"
                       % (behind, ", ".join(blocked)))
            else:
                why = "could not apply the update (%s)" % _reason(out)
            say("[update] %s - nothing was changed, running the current version." % why)
            return False
        say("[update] updated to %s (%d new commit(s))" % (latest[:8], behind))

        if "requirements.txt" in diff.splitlines():
            say("[update] installing dependencies...")
            ok, why = _install_deps()
            if not ok:
                say("[update] installing dependencies failed - the app may not "
                    "start until it does: %s" % why)
        return True
    except Exception as e:  # noqa: BLE001 - a failed update must never block the launch
        say("[update] skipped (%s) - using the current version" % e)
        return False


def _has_topics(path):
    """True if the SQLite file at path has a non-empty topics table (read-only:
    never creates or changes the file)."""
    import sqlite3
    try:
        from urllib.request import pathname2url
        conn = sqlite3.connect("file:%s?mode=ro" % pathname2url(os.path.abspath(path)), uri=True)
        try:
            return conn.execute("SELECT 1 FROM topics LIMIT 1").fetchone() is not None
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - missing, locked, not a database, no table
        return False


def data_problem(data_dir=None):
    """None when there is a library to show, otherwise what to do about it.

    Accepted: data/base.db with content (the current layout), or an older
    single-file data/tempu.db, which the app upgrades on its first start."""
    if data_dir is None:
        from tempu import db as dbmod
        data_dir = dbmod.DATA_DIR
    base = os.path.join(data_dir, "base.db")
    legacy = os.path.join(data_dir, "tempu.db")
    if os.path.isfile(legacy) or _has_topics(base):
        return None
    win = os.name == "nt"
    setup = "setup-windows.bat" if win else "./setup.sh"
    content = os.path.join("local", "content")
    if os.path.isfile(base):
        what = "The library database (%s) is empty or unreadable." % base
    else:
        what = "No library database found in %s." % data_dir
    return ("%s\n"
            "Do one of these, then start the app again:\n"
            "  - put your content in %s and run %s (it builds the library), or\n"
            "  - copy your prebuilt data folder (base.db + user.db, or an old tempu.db) into %s"
            % (what, content, setup, data_dir))


def _port_free(host, port):
    """True if nothing is listening on host:port yet."""
    import socket
    family, kind, proto, _, addr = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)[0]
    with socket.socket(family, kind, proto) as s:
        if os.name != "nt" and family == socket.AF_INET:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(addr)
            return True
        except OSError:
            return False


def _is_this_app(url):
    """True if the server answering at url is this app (it redirects / to /dashboard)."""
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        opener.open(url, timeout=3)
    except urllib.error.HTTPError as e:
        return e.code in (301, 302, 303, 307, 308) and (e.headers.get("Location") or "").endswith("/dashboard")
    except OSError:
        return False
    return False


def _open_browser(url):
    """Open the browser once the server answers, so it never loads too early."""
    import time
    import urllib.error
    import urllib.request
    import webbrowser
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            direct.open(url, timeout=1)
            break
        except urllib.error.HTTPError:
            break  # an error page still means the server is up
        except OSError:
            time.sleep(0.25)
    webbrowser.open(url)


def _tolerate_output_errors():
    """Never crash on a character the console cannot show (e.g. a non-ASCII
    folder name inside a git error message)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:  # noqa: BLE001 - only a nicety
                pass


def main(argv=None):
    _tolerate_output_errors()
    ap = argparse.ArgumentParser(description="Update (optional) and run the app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--no-update", action="store_true",
                    help="skip the update check")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open the browser automatically")
    ap.add_argument("--update-only", action="store_true",
                    help="check for updates and exit (no server)")
    a = ap.parse_args(argv)

    url = "http://%s:%d/" % (a.host, a.port)
    if a.update_only:
        if not _port_free(a.host, a.port) and _is_this_app(url):
            print("The app is running - close it first, then update.")
            return 1
        selfupdate()
        return 0
    if not _port_free(a.host, a.port):
        if _is_this_app(url):
            # started a second time (double-clicked again): just show the running one
            print("The app is already running at %s - opening it in your browser." % url)
            if not a.no_browser:
                import webbrowser
                webbrowser.open(url)
            return 0
        print("Port %d is already in use by another program. Close it, or start "
              "the app on another port with: --port 5050" % a.port)
        return 1

    # (updating only now: never change the files under an app that is running)
    if not a.no_update:
        selfupdate()

    # Checked here, AFTER the update, rather than in run-windows.bat / run.sh:
    # a wrong check in a launcher script used to stop the app before the
    # update that fixes it could ever run.
    problem = data_problem()
    if problem:
        print(problem)
        return 1

    from tempu.app import app  # imported after the update, so new code is used
    print("Starting the USMLE Study Guide at %s  (press Ctrl+C to stop)" % url)
    if not a.no_browser:
        import threading
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
    try:
        app.run(host=a.host, port=a.port, debug=False)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
