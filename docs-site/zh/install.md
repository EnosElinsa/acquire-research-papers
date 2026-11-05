# 安装

普通用户通过标准 Skills 安装器安装，需要 Node.js/npm，无需克隆开发仓库或运行开发依赖同步：

```text
npx skills add EnosElinsa/acquire-research-papers --skill acquire-research-papers -a codex -g
```

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。使用安装器返回的实际 skill 目录；默认共享目录通常是 `~/.agents/skills/acquire-research-papers`：

```powershell
$skill = Join-Path $env:USERPROFILE ".agents/skills/acquire-research-papers"
python "$skill/scripts/arp.py" --help
python "$skill/scripts/arp.py" config status
```

启动器只使用 Python 标准库，根据 `runtime.json` 获取固定版本 wheel、校验 SHA-256，再通过 uv 安装到独立缓存。不会依赖开发 checkout 或把开发工具装进 skill。文件配置与核心命令支持 Windows/macOS/Linux；当前 IEEE 浏览器和旧 DPAPI 仍需要 Windows、PowerShell、Node.js，在 macOS 和 Linux 上 IEEE 论文进入人工下载队列；机构实时权限需单独验证。

更新时重新运行同一条 Skills 安装命令。注册表、凭据、缓存、院校 profile 和浏览器会话保存在 skill 目录之外；交付文件也应使用独立目录。开发构建可按[开发指南](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md)使用经过摘要校验的本地 wheel 验证。

!!! warning "开发 checkout"
    如果现有 skill 目录本身是 Git 开发 checkout，请保留它，不要让第三方安装器覆盖此目录。先构建导出，再用仓库的安全复制安装器放入新目录；它拒绝含 `.git` 的目标，明确替换旧版纯 skill 时也保留备份。详见[安全迁移](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md#safe-copy-and-checkout-migration)。

## 宿主安装与验证范围

Codex、Claude Code、Kiro IDE、Kiro CLI 共用同一 skill 和固定 wheel。用户目录分别为 `~/.agents/skills/`、`~/.claude/skills/`、`~/.kiro/skills/`；只复制导出的 `acquire-research-papers/` 文件夹。Kiro 自定义 agent 需要显式 `skill://` resources，附带[资源模板](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/templates/kiro-agent.example.json)。参见[宿主安装及官方依据](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/hosts.md)，于 **2026-10-20** 核对。

执行 `arp doctor --host <codex|claude-code|kiro-ide|kiro-cli> --skill-directory <实际路径>`。默认仅检查本地 Python、运行时、schema、配置及依赖，宿主是否加载和机构权限仍未验证。`--check-host-version` 显式运行所选宿主版本命令；`--remote-check` 显式进行无凭据 Crossref 连通测试。官方格式兼容与模拟 CI 不等于实机认证；Claude Code 和 Kiro 交互执行仍需单独记录实测。

## 发布文件与手动安装

每个 [GitHub 发布版本](https://github.com/EnosElinsa/acquire-research-papers/releases/latest)都提供：

| 文件 | 用途 |
| --- | --- |
| `acquire-research-papers-skill-<版本>.zip` | 解压后，将其中的 `acquire-research-papers/` 文件夹复制到新的 skill 目录。包含指令、参考资料、schemas、启动器和固定运行版本清单。 |
| `acquire_research_papers-<版本>-py3-none-any.whl` | 用 `uv tool install <wheel-path>` 单独安装 CLI；也可将其绝对路径设置为 `ARP_LOCAL_WHEEL`，供启动器从本地加载。摘要校验仍然生效。 |
| `SHA256SUMS` | PowerShell 使用 `Get-FileHash <path> -Algorithm SHA256`，Linux 使用 `sha256sum <path>`，与清单核对下载文件。 |

手动安装 skill 需要 Python 3.11+ 和 uv。启动器默认在首次运行时下载固定 wheel；依赖安装仍需网络或已有 uv 缓存。IEEE 浏览器另外需要 Node.js 和 Google Chrome。不要把源码压缩包或开发 checkout 整体复制为 skill。启动和迁移问题见 [SUPPORT.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md)。
