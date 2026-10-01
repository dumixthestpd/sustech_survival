# 开源镜像 (mirrors.sustech.edu.cn)

南方科技大学 CRA 维护的**开源镜像站**：培养方案、课程教学大纲、校园地图、
新生手册、目录列表 —— 全部公开、**无需登录**。想知道一门课到底讲什么，
这是最快的路径，不用自己去翻 PDF。

镜像内容由南科大 CRA 维护，采用 **CC-BY-SA-4.0** 许可；转给别人时请保留署名。

**鉴权：** 除 `mirror course` 外都不需要。`mirror course` 读的是 TIS 的
成绩记录 / 课程库，所以要有 TIS 会话（见 [SSO](sso.md)）。

---

## 命令行

```bash
sustech mirror syllabus url CSE104        # 只打印链接，不联网
sustech mirror syllabus exists CSE104     # HEAD 探测，不存在则退出码 1
sustech mirror syllabus get CSE104        # 下载 PDF
sustech mirror syllabus extract CSE104    # 下载并抽取文本（别名 text）
sustech mirror syllabus open CSE104       # 用默认浏览器打开
sustech mirror syllabus list-departments  # 哪些院系有大纲
sustech mirror syllabus batch --semester 2026-2027-1   # 按学期批量抓取

sustech mirror program years              # 镜像里有哪些年级的培养方案
sustech mirror program url 2024级         # 真实存在的链接（先探 PDF，再探年级目录）
sustech mirror program list 2024级        # 该年级目录里各专业的 PDF
sustech mirror program get 2024级         # 下载；目录型年级取 00-通识培养方案
sustech mirror program get 2024级 --all   # 该年级所有专业的方案
sustech mirror program get 2024级 --index 19   # 只要 19-计算机科学与技术专业…

sustech mirror handbook get freshman-2022 # 按类型取一本手册
sustech mirror map get                    # 校园地图 PDF
sustech mirror list /courses              # 目录列表（尽力而为）
sustech mirror course CSE104              # 走 TIS 的课程元数据
```

默认下载到 `~/.sustech_survival/downloads/`（`syllabus/`、`program/`、
`handbook/` 等），可用 `-o/--output` 指定；已存在的文件默认跳过，加
`--overwrite` 才覆盖。

**2019–2024 级是目录，不是单个文件**：每个年级一个目录，里面按专业一份 PDF
（`00-…通识培养方案.pdf`、`01-…金融数学专业…` 等），另有通识必修课要求一览表；
只有最新年级是全校一份 PDF。所以 `program url` 先探测再输出，`program list`
列出目录内容，裸 `program get <年级>` 取锚定该目录的 `00-通识` 方案。
所有输出链接都是百分号编码 —— 镜像对未编码的 UTF-8 路径返回 404，
所以裸链接在浏览器里能开（浏览器会自动编码），在 `curl`/`wget`/脚本里会失败。

`syllabus batch` 会遍历该学期 TIS 课表里出现的所有课程代码，已下载的自动跳过，
因此可以反复执行；`--dry-run` 只列出将要抓取的内容，`--extract` 同时存文本。

---

## Python 接口

```python
from sustech_survival.mirror import (
    MIRROR_BASE, syllabus_url, syllabus_exists, syllabus_fetch,
    syllabus_download, syllabus_extract_text, SyllabusNotFound,
)

syllabus_url("CSE104")                  # 不联网
syllabus_exists("CSE104")               # HEAD 探测 → bool
pdf = syllabus_fetch("CSE104")          # bytes（找不到抛 SyllabusNotFound）
path = syllabus_download("CSE104", out_dir="downloads")
text = syllabus_extract_text("CSE104")
```

`mirror/tis_fallback.py` 负责兜底：镜像里没有的代码，去 TIS 课程库取同样的信息
（课程名、学时、先修），调用方不必自己处理“没找到”。

---

## 两个实现保持一致

TypeScript 版（`sustech-cli` fork）挂载同一族命令，并在
`capabilities`/`describe` 里注册，便于 agent 发现。Python 这边多出
`syllabus open`、`syllabus list-departments`、`syllabus batch`，以及
`mirror course --text/--include-raw`。按 fork 的镜像规则，两边的发现要互相回流。

---

## 相关

- [TIS](tis.md) —— `syllabus batch` 遍历的课表来源。
- [选课](selectcourse.md) —— 拿到大纲之后做什么。
- [NCES](nces.md) —— 社区课程评价，回答“这门课值不值得选”。
