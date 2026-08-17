[English](README.md) | [简体中文](README_cn.md)

# sustech_survival

<p align="center">
  <img src="src/sustech_survival/resources/logo-full-transparent.svg"
       alt="sustech_survival" width="360">
</p>

`sustech_survival` 是一个允许在 API 层面调用南科大各服务系统的 Python 模块。它满足 SUSTech 学生在 BB、TIS、图书馆、PMS 等系统的日常需求。

通过在代码层面打通这些服务，我们简化了校园系统的使用，提供了一条通往个性化校园体验的捷径，更重要的是 —— 接入并欢迎 AI 助手进入你的校园生活。

[![GitHub](https://img.shields.io/badge/github-repo-blue.svg)](https://github.com/dumixthestpd/sustech_survival)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## 功能

### 校园系统

- **毕博平台 Blackboard Learn** (`bb`)
- **教学信息服务 TIS** (`tis`)
- **图书馆 SUSTech Library** (`lib`)
- **统一身份认证 SSO** (`sso`) — 共享认证底座
- **联创打印 PMS** (`pms`)
- **外事 SUSTech Global** (`ws`)
- **网上办事大厅 E-Hall** (`booking`)
- **牛哇课程评价 NCES** (`nces`)

### 自建模块

- **selectcourse** — TIS 选课：浏览课程、加退选、管理购物车。
- **faculty** — 教师信息目录：按学院列表、全文搜索、个人主页查询。
- **transit** — 校园巴士与步行导航：时刻表、实时 GPS、路线规划。
- **calendar** — 南科大校历与日期智能：从 GitHub 上的 `sustech-calendar` 仓库加载 JSON，解析 (周次, 星期) → 日期，处理补课日调换。在线数据为权威源；本地覆盖用于编辑中的数据。
- **ical** — 已选课程的 `.ics` 导出。位于 `selectcourse.ical`，通过 webui 的 `GET /api/tis/ical` 接入。
- **webui** — Flask 单页应用，整合 TIS 选课界面、公交地图、NCES 悬浮卡片、iCal 导出。启动：`python -m sustech_survival.webui serve`。
- **context** — 为 AI 助手设计的每日快照：日期、周次、最近作业/考试/上课时间、天气、AQI。
- **papers** — 学术论文搜索与下载，覆盖 CrossRef、CNKI、WoS、RSC。

---

## 快速开始

### 1. 安装

CLI（`click`）已包含在核心依赖中 —— `pip install sustech_survival` 同时安装 Python API 和 `sustech` 命令。

可选扩展按需安装：

- `webui` — Flask SPA：TIS 选课界面 + 公交地图 + NCES 悬浮卡片
- `nces` — Anubis PoW 求解器（NCES 列表抓取用）
- `papers` — cloudscraper（绕过出版商网站的 requests 拦截）
- `all` — 以上全部

```bash
# 任选其一：
pip install "sustech_survival"               # API + CLI
pip install "sustech_survival[webui]"        # + Web 界面
pip install "sustech_survival[all]"          # 全部
```

### 2. 身份认证

统一 CAS 认证底座位于 `sustech_survival/sso/authorizer.py`。
每个系统（BB、TIS、图书馆、外事、PMS、NCES、场地预约等）的登录都只是一个 `Authorizer` 子类 —— 选一个并调用 `ensure()`：

```python
from sustech_survival.sso import TISAuth

auth = TISAuth()                       # 每类单例
ok, reason = auth.ensure()             # 检查会话，过期则自动刷新
auth.session.get("/xszykb/querydangqianxnxq")   # 使用已认证的会话

# 或使用装饰器：
from sustech_survival.sso import require_auth

@require_auth(TISAuth)
def my_function(auth=None):
    r = auth.session.get(...)
```

凭据按三级优先级解析（越靠后越优先）：

1. `sustech_survival.sso.cred_set(sid=..., pwd=...)` —— 内存中设置，最高优先级
2. `./credentials.txt` —— 当前工作目录
3. `SUSTECH_CREDENTIALS` 环境变量 —— 凭据文件的完整路径

格式：`学号:密码`。会话仅保存在**内存中** —— 不写 `session.json` 到磁盘。

```python
from sustech_survival import sso
sso.cred_set(sid="12410000", pwd="your-password-here")   # 内存中，优先级最高
```

**普通 `pip install` 之后，包内并不会自带凭据文件** —— 运行时不会打包 `credentials.txt`。一条命令即可配置（写入当前工作目录的 `./credentials.txt`，权限 600）：

```bash
sustech sso creds set --sid 12410000 --pass 'your-password-here'
# （省略 --pass 会以隐藏方式提示输入；--password 也是别名）
```

已安装并想先确认凭据可用（不做真实操作）：

```bash
python -m sustech_survival.lib.login   # 图书馆 Primo（无头 CAS 登录）
sustech pms check                      # 校验 PMS 认证
sustech bb --help                      # 列出 bb 子命令
```

> 说明：目前**没有** `sustech <服务> session login|check|refresh` 这类子命令（README 早先写的不存在）。请在 Python 里用 `ensure()` / `auth.check()`，或用上面各模块的只读命令。

### 3. 示例用法

设置完成后的两个常用工作流：

**每日快照（为 AI 助手设计）：**

```python
from sustech_survival.context import Context

ctx = Context(level="normal")   # terse / normal / verbose
print(ctx.to_str())
# → Today is [2026-07-04], [Saturday]
# → Next BB deadline: [Experiment 5] — Due in 3 days
# → Next TIS exam: [...final...]
```

**Web 界面（最常用）：**

```bash
python -m sustech_survival.webui
```

浏览器打开 `http://localhost:20129` —— TIS 选课界面（含冲突求解）、
校园巴士地图（实时 GPS）、每个课程的 NCES 悬浮卡片。

---

## 相关项目

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** — 南科大校历（学期、工作日、节假日）。`calendar` 模块在运行时加载其 JSON；在线数据为权威源。

---

## 架构

```
# 第一行 —— 官方系统（南科大提供；我们去对接）
sustech_survival/
├── sso/      ← 统一 SSO 底座（CAS / Shibboleth；authorizer 层）
├── bb/       ← Blackboard Learn (毕博)
├── tis/      ← TIS 教学信息服务
│   └── classroom/  ← TIS 教室查询 + 场地借用 (cdjy)
├── lib/      ← 图书馆 (Primo)
│   └── booking/   ← IC 图书馆预约（研讨室）
├── pms/      ← 联创打印
├── ws/       ← SUSTech Global 外事
├── booking/  ← E-Hall 网上办事大厅
├── nces/     ← 牛哇课程评价
└── transit/  ← 校巴时刻 + 实时 GPS + 校园地图 官方数据

# 第二行 —— 我们自建（在官方系统之上自己做的模块）
│
├── selectcourse/   ← TIS 选课辅助（浏览 / 加退 / 购物车）
│   └── ical.py     ← 已选学期的 .ics 导出
├── faculty/        ← 教师目录（列表 / 搜索 / 档案）
├── context/        ← 每日快照（日期、截止、当前课程、天气、AQI）
├── calendar.py     ← 校历与日期智能
├── papers/         ← 学术检索 / 抓取（CrossRef、CNKI、WoS、RSC）
├── webui/          ← Flask 单页应用（TIS + transit + NCES + iCal）
└── api/            ← 无 Flask 的 JSON 契约，供 webui / 自定义 skin 使用

# sso / authorizer —— 简化继承关系
Authorizer                      （抽象基类：ensure/check/refresh，内存会话，过期自检）
 ├── CASAuthorizer              （CAS 3.0 握手：取 execution token → POST 凭据 → 换票据）
 │     ├── TISAuth              BASE_URL + SERVICE_URL = TIS
 │     ├── BBAuth               BASE_URL + SERVICE_URL = 毕博
 │     ├── LibAuth              BASE_URL + SERVICE_URL = 图书馆 Primo
 │     ├── WiFiAuth             BASE_URL + SERVICE_URL = 校园 Wi-Fi 网关
 │     └── NCESAuth             CAS 经 Keycloak OIDC + cas-proxy（非普通票据）
 ├── ShibbolethAuthorizer       （Shibboleth：CNKIAuth、WoSAuth）
 ├── BookingAuth                （ehall authcenter，非普通 CAS）
 ├── PMSAuth、ACSAuth、JSTORAuth、IEEEAuth、SpringerAuth、WileyAuth、ScopusAuth、PubMedAuth（直接继承 Authorizer）
 └── WSAuth                     （经 WSProvider）
```

---

## 调试

最快的迭代方式是开发模式安装到工作目录，然后跑 pytest（需要真实凭据）。

```bash
git clone https://github.com/dumixthestpd/sustech_survival
cd sustech_survival
pip install -e ".[all]"

# 单元测试（mocked，快速）
python -m pytest src/test/ -v

# 现场测试（需要真实的 BB/TIS 凭据，详见 tests/）
python -m pytest src/test/ -v --live
```

---

## 待办

- [x] 统一的 `sustech.sso.Authorizer().ensure()` —— 把各系统的认证合并为一次 CAS 调用。✅ 已完成
- [ ] 更好的本地化（清晰区分中英文）
- [ ] 校园食堂每日菜单通知
- [ ] NCES 评论摘要（配置 API key 时可用；也可通过 skill 文档实现）

---

## 关于开发者

本模块由 **dumixthestpd**（南科大非计算机专业本科生）开发，他仅负责宏观设计。本模块 99% 的代码由 AI 助手编写，我们清楚地意识到由此带来的代码质量问题。我们欢迎更多同学加入开发 —— 在 GitHub Issues 发起讨论即可。也欢迎直接提 PR。

---

## 致谢

站在巨人的肩膀上：

- **[xCipHanD/SUSTech_AutoScheduler](https://github.com/xCipHanD/SUSTech_AutoScheduler)** — TIS 课程数据模型与时间编码解析的主要参考；他们的 bug 列表帮助我们在自己的选课器中规避问题。
- **[lethal233/sustech-tis-converter](https://github.com/lethal233/sustech-tis-converter)** — TIS REST 接口的早期探索。
- **[Fros1er/SUSTechTISHelper](https://github.com/Fros1er/SUSTechTISHelper)** — TIS 辅助工具。
- **[SUSTech-CRA/awesome-sustech-service-tools](https://github.com/SUSTech-CRA/awesome-sustech-service-tools)** — 南科大服务工具与 API 参考的精选列表。

完整列表与已知 bug 见 [CREDITS.md](./CREDITS.md)。

---

## 许可证

[PolyForm Noncommercial License 1.0.0](./LICENSE) — 仅限非商业使用，相同方式共享，保留署名。