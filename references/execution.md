# 父编排、环境、恢复与复用

本新版没有移植原caseflow自动付费CLI调度器。父会话实际dispatch高建设、ultra返修及独立验收；本技能脚本提供确定性的manifest、唯一父锁、共享队列/资源、状态、原件/hash、录制、打包和收据门禁。旧原入口仅作为冻结规范/诊断能力参考，绝不对原目录执行run/control/migrate或写旧配置。

所有测试案修改均为以后每个授权案件的通用要求，按本案业务对象/字段实际适配。默认正式成果集中`D:\研发图表\批次\案件`，候选`D:\研发图表\.staging\本批-本案-唯一版本`同卷发布；用户明确工作区或其他目录优先，工作区方案使用总工作区/成品，与cases下每案执行目录隔离。--output仍显式传入，不静默改变显式输出路径，历史不自动搬移，缓存/临时文件仍D:\codex+。仅更新本技能本机配置和当前进程成果变量，不改原环境入口及原快照。

## 总控日常路径

本节是正常批次的接续入口；SKILL中的质量与角色要求始终适用，后文保留完整协议和历史兼容。总控只围绕当前就绪产物、有效票据与真实阻塞作决定，不新增计划审批、预审核模型、复用确认表或单独录制准备模型阶段。

| 触发 | 本轮动作 | 何时展开详情 |
|---|---|---|
| 新授权批次 | 冻结一次清单；register、claim、公共preflight，按真实父运行时绑定动态调度 | 首次读取下文“本批登记与资源”“零模型预检与安全”和[scheduler-policy](scheduler-policy.md)的绑定协议；已有登记不重做 |
| 接续或阶段完成 | 读取一次`batch_control.py status --compact --root 原调度根 --batch-id 原批ID`；只处理本轮发生变化的案件，单案问题加`--case-id 原案ID` | 精简结果保留原记录路径；缺失/异常才定向读对应state/manifest/queue或本案`proflow.py status`，不先打印整批历史 |
| 派发模型 | 原owner queue/acquire原阶段；实际取得后派发正确角色，没取得按返回selected通知对应owner。已派发的原任务继续 | 首次用本阶段时读后文准确协议；容量是预留上限，status不替代acquire，也不证明模型已启动 |
| high提交 | 一次交齐本案实现、图文、数据及真实自检；当期材料检查通过后直接推进依赖产物 | 本案出现实质缺陷才ultra返修；明确环境故障按下文安全规则恢复，不无条件增加模型往返 |
| capture完成 | 原媒体票据由progress_driver立即接evidence；仅证据故障保留原片补evidence | 首次媒体读取[progress](progress.md)及[录制](recording.md)；实际Job未退出不放票 |
| 验收准备完成 | 真实审核准入及verify-review后，用`review_packet.py draft --compact`生成一次中性事实，派另一ultra；按完整必查范围实际审查 | 首次读取[阶段交接早验与最终验证](tools.md#最终验证)和[受控证据](#受控证据审查与优化)；facts不是已阅证明。draft自身已含check，不在相同输入上额外先跑check |
| 审核返回 | complete-review认证最终结果、保存必要返修绑定并放原票；pass接finalize/publish，revise仅修实质未过及受影响项 | 不重新审已通过视频和清洗数据；未读范围不能当已过。停止/诊断无报告走下文真实终态分支 |
| 全部完成 | 以真实发布收据收口，正常完成后停止本批调度 | 旧成品冻结，不为升级重建；批次状态中的delivered仅是登记值，汇报完成须引用已有真实收据 |

精简状态只裁掉模型上下文中的累计历史，不清理原记录、不缓存通过结论、不改变调度和验收。状态未变时沿用本轮结果；等待以实际阶段完成、资源释放、新用户指令或明确失败为触发，避免反复查询与催办。总控交接只写当前动作、原owner/run/token、材料路径和真实阻塞；实现者与审查者仍按角色读取实际需要的完整材料。查历史用原文件定位，接口调用方仍可使用不带`--compact`的完整status。

## 本批登记与资源

### r19 接续与交接优先规则

模型只负责源材料理解、实现和独立业务判断。父不重新抄写完整证据：按当前阶段读取本节及对应参考，确定性缺项由已有脚本补齐；仅在阶段完成、资源释放、真实失败或新用户指令时推进，不定时重跑已通过检查。先派发已有就绪工作，再补不影响准入的后台记录；不能省略派发前必须核准的身份与材料。

以下规则取代下文历史接口中笼统的 finally 放票和文本暂停说明：

- 已派发 review 由 `batch_control.py complete-review --root 根目录 --batch-id 本批 --case-id 本案 --token 原票 --value 请求.json` 完成。请求含 `review_evidence` 与 `review_evidence_sha256`；脚本认证真实独立派发、最新 FINAL 和报告哈希，先记录结果及必需返修绑定，再释放原票。它不代写 pass、不发布成品。未派发的取消继续用 `release-slot`；其他阶段仍按已有实际退出和资源规则释放。
- 已派发审核因真实停止或诊断退出、没有新判定时，请求用 `outcome: cancelled|diagnostic` 和 `reason`。须有真实 child 最新终态与父最新 `list_agents`，且无后来续派；取消另须已有授权 drain。缺证据保留票据，原判定原样保留，不能凭父一句“已结束”放票。
- 新的 `drain/continue --value 控制事件.json` 包含 `batch_id`、`action`（或布尔 `drain`）、`user_evidence:{path,offset,size,sha256,timestamp}`，可附 `statement`。引用真正用户 JSONL 的原始片段，由父解释该批动作的授权范围；脚本核验事件真实性与时间，按已登记事件保存递增 revision 和 supersedes，较新的恢复不再被旧暂停覆盖。未来时间、模型转述和陈旧重放不得替代当前用户指令。未登记的新消息不会自动被脚本获知。
- 没有版本记录的旧批仍兼容原 API；已采用版本控制后，状态改变须继续传真实事件。不得为迁移而伪造原始消息、重登记批次或重写历史证明。正常运行时重复 continue 只是幂等接续，不能借此改变授权。


新授权批次按原流程register/claim/preflight后，`bind-controller`核真实父聊天并`configure-scheduler`显式请求`{"mode":"verified-controller-adaptive-v2","capacity_scope":"verified-parent-runtime","aging_seconds":300}`；直接沿用当前用户批次自动化授权引用，不每批额外征求调度同意。按真实session而非共享PID去重，不设跨批合计、每批、组或stage人为模型配额；建设/返修/普通及已授权加急审核受本父最新已验证runtime真实workers限制，同父多批共享且不能叠加扩容。平台13槽含父时最多12子任务，4槽含父时仍最多3；以后原owner刷新真实证据即可使用真实新容量，不裁到12。每父独立选择本父可运行队列，加急优先取得本父空位，普通候选保留三路/批公平及老化；未知active仍保守扣每组容量。返修仍ultra，未获真实revise额外预算绑定时仍保留原work_kind=build，不假造绑定。未中selected含实际owner及`selected_owner_acquire_then_dispatch`动作，只由其owner接续。省略scope的历史adaptive-v2仍保留原global12，legacy/fair-v1亦兼容；旧active、冻结manifest/run/permit和媒体合同不改，启用/回退仅影响后续acquire。预约不代表实际已运行。准确绑定和命令见[真实聊天调度](scheduler-policy.md)。

仅用户明确调用/点名并确认的清单运行，已确认不逐案重问。一个Word默认一案，多材料合并须清单明确；锁文件、加密/损坏/旧doc不能静默跳过。冻结原basename、绝对/相对路径、大小、采集时间和SHA256，source副本哈希核验，原目录只读。新增工作区为`cases/YYYY-MM/案件名`（同名中文序号），点名旧案只在其独立revision继续。管理在新版`cases/.batches`、运行状态在各案`.product-v2`/`.runtime`，每案独立端口、浏览器、D盘临时目录。用户指定工作区优先。

仅旧legacy或未配置的历史兼容策略使用8建设/返修、3普通独立审核、1明确加急的固定模型上限；旧fair-v1保留其显式配置限额。新adaptive-v2的verified-parent-runtime范围使用上述真实父容量；受控evidence仍单槽。用户本次明确多开录制授权下，新批次CLI默认`--recording-limit auto`最高4路，也可显式2/3/4；旧manifest保持2路及旧worker规则。新批模型槽和媒体槽分开：下例的host-slots 4是历史登记值；有效runtime证据可替代模型容量判断，缺证据才按旧worker容量与3取低值。以后原owner取得新的真实runtime证据时刷新绑定，不改冻结manifest，也不另加全局12裁剪。同一父可直接启动4个Node录制进程，仍须满足实际资源门禁；不虚增host_total_slots。`batch_control.py register --root 新版cases/.batches --batch-id 本批 --cases 已确认清单.json --authorization 本轮用户请求引用 --host-slots 4 --recording-limit auto`冻结manifest，之后config不热改。跨批全局4路、CPU/内存准入、旧active容量保护及launch前lease复查见 [并发录制](recording-concurrency.md)。清单每案含case_id/workspace/source_docx/source_sha256；父补原名/大小/时间及端口等实际字段。

`claim --pid 实际长期父PID`取得唯一负责人身份（PID+创建时间）。同批另一活跃父拒绝；旧父确实退出后，核对状态/源/收据再显式`recover-owner`，保留旧调用、用量、队列和孤儿阶段记录。此工具仅维护状态，不结束进程。临时命令Python PID不能冒充长期父PID。正在执行或正常排队均不重复派发。

`queue --case-id ID --stage build|review|record|evidence|expedited`返回token；`acquire --token TOKEN`按当前实际模式准入：adaptive-v2使用真实父容量、阶段公平及等待老化，legacy/fair-v1沿其原限额与顺序，不能忙轮询；未授予时父按selected及真实owner继续可做工作并在资源释放后接续。`release-slot --token TOKEN`结束阶段释放；等待录制/验收不占建设槽，每案不能双占。批次必须使用分阶段录制：record槽内`record --phase capture`只连续录原片及操作事实，返回后在finally释放record，再queue/acquire evidence槽执行`record --phase evidence`完成编码、完整解码、5fps和全部交互帧。evidence排队时停止新增record，既有capture结束后证据按本阶段公平队列执行；任何live capture与重媒体evidence互斥，等待ticket不占active槽。成功、失败、取消均由父finally释放；失败原片和事实保留，修复后仅证据故障可重跑evidence，不盲目重录。旧不带phase的full调用仅兼容独立无并发运行，批次禁用它以免资源误算；旧manifest容量不热改，若还有旧record+evidence双持有任务则先等其结束释放，再接续新路由。repair实际模型仍ultra；adaptive-v2共享本父容量且不消耗旧repair_extra预算，不伪造revise绑定。录制取得槽后再查实际健康身份和物理可用/Windows提交余量较低值，基线4096MB、每额外录制槽2048MB。不足只在新manifest登记前降为1录制，旧批等待释放确认闲置资源/合法恢复，不热改、不降模型。

`update --case-id ID --value 当前实际状态.json`记录phase、append-only calls/usage、pending、recording_pending和具体blocked_fingerprint，不重置计数。`delivered`须有当前final receipt，最终负责人仍逐案复核清单/当前hash，单案完成不能称整批完成。`priority --case-id ID --value 10`只改排队优先级；`expedite --case-id ID --authorization 真实当前批案授权JSON`核真实肯定user消息，明确“c1加急/指定本批加急”直接等于Astra低思考，不要求“原加急模式”口令；scope名须注册ID或唯一冻结案名，纯“这批”须真实单一当前批context。控制器设本案priority=10并更新waiting，未来queue(review)/waiting acquire自动解析有效route。加急独立Astra/low，不追加ultra；已active有效普通审核保留原模型，授权不跨批外溢。所有MODEL stage共享宿主位，较高priority的加急build/review也优先下一空位；只有源/预检/授权/owner及新review run身份均有效、自身stage有空位的候选才能让低priority任务等待，失活或blocked/drain不阻塞普通，同priority跨stage由父编排。新批review取得active槽后，父先`verify-review --case-id ID --token TOKEN --value 案件工作区`复查并取得不可变dispatch permit/nonce，再按返回模型实际spawn；当前spec/proof和真实JSONL须绑定同admission/permit/token/scope。旧manifest/历史proof兼容和详细顺序见 [加急审核路由](expedited-routing.md)。

`drain --authorization 用户明确暂停/维护请求`让当前阶段完成后停止新阶段，`continue`依原授权接续；不能为监控或改规则擅停正常批。`resume-case --value 本案新的恢复证据.json`仅当前批已登记case，绑定原blocked_fingerprint、新status=ready和实际recovery_evidence，不由旧ready自动解除。父仍存活则本父接续；已退出才recover-owner，不新建批次或丢调用。共享故障由唯一维护者修一次，单案故障不暂停其他案。

共享等待队列只由当前可运行票据参与阶段FIFO/priority和新录制的证据排空判断。已drain、案件blocked/delivered或无有效当前负责人的waiting票据保留原token、提交时间、优先级及恢复历史，不能阻塞其他批；continue或带真实证据的resume-case恢复后重新按原时间/优先级参与。所有active票据仍完整计入容量及record/evidence互斥，等待资格判断不释放活跃槽。`recover-owner`转交active原token与运行身份并追加owner历史，不能因旧父退出改为orphaned；新登记批次媒体由Windows Job覆盖Node/Chromium/FFmpeg子孙，释放必须核Job与原runtime退出，阶段入口必须核冻结工作区绑定及相应active token。详情见recording-concurrency.md；旧无Job恢复保留占用直到明确专属process_guard收尾证明，不热改旧manifest。

## 零模型预检与安全

首次部署/路径或工具变化：运行零模型doctor-equivalent，实际导入依赖、版本、登录有界（60秒）、隔离Chromium和临时Word→PDF→PNG。默认复用当前已验证准确venv和bundled依赖，不盲目安装。旧原`runtime_doctor.py`未接入自动新版流程，父可在新版隔离目录以已核对工具执行相同检查并保存真实命令/退出码/log/工具hash；不得把原CLI路径成功称sandbox可用。

每个真实run在并行派发前，父按已安装CLI帮助选择原workspace-write/read-only接口，执行零模型读写/读回/清理及只读/区外拒绝验证，最长90秒（上限，不是固定等待），保留stdout/stderr及同期sandbox日志；桌面/运行时保持存活。同一run的存活宿主/运行时、CLI、配置、工具和安全模式未变且无新环境错误时，建设、返修和验收沿用已登记的真实通过事实，不按模型阶段重复完整预检。启动新run、相关环境变化或异常时定向重做；一种模式成功不推断另一模式成功。公共预检记录通过`preflight --value 真实环境证据.json`登记（status=ready、zero_model_calls=0、checks含workspace_write/read_only/browser/word_render，实际command/exit_code/log_sha256），模型槽拒绝缺记录/变更记录。公共通过不替代本案必要业务文件ReadWrite句柄和输出可写检查，不改原件/删除文件测试权限。

固定已验证官方CLI缺失不回退；node_repl如现存且绑定CLI才按原规则同路径绑定，不新建MCP。环境报错先保留实际命令、宿主绝对路径/版本/有效配置和原stdout/stderr，核准拒绝适用范围；os error32文件占用、sandbox初始化、tool policy、ACL、组织策略、依赖、编码、健康版本、内存分别记录。否定/不确定措辞不能仅关键词认定策略拒绝，也不能把不同宿主的配置混为一谈。真实sandbox、ACL、组织策略、tool policy或审批拒绝不换入口/命令/安全设置绕过，不改ACL/Deny/sandbox/审批，不反复每案付费重试。涉及其他有效任务的共享重启/中断维护先交用户决定，并保全进度/源/hash/调用/恢复入口。

worker blocked只阻断同故障重复付费，不代表整案永久不可制作；唯一负责人保留本案后续恢复任务，并接续全部授权清单中的可运行项。程序bug、缺依赖和普通路径/编码/venv/入口兼容问题在原安全模式及授权工作区内诊断修复；选错工具版本时，先核宿主和限制范围，确认不是安全拒绝后可恢复到既有已授权、已验证的准确运行时，不将普通本地配置当永久阻塞。可补输入/标定/权重/协议不是外部阻塞；源确实不可读、核心定义确实矛盾不可合理实现、账户/额度不可用或必要写入真实拒绝才保留外部限制。新恢复证据绑定原故障并实跑恢复，不只改状态。保留历史原判断与未读项。

服务启动前核准实际宿主绝对路径及有效配置、准确venv依赖/启动脚本/数据/端口和可恢复路径，hidden启动、记录launcher与listener。健康接口case/workspace/version（启动时冻结）、PID/创建时间/完整command/全部监听一致才复用；不得先停健康服务后试探已拒绝的启动。确需5.1时，中文脚本UTF-8 BOM、实际5.1及准确venv依赖验证，不能仅语法过；已核准其他宿主按其真实入口和配置实跑，不因版本选错改政策或Bypass。可恢复问题本案修复，媒体工具合法独立替代须来源/许可/hash并实际编码探测解码，不复制受限文件。进程收尾见processes.md。

## 受控证据、审查与优化

源完整读正文/表格/文本框/页眉页脚/OMML/DrawingML/VML/媒体/嵌入对象，登记raw/normalized公式、原符号/变量/单位/边界/来源/实施例/代码/测试/图的映射；节点数不等独立公式组。父在建设内一次列全合同/输入约束/说明数值/图文位置/切换问题，high自检先修，再渲染最终版。high提交前实际运行`contracts.chart_snapshot(workspace,Path(run['word']),run)`，核对图清单与Word当前字节、嵌图和图题绑定；labels只登记真实非空可见标签，不登记空轴标签或空字符串，缺项在建设内修齐并重核。这是既有自检中的便宜结构核验，不新增模型、审批或渲染，不替代逐图/全页视觉。

建设在现有源文映射内列清本案核心输入、状态转换、接受/拒绝边界和派生结果，并在同一次high中先验证这条业务链。仅当原技术涉及相应约束时检查版本/类型关联、重复或乱序事件、拒绝操作不产生部分写入、历史记录保留及时间数据泄漏；不向每案套一份无关长清单。录制前先核登录和唯一可见选择器，演示走真实有效主流程；预期失败的反例留在软件测试，不塞入成功演示路径。黑白图的坐标、文字、标记和图例同样使用灰度，不能只改曲线颜色。

标准字段在实际派发/完成的原交接内用`review_packet.py stage-check`核当期到期内容：build-start只核已实际产生的调用，build-complete核完成快照和原建设日志，data-ready核原数据出处字段，pre-review合并原机械验收材料；准确参数见[阶段交接早验](tools.md#阶段交接早验r18)。未发生的独立review记录不提前要求，不另加全量审查或反复扫描父目录；已有有效同一交接直接复用。最终ZIP启动检查使用[统一隔离业务探针](tools.md#准备数据源码)承载案件实际操作与精确Job收尾，原prepared案件登记证据，解包树不假prepare，不为检查器故障重制已合格Word/视频/CSV。

同一次独立审查按原定义检查当前核心链，发现一个问题后继续收集不依赖该缺陷的其余问题，一次给出可复现的完整返修清单。当前Word和视频已稳定时，在该次审查内完成其首次视觉阅读，避免软件每返修一轮便一直推迟首次看图/看片；已实际通过的内容按原复用规则保留。只有无法继续检查的真实依赖故障才提前结束并列明未读项，不能把首个普通缺陷当作整轮审查停止条件。返修只处理合并清单和受影响依赖，独立复验只补未通过、未读或变更部分；pass的完整覆盖和真实证据要求不变。

建设与审查使用[交付质量分级](quality.md#交付质量分级r18)：问题须说明具体业务/真实性/明确合同影响及受影响产物，非阻断外观偏好或小数据差别只留内部建议，不因建议循环返修。一次给出已证实的全部必修问题；返修ultra和另一ultra只读复验保持原角色。已实际通过内容不重读，首次未完成范围如实保留并补齐，不能删失败材料或用建议遮盖坏文件。

最终全页render、源保留、MP4完整decode/5fps接触页/关键帧由父控制工具生成，建设者不能自签。原`controlled_evidence.py/build_preflight.py/review_check.py`未完整移植；等效路由为`contracts.py chart_snapshot`结构/保留校验+父在新版工作区调用已核准原`render_word.py`只生成新证据+`media_evidence.py`固定函数视频证据+本次短ID索引。不调用原caseflow，不写旧目录。Word首次所有页实际看；合法复验只继承同规则未被否定且未变、以前真实已阅的对应每页/图及证据，不整文档抽样。

父冻结request的短E001证据ID、路径/hash和必查集合；审核前后file_map一致才绑定；审核者返回短具体issues、逐图五项、实际reviewed_evidence、coverage/limitations及最终真实proofhash。父保留raw答复和规范绑定，不补已阅ID或改verdict。`revise`缺项仅advisory，保留missing项并定向ultra修复；环境`blocked`仅diagnostic，保留原错误/未读项，不派付费内容返修。旧blocked误用仅在完整已阅、全是具体普通内容缺陷、无环境错误/无blocker时保留原判定另标路由revise；pass全部严格覆盖、逐图五项及hash。可修复问题一次合并清单、ultra返修自检、独立复验直到通过，没有固定两次上限。reviewer不实现。

本案持续服务日志位于.runtime或按原runtime-streams有限模式登记；冻结测试/CSV/源/Word/hash不排除、不删log逃审。首次录制的input显式覆盖当时页面共用逻辑/数据/可见PNG，捕获中的启动版本固定，未完成捕获仍核其输入。成片已经达到要求后保留原录制事实，后续数据、文案、参数及小幅代码变化不让recording_pending重新为true。文档专用变化只渲染受影响最终Word；完成视频按下述一次通过规则复用。合法零字节源码允许，必要成品非空。

父受控索引由 `scripts/evidence_index.py` 生成并可核reviewed IDs（机械检查不补签）。全视频接触页frame_files须完整有序映射全部样本，全部原帧程序逐个hash核验；实际查看完整接触页覆盖所有5fps时间线，首尾/交互前后0.2s/切换/疑点原帧放大读，抽样不能称全部原始帧已观看。ZIP说明专用修订继承链见tools.md，说明排除不触发渲染/重算/重录。

规范首次或规范hash变化才完整载入对应原文；本批后续阶段使用冻结版本、78项对应表与本案必要条款，不重复塞入26篇全文或长日志。短索引列全必查证据及hash，审查范围和真实视觉覆盖不减；`evidence_index.py review-input`从当前索引/成品/图/视频机械收集事实，独立审查者自行核验并写结论、已阅ID和最终proofhash，工具不生成pass或签名。日志先给命令/退出码、关键结论与证据路径，异常再读必要片段，不删除或改写原日志。仅合法同hash且未被否定的真实已阅结论可继承；改变部分定向重审，不能以成本理由降低模型或审查范围。

每批/案保留实际阶段耗时、开始/结束额度快照及去重后的response token；账户周百分比可能含并发会话，不能当单案精确成本、乘订阅价或把累计token_count逐条相加。父使用短上下文和确定性工具处理机械编排；建设high、独立ultra保持规定角色，本技能不修改全局模型/速度设置。

## 原专用入口等效范围

| 原入口 | 新版实际路线 | 边界 |
|---|---|---|
| plan/run/共享全自动调度 | batch_control register/claim/queue/acquire/update + 父显式spawn | 没有旧CLI全自动付费运行能力；模型仍实际记录 |
| control priority/resume/drain/continue/expedite | batch_control对应同批命令 + 父在阶段边界响应 | 不打断有效调用，不自动运行历史/其他批 |
| doctor/sandbox_probe | 父零模型实际检查+preflight登记 | 原受限模式/真实浏览器/Word，不仅版本/配置 |
| controlled_evidence/render_word/video_evidence | 新目录固定工具父调用+media_evidence/evidence_index | 全页/全时间线保留，旧工具只读引用不修改 |
| migrate/workspace_copy | 用户明确授权后父冻结/hash/停止归属，再正常继承新副本逐文件验证 | 未移植原自动迁移器，不rename后假定旧ACL，不清空旧树 |
| 原GitHub发布/安装器/知识库维护 | 保留条件规则，等用户明确认可与发布请求后才执行 | 用户明确授权后才安装、发布；不自动扫描维护无关案件 |

最后查C盘本次新增可再生缓存，D盘temp/tool cache；迁移先D盘backups及核验，只删确认原缓存、保留链接/占用，依赖/凭据/数据库/会话/用户文件不作缓存，不为清理结束任何进程。

## 减少重复工作

用户明确要求停止某些已达到其交付要求的案件时，立即停止这些案件的新建设、返修、录制和审核，保全成果并按归属收尾；停止流程只完成在途安全收尾、释放所属资源、保存已有恢复指针及简短回执，不趁停止新增全量检查、渲染、媒体证据或扩写长交接；记录用户收口范围及真实交付路径，与独立验收是否通过分开，不伪签pass。恢复其他批次时明确排除这些已要求停止的案件。通信工具可用时，使用真实聊天发送并读取回执确认接续；共享交接文件不等于另一聊天已经收到指令。工具暂不可用则如实记录传达状态，不声称已停止远端执行。

视频有一版实际达到要求即记为已完成并沿用其成片和真实已阅结论。后续小细节、文案、数据、参数及小幅代码改动不重新比对视频版本、不填写差异复用表、不重新视觉审查或重录；只有系统主体或主要操作流程明显改变，或视频及其原技术证据本身损坏、缺失、被替换或有实质缺陷时才处理。首次未审查的视频仍完成原规定的独立视觉审查；旧录制事实不改写，当前算法和数据由各自检查验证，不声称旧视频验证新算法。已有原片只缺编码/时间线时只补缺失部分。单次验收合并具体问题，不增加额外模型阶段。

父在新会话接续、阶段完成或相关文件确有变化后调用只读`proflow.py status --workspace 本案 [--plan 当前计划] [--evidence 明确已有proof]`，按现有收据继续尚未完成或依赖已改变的工作；同轮已有有效状态便沿用，不逐步重查或忙轮询，不反复向子会话询问同项完成状态。它不启动服务/媒体/模型、不打开图，也不重扫全部视频帧；同一请求的路径哈希只计算一次。状态区分capture已完成待evidence、technical_ready待首次独立视觉、已有最终独立验收记录、stale的具体依赖及unknown。源码/Word各自变化按各自收据处理；充足且已清洗通过的CSV按下述完成数据规则复用，完成视频按一次通过规则复用，record-plan的input_files保留当时录制上下文，后续变化不作为作废视频的条件。只缺技术timeline或最终MP4且原capture未变则补evidence，不再次消费录制业务；有效原片/技术证据按record既有恢复逻辑复用。

status列出的proof/已阅ID只是原记录指针，不补签、不推定首次视觉已完成；只有既有完整final收据与当前成品/proof绑定未变才显示verified。已发布完整快照匹配后直接返回done，无需重新执行其他阶段。技术就绪明确只核receipt/video/timeline，并未逐核帧；最终finalize保持完整帧哈希及真实独立调用/视觉覆盖，若查出某部分失效只修补该部分。缺信息先定位unknown，不凭mtime缓存猜通过。技能维护任务只以本轮有界回归和独立技能验收完成，不自动接续旧测试案制作；正常案件完整交付不变。

建设初始输入一次给全本案材料、当前政策和必要证据索引，模型读角色相关条款；不重复加载未变原规范全文。总控用当前版本的合并问题、变更和短证据索引交接；建设/返修在本轮授权范围内连续完成范围与自检后一次返回，不为可自行完成的机械步骤逐项往返。被替代材料留历史，仅复现或合法继承需要时读取；不回传长源码、全日志或整份session_meta。使用controller_facts对指定会话增量取实际调用及用量，父只输出当前相关agent/call及新增事实摘要，不反复打印累积calls/usage或全缓存。状态必须由当前案件收据和实际阶段推导，禁止每次同步重置building。最终调用验证仍核原日志，缓存不签通过。

high在原件盘点后先用最小业务对象和源定关键反例实跑最终函数/API，并验证当前部署入口、健康身份、必要持久化及停止/端口释放；通过后再做依赖的耗时图文、扩量与正式录制，不要求先完成全部后端，也不重做已有合格结果。建设与自检仍含图谱覆盖、标注避让、数据规模/专名、业务一致性和正常录制脚本。就绪检查通过直接进入受控录制；只有确有实现或录制计划问题才派ultra修复，不无条件为每案增设一次录制准备模型会话。失败问题一次合并返回；仅对变化和直接影响部分重算/重绘；已通过视频不随小改或数据变化重录。当前软件及图文的独立ultra检查保留，视频沿用真实原结论。软件依赖、工具版本与字体未变可复用已验证环境，同一真实run内的公共双模式预检按上文复用，本案必要文件访问和输出可写检查仍保留。

独立ultra在同一次验收内先核原材料的关键约束、状态转换、当前代码与低成本复算/边界测试，再展开全部Word页及视频视觉检查。前项已发现必须重建的阻断问题时，合并当前已证实问题并如实给revise和未阅范围，不预签未阅项；已有合格视频不因待修的代码或数据小问题作废或重看。修复后的最终pass仍需完整必查集合与全部规定视觉覆盖；这不是新阶段或额外模型调用。返修与复审首先读取问题定位、当前变更和绑定hash；源码和图文仅继承曾真实完成且未被否定、依赖未变的审查，视频按一次通过规则继承其原成片及真实已阅结论，不因后续业务输入小改重复查看。不再次把整份旧proof、原文和代码全部输出到上下文。

数据已有一版充足并清洗、质量检查通过后，即记录为数据成果完成。check-data/status/finalize及继承路径只核对已完成CSV自身的成员和全部字节与原有效通过事实；后续代码、原始输入、data-plan、检查器或运行时改变不要求重生成、扩量、重清洗或再次逐行审计。CSV自身改变/损坏/缺失、原通过事实无效或发现明确数据错误时才处理相关部分。首次未通过的数据仍完成禁列、专名、有效量及领域约束检查；当前算法测试独立进行，不声称旧数据验证后来修改的算法。不用mtime或文件大小代替字节核对，不新增逐项复用确认。

总控接续使用阶段结束/异常事件及有游标的wait_threads快照，等待资源时沿唯一票据和selected接续，做其他可运行工作；不重复建票或为同一等待写多份状态、频繁查询。通信成功后保存一句实际回执和下一步即可，详细证据沿已有路径引用。录制前的原有短入口检查同时确认当前数据库/模型维数与代码一致、首个业务动作成功及业务可见文字；已有合格视频则直接跳过录制准备。

真实selected指向本owner已就绪案件时，优先沿原票据启动现有`progress_driver.py`/`media_job.py`的有界Job，再处理不依赖该Job的其他案件发布元数据或长报告；Job仍由原唯一owner监督，原阶段lease、Windows Job、资源复查及超时保持。指向其他owner时只交接准确batch/case/stage/token及当前原因，不代取票。阶段完成立即释放已证明退出的所属资源并接下一可执行步；阻挡时保存具体原因、原票据和解除条件。正常运行/原因未变不催办，不反复展开全状态、旧合同或累计日志。这是编排执行要求，不宣称新增自动跨案调度服务。
