#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tvbox_updater.py — 抓取 tvbox.clbug.com 的源列表，生成 TVBox 多仓文件（JSON / TXT）
纯 Python 标准库，无第三方依赖，本地 Windows 与 GitHub Actions 均可运行。

用法:
  python tvbox_updater.py             # 抓取 + 可达性检测，输出 有效版(tvbox.json/tvbox.txt) 与 全量版(tvbox_all.json/tvbox_all.txt)
  python tvbox_updater.py --no-check  # 跳过检测，只输出全量版
  python tvbox_updater.py --url <地址> --out <目录>
"""
import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

SOURCE_URL = "https://tvbox.clbug.com/user.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch(url, timeout=20, retries=3):
    """带重试的网页抓取"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError("fetch failed: %s -> %s" % (url, last))


def parse_rows(html_text):
    """解析 <tr data-url="URL"> ... <td class="td-name">名称</td> 结构"""
    pat = re.compile(r'<tr data-url="([^"]+)"(.*?)<td class="td-name">(.*?)</td>', re.S)
    rows = []
    for m in pat.finditer(html_text):
        url = html.unescape(m.group(1).strip())
        name = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        rows.append({"name": name, "url": url})
    return rows


def clean(rows):
    """剔除空值、无效协议及明显非配置源的条目，按(名称,URL)去重"""
    out, seen = [], set()
    for r in rows:
        url, name = r["url"], r["name"]
        if url in ("", "#") or not url.startswith(("http://", "https://")):
            continue
        if any(x in url for x in (".webp", "m.ytdrying.com/play/", "github.com/xisohi/")):
            continue
        key = (name, url)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "url": url})
    return out


def check_one(item):
    """调用源站自带检测接口，标记可达性（单条失败不影响整体）"""
    try:
        data = urllib.parse.urlencode({"action": "check_url", "url": item["url"]}).encode()
        req = urllib.request.Request(SOURCE_URL, data=data, method="POST",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "ignore")
        item["ok"] = json.loads(body).get("status") == "ok"
    except Exception:  # noqa: BLE001
        item["ok"] = False
    return item


def dump(items, tag, out_dir):
    """输出多仓 JSON（{"urls":[...]}）与 TXT（每行 名称|URL）"""
    js = {"urls": [{"name": r["name"], "url": r["url"]} for r in items]}
    with open("%s/tvbox%s.json" % (out_dir, tag), "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1)
    with open("%s/tvbox%s.txt" % (out_dir, tag), "w", encoding="utf-8") as f:
        for r in items:
            f.write("%s|%s\n" % (r["name"], r["url"]))
    return len(items)


def main():
    ap = argparse.ArgumentParser(description="TVBox 源列表抓取自更新")
    ap.add_argument("--url", default=SOURCE_URL, help="抓取页面地址")
    ap.add_argument("--no-check", action="store_true", help="跳过可达性检测")
    ap.add_argument("--out", default=".", help="输出目录")
    args = ap.parse_args()

    print("[1/3] fetching %s ..." % args.url)
    rows = clean(parse_rows(fetch(args.url)))
    print("      parsed %d valid sources" % len(rows))
    if not rows:
        raise SystemExit("ERROR: no rows parsed, page structure may have changed")

    ok_items = rows
    if not args.no_check:
        print("[2/3] checking reachability ...")
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(check_one, r) for r in rows]
            for f in as_completed(futs):
                f.result()  # 异常已在内部吞掉
        ok_items = [r for r in rows if r.get("ok")]
        print("      reachable %d / %d" % (len(ok_items), len(rows)))

    print("[3/3] writing files to %s" % args.out)
    n_all = dump(rows, "_all", args.out)
    n_ok = dump(ok_items, "", args.out) if ok_items else 0

    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    with open("%s/update.log" % args.out, "a", encoding="utf-8") as f:
        f.write("%s  total=%d  reachable=%d\n" % (ts, n_all, n_ok))

    print("done. tvbox_all.json=%d  tvbox.json=%d" % (n_all, n_ok))


if __name__ == "__main__":
    main()
