#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二阶段：对已命中代理做吞吐测速，按速度排序输出可用隧道。
每个代理下载 4MB，超过 1MB/s 的进入第一梯队。
"""
import os, tempfile, subprocess, concurrent.futures as cf, time

URL = ("https://download.unity3d.com/download_unity/f4e960bd2f88/"
       "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")
CHUNK = 4 * 1024 * 1024


def speed_test(arg):
    proxy, scheme = arg
    px = f"{scheme}://{proxy}"
    start = time.time()
    cmd = ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code} %{size_download}",
           "--proxy", px, "--max-time", "25", "-r", f"0-{CHUNK - 1}", URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        parts = (r.stdout.strip().split() + ["0", "0"])[:2]
        code, size = parts[0], int(parts[1])
        dur = max(time.time() - start, 0.01)
        mbps = size / dur / 1024 / 1024
        return proxy, scheme, code, size, mbps
    except Exception:
        return proxy, scheme, "ERR", 0, 0.0


def main():
    path = os.path.join(tempfile.gettempdir(), "unity7", "working.txt")
    lines = [l.strip() for l in open(path) if l.strip()]
    jobs = []
    for l in lines:
        if "://" in l:
            s, p = l.split("://", 1)
            jobs.append((p, s))
    print(f"待测速代理 {len(jobs)} 个，每个拉 4MB", flush=True)

    results = []
    with cf.ThreadPoolExecutor(max_workers=60) as ex:
        for i, r in enumerate(ex.map(speed_test, jobs), 1):
            if r[2] == "206" and r[4] > 0:
                results.append(r)
            if i % 40 == 0:
                top = sorted(results, key=lambda x: -x[4])[:3]
                print(f"...{i}/{len(jobs)}  当前最好: "
                      + ", ".join(f"{t[1]}://{t[0]}={t[4]:.2f}MB/s" for t in top), flush=True)

    results.sort(key=lambda x: -x[4])
    print(f"\n=== 全部 {len(results)} 个可用，速度排序 Top 20 ===")
    for r in results[:20]:
        print(f"{r[1]}://{r[0]:<24} {r[4]:6.2f} MB/s")

    out = os.path.join(tempfile.gettempdir(), "unity7", "ranked.txt")
    with open(out, "w") as f:
        for r in results:
            f.write(f"{r[1]}://{r[0]}\t{r[4]:.3f}\n")
    print(f"\n已写 {out}")
    fast = [r for r in results if r[4] > 1.0]
    print(f"超过 1MB/s 的代理: {len(fast)} 个；超过 3MB/s: {len([r for r in results if r[4] > 3])} 个")


if __name__ == "__main__":
    main()
