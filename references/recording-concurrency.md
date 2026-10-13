# 新批次并发录制

本次用户明确要求多开录制，故新版新登记批次可使用最多4路独立Chromium进程。历史manifest、原技能、原目录、冻结规范与r4证据不改。建设与审核模型、55–75秒时长、1920×1080、全部操作、画质及5fps完整证据保持原要求。此能力只提供确定性准入与真实浏览器隔离，父会话仍负责启动进程、等待完成、finally释放与独立视觉验收。

CLI `register` 默认 `--recording-limit auto`，也可显式设2/3/4。auto登记时按physical/commit较小余量和逻辑CPU数，冻结1–4路容量：首路4096MB、额外每路2048MB，每路4逻辑处理器并保留2个。低于首路门槛仍登记上限1，实际不足时等待；CPU忙属于短期等待，不通过热改manifest解除。登记保存实际资源样本，模型配置不改变。旧程序化 `register(..., recording_limit=None)` 仅保留旧schema1兼容语义；旧manifest读取时保持原2路和全部worker计数。新CLI及新父调用使用schema2。

新profile的host_total_slots只约束模型任务，record/evidence使用单独媒体池。同一父启动4路录制无需虚写host_total_slots=5：本机4模型槽含父仍只允许3模型子任务。所有批共享一个调度root，最多4个active record、1个active evidence；混合活跃旧批时取申请批与所有active批的较小容量，并保留旧worker限制。不能换root绕过宿主全局容量。已drain、blocked或失去负责人的waiting票据可暂不参与公平队列，所有active槽始终计数。

每次acquire重新核实际物理/提交余量；新profile另执行200ms Windows CPU计时采样，逻辑处理器须满足全局拟启动路数的预算且负载不超过85%。失败返回memory_exhausted/cpu_capacity/cpu_busy和实测值，票据保留waiting；父在其他阶段/资源释放后再接续，不忙轮询。容量及模型配置不变，不结束其他项目来制造余量。

父先创建每案独立应用、数据库和监听端口，健康接口及process_guard核所属工作区/PID/创建时间/命令行/端口；不能用同一可写数据库或服务同时录不同案。调度器拒绝新媒体池里跨批同一workspace同时capture。每个record进程独立启动Chromium，不共享browser/context/storage_state；浏览器TEMP/TMP/TMPDIR和downloads是D盘UUID目录，失败仅关闭本进程的浏览器并保留本案原片和事实。会话、数据库与下载证据不作为可删缓存。

```powershell
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' register --root '新版cases\.batches' --batch-id '本批' --cases '授权清单.json' --authorization '真实用户本轮多开请求引用' --host-slots 4 --recording-limit auto
# claim/queue/acquire由唯一长期父操作，使用返回的record token。
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' record --workspace '案件目录' --plan '录制计划.json' --phase capture --batch-root '新版cases\.batches' --batch-id '本批' --case-id '本案ID' --record-token '已取得active槽token' --owner-pid 12345
```

新登记schema2的manifest冻结`media_lease_contract=windows-job-v1`，并在每案`.product-v2/batch-binding.json`以独占新建保存root/batch/case/manifest hash；重复或跨root登记同工作区拒绝，登记写失败回滚仅本次新建文件。此绑定让`proflow record`、直接`record.cjs`、`finishRecording`及`media_evidence.generate`在省略lease时都于媒体启动前拒绝；未登记的旧独立full/capture/evidence继续兼容，旧manifest不热改。

新批次capture必须传齐上述lease参数，evidence也须传本阶段新取得的evidence token（通用名`--media-token`，原`--record-token`仍是兼容别名）。browser launch前`verify-record`重新核active token、长期父身份、case/workspace/source hash及全局媒体互斥和实测资源；证据启动前`verify-evidence`核active evidence token、同绑定、全局无active record且仅一个active evidence。多个媒体进程同时检查时，仅对确切mutation.lock竞争有界等待最多3秒，不删活锁、不重试其他错误；失败保留active槽直至安全释放。启动前复查不会因queued evidence撤销已active捕获，已有capture结束后再排空证据。

直接Node CLI自动进入本次调用专属`media_job.py`监督入口：创建Windows named Job，设置kill-on-close、禁止breakaway，创建内层Node为suspended，先分配Job并冻结PID/创建时间/实际命令行/工作区和supervisor身份，成功绑定active票据后才resume。Node、Chromium和FFmpeg子孙不能脱离本次Job；入口再次核真实Job成员身份，环境标记不能冒充。supervisor只随本次媒体调用存在，不安装服务；Node自然结束或supervisor退出都会关闭Job并收尾遗留子孙。Assign或Resume失败仅回滚本次保有handle的确切child，活Job重试不覆盖，不改process_guard与系统安全设置。

`recover-owner`对active保留原token、stage、runtime及容量，追加原/新owner历史并转交新owner；只waiting可转orphaned。父退出不代表媒体退出，原active record/evidence持续阻止互斥新阶段。新owner可等待本次媒体自然结束，再`release-slot`；释放重新核Job无成员和原runtime确已退出，必要只清理匹配该已退出runtime PID的遗留本案stage lock。旧无Job媒体active恢复后须显式`release-slot --value 本案工作区内本次清退绑定.json`；绑定含workspace、batch_id、token及cleanup/registry两项实际path/sha256，分别指向当前`.product-v2/cleanup.json`与`processes.json`。cleanup必须在本次owner恢复后重新由原process_guard核完整专属登记树收尾，控制器再核所有登记PID/创建时间/命令行及子孙的新census，拒复用其他token/旧cleanup/改hash。缺真实归属证据保持active/cleanup_pending，由负责人补核专属树，不杀无归属进程、不伪写释放；不能仅凭录制receipt推断未知孤儿已退出。历史manifest、收据和过程证据字节保持不变。

每组capture均完成并释放后才运行单槽evidence；等待证据会阻止新capture，任何live capture与编码/解码/抽帧互斥。FFmpeg仍2线程、CRF20、完整decode及5fps/全部交互帧，不能以并发优化减少检查。保存每路资源样本、等待耗时、rAF诊断和全部源帧证据；输出25fps或脚本测试通过不代表录制视觉流畅，真实1/2/3/4路同输入基准与独立只读ultra检查由父另行完成。
