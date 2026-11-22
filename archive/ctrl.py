import subprocess, concurrent.futures as cf, os, tempfile
URL=("https://download.unity3d.com/download_unity/f4e960bd2f88/"
     "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")
D=os.path.join(tempfile.gettempdir(),"unity7")
lst=[l.strip() for l in open(os.path.join(D,"http.txt"),encoding="utf-8",errors="ignore") if l.strip()][:200]
def t(p):
    out=os.path.join(D,f"t{abs(hash(p))%99999}.bin")
    cmd=["curl.exe","-s","-o",out,"-w","%{http_code}","--proxy",f"http://{p}",
         "--max-time","10","-r","0-1023",URL]
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=14)
        sig=""
        if os.path.exists(out) and os.path.getsize(out)>=2:
            sig=open(out,"rb").read(2).hex().upper()
        return p,r.stdout.strip()[:3],sig
    except Exception: return p,"ERR",""
    finally:
        if os.path.exists(out):
            try: os.remove(out)
            except OSError: pass
hit=0
with cf.ThreadPoolExecutor(max_workers=150) as ex:
    for p,c,s in ex.map(t,lst):
        if c in("200","206") and s=="4D5A": hit+=1; print("HIT",p)
print(f"抽样 {len(lst)} 个，命中 {hit} 个")
