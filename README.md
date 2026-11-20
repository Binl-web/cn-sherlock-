# cn-sherlock

面向**国内平台**的用户名存在性探测工具，参考 [Sherlock](https://github.com/sherlock-project/sherlock) 的「配置驱动 + 并发探测 + 多格式导出」工程结构，但判定逻辑针对国内平台重写。

> 输入一个用户名/昵称，输出它在知乎、豆瓣、B站、博客园、语雀等平台是否存在，并给出可核验的主页链接。

- **零第三方依赖**：只使用 Python 标准库，Windows / Linux / 内网环境直接运行。
- **不把风控当“不存在”**：403 / 412 / 521 / 安全验证页统一标记为「受限」，避免误判。
- **区分“同名”与“同人”**：只做公开页面的存在性信号聚合，不输出身份结论。

---

## 1. 与 Sherlock 的差异

| 维度 | Sherlock | cn-sherlock |
|---|---|---|
| 站点来源 | 400+ 海外站点 | 国内主流社区/博客/内容平台 |
| 用户名路径 | 多数站点 `/{username}` 直接可查 | 国内平台常是数字 ID、sec_uid、加密 token |
| 判定方式 | 以 HTTP 状态码为主 | 状态码 + 页面文案 + JSON 接口 + 搜索精确匹配 |
| 风控处理 | 基本无 | 403/412/521/验证页 → 受限，不判负 |
| 数字 ID 平台 | 少量支持 | B站/网易云/CSDN 先搜索解析出 ID，再给主页 |
| 登录墙平台 | 部分支持 | 明确标注「需人工核验」，不伪造结论 |
| 依赖 | requests 等 | 无第三方依赖 |

---

## 2. 快速开始

要求：Python 3.9+，无需安装任何依赖。

```bash
cd cn-sherlock
python cnsherlock.py dudu
```

PowerShell / Windows 同样适用：

```powershell
python .\cnsherlock.py dudu
```

### 常用命令

```bash
# 查询一个用户名（默认只跑稳定站点）
python cnsherlock.py dudu

# 多个用户名
python cnsherlock.py dudu 老番茄

# 只查指定站点（可重复 --site）
python cnsherlock.py dudu --site B站 --site 知乎 --site 豆瓣

# 排除不想查的站点
python cnsherlock.py dudu --exclude 科学网

# 只显示命中项，并导出 JSON / CSV / TXT
python cnsherlock.py dudu --only-found --json result.json --csv result.csv -o result.txt

# 启用实验站点（Gitee / 贴吧 / 微博，稳定性较低）
python cnsherlock.py dudu --include-experimental

# 同时输出需人工核验的平台链接（抖音 / 小红书 / 快手 / 微信）
python cnsherlock.py dudu --include-manual

# 查看配置内全部站点
python cnsherlock.py --list-sites

# 在线自检：每个站点测一个已知存在 + 一个不存在样本
python cnsherlock.py --doctor

# 代理与内网自签名证书
python cnsherlock.py dudu --proxy http://127.0.0.1:7890
python cnsherlock.py dudu --insecure
```

### 可选 Cookie

部分平台对未登录请求风控较严，可通过环境变量注入登录态 Cookie（只在本机读取，不写入任何文件）：

```powershell
# PowerShell
$env:CNSHERLOCK_ZHIHU_COOKIE="z_c0=xxxxxxxx"
$env:CNSHERLOCK_WEIBO_COOKIE="SUB=xxxxxxxx"
python .\cnsherlock.py dudu
```

```bash
# Linux / macOS
export CNSHERLOCK_ZHIHU_COOKIE="z_c0=xxxxxxxx"
python cnsherlock.py dudu
```

| 环境变量 | 作用 | 是否必需 |
|---|---|---|
| `CNSHERLOCK_ZHIHU_COOKIE` | 提高知乎接口成功率 | 否 |
| `CNSHERLOCK_WEIBO_COOKIE` | 微博实验站点所需登录态 | 是（仅微博） |

---

## 3. 输出示例

以下为 2026-11-20 在本机实测的真实结果（用户名 `dudu`）：

```text
[*] 用户名：dudu
────────────────────────────────────────────────────────────────────────────────
       站点        结果    置信度       耗时  链接 / 说明
    [+] 知乎        已发现  high      0.24s  https://www.zhihu.com/people/dudu
    [+] 豆瓣        已发现  high      0.43s  https://www.douban.com/people/dudu/
    [+] 博客园      已发现  high      1.21s  https://www.cnblogs.com/dudu
    [+] 语雀        已发现  high      0.75s  https://www.yuque.com/dudu
    [+] 科学网      已发现  medium    0.46s  https://blog.sciencenet.cn/u/dudu
    [+] B站         已发现  high      0.45s  https://space.bilibili.com/3546822033279589
    [-] InfoQ       未发现  high      0.35s  https://www.infoq.cn/u/dudu  (HTTP 404)
    [-] 网易云音乐  未发现  high      0.34s  https://music.163.com/#/search/m/?s=dudu&type=1002  (搜索结果 20 条，无同名)
    [-] CSDN        未发现  medium    0.80s  https://so.csdn.net/so/search?q=dudu  (搜索结果 23 条，无同名；CSDN 使用文章搜索匹配作者，未命中可能只是文章未被收录，不能完全排除)
────────────────────────────────────────────────────────────────────────────────
    命中 6  |  未发现 3  |  受限 0  |  错误 0  |  跳过 0  |  待核验 0
```

### 状态语义

| 标记 | 状态 | 含义 | 是否可判负 |
|---|---|---|---|
| `[+]` | 已发现 | 明确命中，附主页链接 | — |
| `[-]` | 未发现 | 页面/接口明确表示无此用户 | 是 |
| `[!]` | 受限 | 403/412/521/安全验证/登录墙，**结果未知** | **否** |
| `[x]` | 错误 | 超时、DNS、非 JSON、状态码异常 | 否 |
| `[.]` | 跳过 | 站点不适用（如中文用户名用于子域名）或缺少 Cookie | 否 |
| `[?]` | 待核验 | 平台强制登录/签名，只给搜索入口 | 否 |

**重要**：`未发现` 只代表“当前这次公开请求没有拿到该用户名的主页”，不等于该用户名在所有场景下都不存在；`受限` 必须换网络/配置 Cookie 后重试，不能当作否定结论。

---

## 4. 支持站点

### 稳定站点（默认启用，9 个）

| 站点 | 分类 | 探测方式 | 置信度 | 说明 |
|---|---|---|---|---|
| 知乎 | 问答社区 | `api/v4/members/{name}` | 高 | 200=存在；404/500=不存在。接口对 `Referer` 敏感，带 Referer 会 403，配置已保持最小请求头；偶发 403 自动延迟重试，也可配 Cookie |
| 豆瓣 | 书影音 | `m.douban.com/people/{name}/` | 高 | 移动版可用；电脑版对未登录请求普遍 404 |
| 博客园 | 技术博客 | `{name}.cnblogs.com` | 高 | 自动跟随 301 到 `www.cnblogs.com/{name}`；仅支持 ASCII 用户名 |
| InfoQ | 技术社区 | `infoq.cn/u/{name}` | 高 | 404=未注册 |
| 语雀 | 知识库 | `yuque.com/{name}` | 高 | 404=未注册 |
| 科学网 | 学术博客 | `blog.sciencenet.cn/u/{name}` | 中 | 200 页面中匹配“用户空间不存在”文案 |
| B站 | 视频社区 | 用户搜索接口 + buvid | 高 | 精确匹配 `uname`，解析 `mid` 后给空间链接 |
| 网易云音乐 | 音乐社区 | 用户搜索 `type=1002` | 高 | 精确匹配昵称，解析 `userId` |
| CSDN | 技术博客 | 站内文章搜索 API | 中 | 按 `username/author` 精确匹配，取 `author_space`；命中即存在，未命中可能只是文章未被收录，**负向结论不完全可靠** |

### 实验站点（需 `--include-experimental` 或显式 `--site`）

| 站点 | 说明 |
|---|---|
| Gitee | 存在账号也可能被 WAF 返回 403，默认关闭 |
| 贴吧 | 百度安全验证频繁，建议住宅网络或 Cookie |
| 微博 | 必须配置 `CNSHERLOCK_WEIBO_COOKIE`，否则跳过 |

### 需人工核验（`--include-manual` 输出搜索入口）

| 站点 | 不自动化的原因 |
|---|---|
| 抖音 | 主页用 `sec_uid`，接口需 X-Bogus 签名 + 登录态 |
| 小红书 | 主页用 `user_id` + `xsec_token`，强制登录并校验签名 |
| 快手 | 主页用数字 ID，网页端纯前端渲染并带签名 |
| 微信 | 没有公开的微信号主页 |

> 这些平台并非“做不到”，而是自动化需要逆向签名或绕过登录，既不稳定也违反平台条款，因此工具只给出搜索入口，不伪造判定结果。

---

## 5. 实现原理

### 5.1 三类判定策略

1. **状态码判定（status）**
   适用于有稳定 HTTP 语义的站点。配置 `found / not_found / blocked` 三组状态码，三组必须互斥。
2. **页面文案判定（message）**
   适用于“不存在也返回 200”的站点（如科学网）。命中 `not_found_markers` 判负，否则按页面正常判正。
3. **搜索精确匹配（search）**
   适用于用户名不能直接拼进主页路径的平台（B站、网易云、CSDN）。先调搜索接口，再对 `uname / nickname / username` 做**完全同名**匹配（去 HTML 高亮标签、Unicode NFKC、大小写归一），命中后解析出数字 ID 或主页字段。

### 5.2 风控与稳定性

- `403 / 412 / 521 / 418 / 429` 及“百度安全验证”等页面 → **受限**，绝不判负；
- 同域名串行排队（`DomainLimiter`），站点可配 `delay`，避免并发触发风控；
- 失败请求指数退避重试；知乎首次 403 会延迟重试一次；
- B站首次请求前调用 `x/frontend/finger/spi` 获取 `buvid3/buvid4`，412 时刷新指纹重试；
- 编码自动探测（响应头 charset → meta charset → UTF-8 → GB18030），兼容老站点；
- Windows 控制台自动开启 ANSI 颜色，输出统一 UTF-8。

### 5.3 目录结构

```text
cn-sherlock/
├─ cnsherlock.py              # 入口脚本
├─ cn_sherlock/
│  ├─ cli.py                  # 参数、并发调度、doctor
│  ├─ engine.py               # HTTP、判定策略、B站指纹、限速
│  ├─ report.py               # 终端表格、JSON/CSV/TXT
│  ├─ sites.py                # 配置加载与站点筛选
│  └─ resources/
│     └─ sites_cn.json        # 站点配置（唯一需要维护的文件）
├─ tests/                     # 30 个离线单元测试
├─ requirements.txt           # 无第三方依赖
├─ pyproject.toml
├─ LICENSE
└─ README.md
```

---

## 6. 新增站点

只需编辑 `cn_sherlock/resources/sites_cn.json`，无需改代码。

### 示例 A：状态码判定

```json
{
  "name": "示例社区",
  "category": "社区",
  "status": "stable",
  "confidence": "high",
  "url": "https://example.cn/u/{username}",
  "probe": {
    "url": "https://example.cn/u/{username}",
    "headers": {"Referer": "https://example.cn/"},
    "delay": 0.8
  },
  "detect": {
    "type": "status",
    "found": [200],
    "not_found": [404],
    "blocked": [403, 429],
    "not_found_markers": ["用户不存在"]
  },
  "doctor": {"claimed": "已知存在的用户名"},
  "notes": "说明该站点的坑"
}
```

### 示例 B：搜索精确匹配

```json
{
  "name": "示例视频站",
  "category": "视频",
  "status": "stable",
  "confidence": "high",
  "url": "https://example.cn/space/{uid}",
  "fallback_url": "https://example.cn/search?q={username}",
  "probe": {
    "url": "https://example.cn/api/search?keyword={username}",
    "delay": 2.0
  },
  "detect": {
    "type": "search",
    "list_path": "data.items",
    "match_fields": ["nickname"],
    "strip_html": true,
    "json_check": {"field": "code", "ok": [0], "blocked_values": [-412]}
  },
  "resolve": {"field": "uid", "url": "https://example.cn/space/{value}"},
  "doctor": {"claimed": "已知昵称"}
}
```

字段说明：

| 字段 | 作用 |
|---|---|
| `probe.username_charset` | 设为 `ascii` 时，中文用户名直接跳过（子域名类站点） |
| `probe.cookie_env` | 必需 Cookie 的环境变量名；缺失则跳过 |
| `probe.optional_cookie_env` | 可选 Cookie；存在则注入，不存在不跳过 |
| `probe.retry_on` | 首次命中这些状态码时延迟重试一次 |
| `detect.list_path` | JSON 结果列表路径，支持 `a.b.c` |
| `detect.match_fields` | 参与精确匹配的字段，按顺序 |
| `detect.json_check` | 校验接口状态字段，避免把错误响应当“无结果” |
| `resolve.field` | 命中项中取主页 ID 的字段 |
| `resolve.json_field` | 状态码判定时从响应 JSON 取字段 |
| `resolve.use_final_url` | 用重定向后的最终 URL 作为主页 |
| `fallback_url` | 未发现/受限时展示的搜索页，避免展示含未知 ID 的主页模板 |

新增后执行：

```bash
python cnsherlock.py --list-sites
python cnsherlock.py --doctor
python -m unittest discover -s tests -t .
```

---

## 7. 已知限制

1. **同名不等于同人**：昵称类平台（B站/网易云）只能证明“存在同名账号”，不能证明是你认识的那个人。需要结合头像、简介、绑定信息等人工核验。
2. **昵称 vs 用户名**：本工具查的是公开主页路径/昵称，不涉及手机号、邮箱、实名信息。
3. **平台策略会变**：国内平台接口与风控更新频繁。`--doctor` 用于快速发现失效配置；`data` 中已标注 `notes` 记录实测差异。
4. **IP 影响结果**：机房 IP 更容易触发风控；住宅网络通常更接近真实用户环境。受限时优先换网络/配置 Cookie/降低并发。
5. **不做登录绕过**：不实现验证码识别、签名伪造、Cookie 窃取或代理池绕过。
6. **频率控制**：单机串行+延迟仅用于避免误伤平台，不保证大规模批量查询的稳定性；请勿高频扫描。

---

## 8. 合规使用

本工具只聚合**公开页面**上“某用户名是否存在”的信号，不抓取私密内容、不绕过登录、不提供人肉搜索能力。

允许的典型场景：

- 查询自己的用户名是否被他人占用；
- 品牌/团队账号矩阵自查；
- 经授权的品牌保护、侵权线索初筛；
- 安全研究中的公开信息核验。

严禁用于：骚扰、跟踪、起底他人、批量收集个人信息、绕过平台风控、任何违反《个人信息保护法》《网络安全法》及平台用户协议的行为。使用者需自行承担合规责任。

---

## 9. 开发与测试

```bash
# 离线单元测试（不联网）
python -m unittest discover -s tests -t . -v

# 在线自检（会真实请求各平台，约 20~40 秒）
python cnsherlock.py --doctor

# 安装为命令（可选）
pip install -e .
cnsherlock dudu
```

测试覆盖：状态码判定、200 页面误报、风控不判负、搜索精确匹配、HTML 高亮剥离、JSON 路径空值、URL 编码、配置互斥校验、默认站点筛选等 30 项。

---

## 10. 版本

- `1.0.0`（2026-11-20）：首个可用版本，9 个稳定站点 + 3 个实验站点 + 4 个手工核验入口；零依赖；支持 JSON/CSV/TXT 导出与在线自检。

MIT License.
