"""经 api.github.com 把整个项目推成一个 commit（沙箱内 github.com 被封时的推送通道）。

用法：
    GITHUB_PAT=<令牌> python tools/github_push.py [--repo owner/name] [--dry-run]

- 令牌只从环境变量读，绝不写进文件、绝不进仓库。
- 自动在令牌所属账号下找名为 jingongmen-imperial-kitchen 的仓库（可用 --repo 指定）。
- 走 Git Data API：blobs -> tree -> commit -> ref，一次提交、完整历史、无逐文件噪音。
- 文件挑选规则与 tools/package_skill.py 一致：排除 .workbuddy/、.git/、__pycache__、
  *.pyc、*.zip、.pkg-stage/。
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_NAME = "jingongmen-imperial-kitchen"
EXCLUDE_DIRS = {".workbuddy", ".git", "__pycache__", ".pkg-stage"}


def api(method, path, tok, payload=None):
    url = path if path.startswith("http") else API + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "token " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "ignore")[:300]}


def collect_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith((".pyc", ".zip")):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            out.append((rel, full))
    return sorted(out)


def find_repo(tok):
    page = 1
    while page <= 10:
        st, data = api("GET", f"/user/repos?per_page=100&page={page}&visibility=all", tok)
        if st != 200:
            sys.exit(f"列不出仓库（HTTP {st}）：{data}")
        for r in data:
            if r.get("name") == REPO_NAME:
                return r["full_name"], r.get("private"), r.get("default_branch")
        if len(data) < 100:
            break
        page += 1
    return None, None, None


def main():
    tok = os.environ.get("GITHUB_PAT")
    if not tok:
        sys.exit("缺少环境变量 GITHUB_PAT（令牌只从环境变量读，不落盘）")

    dry = "--dry-run" in sys.argv
    full = None
    if "--repo" in sys.argv:
        full = sys.argv[sys.argv.index("--repo") + 1]
    else:
        full, private, branch = find_repo(tok)
        if not full:
            sys.exit(f"令牌账号下找不到名为 {REPO_NAME} 的仓库；"
                     f"请确认仓库名与所属账号，或用 --repo owner/name 指定")
        print(f"找到仓库：{full}（{'私有' if private else '公开'}，默认分支 {branch}）")

    st, me = api("GET", "/user", tok)
    if st != 200:
        sys.exit(f"令牌无效（HTTP {st}）：{me}")
    print(f"令牌身份：{me.get('login')}")

    files = collect_files()
    total = sum(os.path.getsize(p) for _, p in files)
    print(f"待推送 {len(files)} 个文件，共 {total/1024:.1f} KB")
    if dry:
        for rel, _ in files:
            print("   ", rel)
        return

    # 1. blobs
    t0 = time.time()
    entries = []
    for rel, full_path in files:
        with open(full_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        st, blob = api("POST", f"/repos/{full}/git/blobs", tok,
                       {"content": b64, "encoding": "base64"})
        if st != 201:
            sys.exit(f"建 blob 失败 {rel}（HTTP {st}）：{blob}")
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob {len(entries):>2}/{len(files)}  {rel}")

    # 2. tree
    st, tree = api("POST", f"/repos/{full}/git/trees", tok, {"tree": entries})
    if st != 201:
        sys.exit(f"建 tree 失败（HTTP {st}）：{tree}")

    # 3. commit（有历史就挂到父提交上）
    parents = []
    st, ref = api("GET", f"/repos/{full}/git/ref/heads/main", tok)
    if st == 200:
        parents = [ref["object"]["sha"]]
    st, commit = api("POST", f"/repos/{full}/git/commits", tok,
                     {"message": "金拱门御膳房：麦当劳中国 MCP 御膳房传膳 Skill（参赛首提）",
                      "tree": tree["sha"], "parents": parents})
    if st != 201:
        sys.exit(f"建 commit 失败（HTTP {st}）：{commit}")

    # 4. ref
    if parents:
        st, _ = api("PATCH", f"/repos/{full}/git/refs/heads/main", tok,
                    {"sha": commit["sha"], "force": True})
    else:
        st, _ = api("POST", f"/repos/{full}/git/refs", tok,
                    {"ref": "refs/heads/main", "sha": commit["sha"]})
    if st not in (200, 201):
        sys.exit(f"更新 ref 失败（HTTP {st}）")

    print(f"\n完成：{len(files)} 个文件、1 个 commit，用时 {time.time()-t0:.1f}s")
    print(f"commit: {commit['sha'][:12]}")
    print(f"仓库：  https://github.com/{full}")


if __name__ == "__main__":
    main()
