# IEEE 机构访问

IEEE 使用独立、可见的 Chrome profile，因为机构认证和 PDF 请求必须共享同一个隔离浏览器上下文。创建、选择和检查命名院校档案的方法见[配置](configuration.md#命名院校档案)。

## CARSI 登录的执行过程

流程会先尝试直接读取论文，不会一开始就读取凭据；缺少权限时才会：

1. 进入院校档案中配置的准确 CARSI IEEE 资源入口；
2. 选择准确的院校候选，并写入、校验 IdP entity ID；
3. 只有当前域名与配置的 IdP 域名完全一致时，才读取当前 profile 凭据，并且最多提交一次；
4. 处理单“继续”按钮或“接受/拒绝”属性释放页，永远不点击拒绝；
5. CARSI 返回但尚未获得 IEEE 权限时，只重新访问配置的同一资源入口；
6. 必须确认同一上下文已经返回准确的 `ieeexplore.ieee.org`，才请求 PDF 和 BibTeX。

配置的接受/继续控件默认自动点击。传入 `--no-accept-ieee-attribute-release` 可以把可见页面留给用户手动完成。

## 适配新院校

公共脚本中不包含院校名称分支或共享凭据。新院校应优先通过 profile 适配：准确的 CARSI 候选、entity ID、IdP 域名、可访问表单标签、资源入口和继续/接受控件。保持浏览器可见，只使用脱敏后的阶段/域名诊断；每次修正后先用一篇代表论文测试。

只有可见页面证明出现了 profile 无法表达、而且可以复用的新页面形态时，才修改通用浏览器脚本，并先添加回归 fixture。整个过程必须保留准确域名凭据释放、一次凭据提交、三次资源入口上限、共享 Cookie、禁止点击拒绝和查询参数脱敏。

要申请支持新院校，请只附脱敏诊断提交[院校适配请求](https://github.com/EnosElinsa/acquire-research-papers/issues/new?template=institution.yml)。
