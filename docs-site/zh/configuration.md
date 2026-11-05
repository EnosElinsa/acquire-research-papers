# 配置

## 首次使用：只配置当前任务需要的能力

先检查哪些可选能力已经配置：

```powershell
python "$skill/scripts/arp.py" config status
```

该命令默认只返回能力布尔值；`--details` 可附加非敏感 profile/历史验证摘要。文件凭据会读取到内存检查存在状态但不输出值；旧 DPAPI 仅检查 scope 结构而不解密秘密。`true` 表示本地已有配置，不代表远端 API 或出版社权限一定可用。Agent 应只引导配置当前任务真正需要的能力，再用有代表性的实际操作验证。

| 能力 | 何时配置 | 配置方式 |
| --- | --- | --- |
| 无需配置 | 公开 Crossref 发现；从 ACL、IJCAI、AAAI、NeurIPS、ICLR（2024 年起）、PMLR、CVF 和 USENIX 官方归档发现并获取；Springer 开放获取论文 | 不需要密钥 |
| Semantic Scholar | 需要带 key 的候选搜索、更高额度和第一轮 DOI 摘要补全 | `arp config setup semantic_scholar` |
| OpenAlex | 需要通过 OpenAlex 系列枚举 IEEE 或 ACM 会议（INFOCOM、ICC、GLOBECOM、SIGCOMM 等）、额外候选搜索或第二轮 DOI 摘要补全 | `arp config setup openalex` |
| IEEE | 需要本校 IEEE 访问；默认先人工登录，可另行启用支持的 CARSI 表单 | `arp config setup ieee` |
| Elsevier | ScienceDirect 人工接管前需要解析官方预期身份 | `arp config setup elsevier` |
| MinerU | 需要为内部全文分析解析 PDF，或明确要求导出 Markdown | `arp config setup mineru` |

!!! danger "不要在聊天中提供秘密"
    秘密输入采用交互式、不回显提示；机构名称和官方入口是普通非敏感输入。不要把密码、API key、token 或 Cookie 粘贴到聊天、Agent 消息、命令参数或仓库文件中。

支持在本机编辑仓库外选定凭据文件。各 Provider 独立更新，互不覆盖：添加 OpenAlex 不会替换 IEEE、MinerU、Elsevier 或 Semantic Scholar 配置。

## 可编辑本地凭据

新安装默认使用仓库外本地可编辑文件。使用 `arp config init`、`arp config path`、`arp config edit`；院校使用 `config edit --profile <id>`。配置根包含 `config.toml`、`.env`、`institutions/<id>.json`、`credentials/<id>.env`。`ARP_CONFIG_ROOT` 显式覆盖系统配置根，`ARP_DATA_ROOT` 隔离运行数据；新数据根用应用自身名称，已识别旧根继续兼容。

根 `.env` 含 `SEMANTIC_SCHOLAR_API_KEY`、`OPENALEX_API_KEY`、`ELSEVIER_API_KEY`、`MINERU_TOKEN`；院校文件含 `INSTITUTION_USERNAME`、`INSTITUTION_PASSWORD`。[空模板](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/templates/.env.example)不含值。文件是限制当前用户访问的明文：可本机编辑，保持私有，禁止提交。保存密码不等于启用自动登录。

API 优先级为显式进程环境 → 一个选定文件；文件选择为 `--env-file` → `ARP_ENV_FILE` → 默认 `.env`。不向上搜索、不隐式合并、不执行 shell、不插值，每命令读取一次快照，空值表示未配置。院校仅读取当前 profile 文件。已有 DPAPI 安装保持旧后端；在原 Windows 账户执行 `arp config migrate --from dpapi` 才显式迁移，保留原存储，仅报告冲突键名且不覆盖。详见[配置说明](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/credentials-and-cache.md)。

## 命名院校档案

下列 `arp` 是 `python <skill-directory>/scripts/arp.py` 的简写。

```text
arp config setup ieee --profile my-institution --mode assisted
arp config ieee list
arp config ieee use my-institution
arp config ieee login --profile my-institution
arp config ieee doctor --profile my-institution --reference <IEEE-URL>
```

IEEE 支持 `direct`、`assisted` 与明确表单契约下的 `carsi` 命名 profile，各自使用隔离浏览器上下文。已配置、IdP 登录成功、返回 IEEE、核验下载及证明机构权限是不同状态；开放获取论文下载成功不等于订阅权限已验证。详见 [IEEE 机构访问](ieee.md)和[配置参考](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/configuration.md)。
