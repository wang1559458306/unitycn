#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量测试公开 HTTP/SOCKS5 代理能否真正取到 Unity 国际版 CDN 的字节。
只发 Range 0-1023 的段请求，命中即打印可用的代理地址 + 首字节签名。
"""
import os, sys, subprocess, tempfile, concurrent.futures as cf

URL = ("https://download.unity3d.com/download_unity/f4e960bd2f88/"
       "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")

HOME = os.path.expanduser("~")
CAND_DIRS = [os.path.join(tempfile.gettempdir(), "unity7")]


def load(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        return []


def test(proxy, scheme):
    out = os.path.join(tempfile.gettempdir(), "unity7probe.bin")
    px = f"{scheme}://{proxy}"
    cmd = ["curl.exe", "-s", "-o", out, "-w", "%{http_code} %{size_download}",
           "--proxy", px, "--max-time", "10", "-r", "0-1023", URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        code, size = (r.stdout.strip().split() + ["0", "0"])[:2]
        sig = ""
        if os.path.exists(out) and os.path.getsize(out) >= 2:
            with open(out, "rb") as f:
                sig = f.read(2).hex().upper()
        return proxy, scheme, code, size, sig
    except Exception as e:
        return proxy, scheme, "ERR", "0", str(e)[:40]


def main():
    http_list, socks_list = [], []
    for d in CAND_DIRS:
        http_list += load(os.path.join(d, "http.txt"))
        http_list += load(os.path.join(d, "monosans.txt"))
        socks_list += load(os.path.join(d, "socks5.txt"))

    def clean(lst):
        seen, out = set(), []
        for x in lst:
            if x.count(":") == 1 and x.split(":")[1].isdigit() and x not in seen:
                seen.add(x); out.append(x)
        return out

    http_list, socks_list = clean(http_list), clean(socks_list)
    print(f"HTTP 候选 {len(http_list)}  SOCKS5 候选 {len(socks_list)}", flush=True)

    jobs = [(p, "http") for p in http_list] + [(p, "socks5") for p in socks_list]
    good = []
    with cf.ThreadPoolExecutor(max_workers=150) as ex:
        futs = [ex.submit(test, p, s) for p, s in jobs]
        for i, f in enumerate(cf.as_completed(futs), 1):
            proxy, scheme, code, size, sig = f.result()
            if code in ("200", "206") and size not in ("0", ""):
                good.append((proxy, scheme, code, size, sig))
                print(f"[HIT] {scheme}://{proxy}  code={code} size={size} sig={sig}", flush=True)
            if i % 500 == 0:
                print(f"...已测 {i}/{len(jobs)}，命中 {len(good)}", flush=True)

    print(f"\n总计命中 {len(good)} 个可用代理")
    with open(os.path.join(tempfile.gettempdir(), "unity7", "working.txt"), "w") as f:
        for g in good:
            f.write(f"{g[1]}://{g[0]}\n")


if __name__ == "__main__":
    main()
