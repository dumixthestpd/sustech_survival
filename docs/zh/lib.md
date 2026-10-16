# 图书馆（Primo）

通过 Primo 检索馆藏和文章、读取书目详情。`LibAuth` 使用共享 CAS 登录；
原有 TLS 兼容配置同时覆盖直连和代理连接池，无需关闭本地代理。
登录会话和浏览器渲染保留 cookie 的实际域名、路径及更新。

安装页面渲染依赖及浏览器：

```bash
python -m pip install 'sustech_survival[playwright]'
python -m playwright install chromium
sustech lib search '微分几何入门与广义相对论' --limit 8 --json
sustech lib detail <docid> --json
```

```python
from sustech_survival.lib.search import search, detail, LibraryError

try:
    rows = search("微分几何入门与广义相对论", scope="default", limit=8)
    if rows:
        record = detail(rows[0].docid)
except LibraryError as exc:
    print(exc)
```

`catalog` 为全部资源，`default` 为本馆目录，`eresource` 为电子资源。
检索使用当前 `/discovery/search` 页面；筛选参数传入 Primo URL。
Primo 会把深链接偏移重置为零，因此分页窗口直接应用到页面发出的只读 PNX
查询。
详情按稳定字段标记读取，避免把页面标题或推荐书目拼进题名、ISBN 和出版信息。

只有 Primo 查询响应确认当前窗口无记录时才返回空数组。认证失败、缺少 Playwright/Chromium、
HTTP 错误、跳回登录或交互挑战、结果页未加载或数据不完整均抛出
`LibraryError`；CLI 非零退出，诊断输出到 stderr，不会伪装成成功的 `[]`。
CAS 网络错误区分登录和票据交换阶段、指明失败主机，不输出 ticket 或原始响应。
遇到交互认证挑战会在提交凭据前停止。

IC 空间查询及预约使用独立的 `lib-booking`，见[图书馆预约](lib-booking.md)。
馆藏检索成功不代表出版社全文访问成功，也不会创建任何预约。
