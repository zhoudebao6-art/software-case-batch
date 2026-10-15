# 标准阶段资料与隔离源码包探针

在原阶段已经完成相关工作时进行一次短交接检查；缺项只补真实缺项，不新建完整验收轮次。先在当前 PowerShell 加载已安装 `Enter-Environment.ps1`，使用 `$env:SCB_PRO_PYTHON`。以下工具不派发模型、不签独立通过，不改已完成生产案。

```powershell
& $env:SCB_PRO_PYTHON scripts/review_packet.py stage-check --workspace '原案件绝对目录' --stage build-start
& $env:SCB_PRO_PYTHON scripts/review_packet.py stage-check --workspace '原案件绝对目录' --stage build-complete
& $env:SCB_PRO_PYTHON scripts/review_packet.py stage-check --workspace '原案件绝对目录' --stage build-complete --plan '原工作区内已有自定义录制计划.json'
& $env:SCB_PRO_PYTHON scripts/review_packet.py stage-check --workspace '原案件绝对目录' --stage data-ready
& $env:SCB_PRO_PYTHON scripts/review_packet.py stage-check --workspace '原案件绝对目录' --stage pre-review --execution '工作区内现有六类运行事实.json'
```

`build-start` 对实际父会话 JSONL 的真实 `spawn_agent` 调用及成功返回核对 build/已记录 repair，要求指定模型、思考级别、`fork_turns=none`、真实 `call_id` 和返回 `task_name`。它不要求此时尚未完成的成果快照。`build-complete` 增查各完成阶段保留的快照字段并复用原 `construction_checks` 依赖校验；独立审核仍判断快照和业务检查是否完整真实。`data-ready` 按原最终合同检查内部 `data-provenance.json` 的 `nature/sources/validation`；工具不会编造来源或重新生成合格 CSV。`pre-review` 合并上述完成材料和原机械 review packet；可沿用 `--index` 或 `--manifest` 提供真实 Word 页/源映射覆盖。

`build-complete` 和 `pre-review` 可通过 `--plan` 提供原工作区内已有的自定义录制计划，与 `proflow.py check-build --plan` 共用原根目录和依赖哈希校验；未指定时仍使用 `.product-v2/record-plan.json`。不复制或重写已合格计划。

预审准备不要求此时尚不存在的 review dispatch，也不代写 reviewer 身份、决定或签名。独立审核实际派发后，原 `contracts.model_review` 仍认证真实准入、调用、最终答复及 proof hash。输出 `inputs_ready` 或 `blocked`，每个阶段缺项附具体 `location/message/action`。原 `check/draft` 接口继续保留；它们的历史行为未变。

## 包检查接口

```powershell
& $env:SCB_PRO_PYTHON scripts/package_probe.py run --workspace '原prepared案件绝对目录' --probe '原工作区内真实包业务探针.py' --receipt '原工作区内evidence\全新包检查.json' --timeout 120
```

工具从原 run 的成品目录选择 `模拟系统/项目源码.zip`，核对 `source-package.json` 的最终哈希；在 `D:\codex+\temp` 自动建全新目录，完整校验 ZIP 路径、重复 Windows 名称、链接、成员数量与解包总大小后解包。它不会对隔离树执行 `prepare` 或 `process_guard register/stop`。该目录只承载这次试启动，不是新案件。

案件只需提供真正执行本案启动和核心业务链的 Python 探针。探针使用环境变量 `SCB_PACKAGE_ROOT` 访问最终 ZIP 的隔离内容，使用 `SCB_PACKAGE_RESULT` 写实际断言 JSON，`SCB_PACKAGE_RUN_ID` 是原 run 身份；通过 `subprocess.Popen` 的参数列表从隔离目录启动软件，配置独立数据库/端口，执行本案算法与持久化/查询操作。需要外部交付 CSV 的案件由其探针明确读取或复制本案已合格 CSV；通用工具不替代数据清洗和本案输入映射，不借用已在线的原服务冒充解包启动。

结果格式至少为：

```json
{"core_flow":"实际执行的本案业务链及核对结果", "checks":[
  {"kind":"startup", "name":"实际解包服务启动断言", "passed":true},
  {"kind":"core_flow", "name":"实际核心计算与保存查询断言", "passed":true}
]}
```

这些字段只能由实际运行的探针填写；返回码零但没有结果/必要断言仍失败。结果不是独立技术认可，探针是否真实覆盖本案须由独立审核判断。

Windows 使用既有 `media_job.Job/launch_suspended`，在任何探针指令执行前将进程放入本次唯一 Job；退出和超时均关闭这个 Job，核对剩余成员为空。只输出受控 PID 和收尾事实，不枚举或公布其他进程命令行。POSIX 便携分支采用本次独立 session/process group、信号退出与剩余活进程核对；当前 Windows 回归不代表已在其他操作系统实跑。

原案件的全新 JSON 收据及旁边 `.log` 保存真实执行、最终 ZIP/探针/检查器哈希、案件断言和退出事实。只有进程清理成功、结果完整、ZIP与探针在运行中未变才为 `completed`。成功收据中的 `execution_check` 可复用为原六类运行事实的 `package_startup` 项，顶层 `source_zip_sha256` 绑定最终 ZIP；不伪造其余五类事实或 review 签名。命令路径在内部收据中保留，终端只显示短收据指针。

成功默认仅删除确切新建的临时解包根；`--keep-extracted` 可保留。失败保留现场和日志，原成品和原 run 不改。该工具是受控试运行器，不是限制探针访问文件/网络的操作系统沙箱；案件探针不得复用共享后台或通过外部服务绕开本次受控进程树。

包元数据必须为 JSON 对象；无效元数据在执行前以 `blocked` 返回。损坏 ZIP、损坏 DEFLATE 或不支持的压缩方法在解包阶段以 `failed` 记录 `error`，保留已创建收据、日志及解包现场，不执行案件探针；这些失败的命令返回码为 2。
