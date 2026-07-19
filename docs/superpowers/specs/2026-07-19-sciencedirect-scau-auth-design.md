# ScienceDirect 华南农业大学机构认证设计

## 背景与已确认选择

`v0.1.0` 只在当前网络已经具有华南农业大学校园 IP 权限时获取
ScienceDirect 订阅内容。用户现已明确授权保存并由 agent 自动调用华南农业大学统一身份认证凭据。

华南农业大学图书馆当前推荐从学校 WebVPN 进行校外访问；该入口使用学校统一身份认证的
学号或工号与密码。ScienceDirect 的 Elsevier 个人账号不作为订阅权限来源。

## 方案比较

1. **华南农业大学 WebVPN（采用）**：先尝试现有直接访问；无权限时通过学校官方 WebVPN
   建立校园访问上下文，再访问 WebVPN 重写后的 ScienceDirect 文章。该方案直接对应学校
   官方校外访问说明，并允许隔离 profile 复用已认证会话。学校最新说明同时指出 Elsevier
   全文库在 WebVPN 不适用时需要 aTrust；因此 WebVPN 代理仍无 entitlement 时返回
   `atrust_required`，不得把代理登录成功误报为论文权限成功。
2. **Elsevier 机构搜索/联合登录**：依赖 ScienceDirect 当前前端、组织搜索结果和学校是否
   开通联合身份认证，且当前入口会触发出版商反自动化挑战。保留为未来页面契约，不作为本次主路径。
3. **要求用户预先连接 VPN**：实现最简单，但不能满足无人值守下载要求，仅作为凭据缺失、
   CAPTCHA、OTP 或学校页面变化时的显式回退。

## 安全边界

- 新增可选 DPAPI scope `sciencedirect_scau`，组织必须精确等于
  `South China Agricultural University`。
- 凭据只可由桥接脚本在当前页面主机精确等于 `vpn.scau.edu.cn` 时读取；相似主机、子域扩展、
  HTTP 页面、CAPTCHA、OTP 和未知跳转均停止。
- 入口只允许 `lib-scau-edu-cn-s.vpn.scau.edu.cn`，代理文章及产物只允许
  `www-sciencedirect-com-s.vpn.scau.edu.cn`，规范出版商身份仍是
  `www.sciencedirect.com`。
- 使用 `%LOCALAPPDATA%\Codex\browser-profiles\acquire-research-papers\sciencedirect-scau`
  的独立持久 profile；不访问用户日常 Chrome profile，不导出 Cookie。
- stdout 只输出一个无敏感信息的 JSON 结果；stderr 只输出结构化 phase 与清理后的错误。
- 登录只提交一次。出现 CAPTCHA、OTP、无唯一登录字段、认证未完成或代理 entitlement 缺失时，
  返回结构化 `access_required`；代理登录成功但 Elsevier 仍无权限时返回 `atrust_required`。
  不得循环提交、自动安装/控制 aTrust 或绕过访问控制。

## 数据流

1. `ScienceDirectAdapter` 按现有路径尝试开放获取或当前校园/IP entitlement。
2. 页面没有授权 PDF 或产物返回 401/403 时，调用 `ScienceDirectBridge`。
3. 桥接器在隔离 profile 中打开学校官方 WebVPN 入口。
4. 若已有有效会话，直接进入代理文章；否则仅在精确认证主机读取并提交
   `sciencedirect_scau` 凭据一次。
5. 浏览器从代理文章读取 PII、DOI、标题、作者、年份和期刊，下载同一 PII 的 PDF 与
   `/sdfe/arp/cite` 原始 BibTeX。
6. Python 侧验证代理 URL、PDF 文件头、规范 DOI/PII 和官方 BibTeX，再交给现有交付与注册表流程。

## 组件边界

- `scripts/secret-store.ps1`：原子保存和校验可选 SCAU scope。
- `scripts/setup-sciencedirect-secret.ps1`：只更新 SCAU scope，不要求重输 IEEE 或 MinerU。
- `scripts/read-sciencedirect-credential.ps1`：精确主机凭据桥。
- `scripts/sciencedirect-playwright.mjs`：WebVPN 登录、代理文章解析和产物下载。
- `src/.../sciencedirect.py`：直接访问优先，授权失败时委托浏览器桥，并继续暴露统一 adapter 契约。
- `tests/powershell`、`tests/node`、`tests/unit`：分别覆盖密钥隔离、页面状态机和 Python 边界。

## 验收标准

- 现有密钥文件可原位增加 SCAU scope，IEEE 和 MinerU 密文仍可读取。
- 恶意相似主机无法触发凭据释放。
- 开放获取 ScienceDirect 论文仍不启动浏览器。
- 订阅论文在当前网络无权限时自动尝试一次华农 WebVPN，并交付官方 PDF 与原始 BibTeX。
- 若学校策略要求 aTrust，输出 `atrust_required`，且不下载客户端、不伪造成功。
- 重复获取通过注册表或持久会话复用，无需再次登录。
- 普通 fetch 不产生 Markdown；所有测试、敏感信息扫描和远端 CI 通过。
