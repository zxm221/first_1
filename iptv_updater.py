# -*- coding: utf-8 -*-
"""
iptv_updater.py — 从 iptv.clbug.com 抓取全部分类直播源，自动清理：
  1) HTTP 实测：连不上的剔除
  2) 帧差异检测：抓两帧，MSE<30 视为静态死画面/无信号，剔除
  3) pHash 跨频道去重：不同频道名播同一画面的只保留一个
纯标准库 + ffmpeg（GitHub Actions ubuntu 自带）。
"""
import urllib.request, urllib.parse, os, re, socket, json, time, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://iptv.clbug.com/download.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG = "ffmpeg"  # ubuntu 自带
W, H = 160, 90
MSE_THRESHOLD = 30.0
PHAM_THRESHOLD = 6  # 汉明距离 <=6 视为重复

CN_CATS = ["体育频道","儿童频道","其他频道","卫视频道","台湾频道","地方频道","央视频道",
           "戏曲频道","数字频道","春晚频道","游戏频道","澳门频道","电影频道","直播中国",
           "纪录频道","综艺频道","解说频道","音乐频道","香港频道"]
INTL = {
    "news":"国际-新闻","sports":"国际-体育","movies":"国际-电影","series":"国际-剧集",
    "kids":"国际-少儿","music":"国际-音乐","documentary":"国际-纪录",
    "entertainment":"国际-娱乐","comedy":"国际-喜剧","general":"国际-综合",
    "business":"国际-财经","science":"国际-科技","education":"国际-教育",
    "lifestyle":"国际-生活","cooking":"国际-美食","travel":"国际-旅游",
    "auto":"国际-汽车","animation":"国际-动画","family":"国际-家庭",
    "religious":"国际-宗教","legislative":"国际-议会","outdoor":"国际-户外",
    "shop":"国际-购物","weather":"国际-天气","culture":"国际-文化",
    "classic":"国际-经典","relax":"国际-放松",
}

def fetch(url, timeout=20, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(2*(i+1))
    return None

# 1) 抓分类
tasks = []
for c in CN_CATS:
    tasks.append((urllib.parse.urlencode({"type":"ipv4","category":c,"format":"m3u"}), c))
for en, zh in INTL.items():
    tasks.append((urllib.parse.urlencode({"type":"international_cat","category":en,"format":"m3u"}), zh))
bodies = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for g, body in ex.map(lambda t: (t[1], fetch(BASE+"?"+t[0])), tasks):
        if body: bodies[g] = body
print("fetched cats:", len(bodies), flush=True)

# 2) 合并去 URL
items = []
for g in list(CN_CATS) + list(INTL.values()):
    body = bodies.get(g)
    if not body: continue
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            ln = re.sub(r'group-title="[^"]*"', 'group-title="%s"'%g, lines[i].strip())
            url = lines[i+1].strip() if i+1 < len(lines) else ""
            if url.startswith("http"):
                items.append([ln, url])
            i += 2
        else:
            i += 1
seen, uniq = set(), []
for it in items:
    if it[1] not in seen:
        seen.add(it[1]); uniq.append(it)
print("merged uniq:", len(uniq), flush=True)

# 3) HTTP 实测
socket.setdefaulttimeout(6)
def http_probe(it):
    ext, url = it
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range":"bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return it, r.getcode() < 500
    except urllib.error.HTTPError as e:
        return it, e.code < 500
    except Exception:
        return it, False
http_alive = []
with ThreadPoolExecutor(max_workers=80) as ex:
    for it, ok in ex.map(http_probe, uniq):
        if ok: http_alive.append(it)
print("http alive:", len(http_alive), flush=True)

# 4) 帧检测：抓两帧算 MSE + 收集第 1 帧用于 pHash
def frame_grab(url, at):
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-user_agent", UA,
           "-ss", str(at), "-i", url, "-frames:v", "1",
           "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        if len(r.stdout) == W*H: return r.stdout
    except Exception:
        pass
    return None

def frame_check(it):
    ext, url = it
    f1 = frame_grab(url, 1)
    f2 = frame_grab(url, 6)
    if not f1 or not f2:
        return it, None, f1
    s = sum((f1[k]-f2[k])**2 for k in range(len(f1))) / len(f1)
    return it, s, f1

frame_good = []
phash_list = []  # (idx_in_frame_good, hash_int)
with ThreadPoolExecutor(max_workers=24) as ex:
    futs = [ex.submit(frame_check, it) for it in http_alive]
    done = 0
    for f in as_completed(futs):
        it, mse, f1 = f.result()
        done += 1
        if mse is None or mse >= MSE_THRESHOLD:
            frame_good.append((it, f1))
        if done % 500 == 0:
            print(f"frame probe {done}/{len(http_alive)} good={len(frame_good)}", flush=True)

# 5) pHash（8x8 DCT 简化版：直接下采样 32x32，比较像素均值）
def simple_hash(gray):
    """把 160x90 灰度下采样到 16x9，按均值二值化，返回 int"""
    bw, bh = 16, 9
    px = []
    for y in range(bh):
        row = []
        for x in range(bw):
            sx = int(x * W / bw); sy = int(y * H / bh)
            row.append(gray[sy*W+sx])
        px.append(row)
    flat = [v for row in px for v in row]
    avg = sum(flat) / len(flat)
    h = 0
    for i, v in enumerate(flat):
        if v > avg: h |= (1 << i)
    return h

kept = []
seen_hashes = []
for it, f1 in frame_good:
    if not f1:
        kept.append(it); continue
    h = simple_hash(f1)
    dup = False
    for sh in seen_hashes:
        if bin(h ^ sh).count("1") <= PHAM_THRESHOLD:
            dup = True; break
    if not dup:
        seen_hashes.append(h)
        kept.append(it)
print("after pHash dedup:", len(kept), "from", len(frame_good), flush=True)

# 6) 输出
kept.sort(key=lambda x: [u[1] for u in http_alive].index(x[1]))
with open(os.path.join(OUT_DIR, "iptv_live.m3u"), "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for ext, url in kept:
        f.write(ext+"\n"+url+"\n")

live = {"spider":"", "lives":[{
    "name":"clbug-IPTV(活源+去重)",
    "type":0,
    "url":"https://cdn.jsdelivr.net/gh/zxm221/first_1@master/iptv_live.m3u",
    "epg":"http://epg.51zmt.top:8000/api/diyp/",
    "ua":"", "playerType":0
}]}
with open(os.path.join(OUT_DIR, "live.json"), "w", encoding="utf-8") as f:
    json.dump(live, f, ensure_ascii=False, indent=1)
print("DONE", len(kept), "channels", flush=True)
