# 实施记录：可组合、跨平台、多 Agent 文献工具

验收日期：2026-10-20。版本：0.5.0。本文保留发布前的本地验收快照；后续提交、CI 和正式发布状态以 Git 历史、Actions 及 GitHub Release 为准。分支：`codex/portable-research-workflows`；基线：`9df9641` / v0.4.0。

工作目录：`C:/Users/labs2/.codex/worktrees/portable-research-workflows/acquire-research-papers`。实施阶段保留原始 checkout，未替换用户已安装的 skill，未读取或迁移真实用户凭据。用户随后明确授权提交和发布；发布流程在本地检查及远端 CI 通过后推进。

统一设计与剩余外部验收见 [计划](superpowers/plans/2026-10-20-portable-composable-research-workflows.md)。本文记录实际实现、证据和范围，不将 CI 配置或文件存在当作实测认证。

## 已实现

| 范围 | 实现与兼容边界 |
| --- | --- |
| 文件配置 | 新安装默认文件后端；`config init/path/edit/setup/status`；dotenv 无执行、无插值、无工作区搜索；一个选定文件及每命令快照；进程环境优先，显式空值为未配置。 |
| 院校与迁移 | profile 独立文件、准确域名、保存密码与自动登录分离；Windows 用户 ACL / POSIX 0600；旧后端显式迁移、冲突预检、切换最后执行、保留旧存储；持久迁移日志和 OS 锁恢复中断。 |
| IEEE 凭据通道 | 按需通过 stdin JSON 传递，不进入命令行或公开输出；缺账号不妨碍 inspect、OA 或已有会话；真正填表时才报缺失；域名拒绝和损坏 DPAPI 仍失败。 |
| 通用能力 | identity、metadata、collection、review、selection、verify、parse、evidence、export，以及独立 discovery/acquisition CLI；复用已有来源、发现、冻结选集、获取和核验实现；离线能力不初始化浏览器。 |
| 评审与证据 | v2 记录实际宿主和可用模型信息；v1 保持兼容；身份/相关性/全文策略分别核验；全文证据绑定 PDF、Markdown 哈希及实际原文；不生成摘要或原始 BibTeX。 |
| 状态与恢复 | RunContext 参数/输入/输出哈希、每项状态、next_actions、OS 锁和原子写；重跑前重验；旧 manifest 只读适配；原模式保留原恢复方式；MinerU 缓存哈希、进程终止释放锁、损坏缓存不复用。 |
| 本地库 | 保留扫描、计划、apply、备份、幂等恢复及 rollback；保留原始引用字节、冻结 ID/哈希和来源边界。 |
| 宿主与组合 | 四宿主路径及安全安装、共享 SKILL/runtime、Kiro 资源模板、doctor；七个组合示例和输入模板。没有新增 DAG 引擎、常驻服务或 Agent 并发调度器。 |
| 发布结构 | v0.5.0 wheel 和薄 skill ZIP；schema 镜像、明确资产允许列表及空 `.env` 模板；CI 矩阵扩为三平台 × Python 3.11/3.13。 |

相关入口：[能力接口](../skills/acquire-research-papers/references/capabilities.md)、[凭据说明](../skills/acquire-research-papers/references/credentials-and-cache.md)、[宿主适配](../skills/acquire-research-papers/references/hosts.md)、[七个组合示例](../skills/acquire-research-papers/examples/README.md)。

## 最终验证证据

以下命令均在本地 Windows 执行；Python 环境分别隔离，测试凭据均为临时合成值。基线 495 项；最终每套 664 项，其中 663 通过、1 跳过。

| 检查 | 结果 |
| --- | --- |
| Python 3.11.15，`uv run --python 3.11 --locked pytest -q --tb=short` | 663 passed, 1 skipped；47.75s。 |
| Python 3.13.12，`uv run --python 3.13 --locked pytest -q --tb=short` | 663 passed, 1 skipped；45.06s。 |
| Ruff，`uv run ruff check src tests scripts skills/acquire-research-papers/scripts` | All checks passed。 |
| Node，两个 IEEE helper 测试文件 | 61 passed，0 failed。 |
| PowerShell `test-secret-store.ps1`、`test-install-playwright.ps1`、`test-ieee-profiles.ps1` | 三套均通过。 |
| 源码 skill 与最终导出 skill 的 `scripts/validate_skill.py` | 两者均为 Skill is valid；schema 镜像一致。 |
| 最终 wheel / skill 构建 | 成功，version 0.5.0；runtime.json 绑定实际 wheel 哈希。 |
| 仓库外隔离安装 | 独立 Python 3.11 venv 导入 site-packages；20 次 CLI 调用通过；四个临时项目完成宿主目录安装及本地 doctor。 |
| 工件检查 | wheel/ZIP 不含真实 `.env`、DPAPI 存储、源码 checkout 或运行数据；ZIP 仅含允许的薄 skill 资产和空模板。 |
| 文档及最终分支检查 | 文档允许列表、skill 布局、发行包、doctor 相关 44 项通过；`git diff --check` 通过。 |

唯一跳过项为 Windows 当前账户缺少创建符号链接的权限，对应文件凭据符号链接防护测试。其余测试覆盖特殊字符和中文、配置优先级与脱敏、机构隔离、迁移冲突/中断、独立能力、过期证据、并发锁、哈希变化、原始 BibTeX、入库备份/回滚。

完整套件在最终代理写入结束前曾出现两项失败：3.11 平台探测启动子进程、DPAPI 测试编码异常。平台探测已改为进程内 API，并增加禁止 process-capable API 的断言；最终静态源码下两套完整回归均通过。

隔离 smoke 使用无凭据临时配置和 `ARP_LOCAL_WHEEL`，验证版本、schema、config init/path/status、身份解析及缓存复用、集合比较/合并、CSV 导出、Claude Code v2 评审导入、冻结选集、run status 检测工件变化、薄启动器及四宿主本地 doctor。没有调用实际模型或机构登录。

## 平台与宿主支持矩阵

| 对象 | 自动/本地证据 | 未验证部分 |
| --- | --- | --- |
| Windows 核心 Python | 3.11.15 与 3.13.12 全套回归；隔离 wheel/launcher 安装 | 不代表全部外部 provider 实时可用。 |
| macOS / Linux 核心 Python | 已配置 CI 3.11/3.13；跨平台路径/文件/锁逻辑及合成测试 | 本次未执行这两个系统的 CI，不能称已通过。 |
| Codex | 导出目录安装、doctor；CLI 0.163.0-alpha.10.2 的 `--version` | 此次未实际加载新 skill 或完成宿主交互工作流。 |
| Claude Code | 导出目录安装、doctor、真实宿主标记的 v2 合成评审；CLI 2.1.107 的 `--version` | 未实际加载 skill 或调用 Claude 执行工作流。 |
| Kiro IDE | 安装路径、共享 skill 和本地 doctor | IDE 版本、导入、实际发现及调用未验证。 |
| Kiro CLI | 安装路径、资源配置模板和本地 doctor | 本机未检测到 CLI；真实 custom agent 加载未验证。 |
| IEEE 浏览器 | Windows Node/Python/PowerShell 合成回归；精确域名及 stdin 通道 | 本次未做真实机构订阅验证；macOS/Linux 浏览器引导仍未实现/验证为完整支持。 |
| DPAPI | Windows 合成密文读写、可选读取、拒绝/损坏错误、迁移与恢复测试 | 仅为 Windows 旧后端；不作为跨平台默认。 |

历史成功院校访问不能替代此次真实授权检查；开放获取成功也不证明订阅权限。`doctor` 中 host_load 与 institution_access 继续明确为 unverified。

## 本地构建与审阅

最终本地发布候选目录：`C:/Users/labs2/AppData/Local/Temp/arp-portable-release-050`。

- Wheel：`acquire_research_papers-0.5.0-py3-none-any.whl`。
- Skill：`acquire-research-papers-skill-0.5.0.zip` 及 `skills/acquire-research-papers/`。
- Wheel SHA-256：`fb2da4ca35497586726aee9bd8d6fc84f5bf6cd4253684f891861e3207a94cab`。
- smoke 结果：`C:/Users/labs2/AppData/Local/Temp/arp-portable-smoke-050-i1yxw71y/smoke-summary.json`。

上述目录是本机临时验收工件。发布流程将同一哈希的 wheel、薄 skill ZIP 和 SHA256SUMS 上传 GitHub Release，随后验证公开安装 URL；发布前的本地测试不证明远程引导可用。计划/本记录已列入文档允许列表和 Git 文件清单。
