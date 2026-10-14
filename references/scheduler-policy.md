# 真实聊天容量与可借用公平调度（r14）

本次用户明确授权后，当前负责人可对已登记批次使用独立控制记录接入；无需重新prepare、登记、录制或改冻结manifest。配置仅影响后续`acquire`，不修改原active token、提交/取得时间、owner、历史permit、run、review proof或媒体合同。没有显式配置时沿用已接受旧策略；`mode=legacy`受控回退也只限制后续准入，已运行任务继续完整计数并自行完成。

先对每个真实父聊天`bind-controller`，再`configure-scheduler`。绑定JSON只提供`session_id`及该父实际`session_log`；工具从Codex sessions目录核session_meta、文件名及该聊天已成功执行的`batch_control.py --root/--batch-id/--pid`宿主完成记录，冻结对应行offset/size/hash。用户消息中的引用、任意组名、PID相同、不同批次名、伪ID、子代理日志均不能扩容。同session_id的多批和重复/复制绑定始终共用一组；实际宿主4槽含父，本组最多3子模型任务，也受各批冻结worker_capacity中较低值约束。首次绑定顺扫日志，后续只核首行与已选命令记录的有限范围；日志正常追加不失效。缺失/已变绑定及旧未归属active保守扣容量，不推断另一个组；已有active归属另存控制记录，不能借重新绑定移往新组。

全局默认建设/返修共享8、普通审核3、明确加急审核1；授权配置可在`build<=8/review<=8/expedited<=4`内选择实际需要，本次目标建设8、普通审核4、加急审核4，以及`repair_extra_capacity=2`。返修仍stage=build和独立ultra，不增加模型阶段：额外预算仅由`bind-repair`核实际独立revise的本案run/admission/permit、真实派发与child最终答复精确proof hash后取得；只填repairing/work_kind不能扩容。已核返修可借空闲建设预算，建设硬上限8；两者持续等待时轮转，防止建设吞掉返修机会。未登记返修保留原建设8预算及ultra路由。每真实组仍最多3；两个已核独立组至多合计6个模型子任务，并非登记两批就倍增容量，更不代表已实跑8建设+2返修。录制/evidence仍独立按冻结媒体容量、Windows Job身份、实际CPU/内存及互斥准入。

模型候选先过滤owner、drain、blocked/delivered、源、零模型预检、真实加急授权、review run身份、组与stage已满。普通与priority>=10候选两边都合格时轮流授予（首次加急先行）；只有一边合格时立即借用全部可用份额。每类内建设/已核返修轮转，再按同类同预算最近实际准入较早的组和批轮转，最后priority及原提交时间FIFO；满组/满stage队首不挡有空位的候选。未获准返回兼容`acquired=false`，并用`selected`明确当前应推进的token/batch_id/case_id/stage/work_kind/model/effort及原因；父推进该已有票据，不继续盲等同案、不自动替别人占token。已active不抢占、不改排序。priority10建设可运行high；没有真实Astra授权仍不能取得expedited审核。

```powershell
# 当前进程先加载已安装环境；value文件放本轮授权控制目录，使用真实日志和实际父PID。
. 'D:\自动化2.0\software-case-batch-pro\Enter-Environment.ps1'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' bind-controller --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --value 'controller-binding-request.json' --authorization '本轮真实用户调度授权引用'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' bind-repair --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --case-id '实际需返修case_id' --value 'repair-request.json' --authorization '本轮真实用户返修扩容授权引用'
& $env:SCB_PRO_PYTHON '工具目录\batch_control.py' configure-scheduler --root '原调度根目录' --batch-id '已登记批ID' --pid 实际父PID --value 'scheduler-request.json' --authorization '本轮真实用户调度授权引用'
```

绑定请求：`{"session_id":"实际父聊天UUID","session_log":"C:\\Users\\Administrator\\.codex\\sessions\\2026\\10\\14\\rollout-实际时间-实际父聊天UUID.jsonl"}`。返修请求：`{"case_id":"实际需返修case_id"}`，工具只从该案现有最新completed_revise与对应dispatched记录取真实证据，拒绝pass/被改proof/异run/冒名子日志；首次核验后冻结有限日志片段，后续不全扫会话。配置请求：`{"mode":"verified-controller-fair-v1","capacities":{"build":8,"review":4,"expedited":4},"repair_extra_capacity":2}`。回退请求：`{"mode":"legacy"}`。`status`同时给出独立scheduler配置与追加的控制历史；被冻结批清单不改变。

安装时先逐哈希核验并就位新支持模块`scripts/scheduler_repair.py`和`scripts/scheduler_policy.py`，随后再切换消费它们的`scripts/batch_control.py`；最后才执行授权绑定和启用配置。此工具只维护调度事实，不改变CLI安全配置、不调用app-server改会话、不自动派模型、不自动接续其他批次。独立验收、备份安装及发布仍走原授权与验证门禁。
