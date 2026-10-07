# -*- coding: utf-8 -*-
"""
iptv_updater.py — 从 iptv.clbug.com 抓取全部分类直播源，并发实测，输出 iptv_live.m3u
纯标准库，可在 GitHub Actions ubuntu 上跑。
输出：
  iptv.m3u        全量合并（不分好坏）
  iptv_live.m3u   实测活源（推荐 TVBox 使用）
  live.json       TVBox 直播配置，指向 iptv_live.m3u
"""
import urllib.request, urllib.parse, os, re, socket, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://iptv.clbug.com/download.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

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
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    return None

# 1) 抓取所有分类
tasks = []
for c in CN_CATS:
    tasks.append((urllib.parse.urlencode({"type":"ipv4","category":c,"format":"m3u"}), c))
for en, zh in INTL.items():
    tasks.append((urllib.parse.urlencode({"type":"international_cat","category":en,"format":"m3u"}), zh))

bodies = {}
def work(t):
    q, g = t
    return g, fetch(BASE + "?" + q)
with ThreadPoolExecutor(max_workers=8) as ex:
    for g, body in ex.map(work, tasks):
        if body:
            bodies[g] = body
print("fetched cats:", len(bodies))

# 2) 合并
items = []
order = list(CN_CATS) + list(INTL.values())
for g in order:
    body = bodies.get(g)
    if not body: continue
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("#EXTINF"):
            ln = re.sub(r'group-title="[^"]*"', 'group-title="%s"' % g, ln)
            url = lines[i+1].strip() if i+1 < len(lines) else ""
            if url.startswith("http"):
                items.append((ln, url))
            i += 2
        else:
            i += 1
# 去重
seen, uniq = set(), []
for it in items:
    if it[1] not in seen:
        seen.add(it[1]); uniq.append(it)
print("merged uniq channels:", len(uniq))

# 写全量
with open(os.path.join(OUT_DIR, "iptv.m3u"), "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for ext, url in uniq:
        f.write(ext + "\n" + url + "\n")

# 3) 并发实测
socket.setdefaulttimeout(6)
def probe(item):
    ext, url = item
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return item, r.getcode() < 500
    except urllib.error.HTTPError as e:
        return item, e.code < 500
    except Exception:
        return item, False

alive = []
with ThreadPoolExecutor(max_workers=100) as ex:
    futs = [ex.submit(probe, it) for it in uniq]
    for k, f in enumerate(as_completed(futs)):
        item, ok = f.result()
        if ok: alive.append(item)
        if (k+1) % 2000 == 0:
            print("probe %d/%d alive=%d" % (k+1, len(uniq), len(alive)))
alive.sort(key=lambda x: uniq.index(x))
with open(os.path.join(OUT_DIR, "iptv_live.m3u"), "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for ext, url in alive:
        f.write(ext + "\n" + url + "\n")
print("alive:", len(alive), "/", len(uniq))

# 4) live.json
live = {
    "spider": "",
    "lives": [{
        "name": "clbug-IPTV(实测活源)",
        "type": 0,
        "url": "https://cdn.jsdelivr.net/gh/zxm221/first_1@master/iptv_live.m3u",
        "epg": "http://epg.51zmt.top:8000/api/diyp/",
        "ua": "",
        "playerType": 0
    }]
}
with open(os.path.join(OUT_DIR, "live.json"), "w", encoding="utf-8") as f:
    json.dump(live, f, ensure_ascii=False, indent=1)
print("done")
