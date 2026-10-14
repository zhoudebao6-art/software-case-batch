# 父编排、环境、恢复与复用

本新版没有移植原caseflow自动付费CLI调度器。父会话实际dispatch高建设、ultra返修及独立验收；本技能脚本提供确定性的manifest、唯一父锁、共享队列/资源、状态、原件/hash、录制、打包和收据门禁。旧原入口仅作为冻结规范/诊断能力参考，绝不对原目录执行run/control/migrate或写旧配置。

所有测试案修改均为以后每个授权案件的通用要求，按本案业务对象/字段实际适配。默认正式成果集中`D:\研发图表\批次\案件`，候选`D:\研发图表\.staging\本批-本案-唯一版本`同卷发布；用户明确工作区或其他目录优先，工作区方案使用总工作区/成品，与cases下每案执行目录隔离。--output仍显式传入，不静默改变显式输出路径，历史不自动搬移，缓存/临时文件仍D:\codex+。仅更新本技能本机配置和当前进程成果变量，不改原环境入口及原快照。

## 本批登记与资源

r14真实聊天分组与可借用公平策略需本轮用户授权后显式`bind-controller`及`configure-scheduler`，可直接接入已登记批次，不改冻结manifest/run/permit或原active。按真实session而非共享PID去重，每组最多3模型子任务；建设最多8，授权可另设2个已核返修余量（`bind-repair`核实际revise，仍build/ultra），普通审核/加急审核本次目标4/4。普通/priority10、建设/已核返修合格时轮转，空闲立即借位，先过滤满组/满stage及无效候选；跨组/批按实际准入轮转。未中返回的selected明确实际应接续票据。未启用仍使用以下旧策略；启用及回退仅约束后续acquire，媒体合同保持。请求和命令见 [真实聊天调度](scheduler-policy.md)。

仅用户明确调用/点名并确认的清单运行，已确认不逐案重问。一个Word默认一案，多材料合并须清单明确；锁文件、加密/损坏/旧doc不能静默跳过。冻结原basename、绝对/相对路径、大小、采集时间和SHA256，source副本哈希核验，原目录只读。新增工作区为`cases/YYYY-MM/案件名`（同名中文序号），点名旧案只在其独立revision继续。管理在新版`cases/.batches`、运行状态在各案`.product-v2`/`.runtime`，每案独立端口、浏览器、D盘临时目录。用户指定工作区优先。

共享上限保持8建设/返修、3普通独立审核、1受控证据、1明确加急。用户本次明确多开录制授权下，新批次CLI默认`--recording-limit auto`最高4路，也可显式2/3/4；旧manifest保持2路及旧worker规则。新批模型槽和媒体槽分开：实际宿主4模型槽含父，最多3模型子任务（还须扣其他使用者），同一父可直接启动4个Node录制进程；不虚增host_total_slots。`batch_control.py register --root 新版cases/.batches --batch-id 本批 --cases 已确认清单.json --authorization 本轮用户请求引用 --host-slots 4 --recording-limit auto`冻结manifest，之后config不热改。跨批全局4路、CPU/内存准入、旧active容量保护及launch前lease复查见 [并发录制](recording-concurrency.md)。清单每案含case_id/workspace/source_docx/source_sha256；父补原名/大小/时间及端口等实际字段。

`claim --pid 实际长期父PID`取得唯一负责人身份（PID+创建时间）。同批另一活跃父拒绝；旧父确实退出后，核对状态/源/收据再显式`recover-owner`，保留旧调用、用量、队列和孤儿阶段记录。此工具仅维护状态，不结束进程。临时命令Python PID不能冒充长期父PID。正在执行或正常排队均不重复派发。

`queue --case-id ID --stage build|review|record|evidence|expedited`返回token；`acquire --token TOKEN`按同优先级先到先得及上限授予，不能忙轮询；未授予时父继续其他可做工作并在资源释放后接续。`release-slot --token TOKEN`结束阶段释放；等待录制/验收不占建设槽，每案不能双占。批次必须使用分阶段录制：record槽内`record --phase capture`只连续录原片及操作事实，返回后在finally释放record，再queue/acquire evidence槽执行`record --phase evidence`完成编码、完整解码、5fps和全部交互帧。evidence排队时停止新增record，既有capture结束后证据按本阶段公平队列执行；任何live capture与重媒体evidence互斥，等待ticket不占active槽。成功、失败、取消均由父finally释放；失败原片和事实保留，修复后仅证据故障可重跑evidence，不盲目重录。旧不带phase的full调用仅兼容独立无并发运行，批次禁用它以免资源误算；旧manifest容量不热改，若还有旧record+evidence双持有任务则先等其结束释放，再接续新路由。repair用build资源但实际模型ultra。录制取得槽后再查实际健康身份和物理可用/Windows提交余量较低值，基线4096MB、每额外录制槽2048MB。不足只在新manifest登记前降为1录制，旧批等待释放确认闲置资源/合法恢复，不热改、不降模型。

`update --case-id ID --value 当前实际状态.json`记录phase、append-only calls/usage、pending、recording_pending和具体blocked_fingerprint，不重置计数。`delivered`须有当前final receipt，最终负责人仍逐案复核清单/当前hash，单案完成不能称整批完成。`priority --case-id ID --value 10`只改排队优先级；`expedite --case-id ID --authorization 真实当前批案授权JSON`核真实肯定user消息，明确“c1加急/指定本批加急”直接等于Astra低思考，不要求“原加急模式”口令；scope名须注册ID或唯一冻结案名，纯“这批”须真实单一当前批context。控制器设本案priority=10并更新waiting，未来queue(review)/waiting acquire自动解析有效route。加急独立Astra/low，不追加ultra；已active有效普通审核保留原模型，授权不跨批外溢。所有MODEL stage共享宿主位，较高priority的加急build/review也优先下一空位；只有源/预检/授权/owner及新review run身份均有效、自身stage有空位的候选才能让低priority任务等待，失活或blocked/drain不阻塞普通，同priority跨stage由父编排。新批review取得active槽后，父先`verify-review --case-id ID --token TOKEN --value 案件工作区`复查并取得不可变dispatch permit/nonce，再按返回模型实际spawn；当前spec/proof和真实JSONL须绑定同admission/permit/token/scope。旧manifest/历史proof兼容和详细顺序见 [加急审核路由](expedited-routing.md)。

`drain --authorization 用户明确暂停/维护请求`让当前阶段完成后停止新阶段，`continue`依原授权接续；不能为监控或改规则擅停正常批。`resume-case --value 本案新的恢复证据.json`仅当前批已登记case，绑定原blocked_fingerprint、新status=ready和实际recovery_evidence，不由旧ready自动解除。父仍存活则本父接续；已退出才recover-owner，不新建批次或丢调用。共享故障由唯一维护者修一次，单案故障不暂停其他案。

共享等待队列只由当前可运行票据参与阶段FIFO/priority和新录制的证据排空判断。已drain、案件blocked/delivered或无有效当前负责人的waiting票据保留原token、提交时间、优先级及恢复历史，不能阻塞其他批；continue或带真实证据的resume-case恢复后重新按原时间/优先级参与。所有active票据仍完整计入容量及record/evidence互斥，等待资格判断不释放活跃槽。`recover-owner`转交active原token与运行身份并追加owner历史，不能因旧父退出改为orphaned；新登记批次媒体由Windows Job覆盖Node/Chromium/FFmpeg子孙，释放必须核Job与原runtime退出，阶段入口必须核冻结工作区绑定及相应active token。详情见recording-concurrency.md；旧无Job恢复保留占用直到明确专属process_guard收尾证明，不热改旧manifest。

## 零模型预检与安全

首次部署/路径或工具变化：运行零模型doctor-equivalent，实际导入依赖、版本、登录有界（60秒）、隔离Chromium和临时Word→PDF→PNG。默认复用当前已验证准确venv和bundled依赖，不盲目安装。旧原`runtime_doctor.py`未接入自动新版流程，父可在新版隔离目录以已核对工具执行相同检查并保存真实命令/退出码/log/工具hash；不得把原CLI路径成功称sandbox可用。

每次真实派发前，父按已安装CLI帮助选择原workspace-write/read-only接口，执行零模型读写/读回/清理及只读/区外拒绝验证，最长90秒，保留stdout/stderr及同期sandbox日志；桌面/运行时保持存活。公共预检记录通过`preflight --value 真实环境证据.json`登记（status=ready、zero_model_calls=0、checks含workspace_write/read_only/browser/word_render，实际command/exit_code/log_sha256），模型槽拒绝缺记录/变更记录。公共通过不替代本案必要业务文件ReadWrite句柄和输出可写检查，不改原件/删除文件测试权限。

固定已验证官方CLI缺失不回退；node_repl如现存且绑定CLI才按原规则同路径绑定，不新建MCP。环境报错先保留实际命令、宿主绝对路径/版本/有效配置和原stdout/stderr，核准拒绝适用范围；os error32文件占用、sandbox初始化、tool policy、ACL、组织策略、依赖、编码、健康版本、内存分别记录。否定/不确定措辞不能仅关键词认定策略拒绝，也不能把不同宿主的配置混为一谈。真实sandbox、ACL、组织策略、tool policy或审批拒绝不换入口/命令/安全设置绕过，不改ACL/Deny/sandbox/审批，不反复每案付费重试。涉及其他有效任务的共享重启/中断维护先交用户决定，并保全进度/源/hash/调用/恢复入口。

worker blocked只阻断同故障重复付费，不代表整案永久不可制作；唯一负责人保留本案后续恢复任务，并接续全部授权清单中的可运行项。程序bug、缺依赖和普通路径/编码/venv/入口兼容问题在原安全模式及授权工作区内诊断修复；选错工具版本时，先核宿主和限制范围，确认不是安全拒绝后可恢复到既有已授权、已验证的准确运行时，不将普通本地配置当永久阻塞。可补输入/标定/权重/协议不是外部阻塞；源确实不可读、核心定义确实矛盾不可合理实现、账户/额度不可用或必要写入真实拒绝才保留外部限制。新恢复证据绑定原故障并实跑恢复，不只改状态。保留历史原判断与未读项。

服务启动前核准实际宿主绝对路径及有效配置、准确venv依赖/启动脚本/数据/端口和可恢复路径，hidden启动、记录launcher与listener。健康接口case/workspace/version（启动时冻结）、PID/创建时间/完整command/全部监听一致才复用；不得先停健康服务后试探已拒绝的启动。确需5.1时，中文脚本UTF-8 BOM、实际5.1及准确venv依赖验证，不能仅语法过；已核准其他宿主按其真实入口和配置实跑，不因版本选错改政策或Bypass。可恢复问题本案修复，媒体工具合法独立替代须来源/许可/hash并实际编码探测解码，不复制受限文件。进程收尾见processes.md。

## 受控证据、审查与优化

源完整读正文/表格/文本框/页眉页脚/OMML/DrawingML/VML/媒体/嵌入对象，登记raw/normalized公式、原符号/变量/单位/边界/来源/实施例/代码/测试/图的映射；节点数不等独立公式组。父在建设内一次列全合同/输入约束/说明数值/图文位置/切换问题，high自检先修，再渲染最终版。high提交前实际运行`contracts.chart_snapshot(workspace,Path(run['word']),run)`，核对图清单与Word当前字节、嵌图和图题绑定；labels只登记真实非空可见标签，不登记空轴标签或空字符串，缺项在建设内修齐并重核。这是既有自检中的便宜结构核验，不新增模型、审批或渲染，不替代逐图/全页视觉。

建设与同一次独立审查先按system-data.md从原定义核验适用的接受/拒绝边界及最终引擎派生结果，便宜的算法/API/持久化反例先于耗时视觉阅读。发现明确阻断可先给具体revise并如实保留未读项；pass仍须完整源保护、逐图/Word全页与视频证据，不新增调用或审批，未变且此前真实已阅的内容仍只按合法同hash继承。

最终全页render、源保留、MP4完整decode/5fps接触页/关键帧由父控制工具生成，建设者不能自签。原`controlled_evidence.py/build_preflight.py/review_check.py`未完整移植；等效路由为`contracts.py chart_snapshot`结构/保留校验+父在新版工作区调用已核准原`render_word.py`只生成新证据+`media_evidence.py`固定函数视频证据+本次短ID索引。不调用原caseflow，不写旧目录。Word首次所有页实际看；合法复验只继承同规则未被否定且未变、以前真实已阅的对应每页/图及证据，不整文档抽样。

父冻结request的短E001证据ID、路径/hash和必查集合；审核前后file_map一致才绑定；审核者返回短具体issues、逐图五项、实际reviewed_evidence、coverage/limitations及最终真实proofhash。父保留raw答复和规范绑定，不补已阅ID或改verdict。`revise`缺项仅advisory，保留missing项并定向ultra修复；环境`blocked`仅diagnostic，保留原错误/未读项，不派付费内容返修。旧blocked误用仅在完整已阅、全是具体普通内容缺陷、无环境错误/无blocker时保留原判定另标路由revise；pass全部严格覆盖、逐图五项及hash。可修复问题一次合并清单、ultra返修自检、独立复验直到通过，没有固定两次上限。reviewer不实现。

本案持续服务日志位于.runtime或按原runtime-streams有限模式登记；冻结测试/CSV/源/Word/hash不排除、不删log逃审。recording input显式覆盖真实页面共用逻辑/数据/可见PNG，启动版本固定；输入指纹失败保守recording_pending=true。文档专用变化只渲染受影响最终Word，视频输入未变不重录。合法零字节源码允许，必要成品非空。

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

父在新会话接续、阶段完成或相关文件确有变化后调用只读`proflow.py status --workspace 本案 [--plan 当前计划] [--evidence 明确已有proof]`，按现有收据继续尚未完成或依赖已改变的工作；同轮已有有效状态便沿用，不逐步重查或忙轮询，不反复向子会话询问同项完成状态。它不启动服务/媒体/模型、不打开图，也不重扫全部视频帧；同一请求的路径哈希只计算一次。状态区分capture已完成待evidence、technical_ready待首次独立视觉、已有最终独立验收记录、stale的具体依赖及unknown。已判断合格且依赖未变的内容保存后复用；源码/CSV/Word各自变化按收据依赖失效，Word独改、合法包说明变化或补测试日志不自动作废视频，视频仍由record-plan实际业务input_files绑定。只缺技术timeline或最终MP4且原capture未变则补evidence，不再次消费录制业务；有效原片/技术证据按record既有恢复逻辑复用。

status列出的proof/已阅ID只是原记录指针，不补签、不推定首次视觉已完成；只有既有完整final收据与当前成品/proof绑定未变才显示verified。已发布完整快照匹配后直接返回done，无需重新执行其他阶段。技术就绪明确只核receipt/video/timeline，并未逐核帧；最终finalize保持完整帧哈希及真实独立调用/视觉覆盖，若查出某部分失效只修补该部分。缺信息先定位unknown，不凭mtime缓存猜通过。技能维护任务只以本轮有界回归和独立技能验收完成，不自动接续旧测试案制作；正常案件完整交付不变。

建设初始输入一次给全本案材料、当前政策和必要证据索引，模型读角色相关条款；不重复加载未变原规范全文。总控用当前版本的合并问题、变更和短证据索引交接；建设/返修在本轮授权范围内连续完成范围与自检后一次返回，不为可自行完成的机械步骤逐项往返。被替代材料留历史，仅复现或合法继承需要时读取；不回传长源码、全日志或整份session_meta。使用controller_facts对指定会话增量取实际调用及用量，状态必须由当前案件收据和实际阶段推导，禁止每次同步重置building。最终调用验证仍核原日志，缓存不签通过。

high在原件盘点后先用最小业务对象和源定关键反例实跑最终函数/API，并验证当前部署入口、健康身份、必要持久化及停止/端口释放；通过后再做依赖的耗时图文、扩量与正式录制，不要求先完成全部后端，也不重做已有合格结果。建设与自检仍含图谱覆盖、标注避让、数据规模/专名、业务一致性和正常录制脚本。就绪检查通过直接进入受控录制；只有确有实现或录制计划问题才派ultra修复，不无条件为每案增设一次录制准备模型会话。失败问题一次合并返回；仅变化部分重算/重绘/重录，正常独立ultra完整检查不省。软件依赖、工具版本与字体未变可复用已验证环境，但每次派发的实际受限读写预检照旧。

独立ultra在同一次验收内先核原材料的关键约束、状态转换、当前代码与低成本复算/边界测试，再展开全部Word页及视频视觉检查。前项已发现必须重建的阻断问题时，合并当前已证实问题并如实给revise和未阅范围，不耗时看必将作废的视频，也不预签未阅项。修复后的最终pass仍需完整必查集合与全部规定视觉覆盖；这不是新阶段或额外模型调用。返修与复审首先读取问题定位、当前变更和绑定hash；仅继承曾真实完成且未被否定、依赖未变的审查，不再次把整份旧proof、原文和代码全部输出到上下文。
