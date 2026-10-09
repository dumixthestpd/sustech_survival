# 联创打印 PMS

查询打印点、待打印队列，或将文件上传到校园 PMS 队列。

## 登录与查询

需安装 `[pms]` 扩展依赖，认证模块同时提供旧版 RSA 登录功能。

```python
from sustech_survival.sso import PMSAuth

auth = PMSAuth()
ok, reason = auth.ensure()
if not ok:
    raise RuntimeError(reason)
```

默认登录沿网页的 `Auth/SSoPage → authcenter → CAS → PMS` 流程，实时发现
service 回调，全程复用内存中的会话和 cookies，最后通过 `Auth/Check` 验证。
无需浏览器；遇到交互认证挑战时停止。`pms()` 会检查认证结果并复用有效会话，
失败时保留原因，不继续访问不存在的会话。

`login_via_cas()` 也使用这条流程，保留 `headless` 参数以兼容旧调用。
`login_password()` 是独立的旧版 RSA 打印账号入口，需要 `[pms]` 扩展依赖；
它不是默认 CAS 登录方式。该接口报告“无效会话”不能证明校园密码错误，
默认流程也不会自动回退到它。

```bash
sustech pms check
sustech pms jobs --json
sustech pms stations --json
```

失败返回非零退出码，认证诊断输出到 stderr，JSON 输出可单独解析。

## 上传及核验

```python
from sustech_survival.pms import pms

client = pms()
preview = client.upload_print("PMS_TEST.pdf", paper="A4", color="bw",
                              duplex="long", copies=1, dry_run=True)
# 检查文件和参数、获得上传授权后：
receipt = client.upload_print("PMS_TEST.pdf", paper="A4", color="bw",
                              duplex="long", copies=1)
print(receipt.status, receipt.job_id, receipt.verification_url)
```

预览没有网络请求。实际上传先读取队列 ID，发送一次 multipart POST，
将正确队列页面设为 `BackURL`，识别 JSON 或本站结果跳转，再回读一次队列。
上传请求不会自动跟随跳转或重复 POST。

- `confirmed`：读到唯一新增同名任务，`ok=True`、`uploaded=True`，返回 `job_id`。
- `unknown`：`ok=False`、`uploaded=None`。响应丢失、回读失败、任务尚未出现
  或新增同名任务不唯一时，都不能断言失败。检查 `observed_job_ids`、
  `http_status`、`response_format`、`verification_error`，先查队列再考虑重试。
- `rejected`：明确拒绝且未读到新增同名任务，`uploaded=False`。
  上传前队列不可用则不发送上传。

不能仅凭 `ok=False` 重传。上传只创建队列任务，不触发实际打印。
正确队列页面为 <https://pms.sustech.edu.cn/client/new/cprintPc/printDoc.html>。

## 双面参数与队列显示

客户端以 PMS 队列列表的长短边显示为准：

| 选项 | `dwDuplex` | 队列标记 | 队列显示 |
| --- | --- | --- | --- |
| `"single"` / `DUPLEX_SINGLE` | 1 | `single` | 单面 |
| `"long"` / `"双面长边"` / `DUPLEX_LONG_EDGE` | 2 | `vdup` | 双面长边 |
| `"short"` / `"双面短边"` / `DUPLEX_SHORT_EDGE` | 3 | `hdup` | 双面短边 |

数字及数字字符串直接使用同一参数值。上传页的长短边标签与列表相反，
字符串别名、预览及队列显示均遵循列表含义。本次修正了原来的
`long=3`、`short=2` 别名和常量映射；直接传入数字的调用保持原数值。

队列保留 `duplex_flag`，`vdup` 的 `duplex_edge="long"`，`hdup` 为 `"short"`。
缺失或冲突的单双面标记仍返回 `is_duplex=None`、`duplex_edge=None`。

其他方法见 [英文指南](../en/pms.md)。删除打印或扫描任务会更改账号状态，
需要另外获得授权。
