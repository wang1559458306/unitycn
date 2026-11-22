#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测单代理并发能力 + 多代理并行叠加是否有效（决定分片并发的参数）。"""
import subprocess, concurrent.futures as cf, time, sys

URL = ("https://download.unity3d.com/download_unity/f4e960bd2f88/"
       "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")
CH = 4 * 1024 * 1024


def one(proxy, idx, dur=20):
    a, b = idx * CH, (idx + 1) * CH - 1
    t0 = time.time()
    cmd = ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code} %{size_download}",
           "--proxy", proxy, "--max-time", str(dur), "-r", f"{a}-{b}", URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=dur + 5)
        code, size = (r.stdout.split() + ["0", "0"])[:2]
        el = max(time.time() - t0, .01)
        return code, int(size), int(size) / el / 1024 / 1024
    except Exception:
        return "ERR", 0, 0.0


def bench(proxies, label):
    t0 = time.time()
    total = 0
    per = []
    tasks = [(p, i) for i, p in enumerate(proxies)]
    with cf.ThreadPoolExecutor(max_workers=len(proxies)) as ex:
        for code, size, mb in ex.map(lambda a: one(*a), tasks):
            total += size
            per.append(round(mb, 2))
    el = max(time.time() - t0, .01)
    print(f"{label}: 总 {total/1024/1024:.1f}MB / {el:.1f}s = "
          f"{total/el/1024/1024:.2f} MB/s   各线程 {per}", flush=True)
    return total / el / 1024 / 1024


TOP = ["socks5://183.106.215.208:1080",
       "socks5://47.251.249.48:7777",
       "http://141.94.22.37:3128",
       "socks5://193.25.215.182:22222"]

print("=== 单代理 1 线程基准 ===")
for p in TOP[:3]:
    c, s, mb = one(p, 0)
    print(f"{p:<34} {c} {s/1024/1024:.1f}MB {mb:.2f} MB/s", flush=True)

print("\n=== 同一代理 4 线程 ===")
bench([TOP[0]] * 4, "单代理×4")

print("\n=== 4 个不同代理各 1 线程 ===")
bench(TOP, "4 代理×1")

print("\n=== 4 个不同代理各 2 线程 ===")
bench(TOP * 2, "4 代理×2")
