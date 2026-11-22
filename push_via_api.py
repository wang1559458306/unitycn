#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 GitHub REST API 把本地仓库内容推到远端（绕开 github.com 的 443）。

为什么需要这个：
  本机 TCP 到 github.com:443 不通（Test-NetConnection = False），
  `git push` 必然失败；但 api.github.com 是通的（200）。
  所以改用 Contents API 一个文件一个文件地写。

用法：
  python push_via_api.py --repo wang1559458306/unitycn --token ghp_xxx
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
SKIP_DIRS = {".git", "__pycache__", ".cache", "modules", "_ci_pending",
             "build", "dist"}
SKIP_EXT = {".exe", ".zip", ".pkg", ".xz", ".tmp", ".parts", ".pyc", ".token"}
# 文件名黑名单：凭据类文件绝不能上传
SKIP_FILES = {
    "pool.txt", ".token", "token.txt", "credentials", ".credentials",
    ".env", ".netrc", "id_rsa",
}
# 目录名包含即跳过（egg-info 形如 unitycn.egg-info）
SKIP_DIR_PARTS = ("egg-info",)


def ls_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS
                       and not any(p in d for p in SKIP_DIR_PARTS)]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            low = fn.lower()
            # 双重保险：扩展名 + 文件名黑名单 + 模式匹配
            if os.path.splitext(low)[1] in SKIP_EXT:
                continue
            if low in SKIP_FILES:
                continue
            if low.endswith(".token") or low.startswith(".env"):
                continue
            if low.startswith("pool") and low.endswith(".txt"):
                continue
            out.append((rel, full))
    return sorted(out)


def call(method, url, token, payload=None, retries=4):
    data = json.dumps(payload).encode() if payload is not None else None
    for i in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "unitycn-push")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read().decode("utf-8", "replace")
                return r.status, json.loads(body) if body.strip().startswith(("{", "[")) else body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (409, 422) and "sha" in body.lower() and i < retries - 1:
                time.sleep(1)
                continue
            return e.code, body
        except Exception as e:
            if i < retries - 1:
                time.sleep(2 * (i + 1))
                continue
            return 0, str(e)
    return 0, "exhausted"


def put_file(repo, token, path, content_bytes, message="", sha=None):
    url = f"{API}/repos/{repo}/contents/{urllib.request.quote(path)}"
    payload = {
        "message": message or f"add {path}",
        "content": base64.b64encode(content_bytes).decode(),
    }
    if sha:
        payload["sha"] = sha
    return call("PUT", url, token, payload)


def get_sha(repo, token, path):
    url = f"{API}/repos/{repo}/contents/{urllib.request.quote(path)}"
    st, body = call("GET", url, token)
    if st == 200 and isinstance(body, dict):
        return body.get("sha")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--token", help="直接用 token（会进 shell 历史，不推荐）")
    ap.add_argument("--token-file", default=".token",
                    help="从文件读 token（推荐）。默认 .token")
    ap.add_argument("--root", default=".")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--skip-ci", action="store_true",
                    help="跳过 .github/workflows（PAT 缺 workflow 权限时）")
    a = ap.parse_args()

    token = a.token
    if not token:
        if not os.path.exists(a.token_file):
            raise SystemExit(
                f"缺 token。二选一：\n"
                f"  echo 你的token > {a.token_file}\n"
                f"  或加 --token 参数")
        with open(a.token_file, encoding="utf-8") as f:
            token = f.read().strip()
    if not token:
        raise SystemExit(f"{a.token_file} 是空的")
    a.token = token

    os.chdir(a.root)
    files = ls_files(".")
    if a.skip_ci:
        files = [(r, f) for r, f in files if not r.startswith(".github/workflows/")]

    print(f"{len(files)} 个文件待上传 → {a.repo} ({a.branch})")
    ok = fail = 0
    failed = []
    for i, (rel, full) in enumerate(files, 1):
        with open(full, "rb") as f:
            data = f.read()
        sha = get_sha(a.repo, a.token, rel)
        st, body = put_file(a.repo, a.token, rel, data,
                            message=f"add {rel}", sha=sha)
        good = st in (200, 201)
        mark = "OK " if good else "FAIL"
        print(f"  [{i:>3}/{len(files)}] [{mark}] {rel}"
              + ("" if good else f"  {st} {str(body)[:110]}"), flush=True)
        if good:
            ok += 1
        else:
            fail += 1
            failed.append(rel)

    print(f"\n成功 {ok}，失败 {fail}")
    if failed:
        print("失败清单：")
        for x in failed:
            print("  " + x)
        return 1
    print(f"\n完成：https://github.com/{a.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
