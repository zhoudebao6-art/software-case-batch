# 加急优先与实际审核调用

加急只改变独立只读审核的模型和队列。建设及建设内自检仍 `gpt-6.1-sol/high`，返修及录制准备修复仍 `gpt-6.1-sol/ultra`；普通独立审核为 `gpt-6.1-sol/ultra`，当前批/案明确授权原加急模式后为 `gpt-6-astra/low`。Astra通过后不额外追加Sol ultra，Astra不建设、不实现返修。图文、系统、数据、视频与当前hash的完整验收范围不减。

用户的肯定授权必须来自真实父会话user消息，点名当前批/案，绑定当前run/workspace及消息hash。“原加急模式”不是必须口令；用户已定义加急就是Astra低思考，因此“c1加急”“加急c1”“modern 这批加急”等明确指定当前scope的肯定命令直接授权。单说快一点、支持加急吗、示例/材料引用/代码块、否定或条件句不选择Astra。授权JSON保留原字段：`run_id/workspace/session_log/user_message_sha256/statement/scope_name`。`scope_name`必须是当前注册case_id、batch_id、`batch_id/case_id`或登记时冻结的唯一案名映射；准备title和显式aliases只在本批唯一且不冒充其他案/批标识时纳入。两个案共享同title时必须用注册ID，改auth run/workspace不能把c1语句扩成c2或其他批；新批/案用户请求不自动外溢。批范围按冻结确认清单逐案登记，不扫描其他批/历史案件。授权文件或真实消息变更后，queue/acquire及付费前核验拒绝准入，保留票据和诊断，不静默回普通模型。

授权接受整条真实user消息中的单一简单肯定命令，或真实父会话的完整`<send_user_message_question_reply>`问答卡片中唯一匹配的完整`answer`。卡片沿用原授权字段：`statement`为精确答案，`user_message_sha256`仍为整个原始包装消息的hash，`session_log`仍指真实父JSONL；`questionItemId`必须绑定同文件此前真实`request_user_input_async`调用的题号和一致题目。题目文本不提供授权；多题只取唯一匹配答案，同一scope被其他答案重复提及、重复题号/键、嵌套包装、非字符串答案、包装外文字或缺真实提问均拒绝。此兼容只支持明确点名scope的命令，不扩展“这批加急”的卡片解释。不能先裁掉条件、材料或其他前文再取末句。“如果老板批准，c1加急”“材料：c1加急”及从多行消息单取“c1加急”都拒绝；卡片答案带条件、否定、示例或其他说明同样拒绝。同一共享root内不同案件工作区重复使用case_id或别名时，裸名称必须有此前真实、单一明确的“当前批次：batch_id”等当前批声明，否则直接用`batch_id/case_id`或batch_id指明范围。已有真实当前批上下文时，裸案名不能忽略它授权另一批；显式批限定命令可指明新范围。新合同验证结果同时绑定不可变workspace对应的root/batch/case/manifest身份，不能仅改run/workspace重套旧语句。旧manifest没有这些绑定能力，历史兼容不宣称新能力。

纯“这批加急”需要额外`scope_context:{root,batch_id,manifest_sha256,statement,user_message_sha256}`，绑定同一真实user JSONL中此前最近的当前批上下文及当前冻结manifest。上下文必须整条只有单一、明确的声明，如“当前批次：modern”（也可“当前批次 modern”“本次批次 modern”“现在处理批次 modern”）；不能只因文本提到modern就推断它是当前批。“当前批次other；modern不处理”等冲突、多条或引述上下文拒绝，要求直接点名批次。context元数据不能替代实际user消息；缺真实当前批关联时不猜批次。scope_context的batch_id必须等于本manifest batch_id，scope_name也必须是该batch_id，不能把代指批次套给单案别名。

`expedite`在同一控制事务把本案priority设为原设计的10，更新本案所有waiting票据的priority；waiting review改到expedited，保留token、submitted_ns及历史。未来`queue --stage review`自动解析本案当前授权，选择普通或加急route；waiting acquire再次核真实授权/path/hash、源与预检。active有效普通审核及其准入快照不重写、不打断，未来审核/复验采用新授权路线。calls/usage一直追加，不因切换、负责人恢复或重排归零。

旧legacy历史默认加急审核单槽、普通review3槽；所有MODEL stage（build/review/expedited）共享真实父聊天worker容量，媒体不占新profile模型位。历史未配置批次保留较高priority合格候选优先下一位的旧策略。旧r14/fair-v1经授权绑定真实session后，普通/priority>=10两边持续合格时交替（首次加急先行），空闲份额立即借用；组/批轮转，再按priority/原submitted_ns/token排序，满组/满stage不挡空组。旧fair-v1审核限额可独立配置（历史普通4、加急4），旧模式每真实聊天最多3子任务。r18新授权批次默认adaptive-v2，请求为`{"mode":"verified-controller-adaptive-v2","model_pool_capacity":12,"aging_seconds":300}`：总模型池理论上限12，无固定组或stage业务配额；建设、返修、普通及已授权加急审核按各父已验证runtime真实能力和实际就绪需求动态借用，同父多批共享且不能叠加扩容。当前runtime为4槽含父时实际最多3子任务，只是平台事实；后续真实runtime更新后原owner刷新同父绑定，可在12总池内增长。建设仍high、返修仍独立ultra；priority10建设不等于Astra授权。候选仍须当前owner有效、未drain、案件未blocked/delivered、源hash/零模型预检/真实授权有效，新review合同须当前prepared run_id/workspace有效并冻结admission。已有active建设或审核不抢占、不重写，冻结授权/dispatch permit门禁保持；录制、证据和媒体互斥合同保持。受控接入/回退及证明见 [真实聊天调度](scheduler-policy.md)。

新票在共享root持锁登记时分配严格递增的submitted_ns；宿主时钟同tick或倒退也不会把后提交票因随机UUID排到先票前。既有票、优先级调整、负责人恢复的submitted_ns保持原值。

新登记schema2 manifest增加`review_admission_contract=frozen-review-route-v1`，不热改历史manifest。普通或加急review取得active槽后，控制器在本批`review-admissions`独占新建不可变准入：当前case/run、token、source/preflight、实际route/model/effort、owner和授权快照。加急授权按原字节保存专属snapshot并核原hash；后续案件授权变更不回写已开始有效调用身份。此准入是资源/路线事实，不能称已付费调用或独立通过。

父实际派发审核前执行：

```powershell
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' verify-review --root '当前共享root' --batch-id '本批' --pid 12345 --case-id '本案ID' --token '已取得active审核token' --value '本案绝对工作区'
```

命令复核当前active owner/token、源/预检、冻结admission及当前加急原授权，独占生成本次dispatch permit和随机nonce。仅环境或模型配置不能代替核验。重复核验保持同permit，失败不释放active槽、不启动付费调用；负责人修复、等待或合法结束该阶段后再接续。原manifest没有不可变合同的调用仍返回明确`legacy_admission=true`，保留旧模式/旧proof兼容，不能称具有新合同的route-proof绑定能力。

父使用返回的model/effort，实际 `spawn_agent(fork_turns="none", model=返回model, reasoning_effort=返回effort, message=本案完整只读审核要求)`；message同时明文包括当前workspace、run_id、admission token和dispatch nonce。Astra使用 `gpt-6-astra/low`，不能等待普通ultra槽或追加ultra复核；模型不可调用则如实记录，不换模型或伪签。此脚本没有自动付费CLI或自动模型派发能力。

新合同的`.product-v2/model-dispatch.json`中 `stages.review`增加原样的`review_admission:{path,sha256}`及`review_dispatch_permit:{path,sha256}`；`review_mode`等于冻结admission的ordinary/original-expedited。独立review JSON也包含相同两项引用。final gate核本批真实已取得ticket、不可变hash、实际父JSONL call/output/model/effort/fork、message内token/nonce/run/workspace和实际reviewer最终proofhash；按当时取得的route核模型，不能按最终state加急字段逼旧ordinary调用改名成Astra。旧独立schema1 spec、旧manifest、历史收据按原兼容路径核验，不补写虚构新准入。

父在真实派发前保存attempt/pending标记，真实成功、失败和中断均追加calls/usage及实际session/call ID，继续使用原完整责任和恢复规则。queue/acquire/verify-review不自动计一次付费；不得删失败调用或重置累计计数。返修后下一次审核重新queue/acquire/verify-review并绑定新的token/permit，保留旧调用和历史快照。
