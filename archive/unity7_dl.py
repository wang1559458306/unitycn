#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unity 7 编辑器高速下载器（无需 VPN / 境外 VPS）
================================================
背景（本机实测，2026-11-22）：
  * Unity 官方 CDN download.unity3d.com 对中国大陆 IP 一律 302 到
    download.unitychina.cn，而中国 CDN 并不存放国际版编辑器 —— 直接 404。
    所以 Hub 里"验证失败/进度条不动"不是网络慢，是被重定向到了空仓库。
  * 但同一个 URL 走非大陆出口就是 206 + 真字节（实测前两字节 4D5A = PE 头）。
  * 免费公开 SOCKS5/HTTP 代理单线程只有 0.2~0.8 MB/s，
    但单代理开 96 并发能到 4~6.5 MB/s —— 瓶颈是单连接限速，不是总带宽。

因此策略：小分片 + 高并发 + 代理池轮换 + 断点续传。

用法：
  python unity7_dl.py --version 7000.0.0a20
  python unity7_dl.py                              # 默认最新 7.0 alpha
  python unity7_dl.py --workers 128 --chunk 2
  python unity7_dl.py --check-only                 # 只查元数据不下载
"""
import argparse, base64, hashlib, json, os, random, shutil, subprocess, sys
import tempfile, threading, time, urllib.request
import concurrent.futures as cf

API = ("https://services.api.unity.com/unity/editor/release/v1/releases"
       "?limit=25&offset={off}&order=RELEASE_DATE_DESC"
       "&platform=WINDOWS&architecture=X86_64{stream}")


# ---------------------------------------------------------------- 元数据
def find_release(version=None, stream=None, arch="X86_64"):
    """从 Unity 官方公开 API 查版本 / 直链 / 字节数 / MD5。"""
    st = f"&stream={stream}" if stream else ""
    for off in range(0, 1000, 25):
        url = API.format(off=off, stream=st)
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        res = data.get("results", [])
        if not res:
            break
        for v in res:
            if version and v["version"] != version:
                continue
            if not version and not version and not (
                    v["version"].startswith("7000.") or v["version"].startswith("6000.")):
                continue
            for d in v["downloads"]:
                if d.get("platform") == "WINDOWS" and d.get("architecture") == arch:
                    integ = d.get("integrity", "")
                    md5 = base64.b64decode(integ[4:]).hex() if integ.startswith("md5-") else ""
                    return {"version": v["version"], "url": d["url"],
                            "size": d["downloadSize"]["value"], "md5": md5}
    raise SystemExit(f"官方 API 里找不到版本 {version or '(默认)'}")


# ---------------------------------------------------------------- 代理池
class ProxyPool:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.items = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                px, _, spd = line.partition("\t")
                self.items.append({"proxy": px, "speed": float(spd or 0), "fail": 0})
        self.items.sort(key=lambda x: -x["speed"])
        self.alive = [i for i in self.items if i["fail"] < 3]

    def pick(self):
        with self.lock:
            pool = [i for i in self.items if i["fail"] < 3]
            if not pool:
                for i in self.items:
                    i["fail"] = 0
                pool = self.items
            # 前 40% 的代理里随机挑，避免全挤在一个出口
            head = pool[:max(3, len(pool) * 2 // 5)]
            return random.choice(head)["proxy"]

    def report(self, proxy, ok):
        with self.lock:
            for i in self.items:
                if i["proxy"] == proxy:
                    i["fail"] = max(0, i["fail"] - 1) if ok else i["fail"] + 1
                    break


# ---------------------------------------------------------------- 分片
def fetch_chunk(args):
    """下载分片 [start,end]，出错换代理重试。返回 (idx, ok)。"""
    idx, start, end, url, pool, workdir, retries = args
    path = os.path.join(workdir, f"p{idx:05d}")
    want = end - start + 1

    for attempt in range(retries):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have >= want:
            return idx, True
        a, b = (start + have, end) if 0 < have < want else (start, end)
        if have >= want:
            have = 0

        proxy = pool.pick()
        # curl 的 -C 与 -r 互斥，所以自己算绝对偏移，只发 -r，stdout 追加写。
        cmd = ["curl.exe", "-s", "--proxy", proxy,
               "--connect-timeout", "8", "--max-time", "70",
               "--speed-limit", "4096", "--speed-time", "12",
               "-r", f"{a}-{b}", url]
        try:
            with open(path, "ab" if have else "wb") as fh:
                subprocess.run(cmd, stdout=fh, stderr=subprocess.DEVNULL, timeout=85)
        except (subprocess.TimeoutExpired, OSError):
            pass

        got = os.path.getsize(path) if os.path.exists(path) else 0
        pool.report(proxy, got > have)
        if got >= want:
            return idx, True
        time.sleep(min(0.4 * (attempt + 1), 2.5))
    return idx, False


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None)
    ap.add_argument("--stream", default=None)
    ap.add_argument("--arch", default="X86_64", choices=["X86_64", "ARM64"])
    ap.add_argument("--chunk", type=int, default=2, help="分片 MB（默认 2）")
    ap.add_argument("--workers", type=int, default=96, help="并发数（默认 96）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pool", default=None)
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()

    rel = find_release(a.version, a.stream, a.arch)
    out = a.out or f"UnitySetup64-{rel['version']}.exe"
    print("=" * 72)
    print(f"Unity {rel['version']}")
    print(f"大小  {human(rel['size'])} ({rel['size']} 字节)")
    print(f"MD5   {rel['md5'] or '官方未提供'}")
    print(f"直链  {rel['url']}")
    print("=" * 72, flush=True)
    if a.check_only:
        return 0

    pool_path = a.pool or os.path.join(tempfile.gettempdir(), "unity7", "ranked.txt")
    if not os.path.exists(pool_path):
        raise SystemExit(f"缺代理池 {pool_path}\n先运行: python probe_proxies.py && python speedtest.py")
    pool = ProxyPool(pool_path)
    print(f"代理池 {len(pool.items)} 个", flush=True)

    chunk = a.chunk * 1024 * 1024
    workdir = out + ".parts"
    os.makedirs(workdir, exist_ok=True)
    chunks = [(i, s, min(s + chunk - 1, rel["size"] - 1), rel["url"], pool, workdir, 10)
              for i, s in enumerate(range(0, rel["size"], chunk))]
    print(f"分片 {len(chunks)} × {a.chunk}MB，并发 {a.workers}", flush=True)

    t0 = time.time()
    done = [0]
    lock = threading.Lock()
    failed = []

    def run(c):
        idx, ok = fetch_chunk(c)
        with lock:
            if ok:
                done[0] += c[2] - c[1] + 1
            else:
                failed.append(idx)
            d = done[0]
            el = max(time.time() - t0, .01)
            spd = d / el
            eta = (rel["size"] - d) / spd if spd > 0 else 0
            print(f"\r{d/rel['size']*100:5.1f}%  {human(d)}/{human(rel['size'])}  "
                  f"{human(spd)}/s  ETA {eta/60:4.1f}min  失败{len(failed)}",
                  end="", flush=True)
        return ok

    # 失败分片再补跑一轮
    for rnd in range(3):
        if rnd:
            print(f"\n第 {rnd+1} 轮补跑 {len(failed)} 个分片…", flush=True)
            chunks = [(i, s, e) for (i, s, e, *_ ) in chunks if i in failed]
            failed.clear()
            chunks = [(i, s, e, rel["url"], pool, workdir, 10) for i, s, e in
                      ((c[0], c[1], c[2]) for c in chunks)]
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(run, chunks))
        if not failed:
            break

    print()
    if failed:
        print(f"仍有 {len(failed)} 个分片失败：{failed[:15]}")
        print("重跑同一命令即可续传（已完成分片保留在 %s）" % workdir)
        return 1

    print("拼接中…", flush=True)
    with open(out, "wb") as w:
        for i in range(len(range(0, rel["size"], chunk))):
            p = os.path.join(workdir, f"p{i:05d}")
            with open(p, "rb") as r:
                shutil.copyfileobj(r, w, 8 * 1024 * 1024)

    got = os.path.getsize(out)
    print(f"输出 {os.path.abspath(out)}  {human(got)}")
    if got != rel["size"]:
        print(f"!! 大小不符，期望 {rel['size']}")
        return 1
    if rel["md5"]:
        print("校验 MD5…", flush=True)
        h = hashlib.md5()
        with open(out, "rb") as f:
            for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(b)
        d = h.hexdigest()
        ok = d == rel["md5"]
        print(f"  MD5 {d}\n  期望 {rel['md5']}\n{'✅ 校验通过' if ok else '❌ 校验失败'}")
        if not ok:
            return 1
    print(f"\n完成，用时 {(time.time()-t0)/60:.1f} 分钟")
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
