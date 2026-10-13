# 软通完整交付

用户明确指定案件后，按原Word的正文、公式和实施例制作图文，完成中文业务系统、可核验数据及约一分钟真实操作视频。仓库根目录[新版完整技能](SKILL.md)名为`software-case-batch-pro`。原调用`$software-case-batch`可显式安装[名称兼容模板](skill/README.md)后进入同一工作流，完整规则与阶段引用以新版SKILL为准。

每案成品只包含：

```text
案件/
  原输入完整文件名.docx
  模拟系统/
    项目源码.zip
    演示视频.mp4
    数据/                重要CSV
```

原文、公式、原图及其位置保留；新增说明标红，新增图和图下图题放原文后。业务入口、算法、接口、持久化、浏览器操作、导出及解压源码后的启动均须实际核验。来源、假设、构造过程及未验证范围留案件工作区，不冒充现场数据或已上线系统。

## Windows安装与本机配置

先备好PowerShell 7、Python 3.12或兼容版本、Node.js 22或兼容版本、Pillow、Playwright及其Chromium、FFmpeg/FFprobe；实际Word渲染还需LibreOffice和Poppler或已验证的等效工具。工具路径必须真实可用，通用依赖可复用。模型派发依赖支持指定模型/强度的Codex父会话和当前账户权限；本仓库不提供凭据或自动购买模型额度。

克隆到固定工具目录，保留完整仓库布局。在仓库根目录复制`local.config.example.json`为**仅本机使用且不提交**的`local.config.json`，逐项填写Python、Node、Playwright模块及FFmpeg/FFprobe绝对路径。`output_root`默认`F:\研发图表`；示例中的路径不是自动发现结果。

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

成品默认`F:\研发图表\批次\案件`。`prepare --output`必须显式指向同卷`.staging`下独立候选，独立验收后再`publish --destination`整体原子发布到全新正式目录。用户明确指定其他位置时优先；F盘不可用时不能静默回D盘或桌面。工作区方案将`成品/批次/案件`与`cases/...`分离，历史成果不自动搬移。

建设和自检实际用`gpt-6.1-sol/high`，返修及录制准备修复另派`gpt-6.1-sol/ultra`，普通独立只读验收由另一个ultra承担。验收者不写实现；父须核验真实调用和当前产物哈希，不能自签。本批/本案真实用户肯定授权加急时，使用原`gpt-6-astra/low`独立路由；“c1加急”“指定批次加急”适用，“原加急模式”不是必须口令，见[加急优先与实际调用](references/expedited-routing.md)；“提速”或“提高优先级”不自动授权换模型。加急仍须完整独立验收，不追加普通ultra复核。

新批次录制默认auto，资源许可时最高4路，也可明确2/3/4；实际并发受物理可用内存、提交余量、CPU和共享资源队列限制，取得槽后启动前再检查。旧冻结批次保留原容量。模型槽和媒体槽分开；本机模型子任务数还受会话工具上限限制。capture与编码、解码、抽帧互斥，evidence单槽；取得四路上限不证明四个真实业务系统均已验证。[并发录制](references/recording-concurrency.md)说明准入与恢复边界。

父会话实际分派模型并使用`batch_control.py`、`proflow.py`管理阶段与发布；它们不会自动调用模型，也不代表旧`caseflow plan/run`已接入新版全自动编排。旧CLI仅按其冻结历史合同使用。缓存及临时文件通过`Enter-Environment.ps1`设置到`D:\codex+`，不修改其他应用环境；依赖、数据库、凭据、会话和用户文件不当缓存。

## 升级、历史与验证

本机升级只在用户明确授权且当前版本独立验收通过后进行：列出实际改动文件，先在`D:\codex+\backups`新目录备份并逐hash核验，再更换新版代码和名称入口，记录覆盖前后hash及回滚清单。保留历史cases、Word、数据、数据库、凭据、会话、原manifest/收据/模型调用及冻结原规范；不重置旧仓库的本地修改，不自动续跑、重做或改判旧案。

回滚只恢复本次备份且现场仍符合本次安装hash的文件；安装后用户修改先保全，不能强盖。保留目录链接与其他有效进程。远端版本回退通过明确的新提交保全Git历史，不强推或删除历史标签。

Windows CI使用Python/Node契约与临时夹具回归，不使用账户秘密、不调用付费模型、不修改安全配置。完整内部历史证据审计、真实浏览器一分钟录制、Word全页视觉审查及真实案件交付在本机独立验收；具体CI范围见[CI说明](CI说明.md)。CI候选须以实际Actions结果为准，测试通过不能证明没有缺陷、现场可用或本轮已经完成四个不同业务系统。
