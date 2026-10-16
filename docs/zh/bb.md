# BB（Blackboard）

## 目录发现与可用状态

通用目录扫描 `query.walk_contents()`、`query.discover_pages()` 会排除明确标为
`availability.available = "No"` 的内容，不展开其子目录，也不在全局搜索中继续
请求该项详情。`Yes`、`PartiallyVisible` 和缺失状态仍正常读取，权限错误照常处理。
这项过滤适用于目录发现；直接查询指定内容时仍由 BB 检查权限。

每次实时扫描重新读取父目录列表，目录开放后即可发现，不依赖修改时间或永久
黑名单。`discover_pages()` 在 stderr 提示不可用内容数量；缓存命中时也保留提示。
默认仍有一小时缓存，需要当前状态时使用 `refresh=True`。
不可用内容不计入结果，不能据此宣称已读取课程全部内容。

目录遍历复用一个认证会话，处理分页并拒绝循环、外部主机分页链接；根目录只读
一次。读取失败或响应格式错误会抛出异常，不将失败缓存为空列表或成功的部分
结果。此前包含不可用条目的发现缓存不再复用。

详细 API 示例见[英文版](../en/bb.md#content-discovery-and-availability)。

---

本页尚未翻译。最新内容请参阅[英文版](../en/bb.md)。

This page is not yet translated to Chinese. See the [English version](../en/bb.md) for current content.

要贡献翻译，请直接编辑本文件并提交 PR。
To contribute a translation, edit this file and open a PR.

## 跨课程未交与评分查询

```bash
sustech bb pending --json                  # 当前学期，全部截止时间
sustech bb grades --json                   # 本人已提交评估的各次尝试
sustech bb pending --semester '2026-2027-1' --json
sustech bb grades --course 101 --course 102 --json
sustech bb pending --course 101 \
  --due-from '2026-10-07T00:00:00+08:00' \
  --due-until '2026-10-14T23:59:59+08:00' --json
```

默认实时读取 BB 已选课程和学期表，选择日期范围覆盖查询时刻的唯一学期。
`--semester`（别名 `--term`）支持 BB 学期 ID、名称片段和学年学期代码。
学期日期缺失或重叠时请指定学期或课程 ID，程序不会自行猜测。
重复指定 `--course` 可以跨课程查询，不需要私人基线或本地课程缓存；
同时指定学期时取交集，并报告不属于该学期或未选的指定课程。

`pending` 默认包含历史逾期和无截止时间任务，分别标记未提交与草稿。
可用带时区的 ISO 时间设置包含边界的截止时间窗口；设置任一边界后，无截止
时间任务不属于该窗口，输出会注明。查询覆盖 `grading.type == Attempts`
的普通作业和测试型评估，类型分别展示，测试链接不等同于普通书面作业。

为兼容 SUSTech BB，attempts GET 不传可能触发学生会话 403 的 `userId` 查询
参数；仍完整分页、逐条核验响应中的归属字段，并在本地过滤本人记录。真正的
权限错误照常报告，不自动重试。

程序读取本人成绩记录核对免除状态，并分页读取本人 attempts。已提交待评分
不算欠交，免除项放入 `excluded`。小组任务没有个人提交不能证明无人提交；
不支持的类型、读取失败和标题明确“仅做通知提醒／请勿在此处提交”或对应
英文标记的条目放入 `unknown`/`errors`。标题规则不能识别全部外部平台流程。
个人延期、是否仍允许迟交、外部平台及小组实际完成情况仍需另行核实。

`grades` 查询本人已提交的作业和测试型评估。保留每次尝试的状态、时间和得分，
零分有效，满分取成绩列的实际值，不固定除以 100。`grade` 是 BB 直接报告的
成绩列结果，并标记来源；程序不根据多个尝试自行推断最高、最新或平均成绩。
内容元数据读取失败时仍保留已确认的分数。只有 `InProgressAgain` 而没有可核实
提交的条目保持无法确认。

默认输出易读文本，`--json` 的 stdout 只有 JSON，认证诊断走 stderr。
结构化结果使用 `schema_version: 1`，包含查询时间、时区、`scope`、
`courses_checked`、`attempt_columns_checked`、`items`、`excluded`、
`unknown`、`errors` 和 `complete`。时间使用 Asia/Shanghai。
错误包含阶段、诊断和可获得的 HTTP 状态/端点，不包含用户标识或查询参数。

完整结果退出码为 **0**，部分失败或无法确认为 **1**，无效参数为 **2**。
退出码 1 的结果仍可包含已确认项目，应连同覆盖缺口一起使用。
`items` 为空但 `complete: false` 不能解释为没有欠交。
这两个命令不保存报告、不更改学生账户。

```python
from sustech_survival.bb.assessments import query

pending = query('pending', semester='2026-2027-1')
grades = query('grades', course_ids=['101', '102'])
# 可用 session= 传入包内 authorizer 提供的会话；一次查询复用一个会话。
if not pending['complete']:
    print(pending['unknown'], pending['errors'])
```

截止日期查询读取完整的个人选课列表，不固定 BB 学期 ID，再按日期窗口筛选。尝试列表读取全部分页并过滤当前用户；读取失败或无法确认归属时会报错。`apply_submission()` 的文件与附带评论在同一次请求中提交，只创建一次尝试。
