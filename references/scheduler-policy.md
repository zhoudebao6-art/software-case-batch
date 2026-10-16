# 真实父运行时容量与动态共享公平调度

沿本次真实用户的新批/全自动化或优化授权，当前负责人可对已登记批次使用独立控制记录接入，无需另问调度同意；无需重新prepare、登记、录制或改冻结manifest。配置仅影响后续`acquire`，不修改原active token、提交/取得时间、owner、历史permit、run、review proof或媒体合同。没有显式配置时沿用已接受旧策略；`mode=legacy`受控回退也只限制后续准入，已运行任务继续完整计数并自行完成。

新授权的全自动批次标准接入为原流程`register/claim/preflight`、核实并`bind-controller`真实父聊天、随后`configure-scheduler`设置`{"mode":"verified-controller-adaptive-v2","capacity_scope":"verified-parent-runtime","aging_seconds":300}`。沿用本次真实用户的批次/全自动化授权引用，不再为动态调度追加询问；脚本仍不自行创建聊天或派发模型。已有批次也可在当前优化授权下按同一方式显式接入。未接入的历史配置与冻结清单保持兼容，不自动追改。

`adaptive-v2`的显式`capacity_scope=verified-parent-runtime`取消跨批合计、每批、组及stage的人为模型配额；每个有效绑定父只按最新已核平台developer运行时声明的workers限制预约，不叠加同父多批、不用12裁剪未来真实容量。例如两个独立真实父各12 workers，可分别预约12、合计24；同父两批合计仍最多12；真实20 workers时可预约20，真实3时仍最多3。其他父空闲不能增加本父真实能力，也不能借独立批名扩容。未知归属active保守扣每个候选组，并按旧容量取低值；缺证据/坏绑定不扩大不明容量。旧active超过当前真实上限时不抢停，仅阻止后续准入直至自然释放。实际模型服务可用性仍可能更低，预留不代表已派发。未有效绑定者沿用保守旧stage上限并把所有active视作可能同组。

兼容的`capacity_scope=global-model-pool`仍用总池`model_pool_capacity=12`（整数1–12），省略scope的历史adaptive-v2也默认此范围。它统一计所有active模型预约，并将各父容量裁到总池上限，保留原跨父选择与公平语义。新scope请求禁止同时填写model_pool_capacity，避免把无效值误当有效限额；已存的旧池字段仅作兼容审计，scope切换及回退均记录previous.capacity_scope，不改bindings、owner或原队列。

有效候选先通过既有owner、暂停、blocked/delivered、源、预检、授权、run、组容量及冷却过滤。新scope的acquire只选择请求批所属真实父的可运行候选及该父准入历史，独立父的闲置owner不会阻塞本父；同父跨批仍共享选择次序。先筛本父合格priority>=10候选，再按审核（普通/已授权加急）、返修、建设三路最近准入顺序轮转，首次相同条件优先审核、再返修。加急不受普通业务配额，但计入本父真实上限，不抢占active；普通类内部仍按三路/批最近服务轮转，同组同批同类候选达到`aging_seconds`后按原提交FIFO优先于新高priority。默认300秒，可配置整数1–3600秒，老化不改priority、不授加急、不换模型。新准入保存共享锁内递增`scheduler_turn`，重复或倒退时钟不破坏轮转，历史票据不补写。三路轮转界限仅在同一当前优先类持续合格、有空槽且被选owner实际取得时适用；持续急件可延后普通类，不承诺墙钟时间，不替其他owner代领。旧global范围维持原三路轮转及每路普通/priority>=10交替。

录制准备短修复没有独立revise绑定时，仍依据本案真实`repairing`阶段派ultra并参与返修轮转；其`work_kind`仍是`build`、不伪造repair绑定、不花额外返修预算。有绑定仍核原真实proof。`adaptive-v2`下保留配置中的`capacities`和`repair_extra_capacity`仅为兼容审计，固定配额及extra预算均不参与已绑定组准入；缺失/被改返修proof继续拒绝。模型路由保持high建设、ultra返修/普通审核、仅真实授权Astra加急。

完整及compact `status`展示有效scope和`global_model_hard_limit`；新scope的有效`model_pool_capacity`与`unreserved_global_model_slots`为null，表示没有人为全局模型上限，不能解释成实际无限能力。只读`scheduler_reservations`展示全局预约总数，`groups`按真实父去重展示`worker_ceiling/reserved_model_slots/unknown_active_slots/unreserved_model_slots`及可继续工作的batch；各父空位按本父真实上限扣预约计算，drain或全部blocked/delivered组空位为0，不含就绪门禁与外部模型服务能力。旧global范围的每父空位仍受全局余量限制。预约总数不等于实际运行数。`fixed_group_quotas=false`、`fixed_stage_quotas=false`描述业务配额；新票据`scheduler_admission`记录实际mode、capacity_scope、lane、aged及`repair_extra_budget_used=false`。未取得时`selected`带本父候选的真实token/batch/case/stage/owner/model/effort/lane，`action=selected_owner_acquire_then_dispatch`明确由该owner取得原票并启动；`requester_can_acquire=false`提示当前批不能代领。输出不代表已派发，也不跨owner修改状态。

先对每个真实父聊天`bind-controller`，再`configure-scheduler`。绑定JSON只提供`session_id`及该父实际`session_log`；工具从Codex sessions目录核session_meta、文件名及该聊天已成功执行的`batch_control.py --root/--batch-id/--pid`宿主完成记录，冻结对应行offset/size/hash。用户消息中的引用、任意组名、PID相同、不同批次名、伪ID、子代理日志均不能扩容。同session_id多批与复制绑定共享一组。adaptive真实容量只接受同父日志中平台注入的`role=developer`且metadata为`multi_agent.role_instructions`的`<multi_agent_role>`声明，按“总槽数减父占一槽”派生；JSON提供runtime/host容量拒绝。绑定冻结该证据片段；常规准入与只读status仅核有限offset/size/hash并重新解析真实声明，不全扫会话。平台容量或运行时变化后，原owner在派发前显式对同父执行bind-controller刷新；最新已验证刷新统一作用于同父各批，不改active。首次绑定与显式刷新允许扫描日志；真实派发异常仍沿现有capacity-defer保留模型并冷却。有效实时声明可替代冻结manifest中的历史宿主数，无需改历史清单；没有平台声明时保守用原worker_capacity与已知旧3取低值。4总槽父因此仍显示3，旧模式仍保持3兼容。缺失/已变绑定及旧未归属active保守扣容量，不推断另一个组；已有active归属另存控制记录，不能借重新绑定移往新组。

用户要求通过原生`create_thread`创建的独立聊天也可绑定；协作子代理仍不能充当批次父。首次绑定前，原owner在自己的聊天中单独执行一条成功的`batch_control.py claim`，使用实际Python及脚本绝对路径、字面量root/batch-id/pid，无重定向或条件包装；同owner重复claim幂等，不重登记。若已有合格命令证据则直接复用。这样保留严格证据解析，同时避免复杂脚本使真实调用无法被识别。

兼容模式：历史`legacy`全局默认建设/返修共享8、普通审核3、明确加急审核1；`verified-controller-fair-v1`可在`build<=8/review<=8/expedited<=4`内选择固定stage配额，并支持`repair_extra_capacity=0/1/2`。返修仍stage=build和独立ultra，不增加模型阶段：该旧模式的额外预算仅由`bind-repair`核实际独立revise的本案run/admission/permit、真实派发与child最终答复精确proof hash后取得；只填repairing/work_kind不能扩容。已核返修可借空闲建设预算，旧建设硬上限8；两者持续等待时轮转。未登记返修保留旧建设预算及ultra路由。旧兼容模式每真实组仍最多3；并非登记两批就倍增容量，更不代表已实跑8建设+2返修。录制/evidence在所有模式仍独立按冻结媒体容量、Windows Job身份、实际CPU/内存及互斥准入。

旧`fair-v1`先过滤owner、drain、blocked/delivered、源、零模型预检、真实加急授权、review run身份、组与固定stage已满。普通与priority>=10候选两边都合格时轮流授予（首次高priority先行）；只有一边合格时立即借用全部可用份额。每类内建设/已核返修轮转，再按同类同预算最近实际准入较早的组和批轮转，最后priority及原提交时间FIFO；满组/满stage队首不挡有空位的候选。所有公平模式未获准返回兼容`acquired=false`，父按`selected`推进已有票据，不继续盲等同案、不自动替别人占token。已active不抢占、不改排序。priority10建设可运行high；没有真实Astra授权仍不能取得expedited审核。

```powershell
# 当前进程先加载已安装环境；value文件放本轮授权控制目录，使用真实日志和实际父PID。
. 'D:\自动化2.0\software-case-batch-pro\Enter-Environment.ps1'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' bind-controller --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --value 'controller-binding-request.json' --authorization '本轮真实用户调度授权引用'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' bind-repair --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --case-id '实际需返修case_id' --value 'repair-request.json' --authorization '本轮真实用户返修扩容授权引用'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' configure-scheduler --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --value 'scheduler-request.json' --authorization '本轮真实用户调度授权引用'
```

绑定请求：`{"session_id":"实际父聊天UUID","session_log":"C:\\Users\\Administrator\\.codex\\sessions\\2026\\10\\15\\rollout-实际时间-实际父聊天UUID.jsonl"}`。返修请求：`{"case_id":"实际需返修case_id"}`，工具只从该案现有最新completed_revise与对应dispatched记录取真实证据，拒绝pass/被改proof/异run/冒名子日志；首次核验后冻结有限日志片段，后续不全扫会话。新授权批标准配置请求：`{"mode":"verified-controller-adaptive-v2","capacity_scope":"verified-parent-runtime","aging_seconds":300}`。旧global兼容请求：`{"mode":"verified-controller-adaptive-v2","model_pool_capacity":12,"aging_seconds":300}`。旧固定配额兼容请求：`{"mode":"verified-controller-fair-v1","capacities":{"build":8,"review":4,"expedited":4},"repair_extra_capacity":2}`。回退请求：`{"mode":"legacy"}`。`status`同时给出独立scheduler配置与追加的控制历史；被冻结批清单不改变。

安装时先逐哈希核验并就位新支持模块`scripts/scheduler_repair.py`和`scripts/scheduler_policy.py`，随后再切换消费它们的`scripts/batch_control.py`；最后才执行授权绑定和启用配置。此工具只维护调度事实，不改变CLI安全配置、不调用app-server改会话、不自动派模型、不自动接续其他批次。独立验收、备份安装及发布仍走原授权与验证门禁。
