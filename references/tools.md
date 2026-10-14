# 工具和证据格式

加载 `Enter-Environment.ps1` 后，`$env:SCB_PRO_PYTHON` 是已配置 Python。下面 `工具目录` 均指本技能 scripts；`案件目录` 是用户点名的原案件工作区。工具不调用模型；父会话实际分派high建设、ultra返修，普通独立审核ultra，真实当前批/案原加急授权后的独立审核Astra/low；不能把配置或自检当成调用证明。

`batch_control.py bind-controller|bind-repair|configure-scheduler --root ... --batch-id ... --pid ... --value 请求JSON --authorization 本轮真实调度授权引用`对已登记批次独立保存真实聊天/返修绑定及策略，仅改变后续准入；返修请求含case_id，可同传--case-id校验。请求格式、真实session/revise证明、普通/加急借位、8建设+2已核返修、审核4/4与回退`mode=legacy`见 [真实聊天调度](scheduler-policy.md)。未中用selected接续明确已有票据。安装时两个支持模块先于消费入口就位；不重写manifest/run/review proof或原active。

## 准备、数据、源码

```powershell
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' prepare --workspace '案件目录' --output '成品新目录' --title '业务名称' --source-docx '原输入Word绝对路径.docx'
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' clean-data --workspace '案件目录' --manifest '重要CSV清单绝对路径'
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' check-data --workspace '案件目录'
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' pack-source --workspace '案件目录' --manifest '源码清单绝对路径'
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' scan --workspace '案件目录'
```

`--source-docx` 必须指向一个明确原输入，检查Word包并冻结绝对路径、SHA256和完整basename（含中文、括号等）；不扫描多个Word任意选择。run schema 2的 `word_name`、`word` 是动态交付路径。成品根目录只允许该basename和 `模拟系统`；系统内只允许 `项目源码.zip`、`演示视频.mp4`、`数据`，数据目录直接存重要CSV。源码ZIP也排除使用/运行/安装/部署说明、制作过程、原件解析及数据构造/来源说明，不放揭示模拟性质的文案；启动脚本和必要许可证保留。run 1及旧收据保留，不能原地升级。

清洗前须有本次 `process_guard.py stop` 的成功回执，清洗命令再次查询 OS，旧回执不能掩盖已重启后台。重要 CSV 清单（每项按本案实际替换，路径相对工作区）：

```json
{"files":[{"path":"data/operations.csv","name":"运行记录.csv","reason":"业务主记录及关键结果","primary_key":["对象编号","时间"],"min_rows":100000,"encoding":"utf-8-sig","delimiter":","}]}
```

脚本保留其他单元格和字段顺序，仅去指定元数据整列。输出 UTF-8 BOM。字段数不齐、空/重复列、主键缺失/重复、不足计划行数、禁词值或不安全路径使本次失败；不会静默删行补值。输入不变；事务暂存留在工作区，失败不发布部分数据。清洗前后的哈希和删列记录在 `.product-v2/data-cleaning.json`。主键去重检查用内存集合，百万级以上须按实际内存改用磁盘唯一性检查，不能为过门禁减规模。

数据一版达到充分规模、完成清洗并真实质量通过后，按完成成品复用。`check-data`、status、finalize及文档/包继承共同核实际CSV输出成员/完整字节hash和原`data-cleaning.quality`的data/expansion pass；后续代码、data-plan、检查器、解释器或原始input_csv变化不作废它，不重新审计、扩量、生成、清洗或补填新表。原input_sha256和plan_sha256仅保留首次制作事实，旧真实pass按当时的原形状直接复用，不升级或重写旧收据。

首次或未完成充分质量仍完整执行专名、字段、主外键、有效规模及扩容检查；成品CSV自身变更/缺失/损坏、原清洗/质量证据无效或已知明确数据错误才针对处理。具体已知错误可沿已有build-checks.json的`data_material_error`记录事实（没有则省略），不能清除标记来隐瞒未解决错误。原quality若带已有result_sha256，只用于核原证据完整性，不是独立验收签名；新完成不强制新增字段。只读验收不能暗写质量通过，首次实际check-data成功后才保存原质量事实。

status对已清洗但首次质量未完成的内容显示`cleaned`并建议check-data，充分质量及输出hash已齐显示`data_completed`；完成后不比较当前raw input或plan。当前软件算法/接口/持久化测试保留，用内部隔离输入和结果验证，不覆盖已完成CSV或以新plan强制重制；源码与Word按各自当前合同检查。这些完成事实不代签独立通过。

源码清单是需要交付的实际文件列表；不支持盲目打包全工作区。`exclude` 补充本案特有解析文件名/路径：

```json
{"files":["app/server.py","app/import_parser.py","web/index.html","web/app.js","requirements.txt","启动.ps1","app/.env.example","README.md","evidence/source_trace.json"],"exclude":["材料整理/**","*.analysis.json"]}
```

示例中 README 和 evidence 项会自动排除并记录。`import_parser.py` 是业务模块则保留；针对技术 Word 的解析、抽取、映射文件需逐项核实排除。排除所有层级的 README 名称、原技术文档、过程证据、缓存、依赖、日志、数据库和凭据。不要交付依赖本地状态库的压缩包：通过成品外部 CSV 和初始化脚本恢复运行。额外必需资源按白名单明确加入，许可证按原要求保留；`.env.example` 只能放无真实密钥的配置范例。

所有写入均拒绝覆盖已有同名产物。自检失败后，确认仍为未完成草稿，用下列命令把指定旧草稿保全到原工作区，再重新生成；原输入、旧稿与哈希保留。已经 `finalize` 的交付不能这样改，应建立新案件修订工作区与新成品目录。

```powershell
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' preserve-draft --workspace '案件目录' --artifact data
# artifact 可选 data/source/video；只移动确定的本次草稿，不清空目录。
```

## 录制和进程

```powershell
& $env:SCB_PRO_PYTHON '工具目录\process_guard.py' register --workspace '案件目录' --pid 12345
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' record --workspace '案件目录' --plan '录制计划绝对路径' --phase capture
# 父finally释放record槽；其余live capture结束后，取得evidence单槽。
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' record --workspace '案件目录' --phase evidence
& $env:SCB_PRO_PYTHON '工具目录\process_guard.py' inspect --workspace '案件目录'
& $env:SCB_PRO_PYTHON '工具目录\process_guard.py' stop --workspace '案件目录'
```

新批次默认auto最高4路，显式2/3/4和旧批兼容见 [并发录制](recording-concurrency.md)。新批次capture/evidence均须加`--batch-root 调度root --batch-id 本批 --case-id 本案 --media-token 已取得当前阶段active槽token --owner-pid 真实长期父PID`；原`--record-token`是兼容别名，但token必须属于当前phase。`proflow.py`原样传到录制器；启动前核冻结工作区绑定、阶段互斥和Windows Job身份，capture另重新核资源。省略/部分lease、其他阶段token或批次full调用拒绝。

PID 必须来自本次实际启动，每个专属进程逐项登记；录制器自身浏览器由它关闭。健康服务身份另按本案健康接口核实，不能只看端口可连。录制计划格式：

无phase的旧full入口保留独立串行兼容，批次必须使用以上两阶段。capture不产成功成片或受控证据；evidence可恢复同capture的失败生成，不能用失败原片/旧证据通过finalize。重媒体与live capture互斥的队列/失败释放见execution.md。

父建立完整必查文件清单后，用`evidence_index.py create --workspace 案件目录 --manifest 必查清单.json --index 新内部索引.json`机械收集短ID/hash，再用`review-input --workspace 案件目录 --index 新内部索引.json --output 新内部事实.json`绑定当前产物、图与timeline。事实文件不含decision、已阅ID或审查者签名，不替代finalize的fresh检查；独立审查者读完整必查集合后写自己的review JSON。

新案直接使用 [录制计划](recording.md) 的 `flow-complete-v1` 格式；历史无版本run才沿用原定时计划。这里不另复制秒数模板。

健康接口返回实际 `run_id`（run.json）、`workspace`（案件绝对目录）、`version`（启动时冻结，匹配计划）与 `pid`（实际监听进程）。录制前后与当前 OS 和登记记录核对；Windows venv 的启动器和实际监听子进程可能不同，两者都要登记。选择器和操作必须来自本案实际界面；无需为了符合示例命名修改业务。此计划只是格式示例，不能把“已保存”文本当持久化验证。当前录制工具支持同一浏览器页内操作；需要弹窗或新标签业务时先扩展工具和相应测试，不悄悄改成假流程。不能自动把不足一分钟的内容补长。

## 接续状态与建设证据

status仅在新会话接续、阶段完成或实际依赖变化后用于决策，同轮有效状态直接沿用，不把状态查询变成忙轮询。`next_actions`按现有依赖给当前可执行建议；`remaining_stages`只列未齐项。capture/evidence先于在线工作结束后的cleanup，再清洗数据/打包；源码与最终ZIP启动的六类当前事实未齐，不直接建议独立完整验收。查询不证明当前OS后台状态，cleanup记录只显示last_completed，后续既有工具仍按真实身份保护。只缺MP4且原capture未变推荐evidence；存在变动MP4先保留旧draft，原capture不明或capturing时先定位状态，不盲目重复业务动作。

`proflow.py status --workspace 案件目录 [--plan 本案计划] [--evidence 已有独立proof]`只读汇总现有收据与下一步，不执行阶段或新增台账。`technical_ready`表示录制和技术证据已有绑定记录，尚未finalized时独立视觉仍为pending；核验范围只含video/receipt/timeline，帧文件本次不重核。输出unknown/stale不能当失败视频自动重录，先处理指明依赖；只有缺失或改变的技术timeline走evidence，未完成录制的实际输入变化仍按原恢复规则处理；已合格视频后续一般软件/数据变化不触发capture。published成品及final/proof/publication绑定相同返回空next_actions。proof指针保留原reviewed_evidence值，不追加已阅ID或独立签字。

合格视频只完成一次。`.product-v2/recording.json`成功且成片、原controlled-video/timeline和真实操作收据仍同hash时，后续软件、数据、参数、一般文案或细节改变不再按recording.input_files或plan hash使视频失效；无需逐项差异清单、原字节快照、recording-reuse.json或新增审核确认字段。status显示video_completed并只列尚缺工作，finalize与继承修订共用完成媒体核验，原收据不改。不重复录制、编码、完整解码或重看此前真实已阅且未被否定的完整视频。

首次视频仍须按原完整质量和真实性合同实际检查一次；技术就绪不等于首次独立视觉已通过。原成片/技术证据缺失、hash改变或真实失败仍拒绝，不凭完成文字假通过，只补必要证据。只有系统主体/主要操作路径重大改变或视频本身有实质问题才重新处理视频；建设在现有build-checks.json以非空`video_material_change`记录这一具体重大变化或问题（未发生则省略），不另造台账或模型阶段。完成必要新视频及检查后更新该事实，旧片和旧收据留历史，禁止把标记清空掩盖未解决问题。尚只有capture、未形成合格成片时仍按原输入严格恢复evidence。

当前源码包、数据、Word、六类运行检查和原技术对应继续独立按各自当前hash/真实证据验收；旧片只证明其实际展示的合格流程，不作为当前算法/参数/数据正确性证明。小细节或数据不同不构成重录理由，也不在同一次独立验收之外新增视频复核会话。旧run无需补写新字段或重复确认。

新完整`prepare`冻结`construction_check_policy_version=dependency-bound-v1`；无该字段的旧run保持历史合同，未知值拒绝，文档/包继承修订不补写历史政策。建设沿`.product-v2/build-checks.json`保存`run_id/source_docx_sha256/implementation_hashes/checks`，checks对象至少有`algorithm/api/persistence/browser/build`五类；其他数据事实可保留。每类使用现有`command/exit_code/log/sha256`，另加非空`input_files:{工作区相对文件:SHA256}`和`test_files:[本项实际测试脚本及固定夹具路径]`；test_files均须在input_files中。动态DB、当前业务操作/持续日志不是不可变输入，以测试中准备的固定输入和实际结果日志留证。

implementation_hashes完整对应source-manifest打包有效成员；五类依赖并集覆盖它们及record-plan.input_files，单类依赖由实际代码调用范围决定，不机械要求五类都绑定全部项目。未变项保留原日志和依赖快照，变更共享依赖使引用该依赖的项失效；新增/删除源码成员或漏覆盖录制输入拒绝。独立审查仍核依赖范围和业务含义，不以hash门禁替代真实边界测试。`proflow.py check-build --workspace 本案 [--plan 当前计划]`只读机械核验，不执行业务命令、不写ready或pass。Node --check-ready及直接capture/full共用此函数，evidence和finalize也重核当前gate；录制保存当时gate来源但新补测试日志不要求旧新gate整字节相同，视频按实际plan/input_files绑定，finalize完整门禁不减。

## 最终验证

准备验收材料反复出现格式错误或手工列举大量文件时，可先运行`review_packet.py check --workspace 本案 --execution 六类实际执行事实.json --index 已有完整证据索引.json`，在派发前得到明确的缺失/陈旧/格式问题。`draft`加`--output 本案/.product-v2/review-inputs/全新目录名`生成中性事实和空白审查草稿；保留既有E编号，不覆盖旧proof，不填已阅或通过。没有完整索引时可提供`--manifest 补充必查文件清单.json`辅助收集当前收据引用；自动发现不保证覆盖全部原文、Word页或业务语义，负责人仍核必查集合。已有合格输入不为升级重做此步。

新版默认正式根`D:\研发图表\批次\案件`；`prepare --output`仍必须显式提供，默认路线的私有候选为`D:\研发图表\.staging\本批-本案-唯一版本`，与正式根同卷。`local.config.json.output_root`和当前进程`SCB_PRO_OUTPUT_ROOT/SCB_OUTPUT_ROOT`明确该默认根，不静默改变显式输出路径。用户明确其他目录优先；工作区方案采用`总工作区/成品/...`，每案执行目录为`总工作区/cases/...`，两者隔离。旧成果和冻结原规范中的D路径保留历史，不自动迁移。

`.product-v2/chart-manifest.json`仅在工作区，记录新增图的依据、设计与不同PNG：

新`prepare`及文档修订冻结`run.chart_policy="analytical-v2"`：通常4—6张有效分析图，允许更多；1—2张黑白结果图，专业分析图占多数。每图建设自检绑定实际PNG和Word宽度，存在标注碰撞不得提交。旧analytical-v1继续原合同，未标policy的旧run继续旧2—6，包修订继承父policy，未知policy拒绝，旧run/收据不重写。

在同一个图manifest中说明每图问题/数据/图型/真实标签，完工补当前PNG hash及build_selfcheck，不新造计划台账。`labels`从绘图对象提取必要可见文本，覆盖轴/图例/矩阵行列/色标及短标记，无需人工抄全部自动数字刻度。

```json
{"figures":[
  {"figure_id":3,"png":"evidence/新增图3.png","sha256":"当前PNG的64位SHA256","caption":"图3 候选动作资格与投影偏差矩阵","title_policy":"none","question":"哪些较近候选被约束排除，何者最终采用","data_source":"本案实施例的有限候选、当前约束与原式计算；实际源位置及计算记录保存在工作区","chart_type":"离散资格矩阵与连续偏差矩阵","labels":["首动作","可行 / 排除","投影偏差","采用"]}
]}
```

以上片段只表示一张图的语义字段，不是完整可提交manifest；还须按文末建设自检字段绑定当前PNG，满足全案有效图覆盖。实际caption/labels/单位和源位置必须来自本案。新policy的`question/data_source/chart_type`为非空文本，`labels`为非空字符串数组；caption与labels禁“示意”。图号延续原文并递增，新增图不放顶部整体标题/表头/图N/长解释，必要轴/矩阵行列标签/色标/短图例保留。脚本检查PNG签名/hash、图下精确caption、独立“请参考图N”、实际drawing嵌入同字节PNG和原正文/原媒体保留。`title_policy`及labels声明不替代真实看图；用既有计算记录或manifest保留源锚点、原式、前后文和解释依据供独立审核。

父会话实际调用如下工具阶段（不是PowerShell或自动caseflow命令）：

若桌面原始日志将 `spawn_agent.message` 保存为加密串，沿用 [真实派发证据兼容](dispatch-evidence.md)：工具只提取冻结permit和实际call的绑定事实，由真实独立验收者在当前proof和自身final中确认。不要解密、伪造明文日志或让父代签；旧明文合同保持原校验。

```text
spawn_agent(task_name="本案建设", fork_turns="none", model="gpt-6.1-sol", reasoning_effort="high", message="本案材料和完整建设/自检要求")
spawn_agent(task_name="本案返修", fork_turns="none", model="gpt-6.1-sol", reasoning_effort="ultra", message="本案全部具体问题定向修复和自检；不代独立审查")
spawn_agent(task_name="本案独立验收", fork_turns="none", model="gpt-6.1-sol", reasoning_effort="ultra", message="只读当前产物和证据，独立写review.json，不修改产物；final输出精确验收JSON SHA256")
```

保存 `.product-v2/model-dispatch.json`，schema 1：

```json
{
  "schema_version":1,
  "stages":{
    "build":{"session_log":"C:/Users/Administrator/.codex/sessions/.../父会话.jsonl","call_id":"实际建设call_id","agent_id":"/root/实际建设task_name","artifact_hashes":{"原名.docx":"SHA256","模拟系统/项目源码.zip":"SHA256","模拟系统/演示视频.mp4":"SHA256","模拟系统/数据/记录.csv":"SHA256"},"chart_snapshot":{"chart_policy":"analytical-v2","manifest_sha256":"SHA256","figures":{"3":"PNG_SHA256","4":"PNG_SHA256"}}},
    "review":{"session_log":"C:/Users/Administrator/.codex/sessions/.../父会话.jsonl","call_id":"实际独立验收call_id","agent_id":"/root/实际独立验收task_name","review_session_log":"C:/Users/Administrator/.codex/sessions/.../验收子会话.jsonl","artifact_hashes":{"原名.docx":"SHA256","模拟系统/项目源码.zip":"SHA256","模拟系统/演示视频.mp4":"SHA256","模拟系统/数据/记录.csv":"SHA256"},"chart_snapshot":{"chart_policy":"analytical-v2","manifest_sha256":"SHA256","figures":{"3":"PNG_SHA256","4":"PNG_SHA256"}}}
  }
}
```

`artifact_hashes`是完成该阶段时交付相对路径→hash，`chart_snapshot`取当前工具计算的完整对象；新policy包含上述`chart_policy`，未标旧run保持原shape不加键，不手拼快照。存在返修时`stages`增加按连续顺序`repair-1`、`repair-2`等，每条真实派发均sol/ultra，与建设/独立review不同身份，保留原high建设时快照；最终返修及review须绑定全部当前hash。不能将建设改名返修或让reviewer写实现。`agent_id`为真实canonical task_name。原session JSONL核实际call/output/model/effort/fork，摘要/配置/伪日志不能替代。CLI自动调度未移植；父显式dispatch及批次资源工具提供路由，不能支持目标时保持未验收。

`.product-v2/data-provenance.json` 保留 `nature`（真实数据性质）、`sources`（实际入口/检索失败/许可/下载哈希和适配记录）和 `validation`（规模、边界、主外键及分布验证）；不放进交付目录或源码包。没有成功下载时 `sources` 如实写尝试与限制，不能伪造取得。

建设者保存六类实际执行材料，独立ultra核验后写最后验收JSON：`checks` 恰含 `algorithm/api/persistence/browser/build/package_startup` 六类，每项含实际 `command`、`exit_code`、相对工作区的 `log` 和该日志 `sha256`。`package_startup` 必须从最终 ZIP 解压的新目录执行。另含 `source_zip_sha256`、`video_timeline_sha256`（父控完整5fps timeline）、`reviewed_files`（与scan全部成品路径→hash一致）、`visual_notes`（完整Word页/PNG/全部视频接触页、首尾及操作关键帧，区分实际打开和合法继承）、非空 `limitations`、`reviewer_agent_id`、`decision:"pass"`和chart_snapshot。父短证据索引通过evidence_index.py核实际已阅ID，不自动补签。建设者只提供事实，不写独立decision/pass。

验收JSON的`chart_reviews`覆盖每个当前图，每项含`figure_id`、当前`png_sha256`、`no_title_header:true`及具体`no_title_header_evidence`，沿用`meaning/data/legibility/layout/explanation`五项，每项有`passed`和`evidence`。`analytical-v1/v2`还含`no_schematic:true`及非空`no_schematic_evidence`，说明已实际查看新增图与新图题无“示意”；原图原文不适用该禁词。五项及无标题项证据均为非空具体文本：meaning说明相对原图新增价值，explanation记录实际实施例位置、前文—红字—后文衔接、解释深度、原式关键符号首次简释（有原式才查）和Word页。沿同一review写实际证据，不另设上下文台账。没有实际查看或存在问题不能填true/pass，建设者不代独立验收签字。

独立ultra写完不可再改的验收JSON后，其**最终消息仅输出这个JSON对象**（SHA256实际读取文件计算）：

```json
{"reviewer_agent_id":"/root/实际独立验收task_name","review_evidence_sha256":"最终验收JSON实际SHA256"}
```

门禁从 `review_session_log` 验证真实 `session_meta.source.subagent.thread_spawn.agent_path` 和 `turn_context.model/effort`，并读取真实assistant final的上述精确hash。若系统Memory政策要求末尾引用，允许精确JSON后附一个标准 `oai-mem-citation` 块；除此之外不从任意文字抽取JSON或使用中间答复。建设者代写验收文件、借用调用ID或验收后变更JSON不能通过。独立审查者可写自己的review JSON，产物与其他证据只读。未能完成视觉或业务核查返回具体问题/未完成状态，不给通过hash。

```powershell
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' finalize --workspace '案件目录' --evidence '本案真实验收JSON路径'
```

脚本检查目录合同、内部图/Word嵌入图与caption、CSV和ZIP当前哈希、录屏时长及不变输入、完整5fps timeline及原帧/contact映射hash、六类测试日志、扫描、当前后台退出、真实high建设/ultra返修/独立ultra调用和final答复绑定。它不自行判定图像审美、科研有效性或日志业务含义，不创建独立通过。成功收据位于工作区`.product-v2/final-receipt.json`，已有拒绝重写。进程只读命令中出现case路径不算后台。

## 原子发布候选

最终candidate验收后，父使用`proflow.py publish --workspace '当前工作区' --destination 'D:\研发图表\正式本批\本案'`。门禁冻结publish-intent、再次逐文件核hash与本案后台停止、仅同卷新目标整体原子rename；新run路径更新与独立publish-receipt保存，原final receipt/独立review不改。intent保留便于崩溃后原命令恢复，不删除旧目标、不合并、不重签。未发布verified-candidate不可作下一修订父案；已publish的新schema父验证当前publish receipt，旧历史complete维持原兼容。

## 原显式加急条件路由

默认普通独立审核sol/ultra。真实user明确指定当前案/批“加急”即选择 `original-expedited` 和实际Astra/low，不要求固定“原加急模式”口令；授权格式保留`{run_id,workspace,session_log,user_message_sha256,statement,scope_name}`，scope名必须为注册ID/唯一冻结名称，纯“这批加急”另须同实际user JSONL单一当前批标识的scope_context（绑定root/batch/manifest hash）。真实肯定消息及hash逐次核，快一点/支持吗/条件/示例/材料引用/否定不授权。`batch_control expedite`设全案waiting priority10；build/review争同共享宿主位时较高priority且可获本stage槽的候选先做，inactive/损坏run/invalid source/auth/preflight不阻塞普通。未来queue(review)/acquire自动按有效授权路由，已active普通审核保留原模型。新登记批次冻结review admission，父实际派发前`verify-review`取得不可变permit/nonce，实际spawn message、stages.review及review proof绑定同token/run/workspace与两项path/hash；final gate按取得的route核实际JSONL和proofhash，不依据最终state回写旧模型。详情与完整父调用次序见 [加急审核路由](expedited-routing.md)。建设high/返修ultra、不追加ultra复核、不跨批外溢和完整质量要求保持。

## 已有完整成果的文档局部修订

只有用户明确点名已有完整成果的Word/图文局部修订且旧软件未变时，另建revision工作区和成品目录，最终仍交付原名Word及继承的源码ZIP、CSV和视频全套成品。`--revision-of`指向已实际发布的finalized工作区，冻结旧收据与全系统hash；旧run/旧收据不变。

```powershell
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' prepare --workspace '新修订工作区' --output '新修订成品目录' --title '业务名称' --source-docx '原输入Word绝对路径.docx' --revision-of '旧工作区'
# 若用户授权的新草稿成品已经存在，Word及系统目录精确符合合同，且全部系统字节与旧交付一致，可加 --adopt-draft；不会覆盖文件。
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' finalize-document-revision --workspace '新修订工作区' --evidence '独立ultra写的修订review.json'
```

原六类执行检查、ZIP启动检查、录制及输入hash、CSV输入及输出hash、数据性质/出处、旧后台退出均从未变旧工作区与旧收据重核。新工作区也须有真实process_guard stop收尾记录；不为创建记录启动新软件。新验收JSON保存当前 `reviewed_files/visual_notes/limitations/reviewer_agent_id/decision/chart_snapshot/chart_reviews`，新的high建设与ultra独立验收记录仅证明本次文档修订，不能伪称旧软件按新模型重建。新收据标 `scope:document-revision`、`inherited_system` 与 `inherited_checks`。系统任何字节或旧证据有变化都拒绝继承，改走完整建设检查；未变不强制重建、重录。旧版本仍保持其历史执行身份。

## 源码说明专用修订

仅用户明确授权删ZIP说明/非必要制作用语且业务代码未变使用此入口，不能作为业务bug返修捷径。新工作区和新成品；`--revision-of`指向最近finalized Word或包revision，而不是全盘扫描猜旧case。

```powershell
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' prepare --workspace '新包修订工作区' --output '新成品目录' --title '业务名称' --source-docx '原输入Word.docx' --revision-of '最近finalized工作区' --revision-scope package
# 已授权草稿精确符合结构可--adopt-draft；父输出含未登记用户文件时仅本次包修订可显式--allow-untracked-base。
& $env:SCB_PRO_PYTHON '工具目录\proflow.py' finalize-package-revision --workspace '新包修订工作区' --evidence '独立ultra本次review.json'
```

`--allow-untracked-base`只在package prepare有效：父receipt登记每个文件逐项核hash，拒绝登记文件变动与链接；只按receipt白名单复制。额外Office owner临时文件/用户说明等分别记录`untracked_base_files`与hash，原位保留、不复制、不删除；finalize普通严格目录门禁不忽略杂物。最终新目录仍exact原名Word+模拟系统三项。

门禁沿显式`revision_of/inherited_system`验证每代receipt/proofhash与登记产物、原源文件、原六类测试日志、源码、录制依赖、CSV输入输出和出处，不扫描其他case。当前Word/视频/每CSV与最近父登记文件每字节相同，chart_snapshot包含manifest与PNG也相同；以前真实全页/逐图阅读合法继承并在coverage区别说明，不重新渲染/录制。

ZIP差异只允许移除明确排除的说明文档；业务members不得新增、删除或改变一个字节。许可证/NOTICE如需删非必要构造说明，保留原首段完整作者/题名/发布者/入口/DOI/许可及URL，并保留modified/Changes指示；独立审核确认法律必要内容和语义，不把LICENSES整文件豁免制作用语。真正业务修正改走完整run+ultra返修。

新review具有当前`reviewed_files/chart_snapshot/chart_reviews/visual_notes/limitations/reviewer_agent_id/decision`及`checks`恰一项`package_startup`（实际command/exit_code/log/sha256）、`source_zip_sha256`。`inherited_evidence_chain`按最近父至原完整case列`[{workspace,receipt_sha256,proof_sha256}]`，与受控解析结果精确相同；同时`video_timeline`相对新工作区和`video_timeline_sha256`绑定同hash视频的完整5fps/关键帧证据。新ZIP必须实际新目录解压启动与核心业务验证，不能沿用旧package_startup。当前model-dispatch仍真实high建设/独立ultra，原软件历史执行身份不重写。新receipt标scope=package-revision及inherited_checks/new checks，旧receipt不改。

## 本机与发布

`local.config.json` 仅保存本机运行时路径和配置；不提交仓库、不携带凭据。

`software-case-batch-pro` 是完整技能；原名 `software-case-batch` 作为名称兼容入口时，必须完整读取 pro 及其要求的引用，共享同一交付合同，不维护或回退旧十秒/两页流程。

本机安装按 `SKILL.md` 的用户授权、当前版本独立验收与逐哈希核验备份要求执行。外部发布按当前用户明确指定的目标及当前文件、版本哈希证据执行，实际状态记录在当次发布证据中；历史 HEAD、仓库地址或已完成/未完成事实不作为通用规则。

## r10建设检查与数据

新图manifest每图增加`analysis_role: baseline_result|professional_analysis`、`palette: monochrome|color`和`build_selfcheck`。后者使用figure_preflight返回的`geometry_status/collisions/png_sha256/final_width_mm`，并附`visual_review:{inspected:true,png_sha256,final_width_mm,evidence}`，evidence为high实际查看当前图的具体结果，不能由脚本生成视觉pass。已知collision必须修正；无法自动判断仍需实际目视。

已有原件统计结果可在同一manifest的`retained_results`登记`figure_id/source_member/sha256/analysis_role=baseline_result/palette=monochrome/result_reason/visual_review`，必须绑定原件实际图号和媒体字节。它不重新插图，不冒充新增图；独立proof的`retained_result_reviews`逐项写`figure_id/png_sha256/is_statistical_result/monochrome/evidence`。原流程图不能计数。

新完整run冻结`recording_policy_version=flow-complete-v1`及`data_policy_version=neutral-expanded-v1`；文档/包修订继承父系统政策，不强迫历史视频重录。录制计划和校验详见recording.md；数据检查使用data_preflight，详见system-data.md。周归档详见archive.md。

## 原生公式红字的PDF兼容渲染

已验证的本机LibreOffice/Poppler可由公共入口调用，不依赖历史案件的私有控制目录：

```powershell
& $env:SCB_PRO_PYTHON '工具目录\render_native_math.py' --source '当前最终Word绝对路径.docx' --source-sha256 '当前实际SHA256' --output '新的逐页渲染绝对目录' --office-dir '已验证LibreOffice的program绝对目录' --pdftoppm '已验证pdftoppm.exe绝对路径' --worker-sha256 '同目录native_math_worker.py实际SHA256'
```

入口默认使用同目录`native_math_worker.py`；显式更换worker必须给对应hash。仅在独立profile与本次Popen的PID、创建时间、进程树和loopback listener归属吻合后连接UNO，worker连接及终止前再次核对归属，收尾只处理身份未变的自有Office。原Word与worker受保护只读，影子Word逐hash相同；整对象明确`FF0000`的OMML仅在PDF导出时给原生Formula加颜色包裹，正文不改、不保存Word。混色、对象数/公式正文不符、hash改变或外来listener均拒绝，失败保留日志和影子副本。实际PDF、逐页PNG及生命周期事实在输出`controlled-render.json`，视觉状态保持待实际查看；这条兼容路径不证明Word/WPS GUI显示或业务验收通过。
