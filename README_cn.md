[English](README.md) | [简体中文](README_cn.md)

# sustech-survival

`sustech_survival` 是一个允许在 api 层面调用南科大各服务系统的 Python 模块。它满足南科大学生在 bb、tis、lib、pms 等系统的日常需求。

通过在代码层面打通这些服务，我们简化了校园系统的使用，提供了一条通往个性化校园体验的捷径，更重要的是 —— 接入并欢迎 AI 助手进入你的校园生活。

```bash
pip install git+https://github.com/dumixthestpd/sustech-survival.git
```

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
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

## 安装 / Installation

```bash
pip install git+https://github.com/dumixthestpd/sustech-survival.git
```

可选扩展 / Optional extras：

```bash
pip install "sustech-survival[cli]"        # `sustech` 统一 CLI 调度器
pip install "sustech-survival[webui]"      # Flask 单页应用（TIS + transit + NCES）
pip install "sustech-survival[playwright]" # 旧版 BB 文件爬虫
pip install "sustech-survival[all]"         # 全部
```

---

## 快速开始 / Quick start

### 1. 安装 / Install

```bash
pip install "sustech-survival[webui]"
```

### 2. 首次导入 —— 验证认证 / First import — verify auth

```python
import sustech_survival as sustech

sustech.sso.BBAuth().ensure()   # 首次运行会提示输入凭据
print("Blackboard session OK")
```

### 3. 每日快照（为 AI 助手设计）/ Daily-use snapshot

```python
from sustech_survival.context import Context

ctx = Context(level="normal")   # terse / normal / verbose
print(ctx.to_str())
# → Today is [2026-07-04], [Saturday]
# → Next BB deadline: [Experiment 5] — Due in 3 days
# → Next TIS exam: [...final...]
```

### 4. 启动 Web 界面 / Start the web UI

```bash
python -m sustech_survival.webui
```

浏览器打开 `http://localhost:61019`。你将获得：
- TIS 选课界面（含冲突求解）
- 校园巴士地图（实时 GPS）
- 每个课程的 NCES 悬浮卡片

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

- [ ] 更好的本地化（清晰区分中英文）Better localization (cleanly differentiate EN vs CN)
- [ ] 校园食堂每日菜单通知 Campus canteen daily food notice
- [ ] NCES 评论摘要（配置 API key 时可用；也可通过 skill 文档实现）NCES comment summarization

---

## 关于开发者 / About the dev

本模块由 **dumixthestpd**（南科大非计算机专业本科生，学号 12413021）开发，他仅负责宏观设计。本模块 99% 的代码由 AI 助手编写，我们清楚地意识到由此带来的代码质量问题。我们欢迎更多同学加入开发 —— 通过南科大教育邮箱联系，会进一步提供加入开发的相关信息。也欢迎直接提 PR。

This module is developed by **dumixthestpd**, a non-CS undergraduate student (ID 12413021) at SUSTech, who only controls the macroscopic design. 99% of this module is agent-written and we're aware of the problematic code quality. We welcome more students to join us and contribute — contact via SUSTech edu mail. PRs are also welcome.

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

Non-commercial use only, share-alike, preserve attribution.