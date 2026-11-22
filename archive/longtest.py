import subprocess, concurrent.futures as cf, time
URL=("https://download.unity3d.com/download_unity/f4e960bd2f88/"
     "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")
CH=2*1024*1024
PROXY="socks5://183.106.215.208:1080"
N=256   # 512MB
def one(i,dur=90):
    a,b=i*CH,(i+1)*CH-1
    cmd=["curl.exe","-s","-o","NUL","-w","%{http_code} %{size_download}",
         "--proxy",PROXY,"--max-time",str(dur),"-r",f"{a}-{b}",URL]
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=dur+10)
        c,s=(r.stdout.split()+["0","0"])[:2]
        return c,int(s)
    except Exception: return "ERR",0
t0=time.time(); tot=0; ok=0
with cf.ThreadPoolExecutor(max_workers=96) as ex:
    for c,s in ex.map(one,range(N)):
        tot+=s
        if c in("206","200") and s>0: ok+=1
el=max(time.time()-t0,.01)
print(f"512MB 任务: 成功 {ok}/{N} 分片, {tot/1024/1024:.1f}MB / {el:.1f}s = {tot/el/1024/1024:.2f} MB/s")
print(f"照此速度 3.52GB 需要 {3780208376/(tot/el)/60:.1f} 分钟")
