#!/usr/bin/env python3
"""Team progress tracker for six parallel roles (and their Claude Code sessions).

One JSON file per role in status/role-N.json. You only ever write YOUR role's file,
so there are no merge conflicts. Other roles' files are read from origin/main after
a `git fetch`, so your working tree is never touched while you are editing code.

  python3 tools/status.py board               whole team at a glance
  python3 tools/status.py role [N]            every task of a role with its computed state
  python3 tools/status.py next [N]            what role N can start right now
  python3 tools/status.py set ID STATUS [--note "..."] [--evidence "..."] [--push]
                                              STATUS: todo | in_progress | mock_done | done | cut
  python3 tools/status.py now "what I am doing" [--push]
  python3 tools/status.py check ID [ID...]    exit 0 if all done, else 1
  python3 tools/status.py wait ID [ID...] [--interval 60] [--timeout 7200]
                                              block until done (run it in the background)
  python3 tools/status.py forecast            can each role still finish its must-haves before the freeze?
  python3 tools/status.py ask N "text"        leave a request for role N        [--push]
  python3 tools/status.py requests [N]        open requests addressed to role N
  python3 tools/status.py resolve FILE        close a request                    [--push]
  python3 tools/status.py push                commit + push your status file and requests only

Your role number comes from the file .role in the repo root (not committed), or --as N.
Stdlib only, Python 3.9+.
"""
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "status"
REMOTE_REF = os.environ.get("STATUS_REMOTE_REF", "origin/main")
STATUSES = ["todo", "in_progress", "mock_done", "done", "cut"]
PRIO = {"must": 0, "should": 1, "nice": 2, "stretch": 3}
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Warsaw")
except Exception:
    TZ = None
FREEZE = datetime(2026, 11, 21, 22, 0, tzinfo=TZ)      # feature freeze, Saturday 22:00
SLEEP = (0.5, 8.5)                                      # 00:30-08:30 does not count as working time

def now(): return datetime.now(TZ)
def git(*a, check=False):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=check)
def in_git(): return git("rev-parse", "--git-dir").returncode == 0
def fetch():
    if in_git(): git("fetch", "--quiet")

def my_role(args):
    if getattr(args, "as_role", None): return int(args.as_role)
    f = ROOT / ".role"
    if f.exists(): return int(f.read_text().strip())
    sys.exit("No role set. Create it once with:  echo <your role number 1-6> > .role")

def load(n, mine=None):
    """Own file from disk; other roles from origin/main when available (fresh after fetch)."""
    path = STATUS / f"role-{n}.json"
    if n != mine and in_git():
        r = git("show", f"{REMOTE_REF}:status/role-{n}.json")
        if r.returncode == 0:
            return json.loads(r.stdout)
    return json.loads(path.read_text())
def load_all(mine=None): return {n: load(n, mine) for n in range(1, 7)}
def save(n, data):
    data["updated_at"] = now().isoformat(timespec="seconds")
    (STATUS / f"role-{n}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
def role_of(task_id): 
    m = re.match(r"^(\d)\.", task_id)
    if not m: sys.exit(f"Bad task id: {task_id}")
    return int(m.group(1))
def index(allr): return {t["id"]: t for d in allr.values() for t in d["tasks"]}

def state(t, idx):
    """Computed state: (label, waiting_on_ids)."""
    s = t["status"]
    unmet = [d for d in t.get("needs", []) if idx.get(d, {}).get("status") not in ("done", "cut")]
    own = [d for d in unmet if role_of(d) == role_of(t["id"])]
    other = [d for d in unmet if d not in own]
    if s in ("done", "cut"): return s.upper(), []
    if s == "mock_done": return ("INTEGRATE NOW", []) if not unmet else ("MOCK DONE", unmet)
    if s == "in_progress": return ("IN PROGRESS" if not unmet else "IN PROGRESS (on mock)", unmet)
    if own: return "AFTER", own
    if other: return ("START ON MOCK", other) if t.get("mock") else ("WAITING", other)
    return "READY", []

def fmt_wait(ids, idx):
    return ", ".join(f"{i} [{idx[i]['status']}]" if i in idx else f"{i} [unknown]" for i in ids)

def cmd_board(args):
    fetch(); mine = my_role(args) if (ROOT / ".role").exists() or args.as_role else None
    allr = load_all(mine); idx = index(allr)
    print(f"TEAM BOARD   {now():%a %H:%M}   feature freeze in {max(0, (FREEZE - now()).total_seconds() / 3600):.1f} h (Sat 22:00)\n")
    for n, d in allr.items():
        must = [t for t in d["tasks"] if t["priority"] == "must" and t["status"] != "cut"]
        done = sum(t["status"] == "done" for t in must); mock = sum(t["status"] == "mock_done" for t in must)
        bar = "#" * done + "+" * mock + "." * (len(must) - done - mock)
        print(f"R{n} {d['name']:<34} [{bar}] {done}/{len(must)} must done" + (f", {mock} on mock" if mock else "")
              + (f"   (updated {d['updated_at'][11:16]})" if d.get("updated_at") else "   (never updated)"))
        if d.get("now"): print(f"     now: {d['now']}")
        for t in d["tasks"]:
            lab, w = state(t, idx)
            if lab.startswith("IN PROGRESS"): print(f"     > {t['id']} {t['title']}" + (f"   waiting for {fmt_wait(w, idx)}" if w else ""))
            elif lab in ("WAITING", "MOCK DONE") and t["priority"] == "must": print(f"     ! {t['id']} {lab}: needs {fmt_wait(w, idx)}")
            elif lab == "INTEGRATE NOW": print(f"     * {t['id']} dependencies landed -> integrate now")
    reqs = sorted((STATUS / "requests").glob("*.md"))
    if reqs:
        print("\nOPEN REQUESTS")
        for r in reqs: print(f"  {r.name}: {r.read_text().strip().splitlines()[-1][:110]}")
    print("\nLegend: # done   + works on mock   . open   > in progress   ! blocked   * ready to integrate")

def cmd_role(args):
    fetch(); mine = my_role(args); n = int(args.n) if args.n else mine
    allr = load_all(mine); idx = index(allr); d = allr[n]
    print(f"ROLE {n}: {d['name']}" + (f"   owner: {d['owner']}" if d.get("owner") else ""))
    for t in d["tasks"]:
        lab, w = state(t, idx)
        print(f"  {t['id']:<5} {lab:<22} {t['priority']:<7} {t['est_h']:>4}h  {t['title']}")
        if w: print(f"        needs: {fmt_wait(w, idx)}" + (f"\n        meanwhile: {t['mock']}" if t.get("mock") and lab != "AFTER" else ""))
        if t.get("note"): print(f"        note: {t['note']}")

def cmd_next(args):
    fetch(); mine = my_role(args); n = int(args.n) if args.n else mine
    allr = load_all(mine); idx = index(allr)
    cand = [(t, *state(t, idx)) for t in allr[n]["tasks"]]
    order = {"INTEGRATE NOW": 0, "READY": 1, "START ON MOCK": 2}
    go = sorted([c for c in cand if c[1] in order], key=lambda c: (order[c[1]] if c[1] == "INTEGRATE NOW" else 1, PRIO[c[0]["priority"]], order[c[1]]))
    busy = [c for c in cand if c[1].startswith("IN PROGRESS")]
    for t, lab, w in busy: print(f"IN PROGRESS  {t['id']} {t['title']}")
    if not go: print("Nothing startable. Blocked tasks:"); [print(f"  {t['id']} {lab}: needs {fmt_wait(w, idx)}") for t, lab, w in cand if lab in ("WAITING", "AFTER", "MOCK DONE")]
    for t, lab, w in go:
        print(f"{lab:<14} {t['id']:<5} [{t['priority']}, {t['est_h']}h] {t['title']}")
        if w: print(f"               real dependency not ready: {fmt_wait(w, idx)}\n               meanwhile: {t['mock']}")

def push(n, msg):
    if not in_git(): print("(not a git repo: saved locally only)"); return
    git("add", f"status/role-{n}.json", "status/requests")
    if git("diff", "--cached", "--quiet").returncode == 0: print("(nothing to push)"); return
    git("commit", "-m", msg, "--", f"status/role-{n}.json", "status/requests", check=True)
    for attempt in range(3):
        r = git("pull", "--rebase", "--autostash", "--quiet")
        if r.returncode != 0: sys.exit("pull --rebase failed; resolve it by hand:\n" + r.stderr)
        if git("push", "--quiet").returncode == 0: print("pushed: " + msg); return
        time.sleep(2)
    sys.exit("push failed 3 times; run `git push` by hand")

def cmd_set(args):
    mine = my_role(args); n = role_of(args.id)
    if n != mine: sys.exit(f"Task {args.id} belongs to role {n}; you are role {mine}. Use `ask {n} \"...\"` instead.")
    if args.status not in STATUSES: sys.exit(f"STATUS must be one of {STATUSES}")
    d = load(n, mine); t = next((t for t in d["tasks"] if t["id"] == args.id), None)
    if not t: sys.exit(f"Unknown task {args.id}")
    t["status"] = args.status; stamp = now().isoformat(timespec="minutes")
    if args.status == "in_progress" and not t.get("started_at"): t["started_at"] = stamp
    if args.status in ("done", "mock_done"): t["done_at"] = stamp
    if args.note is not None: t["note"] = args.note
    if args.evidence is not None: t["evidence"] = args.evidence
    save(n, d); print(f"{args.id} -> {args.status}")
    if args.push: push(n, f"status: R{n} {args.id} {args.status}")

def cmd_now(args):
    mine = my_role(args); d = load(mine, mine); d["now"] = args.text; save(mine, d)
    if args.push: push(mine, f"status: R{mine} now: {args.text[:50]}")

def all_done(ids):
    idx = index(load_all(None)); return [i for i in ids if idx.get(i, {}).get("status") != "done"]
def cmd_check(args):
    fetch(); left = all_done(args.ids); idx = index(load_all(None))
    print("all done" if not left else "not done: " + fmt_wait(left, idx)); sys.exit(0 if not left else 1)
def cmd_wait(args):
    t0 = time.time()
    while True:
        fetch(); left = all_done(args.ids)
        if not left: print(f"DONE: {', '.join(args.ids)} - you can integrate now"); return
        if time.time() - t0 > args.timeout:
            print(f"TIMEOUT after {args.timeout}s, still not done: {', '.join(left)}"); sys.exit(2)
        time.sleep(args.interval)

def working_hours(a, b):
    h = 0.0; t = a
    while t < b:
        x = t.hour + t.minute / 60
        if not (SLEEP[0] <= x < SLEEP[1]): h += 0.25
        t += timedelta(minutes=15)
    return h
def cmd_forecast(args):
    fetch(); allr = load_all(None); avail = working_hours(now(), FREEZE)
    print(f"FORECAST   {now():%a %H:%M}   working hours left until feature freeze (sleep excluded): {avail:.1f} h per person\n")
    w = {"todo": 1.0, "in_progress": 0.5, "mock_done": 0.2, "done": 0.0, "cut": 0.0}
    for n, d in allr.items():
        must = sum(t["est_h"] * w[t["status"]] for t in d["tasks"] if t["priority"] == "must" and not t.get("after_freeze"))
        should = sum(t["est_h"] * w[t["status"]] for t in d["tasks"] if t["priority"] == "should")
        verdict = "OK" if must <= 0.8 * avail else ("TIGHT" if must <= avail else "OVER - cut or get help")
        extra = "" if must + should <= avail else f"   should-haves ({should:.1f} h) will not all fit"
        print(f"R{n} {d['name']:<34} must left {must:5.1f} h of {avail:.1f} h  -> {verdict}{extra}")
    print("\nWeights: todo 100%, in_progress 50%, mock_done 20% of the estimate. Tasks marked after_freeze (pitch, slides) are not counted.")
    print("OK = under 80% of the time left. TIGHT = fits with no slack. OVER = does not fit: cut a task or get help.")

def cmd_ask(args):
    mine = my_role(args); slug = re.sub(r"[^a-z0-9]+", "-", args.text.lower())[:40].strip("-")
    f = STATUS / "requests" / f"to-r{args.n}-from-r{mine}-{now():%d%H%M}-{slug}.md"
    f.write_text(f"To role {args.n}, from role {mine}, {now():%a %H:%M}\n\n{args.text}\n"); print(f"created {f.relative_to(ROOT)}")
    if args.push: push(mine, f"status: request R{mine} -> R{args.n}")
def cmd_requests(args):
    fetch(); mine = my_role(args); n = int(args.n) if args.n else mine
    if in_git(): git("pull", "--rebase", "--autostash", "--quiet")
    rs = sorted((STATUS / "requests").glob(f"to-r{n}-*.md"))
    print(f"{len(rs)} open request(s) for role {n}")
    for r in rs: print(f"\n--- {r.name}\n{r.read_text().strip()}")
def cmd_resolve(args):
    mine = my_role(args); f = STATUS / "requests" / Path(args.file).name
    if not f.exists(): sys.exit(f"No such request: {f.name}")
    if in_git() and git("ls-files", "--error-unmatch", str(f.relative_to(ROOT))).returncode == 0: git("rm", "--quiet", str(f.relative_to(ROOT)))
    else: f.unlink()
    print(f"resolved {f.name}")
    if args.push: push(mine, f"status: R{mine} resolved {f.name[:40]}")
def cmd_push(args):
    mine = my_role(args); push(mine, f"status: R{mine} update")

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--as", dest="as_role", help="act as role N (default: read .role)")
sub = p.add_subparsers(dest="cmd")
sub.add_parser("board").set_defaults(f=cmd_board)
s = sub.add_parser("role"); s.add_argument("n", nargs="?"); s.set_defaults(f=cmd_role)
s = sub.add_parser("next"); s.add_argument("n", nargs="?"); s.set_defaults(f=cmd_next)
s = sub.add_parser("set"); s.add_argument("id"); s.add_argument("status"); s.add_argument("--note"); s.add_argument("--evidence"); s.add_argument("--push", action="store_true"); s.set_defaults(f=cmd_set)
s = sub.add_parser("now"); s.add_argument("text"); s.add_argument("--push", action="store_true"); s.set_defaults(f=cmd_now)
s = sub.add_parser("check"); s.add_argument("ids", nargs="+"); s.set_defaults(f=cmd_check)
s = sub.add_parser("wait"); s.add_argument("ids", nargs="+"); s.add_argument("--interval", type=int, default=60); s.add_argument("--timeout", type=int, default=7200); s.set_defaults(f=cmd_wait)
sub.add_parser("forecast").set_defaults(f=cmd_forecast)
s = sub.add_parser("ask"); s.add_argument("n"); s.add_argument("text"); s.add_argument("--push", action="store_true"); s.set_defaults(f=cmd_ask)
s = sub.add_parser("requests"); s.add_argument("n", nargs="?"); s.set_defaults(f=cmd_requests)
s = sub.add_parser("resolve"); s.add_argument("file"); s.add_argument("--push", action="store_true"); s.set_defaults(f=cmd_resolve)
sub.add_parser("push").set_defaults(f=cmd_push)
a = p.parse_args()
(a.f if a.cmd else cmd_board)(a)
