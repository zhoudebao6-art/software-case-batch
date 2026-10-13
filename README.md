# 软通完整交付

用户明确指定案件后，按原Word正文、公式和实施例制作专业分析附图与红字说明，始终完成中文业务系统、数据及一分多钟实操视频的完整交付。图文完成后继续系统深化、数据、Web、录制与收尾；已有完整成果的局部返修可按继承条件保留未变软件，最终仍交付全套成品。源保护、实际计算、独立模型及全页审查保持。仓库根目录[新版技能](SKILL.md)名为`software-case-batch-pro`。原调用`$software-case-batch`可显式安装[名称兼容模板](skill/README.md)后进入同一工作流。

每案完整交付成品只包含：

```text
案件/
  原输入完整文件名.docx
  模拟系统/
    项目源码.zip
    演示视频.mp4
    数据/                重要CSV
```

原文、公式、原图及其位置保留；新增说明标红，新增图和图下图题放原文后。业务入口、算法、接口、持久化、浏览器操作、导出及解压源码后的启动均须实际核验。来源、假设、构造过程及未验证范围留案件工作区，不冒充现场数据或已上线系统。

新案通常4—6张有效分析图，需要时更多；保留1—2张黑白结果图，专业模型、热力、矩阵、轨迹、调度等图占多数，每图回答本案独立问题。原图全部保留，可计入已有的适用统计结果，原流程图不计；不重复信息或凑图。颜色按数据含义选择，0/1资格可用离散编码；新增图与图题禁“示意”，图内无顶部标题、表头、图号或长解释，保留必要轴、矩阵标签、单位和色标。详实红字结合实施例，有原式保留符号，无式不造式。建设时按实际Word宽度完成标注避让和当前PNG目视检查，进入Word后核实际宽度。首次制作某类图打开[视觉基线](references/figure-design.md)中最接近的1–2张；同批已看且哈希未变可复用。新案采用analytical-v2，旧冻结合同不追改。

## 新对话总控命令

只需将 `【批次材料绝对路径】` 替换为本次目录，整段粘贴到新聊天；父会话依本技能取得实际路径、清单与运行参数并执行，不以生成命令文本代替完成案件。

```text
使用 $software-case-batch-pro，批次材料目录：【批次材料绝对路径】。本聊天由父会话担任总控，先读当前技能、本工作区 AGENTS.md 和必要执行规则，只扫描本批材料并冻结授权清单、原名及源哈希；一个Word默认一案。先核对本批manifest、负责人、阶段、调用与收据，按事实接续原工作区，未建案才在 D:\自动化2.0\cases 创建每案独立目录；不双派活跃或正常排队阶段，不重跑已交付历史案，不启动未授权案件。父显式分派建设及自检 gpt-6.1-sol/high，另派 gpt-6.1-sol/ultra 返修及录制准备修复，再由另一个 gpt-6.1-sol/ultra 独立只读验收；验收者不写实现、不兼返修，实际模型调用与记录按技能核验。仅我明确授权当前批或案加急时，才用独立 gpt-6-astra/low 按加急优先路由完整验收，通过后不追加ultra。始终完成完整 product-v2：中文业务系统、算法与充分数据、附图和红字说明、源码ZIP、重要CSV、一分多钟真实操作视频及后台收尾。保留原文、原公式、原图与位置，按本案特征选有计算依据和新增价值的专业图；不重复原图已覆盖信息，通常4—6张有效图且可更多、1—2张黑白结果图、专业分析图占多数，不凑图，新增图及图题无“示意”，不把推演称实测；基线阅读、图文质量及验证全部按当前技能。成品默认 D:\研发图表 下唯一批次目录，候选用同卷 D:\研发图表\.staging，独立验收通过后整体原子发布，不覆盖历史或静默改盘。加载本技能环境入口，当前进程临时和工具缓存统一 D:\codex+。按技能持续推进完整清单、保留真实进度与恢复证据，未通过不发布、不自签完成。本请求不授权改或安装技能、上传GitHub、改其他案件或停止其他项目；冻结案件规则与历史记录保留。
```

## Windows安装与本机配置

先备好PowerShell 7、Python 3.12或兼容版本、Node.js 22或兼容版本、Pillow、Matplotlib、Playwright及其Chromium、FFmpeg/FFprobe；实际Word渲染还需LibreOffice和Poppler或已验证的等效工具。工具路径必须真实可用，通用依赖可复用。模型派发依赖支持指定模型/强度的Codex父会话和当前账户权限；本仓库不提供凭据或自动购买模型额度。

克隆到固定工具目录，保留完整仓库布局。在仓库根目录复制`local.config.example.json`为**仅本机使用且不提交**的`local.config.json`，逐项填写Python、Node、Playwright模块及FFmpeg/FFprobe绝对路径。`output_root`默认`D:\研发图表`；示例中的路径不是自动发现结果。

```powershell
git clone https://github.com/zhoudebao6-art/software-case-batch.git
Set-Location -LiteralPath '.\software-case-batch'
if (-not (Test-Path -LiteralPath '.\local.config.json')) {
    Copy-Item -LiteralPath '.\local.config.example.json' -Destination '.\local.config.json'
}
# 编辑并核对本机路径后加载；仅配置当前PowerShell进程。
. '.\Enter-Environment.ps1'
& $env:SCB_PRO_PYTHON '.\scripts\proflow.py' --help
& $env:SCB_PRO_PYTHON '.\scripts\batch_control.py' --help
```

新安装把用户技能目录中的`software-case-batch-pro`链接到完整仓库根目录。以下命令仅创建尚不存在的入口，已有安装先完成授权范围核对、备份和哈希验证，再按升级方案替换，不能用`-Force`覆盖。

```powershell
$TaskRepo = (Resolve-Path -LiteralPath '.').Path
$TaskCodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$TaskSkillRoot = Join-Path $TaskCodexRoot 'skills'
$TaskPro = Join-Path $TaskSkillRoot 'software-case-batch-pro'
if (Test-Path -LiteralPath $TaskPro) {
    throw '已有技能入口：先按已授权升级方案备份核验，不覆盖现有目录或链接。'
}
New-Item -ItemType Directory -Path $TaskSkillRoot -Force | Out-Null
New-Item -ItemType Junction -Path $TaskPro -Target $TaskRepo | Out-Null
```

需继续原名称时，在已安装pro的前提下，把`skill/SKILL.compatibility.txt`显式复制为用户技能目录`software-case-batch/SKILL.md`，把`skill/openai.compatibility.txt`复制为其`agents/openai.yaml`。具体无覆盖命令见[旧路径迁移说明](skill/README.md)。模板本身不作为活动SKILL放入pro包，避免递归发现第二个旧名称入口。

重新载入技能后，输入`使用 $software-case-batch-pro，按新版完整规则处理我明确指定的案件和清单`；已安装兼容入口时可继续原名称。安装、帮助或准备命令通过不等于真实案件完成。首次部署和工具路径变化先完成零模型环境smoke；真实派发前依[执行规则](references/execution.md)在原受限模式做读写预检，不修改沙箱、审批、ACL、安全Deny或系统执行策略。

## 输出、模型与资源

成品默认`D:\研发图表\批次\案件`。`prepare --output`必须显式指向同卷`.staging`下独立候选，独立验收后再`publish --destination`整体原子发布到全新正式目录。用户明确指定其他位置时优先；F盘不可用时不能静默回D盘或桌面。工作区方案将`成品/批次/案件`与`cases/...`分离，历史成果不自动搬移。

建设和自检实际用`gpt-6.1-sol/high`，返修及录制准备修复另派`gpt-6.1-sol/ultra`，普通独立只读验收由另一个ultra承担。验收者不写实现；父须核验真实调用和当前产物哈希，不能自签。本批/本案真实用户肯定授权加急时，使用原`gpt-6-astra/low`独立路由；“c1加急”“指定批次加急”适用，“原加急模式”不是必须口令，见[加急优先与实际调用](references/expedited-routing.md)；“提速”或“提高优先级”不自动授权换模型。加急仍须完整独立验收，不追加普通ultra复核。

新批次录制默认auto，资源许可时最高4路，也可明确2/3/4；实际并发受物理可用内存、提交余量、CPU和共享资源队列限制，取得槽后启动前再检查。旧冻结批次保留原容量。模型槽和媒体槽分开；本机模型子任务数还受会话工具上限限制。capture与编码、解码、抽帧互斥，evidence单槽；取得四路上限不证明四个真实业务系统均已验证。[并发录制](references/recording-concurrency.md)说明准入与恢复边界。

父会话实际分派模型并使用`batch_control.py`、`proflow.py`管理阶段与发布；它们不会自动调用模型，也不代表旧`caseflow plan/run`已接入新版全自动编排。旧CLI仅按其冻结历史合同使用。缓存及临时文件通过`Enter-Environment.ps1`设置到`D:\codex+`，不修改其他应用环境；依赖、数据库、凭据、会话和用户文件不当缓存。

## 升级、历史与验证

本机升级只在用户明确授权且当前版本独立验收通过后进行：列出实际改动文件，先在`D:\codex+\backups`新目录备份并逐hash核验，再更换新版代码和名称入口，记录覆盖前后hash及回滚清单。保留历史cases、Word、数据、数据库、凭据、会话、原manifest/收据/模型调用及冻结原规范；不重置旧仓库的本地修改，不自动续跑、重做或改判旧案。

回滚只恢复本次备份且现场仍符合本次安装hash的文件；安装后用户修改先保全，不能强盖。保留目录链接与其他有效进程。远端版本回退通过明确的新提交保全Git历史，不强推或删除历史标签。

Windows CI使用Python/Node契约与临时夹具回归，不使用账户秘密、不调用付费模型、不修改安全配置。完整内部历史证据审计、真实浏览器一分钟录制、Word全页视觉审查及真实案件交付在本机独立验收；具体CI范围见[CI说明](CI说明.md)。CI候选须以实际Actions结果为准，测试通过不能证明没有缺陷、现场可用或本轮已经完成四个不同业务系统。

日常成品与候选在D盘同卷；每周将已完成成品核验归档至F盘，见[周归档](references/archive.md)。r10把图数/搭配、标注避让和足量匿名编号数据前移至建设自检；录制一分多钟、按操作自然结束，不固定60秒。旧批次和旧验收合同冻结。
