import os, shutil, tempfile, threading, uuid
from flask import Flask, request, jsonify, send_file, after_this_request, Response
import yt_dlp
from yt_dlp.networking import Request

app = Flask(__name__)
HAS_FFMPEG = shutil.which("ffmpeg") is not None
jobs = {}
media = {}  # önizleme/kapak için orijinal URL ve gereken başlıklar

BASE = {"noplaylist": True, "quiet": True, "no_warnings": True, "no_color": True}
# Docker'da tarayıcı yok: COOKIES_FILE ile dışa aktarılmış cookies.txt kullanılır
_cf = os.environ.get("COOKIES_FILE")
_cb = os.environ.get("COOKIES_BROWSER", "chrome")
if _cf and os.path.exists(_cf):
    BASE["cookiefile"] = _cf
elif _cb != "none":
    BASE["cookiesfrombrowser"] = (_cb,)

PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Video İndirici</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;background:#f6f7f9;color:#1f2328;display:flex;justify-content:center;padding:64px 16px}
.box{width:100%;max-width:720px}
h1{font-size:24px;font-weight:650;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:#6b7280;font-size:14px;margin:0 0 24px}
form{display:flex;gap:8px;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:6px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
input{flex:1;min-width:0;padding:10px 12px;border:0;outline:0;font-size:15px;background:transparent;color:#1f2328}
input::placeholder{color:#9ca3af}
button{padding:10px 18px;border:0;border-radius:8px;background:#2563eb;color:#fff;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s;white-space:nowrap}
button:hover{background:#1d4ed8}
button:disabled{background:#93b4f3;cursor:default}
.err{color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:10px 12px;margin-top:14px;font-size:14px;word-break:break-word}
.err:empty{display:none}
.card{margin-top:20px;background:#fff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.05);display:none}
.media{background:#0f1115;aspect-ratio:16/9}
.media img,.media video{width:100%;height:100%;object-fit:contain;display:block}
.info{padding:16px 18px}
.title{font-weight:600;font-size:16px;line-height:1.4;margin-bottom:4px}
.meta{color:#6b7280;font-size:13px}
.tabs{display:flex;border-top:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb}
.tab{flex:1;background:none;color:#6b7280;border-radius:0;padding:14px;font-size:15px;border-bottom:2px solid transparent;margin-bottom:-1px}
.tab:hover{background:#f9fafb;color:#1f2328}
.tab.on{color:#1f2328;border-bottom-color:#2563eb}
.row{display:grid;grid-template-columns:1.2fr 1fr 1fr auto;align-items:center;gap:8px;padding:12px 18px;border-bottom:1px solid #f0f1f3}
.row:last-child{border-bottom:0}
.head{background:#f9fafb;color:#6b7280;font-size:13px;padding:10px 18px}
.q{font-weight:600;font-size:15px;display:flex;align-items:center;gap:6px}
.q svg{width:16px;height:16px;color:#9ca3af}
.best .q{color:#2563eb}
.c{color:#6b7280;font-size:14px}
.row button{min-width:96px}
.status{font-size:13px;color:#6b7280;padding:0 18px 14px}
.status:empty{display:none}
.empty{padding:20px 18px;color:#9ca3af;font-size:14px}
@media(max-width:520px){.row{grid-template-columns:1fr 1fr auto}.row .sz{display:none}}
</style></head><body><div class="box">
<h1>Video İndirici</h1><p class="sub">Linki yapıştır, önizle ve istediğin kalitede indir.</p>
<form id="f"><input id="url" placeholder="Video linkini yapıştır" required autofocus><button id="pb">Önizle</button></form>
<div id="err" class="err"></div>
<div id="card" class="card">
  <div class="media" id="media"></div>
  <div class="info"><div class="title" id="title"></div><div class="meta" id="meta"></div></div>
  <div class="tabs"><button class="tab on" data-t="video">Video</button><button class="tab" data-t="audio">Ses</button></div>
  <div id="list"></div>
  <div class="status" id="status"></div>
</div></div>
<script>
const $=id=>document.getElementById(id);
const ON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/></svg>';
const OFF='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="m22 9-6 6M16 9l6 6"/></svg>';
let cur={url:"",video:[],audio:[]},tab="video",busy=false;
const fmtDur=s=>s?new Date(s*1000).toISOString().substr(s>=3600?11:14,s>=3600?8:5):"";
const fmtSize=b=>!b?"—":b>=1048576?(b/1048576).toFixed(2)+" MB":(b/1024).toFixed(0)+" KB";

function render(){
  const rows=cur[tab];
  const h=`<div class="row head"><div>${tab==="video"?"Kalite":"Bit hızı"}</div><div>Format</div><div class="sz">Boyut</div><div></div></div>`;
  $("list").innerHTML=h+(rows.length?rows.map((r,i)=>`<div class="row${i===0?" best":""}">
    <div class="q">${r.label}${tab==="video"?(r.audio?ON:OFF):""}</div>
    <div class="c">${r.ext.toUpperCase()}</div><div class="c sz">${fmtSize(r.size)}</div>
    <div><button data-i="${i}" ${busy?"disabled":""}>İndir</button></div></div>`).join(""):`<div class="empty">Bu video için ${tab==="video"?"video":"ses"} formatı yok.</div>`);
  $("list").querySelectorAll("button[data-i]").forEach(b=>b.onclick=()=>download(rows[b.dataset.i],b));
}
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x===t));tab=t.dataset.t;render();
});

$("f").onsubmit=async e=>{
  e.preventDefault();$("err").textContent="";$("card").style.display="none";$("status").textContent="";
  $("pb").disabled=true;$("pb").textContent="Yükleniyor...";
  try{
    const u=$("url").value.trim();
    const r=await fetch("/info",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:u})});
    const d=await r.json(); if(!r.ok) throw new Error(d.error);
    cur={url:u,video:d.video,audio:d.audio};
    $("title").textContent=d.title||"";
    $("meta").textContent=[d.uploader,fmtDur(d.duration)].filter(Boolean).join(" · ");
    const m=$("media"); m.innerHTML="";
    const img=()=>{if(d.thumbnail){const i=document.createElement("img");i.src=d.thumbnail;m.replaceChildren(i);}};
    if(d.preview){
      const v=document.createElement("video");v.src=d.preview;v.controls=true;v.preload="metadata";
      v.poster=d.thumbnail||"";v.onerror=img;m.appendChild(v);
    } else img();
    tab="video";document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x.dataset.t==="video"));
    render();$("card").style.display="block";
  }catch(x){$("err").textContent="Bilgi alınamadı: "+x.message}
  $("pb").disabled=false;$("pb").textContent="Önizle";
};

async function download(row,btn){
  if(busy) return; busy=true;$("err").textContent="";
  document.querySelectorAll("#list button").forEach(b=>b.disabled=true);
  btn.textContent="%0";
  const r=await fetch("/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:cur.url,format:row.format})});
  const {id}=await r.json();
  const done=()=>{busy=false;document.querySelectorAll("#list button").forEach(b=>b.disabled=false);};
  const t=setInterval(async()=>{
    const p=await (await fetch("/progress/"+id)).json();
    if(p.state==="downloading"){btn.textContent="%"+Math.floor(p.percent);$("status").textContent=[p.speed,p.eta&&"kalan "+p.eta].filter(Boolean).join(" · ");}
    else if(p.state==="merging"){btn.textContent="Birleştiriliyor";$("status").textContent="Ses ve görüntü birleştiriliyor...";}
    else if(p.state==="done"){clearInterval(t);btn.textContent="İndirildi";$("status").textContent="";done();location.href="/file/"+id;}
    else if(p.state==="error"){clearInterval(t);btn.textContent="İndir";$("status").textContent="";$("err").textContent="İndirilemedi: "+p.error;done();}
  },500);
}
</script></body></html>"""

def size_of(f):
    return f.get("filesize") or f.get("filesize_approx") or 0

def build_formats(i):
    fmts = [f for f in (i.get("formats") or [i]) if f.get("ext") != "mhtml"]
    http = lambda f: (f.get("protocol") or "http").startswith("http")
    audios = [f for f in fmts if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    by_abr = lambda a: a.get("abr") or a.get("tbr") or 0
    best_audio = max([a for a in audios if a.get("ext") == "m4a"] or audios, key=by_abr, default=None)

    videos = {}
    for f in fmts:
        if f.get("vcodec") == "none" or not f.get("height"):
            continue
        h = min(f["height"], f.get("width") or f["height"])  # dikey videolarda da 1080p gibi göster
        score = (http(f), f.get("ext") == "mp4", f.get("tbr") or 0)
        if h not in videos or score > videos[h][0]:
            videos[h] = (score, f)

    video = []
    for h, (_, f) in sorted(videos.items(), reverse=True):
        label = f"{h}p" + (str(round(f["fps"])) if (f.get("fps") or 0) > 30 else "")
        if f.get("acodec") not in (None, "none"):
            video.append(dict(label=label, ext=f.get("ext", "mp4"), size=size_of(f) or None, audio=True, format=f["format_id"]))
        elif HAS_FFMPEG and best_audio:
            vs = size_of(f)
            video.append(dict(label=label, ext="mp4", size=(vs + size_of(best_audio)) if vs else None,
                              audio=True, format=f'{f["format_id"]}+{best_audio["format_id"]}'))
        else:
            video.append(dict(label=label, ext=f.get("ext", "mp4"), size=size_of(f) or None, audio=False, format=f["format_id"]))

    seen, audio = set(), []
    for a in sorted(audios, key=lambda a: (by_abr(a), http(a), size_of(a)), reverse=True):
        key = (round(by_abr(a)), a.get("ext"))
        if key in seen or not http(a):
            continue
        seen.add(key)
        audio.append(dict(label=f"{round(by_abr(a))}kbps" if by_abr(a) else "Ses", ext=a.get("ext", ""),
                          size=size_of(a) or None, format=a["format_id"]))
    return video, audio

@app.get("/")
def index():
    return PAGE

@app.post("/info")
def info():
    url = request.json.get("url", "")
    try:
        with yt_dlp.YoutubeDL({**BASE, "format": "best/bestvideo+bestaudio"}) as ydl:
            i = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify(error=str(e)), 400
    video, audio = build_formats(i)
    # Önizleme: ses+görüntü tek dosyada olan, tarayıcının oynatabileceği format
    prog = [f for f in i.get("formats", []) if f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none") and f.get("ext") == "mp4"
            and (f.get("protocol") or "").startswith("http")]
    pid = uuid.uuid4().hex
    media[pid] = {"thumb": i.get("thumbnail"), "preview": prog[-1]["url"] if prog else None,
                  "headers": (prog[-1].get("http_headers") if prog else None) or i.get("http_headers") or {}}
    return jsonify(title=i.get("title"), duration=i.get("duration"), uploader=i.get("uploader"),
                   thumbnail=f"/media/{pid}/thumb" if media[pid]["thumb"] else None,
                   preview=f"/media/{pid}/preview" if media[pid]["preview"] else None,
                   video=video, audio=audio)

@app.get("/media/<pid>/<kind>")
def proxy(pid, kind):
    m = media.get(pid)
    if not m or kind not in ("thumb", "preview") or not m[kind]:
        return "", 404
    hdrs = dict(m["headers"])
    if "Range" in request.headers:
        hdrs["Range"] = request.headers["Range"]
    ydl = yt_dlp.YoutubeDL(BASE)
    try:
        r = ydl.urlopen(Request(m[kind], headers=hdrs))
    except Exception:
        ydl.close()
        return "", 502
    def stream():
        try:
            while chunk := r.read(65536):
                yield chunk
        finally:
            r.close(); ydl.close()
    keep = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges")
    return Response(stream(), status=r.status, headers={k: r.headers[k] for k in keep if r.headers.get(k)})

def run(job_id, url, fmt):
    job = jobs[job_id]
    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            job.update(state="downloading", percent=(d["downloaded_bytes"] / total * 100) if total else job["percent"],
                       speed=(d.get("_speed_str") or "").strip(), eta=(d.get("_eta_str") or "").strip())
    def post(d):
        if d["status"] == "started" and d.get("postprocessor") == "Merger":
            job["state"] = "merging"
    opts = {**BASE, "format": fmt, "outtmpl": os.path.join(job["dir"], "%(title).80s.%(ext)s"),
            "progress_hooks": [hook], "postprocessor_hooks": [post]}
    if "+" in fmt:
        opts["merge_output_format"] = "mp4"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = [f for f in os.listdir(job["dir"]) if not f.endswith((".part", ".ytdl"))]
        job.update(state="done", percent=100, file=os.path.join(job["dir"], files[0]))
    except Exception as e:
        job.update(state="error", error=str(e))

@app.post("/start")
def start():
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"state": "starting", "percent": 0, "dir": tempfile.mkdtemp()}
    body = request.json
    threading.Thread(target=run, args=(job_id, body["url"], body.get("format") or "best"), daemon=True).start()
    return jsonify(id=job_id)

@app.get("/progress/<job_id>")
def progress(job_id):
    j = jobs.get(job_id, {"state": "error", "error": "İş bulunamadı", "percent": 0})
    return jsonify({k: j.get(k) for k in ("state", "percent", "speed", "eta", "error")})

@app.get("/file/<job_id>")
def file(job_id):
    job = jobs.pop(job_id)
    @after_this_request
    def cleanup(resp):
        shutil.rmtree(job["dir"], ignore_errors=True)
        return resp
    return send_file(job["file"], as_attachment=True, download_name=os.path.basename(job["file"]))

if __name__ == "__main__":
    app.run(port=5050, threaded=True)
