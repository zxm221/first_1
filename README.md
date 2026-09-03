# TVBox 聚合源自更新

每天自动抓取 [tvbox.clbug.com/user.php](https://tvbox.clbug.com/user.php) 的配置源列表，
清洗并检测可达性后生成多仓文件并自动提交，TVBox 导入下方链接即可，无需手动更新。

## 生成的文件

| 文件 | 内容 |
|---|---|
| `tvbox.json` / `tvbox.txt` | 当前可达的源（推荐导入） |
| `tvbox_all.json` / `tvbox_all.txt` | 全部源（含失效） |
| `update.log` | 每次更新的时间和条数 |

## TVBox 导入地址

把下面的 `用户名` 和 `仓库名` 换成你自己的，填入 TVBox「设置 → 配置订阅（多仓）」：

```
https://raw.githubusercontent.com/用户名/仓库名/main/tvbox.json
```

国内访问较慢时可加 CDN 前缀（任选其一）：

```
https://cdn.jsdelivr.net/gh/用户名/仓库名@main/tvbox.json
https://ghfast.top/https://raw.githubusercontent.com/用户名/仓库名/main/tvbox.json
```

## 本地运行

```bash
python tvbox_updater.py            # 抓取 + 检测，输出有效版与全量版
python tvbox_updater.py --no-check # 跳过检测，只输出全量版
```
