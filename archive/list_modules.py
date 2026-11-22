#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""递归展开 Unity 版本的所有模块（含 subModules 的 subModules），输出下载清单。"""
import json, sys, urllib.request

API = ("https://services.api.unity.com/unity/editor/release/v1/releases"
       "?limit=25&offset=0&order=RELEASE_DATE_DESC"
       "&platform=WINDOWS&architecture=X86_64&stream=ALPHA")


def walk(mods, out, parent=""):
    for m in mods or []:
        rec = {
            "id": m.get("id"),
            "name": m.get("name"),
            "url": m.get("url") or m.get("downloadUrl"),
            "size": (m.get("downloadSize") or {}).get("value", 0),
            "integrity": m.get("integrity", ""),
            "parent": parent,
            "category": m.get("category", ""),
        }
        out.append(rec)
        walk(m.get("subModules"), out, m.get("id"))


with urllib.request.urlopen(API, timeout=30) as r:
    data = json.load(r)

v = next(x for x in data["results"] if x["version"] == "7000.0.0a20")
d = next(x for x in v["downloads"]
         if x["platform"] == "WINDOWS" and x["architecture"] == "X86_64")

out = []
walk(d.get("modules"), out)
print(f"共 {len(out)} 个条目\n")
for r in out:
    mb = r["size"] / 1024 / 1024 if r["size"] else 0
    print(f"[{r['id']}]  {mb:8.2f} MB  parent={r['parent'] or '-'}")
    print(f"    {r['name']}")
    print(f"    {r['url']}")
    if r["integrity"]:
        print(f"    {r['integrity']}")
    print()

json.dump(out, open("modules.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("清单已写 modules.json")
