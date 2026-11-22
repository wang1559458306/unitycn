#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unity 模块批量下载器
=====================
按 modules.json 清单并发下载多个文件，每个文件独立分片 + 独立代理池。

关键设计：
  * 直连优先：Google / Microsoft 的地址在国内能直连且很快（实测 9MB/s），
    只有 Unity CDN 的地址会被 302 到空仓库，需要走代理。
  * 自动判别：先试直连，拿到 206 且首两字节是 MZ/PK 就用直连（多线程叠加），
    否则自动切代理池。
  * 每个文件独立断点续传，中断后重跑本命令即可。

用法：
  python fetch_modules.py --only android,windows-il2cpp,jdk,vs
  python fetch_modules.py --all
  python fetch_modules.py --list
"""
import argparse, base64, hashlib, json, os, random, shutil, subprocess, sys
import tempfile, threading, time, urllib.request
import concurrent.futures as cf

D = os.path.join(tempfile.gettempdir(), "unity7")
CHUNK = 2 * 1024 * 1024          # 2MB 分片
HERE = os.path.dirname(os.path.abspath(__file__))


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def md5_of(integrity):
    """integrity 形如 md5-<base64> 或 sha384-<base64>，返回 (算法, hex)。"""
    if not integrity or "-" not in integrity:
        return None, None
    alg, _, b64 = integrity.partition("-")
    if alg not in ("md5", "sha384", "sha256"):
        return None, None
    try:
        return alg, base64.b64decode(b64).hex()
    except Exception:
        return None, None


# ------------------------------------------------------------ 代理池
class Pool:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.items = []
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                px, _, spd = line.partition("\t")
                self.items.append({"p": px, "s": float(spd or 0), "f": 0})
            self.items.sort(key=lambda x: -x["s"])

    def pick(self):
        with self.lock:
            live = [i for i in self.items if i["f"] < 4]
            if not live:
                for i in self.items:
                    i["f"] = 0
                live = self.items
            if not live:
                return None
            return random.choice(live[:max(3, len(live) * 2 // 5)])["p"]

    def bad(self, p):
        with self.lock:
            for i in self.items:
                if i["p"] == p:
                    i["f"] += 1
                    break


# ------------------------------------------------------------ 探测
def probe(url, proxy=None, timeout=12):
    """返回 (ok, 首两字节hex)。直连或经代理试探前 64 字节。"""
    out = os.path.join(D, f"probe_{threading.get_ident()}.bin")
    cmd = ["curl.exe", "-s", "-o", out, "-w", "%{http_code}",
           "--connect-timeout", "6", "--max-time", str(timeout), "-r", "0-63", url]
    if proxy:
        cmd[1:1] = ["--proxy", proxy]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        code = r.stdout.strip()[:3]
        sig = ""
        if os.path.exists(out) and os.path.getsize(out) >= 2:
            with open(out, "rb") as f:
                sig = f.read(2).hex().upper()
            os.remove(out)
        return code in ("200", "206"), sig
    except Exception:
        return False, ""


# ------------------------------------------------------------ 分片下载
def fetch_chunk(job):
    idx, start, end, url, pool, use_proxy, workdir, retries = job
    path = os.path.join(workdir, f"c{idx:05d}")
    want = end - start + 1

    for attempt in range(retries):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have >= want:
            return idx, True
        a = start + have if 0 < have < want else start
        if have >= want:
            have = 0
        b = end

        px = pool.pick() if (use_proxy and pool and pool.items) else None
        cmd = ["curl.exe", "-s", "--connect-timeout", "8",
               "--max-time", "70", "--speed-limit", "4096", "--speed-time", "12",
               "-r", f"{a}-{b}", url]
        if px:
            cmd[1:1] = ["--proxy", px]
        try:
            with open(path, "ab" if have else "wb") as fh:
                subprocess.run(cmd, stdout=fh, stderr=subprocess.DEVNULL, timeout=85)
        except (subprocess.TimeoutExpired, OSError):
            pass

        got = os.path.getsize(path) if os.path.exists(path) else 0
        if px and got <= have:
            pool.bad(px)
        if got >= want:
            return idx, True
        time.sleep(min(0.4 * (attempt + 1), 2.5))
    return idx, False


def download_one(name, url, size, integrity, outdir, pool, workers, chunk_mb):
    out = os.path.join(outdir, name)
    if os.path.exists(out) and size and os.path.getsize(out) == size:
        print(f"  [{name}] 已存在且大小正确，跳过", flush=True)
        return True

    # 决定直连还是代理
    ok, sig = probe(url)
    use_proxy = not (ok and sig in ("4D5A", "504B", "1F8B"))
    route = "直连" if not use_proxy else "代理池"
    print(f"  [{name}] {human(size)}  首字节测试={'通过' if ok else '失败'} sig={sig or '-'} → 用{route}",
          flush=True)

    chunk = chunk_mb * 1024 * 1024
    workdir = out + ".parts"
    os.makedirs(workdir, exist_ok=True)
    chunks = [(i, s, min(s + chunk - 1, size - 1), url, pool, use_proxy, workdir, 10)
              for i, s in enumerate(range(0, size, chunk))]

    t0 = time.time()
    done = [0]
    lock = threading.Lock()
    failed = []

    def run(c):
        idx, o = fetch_chunk(c)
        with lock:
            if o:
                done[0] += c[2] - c[1] + 1
            else:
                failed.append(idx)
        return o

    for rnd in range(3):
        todo = chunks if rnd == 0 else [c for c in chunks if c[0] in failed]
        if not todo:
            break
        if rnd:
            print(f"    [{name}] 第 {rnd+1} 轮补跑 {len(todo)} 片…", flush=True)
            failed.clear()
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(run, todo))
        if not failed:
            break

    el = max(time.time() - t0, .01)
    if failed:
        print(f"    [{name}] 失败 {len(failed)} 片：{failed[:10]}")
        return False

    with open(out, "wb") as w:
        for i in range(len(chunks)):
            with open(os.path.join(workdir, f"c{i:05d}"), "rb") as r:
                shutil.copyfileobj(r, w, 8 * 1024 * 1024)
    shutil.rmtree(workdir, ignore_errors=True)

    got = os.path.getsize(out)
    print(f"    [{name}] 完成 {human(got)}  用时 {el/60:.1f}min  "
          f"均速 {human(got/el)}/s", flush=True)
    if size and got != size:
        print(f"    !! 大小不符，期望 {human(size)}")
        return False

    alg, want = md5_of(integrity)
    if alg and want:
        h = hashlib.new(alg)
        with open(out, "rb") as f:
            for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(b)
        d = h.hexdigest()
        if d == want:
            print(f"    [{name}] {alg.upper()} 校验通过", flush=True)
        else:
            print(f"    [{name}] !! {alg.upper()} 不符\n      实际 {d}\n      期望 {want}", flush=True)
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="逗号分隔的 id 列表")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--workers", type=int, default=96)
    ap.add_argument("--chunk", type=int, default=2)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--pool", default=None)
    a = ap.parse_args()

    mods_path = os.path.join(HERE, "modules.json")
    if not os.path.exists(mods_path):
        raise SystemExit("缺 modules.json，先跑 python list_modules.py")
    mods = {m["id"]: m for m in json.load(open(mods_path, encoding="utf-8"))}

    if a.list:
        for k, m in mods.items():
            print(f"{k:<40} {m['size']/1024/1024:9.2f} MB  {m['name']}")
        return 0

    # 只取"用户截图里勾选的那 4 项"及其依赖
    default = ["android", "android-open-jdk-17.0.21+9", "windows-il2cpp",
               "visualstudio"]
    # Android SDK & NDK Tools 的 8 个 Google 组件
    default += [k for k, m in mods.items()
                if m["parent"] == "android-sdk-ndk-tools" and m["size"] > 1000]

    ids = default if not a.only else [x.strip() for x in a.only.split(",")]
    if a.all:
        ids = list(mods.keys())

    outdir = a.outdir or os.path.join(HERE, "modules")
    os.makedirs(outdir, exist_ok=True)
    pool = Pool(a.pool or os.path.join(D, "ranked.txt"))
    print(f"代理池 {len(pool.items)} 个；输出目录 {outdir}\n")

    results = {}
    for k in ids:
        if k not in mods:
            print(f"跳过未知 id: {k}")
            continue
        m = mods[k]
        if not m["url"] or m["size"] < 1000:
            print(f"跳过 {k}（占位/无直链）")
            continue
        fn = m["url"].split("?")[0].split("/")[-1]
        if k == "visualstudio":
            fn = "vs_Community.exe"
        print(f"\n>>> [{k}] {m['name']}")
        results[k] = download_one(fn, m["url"], m["size"], m["integrity"],
                                  outdir, pool, a.workers, a.chunk)

    print("\n" + "=" * 60)
    ok = sum(1 for v in results.values() if v)
    print(f"完成 {ok}/{len(results)}")
    for k, v in results.items():
        print(f"  {'✅' if v else '❌'} {k}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
