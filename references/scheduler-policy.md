# 真实聊天容量与动态共享公平调度（r18）

沿本次真实用户的新批/全自动化或优化授权，当前负责人可对已登记批次使用独立控制记录接入，无需另问调度同意；无需重新prepare、登记、录制或改冻结manifest。配置仅影响后续`acquire`，不修改原active token、提交/取得时间、owner、历史permit、run、review proof或媒体合同。没有显式配置时沿用已接受旧策略；`mode=legacy`受控回退也只限制后续准入，已运行任务继续完整计数并自行完成。

新授权的全自动批次标准接入为原流程`register/claim/preflight`、核实并`bind-controller`真实父聊天、随后`configure-scheduler`设置`{"mode":"verified-controller-adaptive-v2","aging_seconds":300}`。沿用本次真实用户的批次/全自动化授权引用，不再为默认动态调度追加询问；脚本仍不自行创建聊天或派发模型。已有批次也可在当前优化授权下按同一方式显式接入。未接入的历史配置与冻结清单保持兼容，不自动追改。

`adaptive-v2`仅让有效绑定的真实父组共享本组实际空闲模型预留槽，不再分别固定建设8、普通审核4或加急审核4等stage配额。每组最多3模型子任务，冻结worker_capacity更低时取更低值；同一真实父的所有批次共用这些槽。两真实组审核可借满6个预留槽，建设或返修同理；三真实组理论最多9个预留槽。不存在从停用/完成组借来的额外槽，也不通过求和重复binding为其他组提供容量。未知归属active保守扣每个候选组，全部旧active继续计数。实际模型服务可用性和父聊天的实际空闲子任务仍可能更低，不能将预留上限称已实际派发并发或无限并发。未有效绑定者沿用保守旧stage上限并把所有active视作可能同组。

有效候选先通过既有owner、暂停、blocked/delivered、源、预检、授权、run、组容量及冷却过滤，然后按审核（普通/已授权加急）、返修、建设三路最近准入顺序轮转；首次相同条件优先审核、再返修。三路持续合格时每路最多等待另外两次成功模型准入，建设不会因审核持续到来而饿死。每路内仍交替普通与priority>=10候选，再按真实组/批最近服务轮转；同组同批同类候选等待达到`aging_seconds`后按原提交FIFO优先于新高priority。默认300秒，可配置整数1–3600秒，老化不改priority、不授加急、不换模型。新准入保存共享锁内递增`scheduler_turn`，重复或倒退时钟不破坏轮转，历史票据不补写。这里的等待界限是有空槽、候选持续合格且被选owner实际取得时的成功准入次数，不是墙钟承诺；不抢停active，不替未启动的owner代领。

录制准备短修复没有独立revise绑定时，仍依据本案真实`repairing`阶段派ultra并参与返修轮转；其`work_kind`仍是`build`、不伪造repair绑定、不花额外返修预算。有绑定仍核原真实proof。`adaptive-v2`下保留配置中的`capacities`和`repair_extra_capacity`仅为兼容审计，固定配额及extra预算均不参与已绑定组准入；缺失/被改返修proof继续拒绝。模型路由保持high建设、ultra返修/普通审核、仅真实授权Astra加急。

`status.scheduler_runtime_policy`展示`fixed_stage_quotas=false`、每父最多3、三路与老化参数及预留范围；只读`scheduler_reservations.groups`按真实group去重展示`worker_ceiling/reserved_model_slots/unknown_active_slots/unreserved_model_slots`及可继续工作的batch，drain或全部blocked/delivered的组可用槽为0。该计数只是本地空闲预留，不含源/预检等就绪门禁与外部模型服务容量，未知active在各组重复扣减时不能再把组计数当全局任务数相加。新票据`scheduler_admission`记录实际mode、lane、aged及`repair_extra_budget_used=false`。未取得时`selected`带真实token/batch/case/stage/owner/model/effort/lane，`action=selected_owner_acquire_then_dispatch`明确由该owner及时取得原票并启动；`requester_can_acquire=false`提示当前批不能代领。输出不代表已派发，也不跨owner修改状态。

先对每个真实父聊天`bind-controller`，再`configure-scheduler`。绑定JSON只提供`session_id`及该父实际`session_log`；工具从Codex sessions目录核session_meta、文件名及该聊天已成功执行的`batch_control.py --root/--batch-id/--pid`宿主完成记录，冻结对应行offset/size/hash。用户消息中的引用、任意组名、PID相同、不同批次名、伪ID、子代理日志均不能扩容。同session_id的多批和重复/复制绑定始终共用一组；实际宿主4槽含父，本组最多3子模型任务，也受各批冻结worker_capacity中较低值约束。首次绑定顺扫日志，后续只核首行与已选命令记录的有限范围；日志正常追加不失效。缺失/已变绑定及旧未归属active保守扣容量，不推断另一个组；已有active归属另存控制记录，不能借重新绑定移往新组。

兼容模式：历史`legacy`全局默认建设/返修共享8、普通审核3、明确加急审核1；`verified-controller-fair-v1`可在`build<=8/review<=8/expedited<=4`内选择固定stage配额，并支持`repair_extra_capacity=0/1/2`。返修仍stage=build和独立ultra，不增加模型阶段：该旧模式的额外预算仅由`bind-repair`核实际独立revise的本案run/admission/permit、真实派发与child最终答复精确proof hash后取得；只填repairing/work_kind不能扩容。已核返修可借空闲建设预算，旧建设硬上限8；两者持续等待时轮转。未登记返修保留旧建设预算及ultra路由。所有模式每真实组仍最多3；并非登记两批就倍增容量，更不代表已实跑8建设+2返修。录制/evidence在所有模式仍独立按冻结媒体容量、Windows Job身份、实际CPU/内存及互斥准入。

旧`fair-v1`先过滤owner、drain、blocked/delivered、源、零模型预检、真实加急授权、review run身份、组与固定stage已满。普通与priority>=10候选两边都合格时轮流授予（首次高priority先行）；只有一边合格时立即借用全部可用份额。每类内建设/已核返修轮转，再按同类同预算最近实际准入较早的组和批轮转，最后priority及原提交时间FIFO；满组/满stage队首不挡有空位的候选。所有公平模式未获准返回兼容`acquired=false`，父按`selected`推进已有票据，不继续盲等同案、不自动替别人占token。已active不抢占、不改排序。priority10建设可运行high；没有真实Astra授权仍不能取得expedited审核。

```powershell
# 当前进程先加载已安装环境；value文件放本轮授权控制目录，使用真实日志和实际父PID。
. 'D:\自动化2.0\software-case-batch-pro\Enter-Environment.ps1'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' bind-controller --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --value 'controller-binding-request.json' --authorization '本轮真实用户调度授权引用'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' bind-repair --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --case-id '实际需返修case_id' --value 'repair-request.json' --authorization '本轮真实用户返修扩容授权引用'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' configure-scheduler --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --value 'scheduler-request.json' --authorization '本轮真实用户调度授权引用'
```

绑定请求：`{"session_id":"实际父聊天UUID","session_log":"C:\\Users\\Administrator\\.codex\\sessions\\2026\\10\\15\\rollout-实际时间-实际父聊天UUID.jsonl"}`。返修请求：`{"case_id":"实际需返修case_id"}`，工具只从该案现有最新completed_revise与对应dispatched记录取真实证据，拒绝pass/被改proof/异run/冒名子日志；首次核验后冻结有限日志片段，后续不全扫会话。新授权批标准配置请求：`{"mode":"verified-controller-adaptive-v2","aging_seconds":300}`。旧固定配额兼容请求：`{"mode":"verified-controller-fair-v1","capacities":{"build":8,"review":4,"expedited":4},"repair_extra_capacity":2}`。回退请求：`{"mode":"legacy"}`。`status`同时给出独立scheduler配置与追加的控制历史；被冻结批清单不改变。

安装时先逐哈希核验并就位新支持模块`scripts/scheduler_repair.py`和`scripts/scheduler_policy.py`，随后再切换消费它们的`scripts/batch_control.py`；最后才执行授权绑定和启用配置。此工具只维护调度事实，不改变CLI安全配置、不调用app-server改会话、不自动派模型、不自动接续其他批次。独立验收、备份安装及发布仍走原授权与验证门禁。
