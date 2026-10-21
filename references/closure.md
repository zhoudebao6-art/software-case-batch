# 标准阶段资料与隔离源码包探针

## r19 单次审核交接

父的新交接统一使用 `review_packet.py draft --compact`，只传返回的 facts 路径、哈希和本轮差异，不把完整索引抄入派发词。审核准入后，工具从绑定批次唯一且已验证的当前审核票机械填入 admission/permit；也可显式 `--root --batch-id --token`。提前准备、尚未取得审核票时仍可生成中性草稿。`--compact` 只将事实展开内容改为路径、哈希、计数等短索引，保留完整覆盖文件；不会填写 reviewer 决定、已阅 ID 或继承关系，不自动缩减首次 Word/视频范围。旧 CLI 不带开关的默认行为仅为接口兼容保留。审核者只展开本轮需要阅读的材料，机械缺字段不另派一轮模型补抄。

facts的 `visual_navigation` 直接列当前图、视频接触页、首尾及操作关键帧的路径/hash和已有证据ID。审核者直接打开这些文件及完整索引中的全部Word页，不为找图反复输出数百个均匀帧条目；全部原帧和覆盖要求保留，需要辨读的帧仍看原尺寸。导航不是已阅或通过证明，未在索引中的文件不伪造ID；发现问题仍一次读完其余稳定材料。

新案与合法新文档修订冻结 `review_coverage_policy=required-evidence-v1`。在原有 manifest（或已有完整 index）内声明 `review_scope`，引用已经生成的逐页图和源映射，不新增渲染器或台账：

```json
{
  "files": ["本案既有补充证据路径"],
  "review_scope": {
    "word": {
      "sha256": "当前成品Word实际SHA256",
      "page_count": 2,
      "pages": [
        {"page": 1, "path": "evidence/word/page-1.png"},
        {"page": 2, "path": "evidence/word/page-2.png"}
      ]
    },
    "source_mappings": ["evidence/source_audit.json", "evidence/formula_registry.json", "evidence/source_trace.json", "evidence/calculation_trace_map.json", "evidence/coverage_matrix.json"]
  }
}
```

页数、路径和文件名必须对应本案实际完整渲染结果；兼容的既有 CSV 映射仍可引用，不为格式重抄。脚本核当前 Word 哈希、连续页序、文件及已声明必查范围，不能证明页图内容完整或审核者真的阅读。负责人核范围，独立审核实际读全部页。`draft` 在原 index 冻结 run、当前产物、`required_evidence` 与上述 scope；`review_scope.video` 从原录制时间线自动产生，无需人工填写，源码成员与逐图快照复用原 proof 字段。显式 index 不能省略已声明必查文件，也不能塞入会在派发时变化的 `model-dispatch.json`，实际派发另由原合同认证。完整原始技术帧仍绑定哈希，但只把完整接触页、首尾与操作关键帧列作对应视觉必读，不能把所有均匀原始帧另变成逐帧模型任务。

同一审核草稿保留 `review_id` 和 `review_index:{path,sha256}`，父在原 review 阶段记录中绑定同一引用，派发引用当前 index 或 facts 哈希。审核者只填真实 `reviewed_evidence`，阅读说明沿用 `visual_notes/limitations`；不由脚本补已阅或通过。最终入口拒绝未知/重复/缺失必读 ID、索引被换或明确未读声明。旧 run、已签收据不回填；包修订继承父策略与合法旧视觉事实。简化收尾认证原首审冻结索引和覆盖，修后只核受影响项，不拿已修改源码重新校验旧首审字节，不追加整案审核。

既有draft会从实际源码ZIP读取成员哈希，内嵌到原审查草稿的source_package；首审保留这一事实即可，无需新台账。后续仅压缩方式改变且成员完全相同时，只检查当前包的完整性、解压启动与原核心流程，不重做未受影响的业务测试；源码成员变化或缺少可信旧成员依据时，仍核实际受影响功能。

审核结束统一使用 [父编排的 complete-review](execution.md#r19-接续与交接优先规则)，真实结果先落盘，必要返修关联后再放票。随后按下节分流；首审revise保留原样，小修自检不伪写成独立pass。不重复计算未变的合格数据或重录合格视频。

新完整run的 `web_experience_policy=case-workflow-v1` 沿现有 browser 检查绑定业务页面、任务、原技术映射、实际浏览器断言和全部页面截图；视觉类再绑定真实输入、出处/许可和处理结果。`review_packet` 的既有索引将这些当前证据列为必读，`review_scope.web` 机械保存范围；审核者实际对照源文和源码核页面是否覆盖该案全部主体任务、输入是否驱动真实处理及结果是否可用，并实看全部业务页及主要状态的当前截图，按[页面检查](web-presentation.md#在原检查中实看)核视觉层次、文字可读性、密度与无用说明。词表和截图数量不能代签文案精简或视觉通过，不由结构检查代签业务通过。缺少必查文件或缩减范围直接拒绝，问题仍在同一首次独立审查收齐。字段见[Web设计](web-design.md)，复用原日志和截图，不新增第二个验收流程。

## 按实际问题收尾

用户2026-10-16要求适用于后续授权案件：已有审核的小问题由原修复者最小修改、核对受影响项后直接打包，不再另排整案复验。首次独立质量核对仍须完成。当前优先多有效业务模块与充足有效数据；沿已有映射和实际统计核覆盖，8—12模块及万/十万行级是适配起点；新rich-delivery-v1至少6个真实模块和10份有效CSV且均无数量上限，具体行数按领域确定。纯风格细节不返修阻塞，技术真实、启动、导出、文件完整及核心业务缺陷仍处理。审核一次列齐每项具体影响、定位、复现和最小修补范围；不将风格偏好、无损主功能的排版建议、参数差异或已合格视频与新代码的细节差异列为返修阻塞。

- 首审通过：沿用 `finalize` / `publish`。
- 已有审核、必要小修已完成：用 `close-simplified` 记录真实首审、原修复者和受影响项自检，直接发布并生成整案ZIP、同步交付状态。不再为获得新pass派模型，不先故意执行旧finalize取得失败记录。
- 核心计算/来源技术不符、无法启动或导出、文件缺失损坏、主体操作未建成（含核心业务页面缺失、装饰图或固定结果冒充视觉识别）、首次必要阅读未完成：一次列齐并定向处理；只补这些问题及实际受影响的验证，不能用“简化”掩盖未解决问题，也不把已通过产物全部推倒重做。
- 用户明确认可特定现状并要求结案：停止该范围后续返修复验，只做实际导出、复制和压缩包完整性检查；收据明确写“用户认可现状”，保留历史问题，不能伪称独立通过。此授权不外推至其他案，也不把缺失或坏文件写成可用。

小修交接复用已有问题ID、修复记录和日志，不再创建第二套审核台账。源代码改动只更新源码包及受影响功能检查；Word改动只核受影响页面/图；CSV或视频自身未坏且已有通过事实时复用。未通过、未读、确实受影响的范围如实列出，不能靠复制旧hash、改判定或撤销问题伪造通过。

解释脱离上下文等实质文档问题保留实质分类，不能降级为小瑕疵。原问题的 `affected_artifacts` 与修复范围均仅为原名 Word、且不涉及明确核心业务或业务必检项时，按当前 Word 绑定的 `word_visual` 和对应逐图 `explanation` 证据核实受影响上下文；缺少、未读或失败仍阻止收尾，不要求无关算法/API/视频重验。首次必要独立阅读及实质问题的受影响独立核对仍按质量规则完成；简化收据不冒称新独立通过。软件核心或跨产物实质问题继续要求真实业务检查，不能只改影响标签或补打包记录放行。

整案ZIP在目标目录的独立草稿中直接写出；MP4、源码ZIP及DOCX保留原压缩内容，CSV等文本压缩。每个成员读到EOF时同时核CRC和发布收据SHA256，核过后同卷改名，不再对同一文件重复解压。重入按原收据或保留草稿恢复，不能跳过实际失败。交付之后仅在批次交付/用户查找时更新 `delivery_index.py --root '实际交付根目录'`；目录索引不参与验收、状态同步或通过判定，刷新失败仅补索引，不重复finalize、录制或审核。

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

工具从原 run 的成品目录选择 `系统材料/源代码.zip`，核对 `source-package.json` 的最终哈希；在 `D:\codex+\temp` 自动建全新目录，完整校验 ZIP 路径、重复 Windows 名称、链接、成员数量与解包总大小后解包。它不会对隔离树执行 `prepare` 或 `process_guard register/stop`。该目录只承载这次试启动，不是新案件。

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

新research-materials-v3成品包含原名Word及“研发证明材料-案件名称”目录，内有源码ZIP、>60秒且≤300秒操作视频、一张真实高清界面截图.png及数据目录。交付PNG与原browser绑定字节一致，沿原首次审查实看文字及核心业务内容；全部页面内部证据照旧保留，不增加复验轮次。合法局部修订继承父布局与已通过媒体，历史旧合同不热改。
