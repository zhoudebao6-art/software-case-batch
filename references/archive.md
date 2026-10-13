# 日常成品与每周归档

日常发布到 `D:\研发图表\批次\批次名\案件名`，候选继续在 D 盘同卷 `.staging`。每周归档使用确定性的本机脚本，不调用模型；脚本只读取明确的案件批次控制根下的 manifest/state/queue 和每案工作区冻结收据，**不扫描 D 盘成品树来猜测哪些材料可以移动**。当前版仅准备归档入口；未安装定时任务、未归档当前试验或历史成品。

## 显式入口

以下路径只是参数示例，`--batch-root` 必须换成实际用于 `batch_control.py` 的共享控制根，不能指向某一批次子目录或人为制作的空队列。`--state-root` 位于工作区，不能放到成品目录。所有根目录须绝对、无符号链接/重解析点、互不包含；源和目的成品根须已存在。F 盘未连接时不会创建替代目录。

```powershell
. 'D:\自动化2.0\software-case-batch-pro\Enter-Environment.ps1'
& $env:SCB_PRO_PYTHON 'D:\自动化2.0\software-case-batch-pro\scripts\archive_products.py' plan `
  --source-root 'D:\研发图表' --destination-root 'F:\研发图表' `
  --batch-root 'D:\自动化2.0\cases\.batches' --state-root 'D:\自动化2.0\archive-state'

# 审阅计划后，由当前授权负责人调用；不是定时任务注册命令。
& $env:SCB_PRO_PYTHON 'D:\自动化2.0\software-case-batch-pro\scripts\archive_products.py' apply `
  --source-root 'D:\研发图表' --destination-root 'F:\研发图表' `
  --batch-root 'D:\自动化2.0\cases\.batches' --state-root 'D:\自动化2.0\archive-state'
```

`plan` 只读。`apply` 重新生成计划并验证当前内容，串行处理符合条件的产品。JSON 的 `retained` 给出保留原因，退出码 2 表示至少一案保留或输入不可用；退出码 0 包括没有新产品可归档的情况。正在修订的案件、未完成案件和位于显式源根之外的冻结历史交付均保留，不能把这些结果描述为迁移失败后删除源件。

## 准入与顺序

1. 以完整注册批次为准：清单中每案状态都须为实际 `delivered`，每个当前 run 都必须仍是 published，且不存在本批活动工作或返修；paused、cancelled、waiting 和未完成案件均不视为交付。一个兄弟案件收据、实际内容或状态未通过，整批保留；无关批次的 idle/waiting 记录不阻止完整已完成批次。复制后发布前和共享批次锁内清理前都会重新核验整批状态。每案须绑定同一工作区和发布目录；原 `final-receipt.json` 须是完整 verified-candidate 验收，`publish-receipt.json` 须绑定该收据 SHA-256 和逐文件产品哈希，独立验收证明的哈希也核对。真实成品文件清单必须完全匹配收据，链接、额外文件、缺文件和内容变化均不迁移。
2. 核对权威 `queue.json`。只有经过 PID 与创建时间验证的活动录制/重媒体处理，或本案件的活动任务阻止本次处理；等待、已释放、无活动进程的旧记录和其他案件的普通建设不阻塞。未知或不完整的活动身份不能推定安全。清理阶段持有共享 batch mutation lock，防止通过本工具链新派发修订或录制。
3. 写工作区中的归档 intent，复制到 `F:\研发图表\.archive-staging\归档ID`。逐文件检查相对路径、大小及 SHA-256，保留空目录并核对目录树。复制前核对剩余空间；源文件以原生 Windows 读句柄保护，拒绝写入与替换。同一 intent 的中断候选可以续传，每次重新核验；其他候选不能自动接管。
4. 在 F 盘同卷、非覆盖、带 write-through 的原生 rename 发布完整目录。同名目标即使字节一致，若无本次归档 intent 也判为冲突，不采用、不覆盖、不合并。发布后再完整核验。
5. 先持久化 `archive-state\current-locations.json` 当前路径索引，再核验原验收/发布收据、run 和案件状态仍相同。索引与每次归档 journal 均在工作区，成品外层仍只有原名 Word 和“模拟系统”。原签收据、历史路径及案件执行证据不改写。
6. 仅在 Windows 支持原生保护句柄时清理。一次性取得所有现存源文件的读+DELETE句柄（拒绝写及重命名）和全部目标文件的读句柄；保护目录边界，重新核对每个源文件的 inode/device/mtime/大小和受保护句柄 SHA-256，目标受保护句柄亦核对。全部确认后才写 cleanup-started 进度并按句柄删除本次原对象。禁止 `rmtree`、递归 Delete/Move 或删除某个链接指向的内容。

如果源被占用、修改、目标不一致、空间不足、输入丢失或校验失败，保留源和进度。**文件系统无法把多个文件的删除变成一个原子事务**：清理中断可能留下部分 D 盘目录，但所有已删除的原件已在 F 盘核验并有持久路径索引；续跑只清理 intent 中剩余且身份完全相同的原文件。新增加、替换或修改的文件不会被清理，新增目录也会阻止自动清理；请人工处理冲突，不手动删除正在持有的锁。

归档进程的 exclusive Windows 文件锁随进程退出自动释放；持久锁文件的存在本身不代表运行中。批次原有 `mutation.lock` 仍按其原契约处理，归档不擅自删除它。非 Windows 系统可读计划，但不会执行复制发布或删除。

## 后续查看和修订

代码入口为 `resolve_location(state_root, original, expected_files=None)`：按原成品绝对路径读取独立索引，确认目的仍在记录的根内，按原收据的哈希重新核验实际归档内容；给出 `expected_files` 时还核对版本。不通过时明确报错，不把归档后原 D 路径不存在当作案件未交付。没有索引项时返回原路径。`common.state()` 对 published run 使用 `SCB_PRO_ARCHIVE_STATE_ROOT` 或当前 `local.config.json` 的 `archive_state_root` 解析位置，并将原验收/发布收据 SHA-256 与索引核对；环境变量仅当前进程有效，已部署配置须保存实际索引目录。

调用者在读取冻结收据后解析实际成品位置，不改写旧收据或 run；修订必须创建独立候选/输出版本，不能覆盖 F 盘归档。归档前建立的 `revision_of` / `inherited_system` 保留原发布路径，归档后新建的关系记录经验证的当前位置；返修链只允许这两种精确路径，并逐级核对原收据、发布收据、证明及成品哈希，拒绝任意同内容别名。旧 D 目录若因清理中断仅留原收据中的未变子集，仍可解析 F；出现新文件或改变的字节则拒绝，保留冲突材料。这里的索引不是新验收证明，也不替代原独立验收。

## 每周执行准备（尚未启用）

`scripts/Run-WeeklyArchive.ps1` 要求现有 PowerShell 7，默认 `-Mode Plan`；四个根均显式必填，Python 使用 `-PythonPath` 指定或由当前 `Enter-Environment.ps1` 中的配置给出。脚本只设置当前进程及子进程的 D 盘 TEMP/TMP/缓存，使用 `ProcessStartInfo.CreateNoWindow` 启动指定 Python，将 plan/apply JSON、stderr 和 runner 状态写入 `StateRoot\logs\唯一运行ID.*`。跨 plan/apply 持有原生 exclusive 文件锁 `weekly-run.lock`；已有锁文件不代表正在运行，不删除锁文件抢占。Apply 必须明确指定，它先执行 plan，仅在有合格产品时调用原 CLI apply；apply 重新计划并使用其原有保护。目的盘失联、活动案件或未知身份均保留来源并以退出码 2 和日志说明；没有合格产品则不开始复制。不会停止其他进程。

`scripts/Install-WeeklyArchive.ps1` 仅生成 `StateRoot\weekly-task-plan.json` 和 `StateRoot\Register-WeeklyArchive.ps1` 两个可审阅文件，支持 `-WhatIf` 且绝不自动注册。已有审阅文件不覆盖。设置为当地时间星期日 22:00，当前用户 InteractiveToken、Limited、Hidden、StartWhenAvailable 和 MultipleInstances IgnoreNew；账户必须已登录，不存储密码。任务执行已核对的 pwsh.exe 绝对路径，可用 `-PowerShellPath` 指定现有 PowerShell 7；没有执行策略、sandbox、审批或 ACL 绕行。注册脚本默认只显示计划，负责人明确调用 `-Register` 后才可能注册；`-Register -WhatIf` 可审阅动作。发现未知同名任务的路径、用户或设置不匹配时拒绝，不用 Force 覆盖，也不自动启动任务。

```powershell
# 在现有 PowerShell 7 中执行；batch-root 换成真实权威控制根。
& 'D:\自动化2.0\software-case-batch-pro\scripts\Run-WeeklyArchive.ps1' -Mode Plan `
  -SourceRoot 'D:\研发图表' -DestinationRoot 'F:\研发图表' `
  -BatchRoot 'D:\自动化2.0\cases\.batches' -StateRoot 'D:\自动化2.0\archive-state'

# 仅生成可审阅设置文件，不注册任务。
& 'D:\自动化2.0\software-case-batch-pro\scripts\Install-WeeklyArchive.ps1' `
  -BatchRoot 'D:\自动化2.0\cases\.batches' -StateRoot 'D:\自动化2.0\archive-state'

# 当前只准备入口；以下命令留给已完成本机验收并获启用授权的负责人。
# & 'D:\自动化2.0\archive-state\Register-WeeklyArchive.ps1' -Register -WhatIf
# & 'D:\自动化2.0\archive-state\Register-WeeklyArchive.ps1' -Register
```

测试只在 `D:\codex+\temp` 创建一次性源/目的/批次 fixture；没有使用真实成品，也没有进行真实 F 盘跨卷验收。任务计划测试只生成审阅文件并以 stub 验证 WhatIf/冲突，未读写本机任务。部署前应以独立命名的非业务小样本根验证实际 F 盘文件系统、空间、连接和所用账户的权限，不扫描、采用或删除真实 F 盘产品。

`tests/archive_smoke_helper.py --run-id <新UUID小写hex>` 是负责人显式选择的实际跨卷小样本验收入口，不会被 unittest 自动调用。它仅使用 `D:\codex+\temp` 新 fixture 和已存在 `F:\研发图表` 内一个全新的 `.archive-smoke-UUID` 子目录；不同实际 volume、父目录已存在、无链接、UUID有效且目标未存在才开始。样本均为标记的测试字节，不注册真实案件、不读取/扫描 F 盘其他成品。逐文件哈希、冻结收据、源清理、位置索引及原 D 路径的返修继承均需通过才写 `cross-volume-report.json`。小样本与报告保留供审阅，不自动递归清理。负责人应在新UUID实际烟测成功后，再对真实权威根运行 Plan，审阅保留原因，最后按授权启用任务。
