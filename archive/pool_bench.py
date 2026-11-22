#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用新代理池测并发叠加能力：多代理混跑 vs 单代理多线程。"""
import subprocess, concurrent.futures as cf, time, os, tempfile

URL = ("https://download.unity3d.com/download_unity/f4e960bd2f88/"
       "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")
CH = 2 * 1024 * 1024
D = os.path.join(tempfile.gettempdir(), "unity7")


def load_pool():
    out = []
    for line in open(os.path.join(D, "ranked.txt"), encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        px, _, spd = line.partition("\t")
        out.append((px, float(spd or 0)))
    return out


def one(item, dur=20):
    px, idx = item
    a, b = idx * CH, (idx + 1) * CH - 1
    t0 = time.time()
    cmd = ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code} %{size_download}",
           "--proxy", px, "--connect-timeout", "8", "--max-time", str(dur),
           "-r", f"{a}-{b}", URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=dur + 6)
        c, s = (r.stdout.split() + ["0", "0"])[:2]
        return int(s) if c in ("200", "206") else 0
    except Exception:
        return 0


def bench(pool, n, label, per_proxy=1):
    """pool 前 n 个代理，每个开 per_proxy 条连接。"""
    tasks = []
    for i in range(n):
        for k in range(per_proxy):
            tasks.append((pool[i % len(pool)][0], i * per_proxy + k))
    t0 = time.time()
    tot = 0
    with cf.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        for s in ex.map(one, tasks):
            tot += s
    el = max(time.time() - t0, .01)
    print(f"{label:<34} {len(tasks):3d} conns  {tot/1024/1024:7.1f}MB  "
          f"{tot/el/1024/1024:5.2f} MB/s", flush=True)
    return tot / el / 1024 / 1024


pool = load_pool()
print(f"代理池 {len(pool)} 个，前 5: {[f'{p}({s:.2f})' for p, s in pool[:5]]}\n")

bench(pool, 1,  "最快代理 ×1")
bench(pool, 3,  "前3代理 ×1")
bench(pool, 5,  "前5代理 ×1")
bench(pool, 10, "前10代理 ×1")
bench(pool, 20, "前20代理 ×1")
bench(pool, 5,  "前5代理 ×8连接", per_proxy=8)
bench(pool, 10, "前10代理 ×8连接", per_proxy=8)
