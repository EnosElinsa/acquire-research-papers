# 可组合、跨平台、多 Agent 的文献工具重构计划

状态：代码、文档、构建及本地验收已完成；用户已授权提交和发布 v0.5.0，远端验收结果以 Actions 和 GitHub Release 为准。基线：v0.4.0；495 项 Python 回归测试。真实宿主加载、平台执行及当前院校访问的验证边界见 [实施记录](../../portable-workflows-progress.md)。

## 目标与约束

重构为独立能力、共享契约、轻量运行记录和应用组合示例。当前 Agent 负责语义判断；Python CLI 负责确定性执行和核验。本文统一替代此前互相冲突的发现、凭据、平台和宿主重构方案，历史实现记录保留。

- 本地可编辑 `.env` 是新安装默认凭据后端；DPAPI 仅保留旧安装兼容与显式迁移。
- 作者查漏、论文集、Related Work 和 gap 分析是组合场景，不是新的内核任务类型。
- 核心能力可以独立执行；保留现有命令、冻结清单和 ID、原始 BibTeX 字节、核验、人工接管、备份和回滚。
- 共用运行时支持 Codex、Claude Code、Kiro IDE 与 Kiro CLI。核心覆盖 Windows/macOS/Linux；IEEE 浏览器逐平台验证。
- 保留官方 PDF/原始 BibTeX 获取契约、准确域名释放、院校与浏览器隔离；ScienceDirect 页面操作保持用户手动完成。
- Python 3.11+；现有 HTTP/解析库、JSON Schema、薄启动器；增加 python-dotenv。不增加常驻服务、任意 DAG 引擎、并发 Agent 编排或首轮 MCP。

## 能力与组合

依赖方向：宿主入口 → 配方/示例 → 独立服务/CLI → 来源、凭据、存储和运行基础设施。核心服务不导入宿主工具或示例。

1. 身份解析：DOI、正式链接或记录映射到规范身份，歧义明确保留。
2. 发现：查询、venue/year、作者和引用种子产生候选与覆盖记录，不隐式下载。
3. 元数据补全：保留字段来源和冲突，不生成摘要或覆盖可信字段。
4. 集合：精确身份合并、去重、比较；标题相似性只作提示。
5. 评审：共享证据包/导入接口，身份、主题、全文证据各自保留策略。
6. 选集：显式评审与可选数量/配额产生不可变选集。
7. 获取/核验：单篇或选集通过共同获取与核验服务；支持核验已有本地文件。
8. 解析：独立输入 PDF，通过缓存解析；没有 BibTeX 也可解析，但不升级官方来源保证。
9. 证据：观点关系、定位、短原文和全文哈希验证。
10. 库操作：审计、计划、执行、恢复与回滚分开。
11. 导出：结构化记录生成 JSON/CSV/Markdown，不承担发现和获取。

提供七个可复制组合示例：已知列表获取、主题论文集、作者查漏补齐、本地库更新整理、Related Work/观点证据、gap 分析、显式身份和页码的章节整理。各示例附输入模板、步骤、预期结果、恢复与限制。旧 corpus/research/author 命令逐步委托共享服务。

## 文件配置

配置根由 platformdirs 解析，`ARP_CONFIG_ROOT` 可覆盖；`arp config path` 显示实际路径。

```text
config.toml
.env
institutions/<profile-id>.json
credentials/<profile-id>.env
```

根 .env：SEMANTIC_SCHOLAR_API_KEY、OPENALEX_API_KEY、ELSEVIER_API_KEY、MINERU_TOKEN。院校文件：INSTITUTION_USERNAME、INSTITUTION_PASSWORD。均为空模板，浏览器会话不放入凭据文件。

- dotenv 读取不执行、不插值；每命令读取一次快照。
- API 值：显式进程环境 → 选定 .env；文件：`--env-file` → `ARP_ENV_FILE` → 默认 .env。只读一个文件，不向上搜索或隐式合并。
- 院校只读当前 profile 引用的文件；空值为未配置。保存密码不等于启用自动登录。
- config init/path/edit/setup/status 提供不覆盖初始化、编辑器打开、保留注释的更新和仅含脱敏状态的输出。
- 新装用文件；旧装保持 legacy，显式 `config migrate --from dpapi` 本机迁移，冲突只报告键名且不覆盖，旧存储保留。无静默混用。
- 新文件限制当前用户权限；解析错误只含字段/路径/行号；值不进入日志、manifest 或发布包。发布空模板并修订忽略/允许规则。
- 数据和运行时使用应用自身命名，旧根兼容，浏览器路径边界同步更新。

## 共享契约、状态、宿主

共享身份、元数据快照、工件引用、评审决定和操作结果；引用绑定内容哈希。v2 评审记录真实宿主和可用模型信息，旧 Codex 记录继续读取、原文件和哈希不变。

RunContext 记录步骤、输入引用、输出哈希、每项状态和 next_actions；`run status --run` 汇总。能力命令同目录恢复并重验工件；区分 Agent 评审、用户下载、缺配置、限流、永久失败；单篇故障不阻塞其他项；使用运行锁、原子写入与库日志。

共用 SKILL.md、资料、模板、schemas、固定 wheel；仅宿主安装/发现/执行和交互差异分开。Codex 保留 openai.yaml；Claude 原生 skills；Kiro IDE 导入/目录；Kiro CLI 自定义 agent 提供 skill:// 资源模板。`doctor --host` 仅报告已检查本地能力，配置/实时可用/机构权限分开。

## 实施任务与验收

- [x] Task 1：文件配置与凭据、旧后端兼容迁移、应用路径与 IEEE 凭据通道。
- [x] Task 2：共享能力、能力级 CLI、通用评审契约；旧入口保留并复用已有发现、获取、核验和选集服务。
- [x] Task 3：RunContext、工件校验、锁、恢复、下一步状态；旧运行记录只读兼容，仍通过原命令恢复。
- [x] Task 4：宿主 doctor、通用 skill、七个示例、安装模板和文档；真实交互式加载不在本地模拟结果中宣称通过。
- [x] Task 5：Windows 完整回归、三平台 CI 配置、wheel/skill 构建、隔离安装和支持矩阵。

尚未完成的外部验收单列保留，不计作本地自动测试通过：

- [ ] 在 macOS、Linux 上执行 Python 3.11/3.13 CI，而非仅配置矩阵。
- [ ] 在 Codex、Claude Code、Kiro IDE、Kiro CLI 中实际加载该导出 skill，并完成代表性工作流。
- [ ] 按平台完成 IEEE 浏览器及真实机构订阅访问验证；当前浏览器实现仍以 Windows 为验证范围。
- [ ] 发布后验证公开 release URL、安装器和下载资产；本次只验证本地匹配 wheel。

覆盖 dotenv 特殊字符/中文/注释/空值/无插值/优先级；更新保留其他字段；日志无秘密；院校隔离/域名/迁移冲突；能力独立与多输入组合；过期哈希/并发/重复执行/人工恢复；入库回滚和原始字节。运行现有 Python、Node、PowerShell、Ruff、schema、构建和隔离安装验证。CI 为三平台 × Python 3.11/3.13。实际宿主/院校验证独立记录版本、系统和范围，不以模拟测试宣称实测兼容。
