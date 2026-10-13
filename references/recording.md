# 一分多钟完整真实操作

新案在建设时按真实使用流程编排一分多钟演示，时长由有效操作、页面响应和必要阅读决定，各案可以不同。关键操作和末步结果展示完成后自然结束，不为凑时长空等、无意义点击、重复操作、加速或截断。调用工具见tools.md。

新案 `run.json` 冻结 `recording_policy_version=flow-complete-v1`，计划必须使用同版本。历史run缺省版本仅按 `legacy-fixed-v1` 保留其原55–75秒规则；历史manifest、计划、视频、收据和冻结规范不追改，未知或不匹配版本拒绝。独立验收核实测时长和完整流程，正常超过75秒不构成重录理由；明显拖长、无意义停留仍按真实流程审查，不能以取消固定上限代替一分多钟要求。

用户本次明确多开要求适用新版新批次：[并发录制](recording-concurrency.md)规定默认auto最高4路、显式2/3/4、模型槽与媒体槽分离、CPU/内存保护和旧批兼容。父启动每案独立进程，capture传齐batch-root/batch-id/case-id/record-token/owner-pid，launch前复查active槽及实际资源。真实操作、画质、完整证据和独立验收要求不变。

用真实浏览器验证整个业务流程，建设自检覆盖当前record-plan的实际导航、选择器和关键断言，可复用同动作的既有E2E；关闭须核抽屉及遮罩确已关闭，跨页须核当前活动页，不能用底层旧节点仍可见判成功。最终录制在同一浏览器会话检查就绪并开始连续录制，不额外启动/关闭预热浏览器。JSON计划保留本机HTTP地址、健康接口、启动时冻结版本、就绪选择器、输入文件哈希绑定列表和有实际业务意义的操作。健康接口、当前OS监听身份、登记PID/创建时间/命令行与本案一致才录制，录后复查。至少六次操作、三类操作，每个改变界面的步骤给出当前结果的可见断言。按本案安排概览→筛选/查询→详情→任务提交→结果/历史→导出和返回，不添加无意义步骤。

high提交录制计划前实际调用现有`record.cjs`的`validatePlan(plan)`做计划就绪检查。全部`input_files`声明值及可选`storage_state`必须是非空字符串的工作区相对路径；不接受Windows/Unix绝对路径、盘符或其他冒号、含`..`的路径分量。`storage_state`可省略，声明时不能留空。此检查只核计划词法，不猜工作区或自动改写路径；录制时`safeFile`仍核实际存在、文件、链接和工作区根保护。录制器不替代真实登录会话就绪及业务流程的浏览器实测，不增加模型、审批或额外预热浏览器。

服务须以本案绝对.py启动文件登记launcher/listener，确认`process_guard inspect.owned`含实际监听，不能只凭register成功判就绪。high随后实际运行`record.cjs --check-ready --workspace 本案绝对目录 --plan 本案计划绝对路径`（先加载环境，以`$env:SCB_PRO_NODE`调用）；它只读复用计划/策略、实际文件根与链接、健康接口同源run/workspace/version/pid及当前登记监听身份检查，不启动浏览器、不获取媒体槽、不写recording/capture状态，只返回哈希与身份事实，不代表录制或视觉通过。健康请求拒绝重定向并有10秒超时；文件存在和服务身份通过后，父才按原槽/lease/Job进入capture，正式录制继续复查同一健康身份。检查不替代正常登录、UI就绪及完整业务流程的真实浏览器实测。

新计划必须声明 `estimated_duration_seconds` 和 `timeout_seconds`。预估大于60秒，仅按本案动作、响应和阅读估算，不是停止时刻；超时保护必须大于预估，不当成片目标。步骤可省略 `at`；保留时只作预计时点，录制不等时点、不因动作较预计晚五秒而中断。每步可选 `reading_seconds`，非零时必须给 `reading_reason` 解释真实结果的必要阅读。必须给 `final_result={selector,text?,reading_seconds,reading_reason}`，末步正数阅读时间按本案内容决定；真实结果可见且阅读前后断言成立后自然结束，不设置统一尾部补时。

计划结构示例，具体选择器、动作及阅读按本案填写，示例预估、超时和阅读不是每案固定秒数：

```json
{
  "recording_policy_version": "flow-complete-v1",
  "estimated_duration_seconds": 83,
  "timeout_seconds": 180,
  "url": "http://127.0.0.1:8123",
  "health_path": "/api/health",
  "version": "本次冻结服务版本",
  "ready": "#dashboard",
  "input_files": ["app.py", "web/app.js"],
  "steps": [
    {"action":"fill","selector":"#search","value":"对象001","expect":"#search","reading_seconds":7,"reading_reason":"核对检索对象及范围"},
    {"action":"click","selector":"#query","expect":"#table","reading_seconds":8,"reading_reason":"阅读筛选结果及统计"},
    {"action":"click","selector":"#detail","expect":"#panel","reading_seconds":9,"reading_reason":"核对当前对象详情"},
    {"action":"select","selector":"#status","value":"ready","expect":"#status","reading_seconds":10,"reading_reason":"核对本次提交参数及影响"},
    {"action":"click","selector":"#save","expect":"#saved","reading_seconds":9,"reading_reason":"检查保存结果和状态摘要"},
    {"action":"download","selector":"#download","expect":"#saved","reading_seconds":8,"reading_reason":"查看导出后的业务结果"}
  ],
  "final_result":{"selector":"#saved","reading_seconds":6,"reading_reason":"完成阅读本次结果和历史摘要"}
}
```

录制器只支持 `click`、`fill`、`select`、`press`、`download`，每步 `expect` 是等待可见的选择器，可附 `text` 校验。提交后断言业务结果，必要时在独立测试中检查接口、数据库和刷新持久性；可见文字出现不能单独证明落库。下载由浏览器真实事件取得并记录文件哈希。

输入文件列表包括影响页面的实际业务逻辑、前端代码及只读输入，不能只列 index.html；会变化的业务库另作前后快照并验证合法状态变化，不纳入不变文件哈希集合。录制前后核对不变依赖，页面脚本报错、HTTP 失败、禁词、断言失败或版本改变都失败，不把旧视频充当本次结果。

原连续WebM和截图保存在 `.product-v2/recordings`。FFmpeg仅裁去导航就绪前导段和操作已完成后的辅助尾段，保留完整连续操作与结果阅读，不拼接、变速、循环或补帧延长。FFprobe核1920×1080和实际媒体时长；新策略实际媒体大于60秒且对应实际流程结束，不使用配置预估代替实测，不设置75或120秒机械上限。capture事实冻结策略版本、计划哈希、预估、独立超时、计划/完成动作数量、每次阅读起止及末步完成证据。操作事件仍记录真实开始/完成时间、截图、文字和下载；计划录前后哈希也必须一致。

自然实操节奏：在真实点击前平滑移动鼠标，输入框逐字键入，关键结果留出阅读停顿；光标标记仅跟随实际指针事件，不得改动业务 DOM 或数据。可交互准备使用不移动指针的状态检查和实际目标点命中复核；Playwright的trial点击仍会移动真实指针，不能当作无指针副作用的探测。核验首个动作、反向长距离及悬停变化时的原生坐标时序和每次位移，不能只数mousemove次数；准备可有界重试，业务输入发出后不得重发。可用 `storage_state` 的工作区相对路径（如`.product-v2/browser-state.json`）指向本案内部真实登录取得的会话文件，禁止带入源码包。录制期间停止本案构建、文档渲染和批量数据计算，避免争抢处理器造成鼠标卡顿；不为此结束其他项目。文本断言等待实际异步结果，不能在已存在的旧节点上立即判定成功。一次最终合格成片可有内部失败重试，失败原片与业务快照保留；只有测试夹具可以从已核验快照重新开局，真实用户数据不得倒退。

父固定 `media_evidence.py` 一次完整解码同时统计原始帧数、核损坏、检查黑屏/冻结并抽完整5fps时间线、真正首帧及全部交互原帧；只对最后0.5秒短尾段取真正末帧。5fps包括最后不足0.2秒的部分区间，接触页 `frame_files` 有序对应全部采样原帧并核每个哈希。每个真实交互开始前0.2秒/完成后0.2秒原帧保留各自文件和哈希，重复时点可从同批抽帧复制，不另完整解码。首尾、交互截图、场景切换和疑点原帧也须放大核对。独立ultra实际看完整接触页与必要原帧，核白屏、遮挡、错对象、英文占满、推导画面和难读瞬间；抽样不能称看过全部原始帧。黑屏/冻结信号只提示检查，正常阅读静止不直接失败。record槽仅capture，浏览器关闭后返回captured/passed=false；所有capture释放后evidence单槽编码、完整技术证据，当前review绑定timeline哈希，技术检查不能签视觉通过。任何live capture与编码/解码/抽帧互斥，FFmpeg解码、滤镜、JPEG编码及x264固定2线程。每次下载使用D盘唯一目录，不共享状态。

capture绑定原片hash、本案run、依赖、操作和实际服务身份；失败保留原片/observed事实，不当成功缓存。evidence失败可在同capture输入未变时继续，新证据目录保留失败历史，已有成片须属于同capture且hash一致。已完成timeline只有在当前策略、同capture、同录制收据、媒体哈希及全部帧/接触页哈希重新核对后才复用，不重复编码或解码；当前独立视觉验收仍必需。finalize强制完整decode/5fps/全部交互、当前review及收尾，不接受只有capture的原片。每案stage lock防同案双写，遗留锁须核PID身份确已退出并保留故障证据后由唯一父恢复，不能删活锁。rAF只供性能诊断，不能代替源帧连续性和视觉检查，输出25fps不能证明流畅。

检查失败只修相关页面/计划，录制准备修复由ultra，父在录制槽重录并按当前依赖重新证据；首次已有合格一分钟不额外录短视频。ZIP说明专用修订只对同hashMP4补解码证据，不能借此重录。最终只向成品模拟系统复制当前合格演示视频.mp4，原片/失败证据完整内部保留。
