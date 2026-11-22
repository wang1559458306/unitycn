"""
unitycn CLI —— 命令行入口

    python -m unitycn pool     --out pool.txt          # 建代理池
    python -m unitycn versions --alpha                 # 列版本
    python -m unitycn fetch    --version 7000.0.0a20   # 下编辑器
    python -m unitycn modules  --version 7000.0.0a20   # 列模块
    python -m unitycn fetchm   --version 7000.0.0a20 --only android,windows-il2cpp
    python -m unitycn doctor                           # 环境诊断
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .downloader import Job, download, md5_file
from .pool import Pool
from .sources import SOURCES
from .unity import (BLOCKED_HOSTS, find_release, hub_releases, human,
                    list_modules)


def _pool(path: str | None) -> Pool | None:
    if path and os.path.exists(path):
        p = Pool.load(path)
        print(f"代理池 {len(p)} 个（存活 {p.alive}）", file=sys.stderr)
        return p
    return None


def cmd_pool(a):
    from . import build_pool
    build_pool(a.out, workers=a.workers)


def cmd_versions(a):
    stream = "ALPHA" if a.alpha else ("BETA" if a.beta else None)
    rel = find_release(None if a.alpha else a.version, stream=stream)
    print(f"最新 {rel.version}  {rel.release_date[:10]}")
    print(f"  {human(rel.size)}  md5={rel.md5}")
    print(f"  {rel.url}")


def cmd_fetch(a):
    stream = "ALPHA" if a.alpha else None
    rel = find_release(a.version, stream=stream)
    out = a.out or rel.filename
    print(f"{rel.version}  {human(rel.size)}  md5={rel.md5 or '-'}")
    print(f"{rel.url}\n")
    pool = _pool(a.pool)

    def prog(done, total, el):
        pct = done / total * 100 if total else 0
        spd = done / el if el else 0
        eta = (total - done) / spd if spd else 0
        print(f"\r{pct:5.1f}%  {human(done)}/{human(total)}  "
              f"{human(spd)}/s  ETA {eta/60:4.1f}min", end="", flush=True)

    res = download(Job(rel.url, out, rel.size,
                       f"md5-{_b64md5(rel.md5)}" if rel.md5 else "",
                       workers=a.workers, chunk_mb=a.chunk), pool, prog)
    print()
    print(f"路线 {res.route}；{human(res.bytes)} / {res.seconds/60:.1f}min "
          f"= {res.mbps:.2f} MB/s")
    if res.verified is True:
        print("MD5 校验通过")
    elif res.verified is False:
        print("!! MD5 校验失败")
    print("完成" if res.ok else f"失败，缺失分片 {res.failed_chunks}")
    return 0 if res.ok else 1


def _b64md5(hexmd5: str) -> str:
    import base64
    return base64.b64encode(bytes.fromhex(hexmd5)).decode()


def cmd_modules(a):
    mods = list_modules(a.version, stream="ALPHA" if a.alpha else None)
    print(f"{len(mods)} 个条目\n")
    for m in mods:
        mb = m["size"] / 1024 / 1024
        flag = "  " if m["url"] else "× "
        par = f" ←{m['parent']}" if m["parent"] else ""
        print(f"{flag}{m['id']:<38} {mb:8.1f} MB  {m['name']}{par}")


def cmd_fetchm(a):
    stream = "ALPHA" if a.alpha else None
    mods = {m["id"]: m for m in list_modules(a.version, stream=stream)}
    ids = ([x.strip() for x in a.only.split(",")] if a.only
           else [k for k, m in mods.items() if m["size"] > 1000 and m["url"]])
    pool = _pool(a.pool)
    ok = 0
    for k in ids:
        m = mods.get(k)
        if not m:
            print(f"跳过未知 id：{k}")
            continue
        if not m["url"] or m["size"] < 1000:
            print(f"跳过 {k}（占位或无直链）")
            continue
        fn = m["url"].split("?")[0].rsplit("/", 1)[-1]
        print(f"\n>>> {k}  {m['name']}  {human(m['size'])}")
        res = download(Job(m["url"], os.path.join(a.outdir, fn),
                           m["size"], m["integrity"],
                           workers=a.workers, chunk_mb=a.chunk), pool)
        tag = "OK" if res.ok else "FAIL"
        ver = {True: " 校验通过", False: " 校验失败", None: ""}[res.verified]
        print(f"    [{tag}] {res.route}  {res.mbps:.2f} MB/s{ver}")
        ok += bool(res.ok)
    print(f"\n完成 {ok}/{len(ids)}")
    return 0 if ok == len(ids) else 1


def cmd_doctor(a):
    from .downloader import _probe_direct
    from .probe import probe

    print(f"unitycn {__version__}")
    print(f"Python {sys.version.split()[0]}")
    ok = True

    import shutil as sh
    curl = sh.which("curl") or sh.which("curl.exe")
    print(f"curl    {curl or '缺失'}")
    ok &= bool(curl)

    print("\n直连可达性：")
    checks = [
        ("Unity 元数据 API", "https://services.api.unity.com/unity/editor/release/v1/releases?limit=1"),
        ("Hub 发布清单", "https://public-cdn.cloud.unity3d.com/hub/prod/releases-win32.json"),
        ("Google SDK 源", "https://dl.google.com/android/repository/cmake-3.22.1-windows.zip"),
        ("Microsoft VS 源", "https://aka.ms/vs/18/stable/vs_community.exe"),
        ("Unity 下载 CDN", "https://download.unity3d.com/download_unity/f4e960bd2f88/Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe"),
    ]
    for name, url in checks:
        code, sig = _probe_direct(url, timeout=10)
        mark = "OK" if code in ("200", "206") else f"拦({code})"
        extra = f" sig={sig}" if sig else ""
        print(f"  {name:<18} {mark}{extra}")

    print("\n被区域重定向的主机：")
    for h in BLOCKED_HOSTS:
        print(f"  {h}")

    print("\n提示：Unity 下载 CDN 显示“拦(302)”属预期 —— 该走代理或本地分片。")
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="unitycn", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-V", "--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pool", help="抓取并测试代理，产出池文件")
    sp.add_argument("--out", default="pool.txt")
    sp.add_argument("--workers", type=int, default=200)
    sp.set_defaults(func=cmd_pool)

    sv = sub.add_parser("versions", help="查询版本与直链")
    sv.add_argument("version", nargs="?")
    sv.add_argument("--alpha", action="store_true")
    sv.add_argument("--beta", action="store_true")
    sv.set_defaults(func=cmd_versions)

    sf = sub.add_parser("fetch", help="下载编辑器")
    sf.add_argument("--version", default=None)
    sf.add_argument("--alpha", action="store_true")
    sf.add_argument("--out")
    sf.add_argument("--pool")
    sf.add_argument("--workers", type=int, default=96)
    sf.add_argument("--chunk", type=int, default=2)
    sf.set_defaults(func=cmd_fetch)

    sm = sub.add_parser("modules", help="列出某版本全部模块")
    sm.add_argument("--version", required=True)
    sm.add_argument("--alpha", action="store_true")
    sm.set_defaults(func=cmd_modules)

    fm = sub.add_parser("fetchm", help="下载模块")
    fm.add_argument("--version", required=True)
    fm.add_argument("--alpha", action="store_true")
    fm.add_argument("--only", help="逗号分隔的模块 id")
    fm.add_argument("--outdir", default="modules")
    fm.add_argument("--pool")
    fm.add_argument("--workers", type=int, default=96)
    fm.add_argument("--chunk", type=int, default=2)
    fm.set_defaults(func=cmd_fetchm)

    sd = sub.add_parser("doctor", help="环境与连通性诊断")
    sd.set_defaults(func=cmd_doctor)

    a = p.parse_args(argv)
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
