# 软通完整交付

当前技能为 **software-case-batch-pro**，唯一活动入口是仓库根目录 [SKILL.md](SKILL.md)。`$software-case-batch`只是可选的原名称兼容入口，执行同一份当前规则。

根据用户授权的技术Word逐案交付：保留原文、公式及原图内容与相对顺序，在对应实施例正文中插入衔接上下文的红字解释，仅将新增专业分析图片及图题追加到全文末尾，完成技术相符的中文业务系统、足量清洗数据、可启动源码和一分多钟真实操作视频。完成一件交付一件。

```text
案件/
  原输入完整文件名.docx
  研发证明材料-案件名称/
    源代码.zip
    操作视频.mp4
    界面截图.png
    数据/
```

当前流程保留必要首次独立质量核对。已有审核的小问题由原修复者定向修补、自检受影响项后直接打包；已通过的视频、数据和未变成果复用，不新增整案复验。缺失、损坏、无法启动或核心计算错误不能按小问题放行。具体分流见[收尾规则](references/closure.md#按实际问题收尾)。建设可复用[异步状态组件](references/web-design.md)，多件已有录制票使用[一次接续入口](references/progress.md)，首次审核从中性事实的视觉导航打开稳定材料；这些改进复用现有阶段，不增加模型轮次。

本轮通用修复把已经写明的要求接入既有入口：原 Word 关系、节属性和未登记插图保护，普通发布的实际阅读声明与索引覆盖核对，源码包排除和文本扫描、有效业务数据去重，以及简化收尾的明确视频重大变化检查。新策略在新案或合法文档修订冻结，历史成品不回填；确定性检查不代替真实视觉和技术判断。

## 新聊天使用

已安装时，将下方的`【批次材料绝对路径】`替换为本次目录，整段粘贴到新聊天。

```text
使用 $software-case-batch-pro，批次材料目录：【批次材料绝对路径】。本聊天由父会话担任总控，先读当前技能、本工作区 AGENTS.md 和必要执行规则，只扫描本批材料并冻结授权清单、原名及源哈希；一个Word默认一案。先核对本批manifest、负责人、阶段、调用与收据，按事实接续原工作区，未建案才在 D:\自动化2.0\cases 创建每案独立目录；不双派活跃或正常排队阶段，不重跑已交付历史案，不启动未授权案件。父显式分派建设及自检 gpt-6.1-sol/high，另派 gpt-6.1-sol/ultra 返修及录制准备修复，再由另一个 gpt-6.1-sol/ultra 独立只读验收；验收者不写实现、不兼返修，实际模型调用与记录按技能核验。仅我明确授权当前批或案加急时，才用独立 gpt-6-astra/low 按加急优先路由完整验收，通过后不追加ultra。始终完成完整 product-v2：中文业务系统、算法与充分数据、附图和红字说明、源码ZIP、重要CSV、一分多钟真实操作视频及后台收尾。保留原文、原公式、原图与位置，按本案特征选有计算依据和新增价值的专业图；不重复原图已覆盖信息，通常4—6张有效图且可更多、1—2张黑白结果图、专业分析图占多数，不凑图，新增图及图题无“示意”，不把推演称实测；红字解释按所属实施例、计算或结果分析插入原正文合理位置，仅新增图片和图题放文末，说明失位及新增完整重复原公式均属实质缺陷；引用原式只承接计算含义和必要符号，不再抄写整式。基线阅读、图文质量及验证全部按当前技能。成品默认 D:\研发图表 下唯一批次目录，候选用同卷 D:\研发图表\.staging，完成首次独立质量核对后按实际问题收尾：首审pass正常发布；以后所有案件的小问题在首次审核后由原修复者最小修补、自检受影响项后close-simplified直接打包，不再另排整案复验，通过视频及充足清洗数据复用。实质缺陷和未读范围只补必要项；以真实收据整体原子发布，不覆盖历史或静默改盘。加载本技能环境入口，当前进程临时和工具缓存统一 D:\codex+。按技能持续推进完整清单、保留真实进度与恢复证据，缺失、损坏或未解决的实质问题不记完成；用户授权简化收尾不伪写独立pass。本请求不授权改或安装技能、上传GitHub、改其他案件或停止其他项目；冻结案件规则与历史记录保留。
```

## Windows安装

准备PowerShell 7、Python 3.12或兼容版本、Node.js 22或兼容版本、Pillow、Matplotlib、Playwright及Chromium、FFmpeg/FFprobe。Word渲染需LibreOffice和Poppler或已验证的等效工具。模型派发需要支持指定模型及强度的Codex父会话和相应账户权限。

克隆到固定工具目录，保留完整仓库布局。示例配置中的工具路径必须按本机实际安装填写，`local.config.json`仅本机使用，不提交。

```powershell
git clone https://github.com/zhoudebao6-art/software-case-batch.git
Set-Location -LiteralPath '.\software-case-batch'
if (-not (Test-Path -LiteralPath '.\local.config.json')) {
    Copy-Item -LiteralPath '.\local.config.example.json' -Destination '.\local.config.json'
}
# 编辑并核对本机工具路径后加载；只设置当前进程环境。
. '.\Enter-Environment.ps1'
& $env:SCB_PRO_PYTHON '.\scripts\proflow.py' --help
```

新安装将用户技能目录中的`software-case-batch-pro`链接到仓库根目录。已有入口先按已授权升级方案备份核验，下面命令不会覆盖它。

```powershell
$TaskRepo = (Resolve-Path -LiteralPath '.').Path
$TaskCodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$TaskSkillRoot = Join-Path $TaskCodexRoot 'skills'
$TaskPro = Join-Path $TaskSkillRoot 'software-case-batch-pro'
if (Test-Path -LiteralPath $TaskPro) { throw '已有技能入口，先备份核验。' }
New-Item -ItemType Directory -Path $TaskSkillRoot -Force | Out-Null
New-Item -ItemType Junction -Path $TaskPro -Target $TaskRepo | Out-Null
```

重新载入技能后使用`$software-case-batch-pro`。首次部署或依赖路径变化按[执行规则](references/execution.md)做环境预检；帮助命令通过不代表真实案件已经完成。

### 可选：保留原名称

已安装pro且旧名称尚不存在时，在仓库根目录继续运行：

```powershell
$TaskRepo = (Resolve-Path -LiteralPath '.').Path
$TaskCodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$TaskSkillRoot = Join-Path $TaskCodexRoot 'skills'
$TaskPro = Join-Path $TaskSkillRoot 'software-case-batch-pro'
$TaskAlias = Join-Path $TaskSkillRoot 'software-case-batch'
if (-not (Test-Path -LiteralPath (Join-Path $TaskPro 'SKILL.md'))) { throw '先安装并核验完整pro技能。' }
if (Test-Path -LiteralPath $TaskAlias) { throw '已有旧名入口，先备份核验。' }
New-Item -ItemType Directory -Path (Join-Path $TaskAlias 'agents') | Out-Null
Copy-Item -LiteralPath (Join-Path $TaskRepo 'skill\SKILL.compatibility.txt') -Destination (Join-Path $TaskAlias 'SKILL.md')
Copy-Item -LiteralPath (Join-Path $TaskRepo 'skill\openai.compatibility.txt') -Destination (Join-Path $TaskAlias 'agents\openai.yaml')
```

`skill/`仅存两份兼容模板，不是另一套活动技能。pro不可读时保留未完成状态，不回退旧流程。

## 按需查阅

| 内容 | 当前说明 |
|---|---|
| 质量、角色、图文与完整交付要求 | [SKILL.md](SKILL.md) |
| 总控接续、模型调用和阶段交接 | [执行规则](references/execution.md)、[阶段工具](references/tools.md) |
| 实际父运行时容量、动态公平与加急 | [调度](references/scheduler-policy.md)、[加急路由](references/expedited-routing.md) |
| 原技术实现、数据和领域边界 | [系统与数据](references/system-data.md)、[领域检查](references/domain-boundaries.md) |
| 录制与资源准入 | [录制](references/recording.md)、[并发](references/recording-concurrency.md) |
| 发布、定向小修与压缩包恢复 | [收尾](references/closure.md) |
| 完成批次周归档 | [归档](references/archive.md) |
| 自动回归范围及限制 | [CI说明](CI说明.md) |
| 旧规范及用户覆盖关系 | [继承依据](references/inheritance.md)；仅维护或冲突时查阅 |

成品默认`D:\研发图表\批次\案件`，候选在同卷`.staging`，输出参数仍显式提供；用户指定目录优先。临时与可再生缓存为`D:\codex+`，不修改系统或其他应用环境。模型按已验证真实父运行时容量调度，不将配置或预约数当作实际运行数；媒体按真实资源准入。

## 更新与历史

从`main`取得当前版本。升级前保全本机修改、配置和有效入口；候选独立验收通过后，备份并逐哈希核验改动，再安装并保存回滚清单。回滚只恢复本次更改且现场仍匹配安装哈希的文件，不强盖用户后续修改。

`references/original/`及其索引是冻结的规范证据，不是可调用的旧技能。历史案件、收据和适配代码保留原合同；新案不读取整套旧资料，也不重跑历史成品。已经合入main的旧发布分支可清理，历史提交继续通过Git追溯。

Python/Node回归使用隔离夹具，不调用付费模型。独立验收和实际Actions结果分别记录；测试通过不等于真实生产速度已经测量，也不等于所有领域场景均已验证。

2026-10-21新完整run使用rich-delivery-v1/research-materials-v3：至少10份有效CSV、6个真实业务模块，均无数量上限；视频实测>60秒且≤300秒，原生1080一次CRF18编码，交付一张实际原生高清界面PNG。旧合同/路径及已合格媒体冻结，首次审查与小修简化规则保持。详情见references/recording.md及tools.md。
