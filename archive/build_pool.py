#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建可用代理池 v3
==================
修正了两个此前踩过的坑：
  * 必须按来源标注协议（v1 把 SOCKS5 列表当 HTTP 测，7529 个只命中 5 个）
  * 探测必须用 offset 0 的段（CDN 对中间偏移常返回 000，会把好代理误判成死代理）

用法：python build_pool.py --workers 250
"""
import argparse, concurrent.futures as cf, os, subprocess, tempfile, threading, time

URL = ("https://download.unity3d.com/download_unity/f4e960bd2f88/"
       "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")
CHUNK = 4 * 1024 * 1024
D = os.path.join(tempfile.gettempdir(), "unity7")

# 文件名 -> (协议, 每行格式)
#   plain : ip:port
#   scheme: scheme://ip:port
#   colon : ip:port:Country
SOURCES = {
    "http.txt":          ("http",   "plain"),
    "monosans.txt":      ("http",   "plain"),
    "socks5.txt":        ("socks5", "plain"),
    "monosansSocks5.txt":("socks5", "plain"),
    "big1.txt":          ("socks4", "plain"),
    "big2.txt":          ("socks5", "scheme"),
    "big3.txt":          ("socks5", "colon"),
    "big4.txt":          ("http",   "colon"),   # hideip.me 的 https.txt 是支持 CONNECT 的 http 代理
    "big5.txt":          ("http",   "colon"),
}

_tls = threading.local()


def tmpfile():
    if not hasattr(_tls, "path"):
        fd, p = tempfile.mkstemp(prefix="up_", dir=D)
        os.close(fd)
        _tls.path = p
    return _tls.path


def parse(line, fmt):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if fmt == "scheme":
        if "://" not in line:
            return None
        sch, _, host = line.partition("://")
        if host.count(":") != 1 or not host.split(":")[1].isdigit():
            return None
        return host, sch.lower()
    if fmt == "colon":
        parts = line.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            return None
        return f"{parts[0]}:{parts[1]}", None
    # plain
    if line.count(":") != 1 or not line.split(":")[1].isdigit():
        return None
    return line, None


def probe(item, timeout=10):
    """offset 0 段探测，验证拿到 PE 头 4D5A。"""
    host, scheme = item
    out = tmpfile()
    with open(out, "wb"):
        pass
    cmd = ["curl.exe", "-s", "-o", out, "-w", "%{http_code}",
           "--proxy", f"{scheme}://{host}", "--connect-timeout", "6",
           "--max-time", str(timeout), "-r", "0-1023", URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 4)
        code = r.stdout.strip()[:3]
        sig = ""
        if os.path.exists(out) and os.path.getsize(out) >= 2:
            with open(out, "rb") as f:
                sig = f.read(2).hex().upper()
        return host, scheme, code, sig
    except Exception:
        return host, scheme, "ERR", ""


def bench(item):
    host, scheme, idx = item
    a, b = idx * CHUNK, (idx + 1) * CHUNK - 1
    t0 = time.time()
    cmd = ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code} %{size_download}",
           "--proxy", f"{scheme}://{host}", "--connect-timeout", "8",
           "--max-time", "20", "-r", f"{a}-{b}", URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=24)
        c, s = (r.stdout.split() + ["0", "0"])[:2]
        el = max(time.time() - t0, .01)
        return host, scheme, c, int(s), int(s) / el / 1024 / 1024
    except Exception:
        return host, scheme, "ERR", 0, 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=250)
    a = ap.parse_args()

    cands, seen = [], set()
    for fn, (def_scheme, fmt) in SOURCES.items():
        p = os.path.join(D, fn)
        if not os.path.exists(p):
            continue
        n0 = len(cands)
        for line in open(p, encoding="utf-8", errors="ignore"):
            got = parse(line, fmt)
            if not got:
                continue
            host, sch = got
            sch = sch or def_scheme
            key = (host, sch)
            if key in seen:
                continue
            seen.add(key)
            cands.append((host, sch))
        print(f"  {fn:<22} {def_scheme:<7} +{len(cands)-n0}")

    byh = {}
    for h, s in cands:
        byh[s] = byh.get(s, 0) + 1
    print(f"\n候选合计 {len(cands)} 个  {byh}\n探测中（{a.workers} 并发）…", flush=True)

    alive = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, (host, sch, code, sig) in enumerate(ex.map(probe, cands), 1):
            if code in ("206", "200") and sig == "4D5A":
                alive.append((host, sch))
            if i % 2000 == 0:
                print(f"  探测 {i}/{len(cands)}，命中 {len(alive)}", flush=True)

    print(f"\n可用 {len(alive)} 个，测速中…", flush=True)
    bitems = [(h, s, i) for i, (h, s) in enumerate(alive)]
    ranked = []
    with cf.ThreadPoolExecutor(max_workers=min(a.workers, 150)) as ex:
        for i, (host, sch, code, size, mb) in enumerate(ex.map(bench, bitems), 1):
            if code in ("206", "200") and size > 0:
                ranked.append((host, sch, mb))
            if i % 100 == 0:
                print(f"  测速 {i}/{len(bitems)}，有效 {len(ranked)}", flush=True)

    ranked.sort(key=lambda x: -x[2])
    out = os.path.join(D, "ranked.txt")
    with open(out, "w", encoding="utf-8") as f:
        for host, sch, mb in ranked:
            f.write(f"{sch}://{host}\t{mb:.3f}\n")

    print(f"\n=== 写入 {out}：{len(ranked)} 个 ===")
    for host, sch, mb in ranked[:20]:
        print(f"  {sch}://{host:<26} {mb:5.2f} MB/s")
    for th in (.1, .3, .5, 1.0):
        print(f"  >{th:>4}MB/s : {len([r for r in ranked if r[2] > th])} 个")


if __name__ == "__main__":
    main()
