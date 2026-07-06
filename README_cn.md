[English](README.md) | [简体中文](README_cn.md)

# sustech-survival

`sustech_survival` 是一个允许在 API 层面调用 SUSTech 各服务系统的 Python 模块。它满足 SUSTech 学生在 BB、TIS、图书馆、PMS 等系统的日常需求。

通过在代码层面打通这些服务，我们简化了校园系统的使用，提供了一条通往个性化校园体验的捷径，更重要的是 —— 接入并欢迎 AI 助手进入你的校园生活。

[![GitHub](https://img.shields.io/badge/github-repo-blue.svg)](https://github.com/dumixthestpd/sustech-survival)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## 功能 / Features

### 校园系统 / Campus systems

包装南科大现有服务。For the English name, see [README.md](./README.md).

- **毕博平台 Blackboard Learn** (`bb`)
- **教学信息服务 Teaching Information System (TIS)** (`tis`)
- **图书馆 SUSTech Library** (`lib`)
- **统一身份认证 Single Sign-On (SSO)** (`sso`) — 共享认证底座
- **联创打印 Campus Printing System** (`pms`)
- **外事 SUSTech Global** (`ws`)
- **网上办事大厅 E-Hall** (`booking`)
- **牛哇课程评价 Niuwa Curriculum Evaluation System (NCES)** (`nces`)

### 自建 / We built

- **selectcourse** — TIS 选课：浏览课程、加退选、管理购物车。
- **faculty** — 教师信息目录：按学院列表、全文搜索、个人主页查询。
- **transit** — 校园巴士与步行导航：时刻表、实时 GPS、路线规划。
- **webui** — Flask 单页应用，整合 TIS 选课界面、公交地图、NCES 悬浮卡片。启动方式：`python -m sustech_survival.webui`。
- **context** — 为 AI 助手设计的每日快照：日期、周次、最近的作业/考试/上课时间、天气、AQI。
- **papers** — 学术论文搜索与下载，覆盖 CrossRef、CNKI、WoS、RSC。

---

## 快速开始 / Quick start

### 1. 安装 / Install

按需选择扩展：

| 扩展 / Extra | 提供能力 | 适用场景 |
|---|---|---|
| (无) | 仅 Python 模块 | 你写自己的脚本 |
| `cli` | `sustech bb`、`sustech tis`、`sustech nces` 等统一调度器 | 你想要终端工作流 |
| `webui` | Flask 单页应用：TIS 选课界面 + 公交地图 + NCES 悬浮卡片 | 你想要浏览器界面 |
| `playwright` | 旧版 BB 文件下载爬虫 | 你在无头服务器上 |
| `all` | 以上全部 | 你不想思考 |

```bash
# 任选其一：
pip install "sustech-survival[cli]"          # 仅 CLI
pip install "sustech-survival[webui]"        # 仅 web UI
pip install "sustech-survival[all]"          # 全部
```

### 2. 身份认证（计划中 —— 暂未实现）

> 计划是在 `sustech_survival/sso/authorizer.py` 中提供一个直接对接
> 南科大 CAS 的统一基类：
>
> - CAS 端点：`https://cas.sustech.edu.cn/cas/login`
> - 统一调用：`sustech.sso.Authorizer().ensure()`
>
> 上线后，每个系统（BB、TIS、NCES 等）的登录都将合并为一次调用。
> 在此之前，各子模块有各自的 authorizer，请按对应子模块的具体
> 说明进行设置。进展见 Todo 章节。

### 3. 示例用法 / Example use

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

**Web 界面（最常用的工作流）：**

```bash
python -m sustech_survival.webui
```

浏览器打开 `http://localhost:61019` —— TIS 选课界面（含冲突求解）、
校园巴士地图（实时 GPS）、每个课程的 NCES 悬浮卡片。

---

## 相关项目 / Related projects

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** — 南科大校历（学期、工作日、节假日）。计划作为 `tis`、`context` 等时间相关模块的依赖。

---

## 架构 / Architecture

```
sustech_survival/
├── bb/                ← Blackboard Learn / 毕博
├── tis/               ← Teaching Information System (TIS) / 教学信息服务
│   └── classroom/     ← TIS 教室查询 + 场地借用 (cdjy)
├── lib/               ← SUSTech Library / 图书馆
├── sso/               ← 共享认证底座（CAS + Shibboleth）
├── pms/               ← Campus Printing System / 联创打印
├── transit/           ← 校园巴士地图（自建）
├── faculty/           ← 教师目录（自建）
├── selectcourse/      ← TIS 选课辅助（自建）
├── booking/           ← E-Hall / 网上办事大厅
├── ws/                ← SUSTech Global / 外事
├── context/           ← 每日快照（自建）
├── nces/              ← Niuwa Curriculum Evaluation System / 牛哇课程评价
├── papers/            ← CrossRef / CNKI / WoS / RSC（自建）
├── exceptions.py
└── webui/             ← Flask 单页应用（自建）：TIS + transit + NCES
```

---

## 调试 / Debugging

最快的迭代方式是开发模式安装到工作目录，然后跑 pytest（需要真实凭据）。

```bash
git clone https://github.com/dumixthestpd/sustech-survival
cd sustech-survival
pip install -e ".[all,playwright]"
playwright install chromium

# 单元测试（mocked，快速）
python -m pytest tests/ -v

# 现场测试（需要真实的 BB/TIS 凭据，详见 tests/）
python -m pytest tests/ -v --live
```

---

## 待办 / Todo

- [ ] 更好的本地化（清晰区分中英文）Better localization
- [ ] 校园食堂每日菜单通知 Campus canteen daily food notice
- [ ] NCES 评论摘要（配置 API key 时可用；也可通过 skill 文档实现）
- [ ] 统一的 `sustech.sso.Authorizer().ensure()` —— 把各系统的认证合并为一次 CAS 调用（`https://cas.sustech.edu.cn/cas/login`）

---

## 关于开发者 / About the dev

本模块由 **dumixthestpd**（南科大非计算机专业本科生，学号 12413021）开发，他仅负责宏观设计。本模块 99% 的代码由 AI 助手编写，我们清楚地意识到由此带来的代码质量问题。我们欢迎更多同学加入开发 —— 通过南科大教育邮箱联系，会进一步提供加入开发的相关信息。也欢迎直接提 PR。

---

## 致谢 / Credits

站在巨人的肩膀上：

- **[xCipHanD/SUSTech_AutoScheduler](https://github.com/xCipHanD/SUSTech_AutoScheduler)** — TIS 课程数据模型与时间编码解析的主要参考；他们的 bug 列表帮助我们在自己的选课器中规避问题。
- **[lethal233/sustech-tis-converter](https://github.com/lethal233/sustech-tis-converter)** — TIS REST 接口的早期探索。
- **[Fros1er/SUSTechTISHelper](https://github.com/Fros1er/SUSTechTISHelper)** — TIS 辅助工具。
- **[SUSTech-CRA/awesome-sustech-service-tools](https://github.com/SUSTech-CRA/awesome-sustech-service-tools)** — 南科大服务工具与 API 参考的精选列表。

完整列表与已知 bug 见 [CREDITS.md](./CREDITS.md)。

---

## 许可证 / License

[PolyForm Noncommercial License 1.0.0](./LICENSE) — 仅限非商业使用，相同方式共享，保留署名。