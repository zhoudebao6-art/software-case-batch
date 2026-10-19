# 有界媒体接续与原模型容量等待

同一owner同一批已有多件就绪媒体票时，优先用 `--ready` 替代逐案手动接续。一次调用固定入口时已waiting/active的record/evidence案件与run集合；同批后加入的案件留给下次原owner调用，不创建新批或模型任务。按原全局队列、资源门禁允许并发capture，evidence仍按原互斥串行；只在本次任务完成事件后继续下一就绪票，无后台服务、定时轮询或失败capture自动重试。

```powershell
& $env:SCB_PRO_PYTHON -B '工具目录\progress_driver.py' --root '现有共享调度根目录' --batch-id '现有批ID' --pid 12345 --ready
```

默认复用各案 `.product-v2/record-plan.json`；原计划位于别处时，`--plans`可传现有JSON映射 `{案件ID: 本案工作区内计划绝对路径}`，不复制改写计划。只允许初始已排队本案，不能指向其他工作区。已有活跃Job保留，drain停止后续派发；当前实际selected属于其他owner/批次、无资源或需定向修复时返回原等待/问题指针，不代领、不取消头部票插队。`--ready`不能与`--retry-capture`混用；修复失败录制后仍用原单案显式重试。整个调用只产生技术事实，首次独立视觉与最终门禁不变。


父会话在本案进入录制或媒体进程结束时调用下列确定性入口。一次调用最多运行本案一次capture与一次evidence，不调模型、不安装后台服务、不轮询共享队列。使用当前唯一长期负责人PID及已有root/batch/case绑定；没有真实Windows Job冻结绑定的历史批次仍走原显式process_guard恢复，不新增假lease。

```powershell
. 'D:\自动化2.0\software-case-batch-pro\Enter-Environment.ps1'
& $env:SCB_PRO_PYTHON -B '工具目录\progress_driver.py' --root '现有共享调度根目录' --batch-id '现有批ID' --pid 12345 --case-id '本案ID' --plan '本案录制计划绝对路径.json'
```

入口复用本案现有waiting/active票据，使用原`queue/acquire/verify`与`media_job.py`，保留全局媒体互斥、CPU/内存启动复查、冻结绑定和源hash。capture返回后立即在finally核Job及runtime退出再释放record；原片收据成功则在同一次调用中queue/acquire evidence，完整编码、解码、5fps与交互帧后同样释放。每阶段默认超时1800秒，`--timeout`可显式设30至3600秒；只限制本次监督进程，Windows Job负责其自己的子孙，不终止其他项目。

状态写于本批`progress/本案ID.json`，日志和本案短锁也在该目录。短锁含helper实际PID与创建时间，只在证明helper退出后恢复。重复调用保留原token与顺序，不重排、不重复启动；已有r16活跃媒体返回`running`并保留原runtime/Job/token。旧capture已成功且只缺技术证据时直接进入evidence；进程退出后遗留active槽由原释放规则核退出再释放。崩溃后以本案当前run、原成功capture收据及实际文件恢复，不能仅信checkpoint。未完成原capture保留并返回明确修复动作，修复后显式加`--retry-capture`才重试捕获；成功capture始终复用，不受该参数影响。

已有evidence票据、`capture_complete`/evidence检查点或同run原capture收据时，缺失`capture-pending.json`返回`repair_capture_pointer_then_resume_evidence`，保留原票据及原片，不降回record。负责人先核原收据及原片并恢复指针，再沿原evidence票继续；`--retry-capture`不能绕过该修复。未完成capture的running/failed检查点即使仍有waiting record票，也须先修复并显式重试；正常尚未启动的排队不视为失败capture。

队列/资源不满足时入口立即返回`waiting`及实际准入原因、原票据和必要的`selected`指针，不睡眠重试。selected含实际batch/case/stage/token/owner；负责人接续该票据所属的授权聊天/案件，入口不取得或执行其他owner/其他case的token。媒体运行结束、其他owner推进或实际资源变化后重新调用原命令；不要盲问相同阶段，也不要取消正常排队来抢位。`cleanup_pending`保留active并指明核原Job退出后接续；不能凭Node父退出推断Chromium/FFmpeg退出。`technical_evidence_ready`仅表示本次受控媒体命令成功，下一步仍为实际独立视觉审查；它不签pass、不发布、不代替finalize。重复调用已完成checkpoint只核当前run/冻结绑定和两份短receipt，不重复整视频或timeline哈希、不重新解码或扫描全部帧；首次继承原完成事实与最终完整媒体、成果门禁保持原规则。

负责人看到真实selected已指向自己就绪的授权案件时，先启动上述有界入口及现成Job，再做与其无依赖的记账；不要让上一案的长报告或元数据收尾占住下一就绪媒体任务。阶段结束优先衔接下一可执行步，再发简短交接；等待仅保留真实原因、解除条件和当前票据，不无变化催办、重建票据或反复打印全状态。其他owner的selected只交回原负责人。本条约束父执行次序，单案入口仍只执行指定本案，--ready只接续初始已排队同owner同批集合，不是跨owner后台调度。

模型返回`Selected model is at capacity`时，负责人把实际失败的父session JSONL、spawn `call_id`保存为本案控制请求后调用：

```powershell
& $env:SCB_PRO_PYTHON -B '工具目录\batch_control.py' defer-capacity --root '现有共享调度根目录' --batch-id '现有批ID' --pid 12345 --case-id '本案ID' --token '该次实际active模型token' --value '本案容量失败请求.json'
```

请求为`{"session_log":"实际父session绝对路径.jsonl","call_id":"实际spawn调用ID"}`；已成功派生child后失败则另加`child_session_log`。实际spawn必须明确`fork_turns=none`及原admission的model/effort，message含本次token和工作区。没有返回child的真实容量失败可直接延期；已返回child必须从该child真实JSONL核parent/agent身份、实际模型、最后生命周期为`task_complete`且error为`server_overloaded`，并从父日志核最新实际`list_agents`结果仍为该agent的capacity errored，且之后无本agent接续调用。用户文本、日志里示例命令、旧errored但实际已恢复child、仅caller声称退出均拒绝，保持原槽。当前工具未支持的生命周期/工具结果格式保守保留槽，由负责人补真实证据。

`defer-capacity`在原共享owner事务内将本次失败槽释放并一次原子替换queue，同时创建唯一同stage/model/effort waiting票据；队列是重试日志。重复失败请求返回同票据，崩溃也不会出现“已释放却未重新排队”的中间状态。旧调用/admission/permit及case的实际业务阶段保留，不能伪造已完成。冷却依次30、60、120、240、300秒，之后每次最多300秒，累计尝试数持久保存。未到期票据单独不参与公平选择，不占active，不挡其他ready案件；`acquire`明确返回剩余截止事实，`status.current_tickets`展示当前票据及capacity_retry。到期后仅下一次显式acquire取得原规定模型，不自动付费重试、不降级、不改全局模型，也不增加审核阶段。

原正常active模型/媒体票据不因安装而改变。已有r16完整recording与controlled-video事实、尚无r17 checkpoint时，入口先调用原`completed_recording`核视频和短timeline的原完成绑定，建立首次checkpoint后直接返回；不重新decode/encode/读全部帧，不要求保留raw或capture-pending，不因后续小改重复evidence。仍在运行的旧Job保留，先等它自然结束。旧父此前已手动release的容量失败历史不自动重写；已经恢复的原waiting票继续原token，不重建、不重跑，只由原owner接续。所有新失败应先`defer-capacity`，不要先release再准备而丢失重试票据。
