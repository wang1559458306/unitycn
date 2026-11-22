import subprocess, concurrent.futures as cf, time
URL=("https://download.unity3d.com/download_unity/f4e960bd2f88/"
     "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")
CH=1*1024*1024
PROXY="socks5://183.106.215.208:1080"
def one(i,dur=25):
    a,b=i*CH,(i+1)*CH-1
    cmd=["curl.exe","-s","-o","NUL","-w","%{http_code} %{size_download}",
         "--proxy",PROXY,"--max-time",str(dur),"-r",f"{a}-{b}",URL]
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=dur+5)
        c,s=(r.stdout.split()+["0","0"])[:2]
        return c,int(s)
    except Exception:
        return "ERR",0
for n in (128,200):
    t0=time.time(); tot=0
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        for c,s in ex.map(one,range(n)): tot+=s
    el=max(time.time()-t0,.01)
    print(f"{n:3d} threads: {tot/1024/1024:7.1f}MB / {el:5.1f}s = {tot/el/1024/1024:5.2f} MB/s",flush=True)
