"""Freeze read-only original normative sources and validate line-level coverage."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from common import digest,read_json,write_json

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path(r'D:\软通自动化')
SNAPSHOT_NAMES={'AGENTS.md':'AGENTS.snapshot.txt','skill/SKILL.md':'skill/SKILL.snapshot.txt'}

def snapshot_path(relative):
    return ROOT/'references/original'/SNAPSHOT_NAMES.get(relative,relative)
SOURCES=['AGENTS.md','skill/SKILL.md','config.json','开始使用.md','本机接手说明.md']
SOURCES += ['rules/'+name for name in (
 'requirements.md','chart-quality.md','chart-acceptance.md','chart-professional.md',
 'chart-professional-scope.json','chart-legend.md','chart-legend-scope.json',
 'rejected-chart-versions.json','case-design.md','deliverable-first.md',
 'material-sourcing.md','web-visible-copy.md','worker-environment.md',
 'execution-efficiency.md','efficient-pipeline.md','expedited-review.md')]
SOURCES += ['docs/'+name for name in ('artifact-contract.md','capture-plan.md','architecture.md','发布核验.md','新电脑使用.md')]

# Human decisions: exact original clauses, concrete new route, applicable scope,
# and a material gap/fix. The script only freezes/verifies this maintained audit.
DECISIONS=[
 ('authorization','skill/SKILL.md','仅执行用户明确授权','preserved','execution.md','batch_control.py','parent plus register','原新版仅单案入口未完整批责任；新增确认清单与唯一父路由，禁止后台扫描'),
 ('case-completeness','skill/SKILL.md','承接整批即负责','preserved','execution.md','batch_control.py','parent plus state','明确负责人持续修复可恢复故障并接续完整清单，单案/plan/worker退出不能称整批完成'),
 ('one-word-one-case','rules/requirements.md','一个 Word 默认一案','preserved','execution.md','batch_control.py','parent guidance','保留合并材料须清单明确及doc损坏/加密/锁文件规则，不静默跳案'),
 ('frozen-source','rules/requirements.md','保存原文件名','preserved','quality.md','contracts.py','prepare and chart gate','显式source-docx冻结原basename/hash，原件只读，内部源复制逐文件核验'),
 ('output-no-overwrite','rules/requirements.md','遇到同名案件','preserved','tools.md','proflow.py','prepare immutable receipt','保留历史与源，draft显式保全，修订另存工作区/输出，不改旧receipt'),
 ('model-build','skill/SKILL.md','建设与建设内自检','preserved','tools.md','contracts.py','actual JSONL gate','实际spawn sol/high，配置不当执行，自检不冒充独立审核'),
 ('model-repair','skill/SKILL.md','返修、录制准备修复','preserved','tools.md','contracts.py','actual repair dispatch gate','修复新版错误high返修override；stages repair-N连续sol/ultra，独立于reviewer'),
 ('model-review','skill/SKILL.md','普通独立只读验收','preserved','tools.md','contracts.py','actual final proof gate','真实另一个sol/ultra，session identity及final精确proofhash，reviewer不建设'),
 ('model-expedited','rules/expedited-review.md','批次/单案加急授权','conditional-preserved','execution.md','batch_control.py','parent scoped conditional route','仅显式原加急模式Astra/low；本次不启用，提速不能换模型，授权不跨批'),
 ('inflight-model','skill/SKILL.md','不为腾槽打断有效调用','preserved','execution.md','batch_control.py','parent guidance','保留历史模型身份与已在途有效调用，不热切换/重复启动'),
 ('unique-owner','skill/SKILL.md','入口对话负责本批接续','preserved','execution.md','batch_control.py','claim and scoped state','补唯一父PID+创建时间，worker本案写权限、review原始结果由父保存、共享唯一维护'),
 ('workspace-month','skill/SKILL.md','cases/YYYY-MM','preserved','execution.md','batch_control.py','parent case list','新案按登记月份/同名中文序号，本次用户指定旧revision优先，不移动运行目录'),
 ('capacities','skill/SKILL.md','共享8个','preserved','execution.md','batch_control.py','manifest and shared queue','保留8/3/2/1/1原逻辑上限；本机4总槽扣父及占用仅降并发，不降低模型'),
 ('manifest-freeze','rules/execution-efficiency.md','登记后配置已冻结','preserved','execution.md','batch_control.py','immutable register','原新版遗漏execution冻结；新增host capacity及model/resource manifest，旧batch不热改'),
 ('fair-queue','rules/efficient-pipeline.md','同优先级先到先得','preserved','execution.md','batch_control.py','queue/acquire/release-slot','补同优先级FIFO及优先级；等待录制/审核释放建设槽，单案不双占'),
 ('memory-admission','rules/execution-efficiency.md','物理可用内存与 Windows 提交','preserved','execution.md','batch_control.py','actual Windows memory admission','补录制取得槽复查min physical/commit、4096+2048；新批可降1路不热改旧批'),
 ('priority','rules/execution-efficiency.md','priority --value 10','preserved','execution.md','batch_control.py','priority scoped pending tickets','父显式提高未开始阶段priority，不打断付费调用，不等于Astra'),
 ('drain','rules/execution-efficiency.md','drain`','conditional-preserved','execution.md','batch_control.py','drain/continue boundary','只用户显式暂停维护；现阶段完成后停新派发，保留状态和队列'),
 ('resume','rules/execution-efficiency.md','resume-case','preserved','execution.md','batch_control.py','resume-case/recover-owner','本父存活接续；已退出核锁/源/状态恢复原批，不重建，不重置calls/usage'),
 ('environment-first','rules/worker-environment.md','首次部署或运行时变化','preserved','execution.md','batch_control.py','parent smoke plus preflight gate','补零模型实际依赖/浏览器/临时Word，版本登录不替代；原doctor未自动移植明确等效'),
 ('sandbox-preflight','rules/worker-environment.md','保持建设workspace-write','preserved','execution.md','batch_control.py','parent actual constrained checks','付费派发前原write/read-only命令+读写边界，桌面存活，环境证据登记不绕过安全'),
 ('bounded-probes','rules/worker-environment.md','单次最多等90秒','preserved','execution.md','batch_control.py','parent bounded execution','保留登录60秒、受限冷初始化90秒，实际退出与原错/耗时；不循环免费/付费试错'),
 ('local-write','rules/worker-environment.md','ReadWrite句柄','preserved','execution.md','batch_control.py','worker parent guidance','每案必要现有业务文件只开RW不改字节及输出可写，不用删原件测权限'),
 ('error-classification','rules/worker-environment.md','是尚未证实的原因说明','preserved','execution.md','batch_control.py','parent diagnosis','策略/ACL/占用/初始化/OOM/依赖分别记，否定措辞不关键词误分类'),
 ('no-safety-bypass','rules/worker-environment.md','不更改Codex配置','preserved','execution.md','batch_control.py','parent constraint','保留原sandbox/approval/ACL/Deny，固定CLI缺失不回退，共享重启先用户明确授权'),
 ('repair-recovery-proof','rules/worker-environment.md','旧ready','preserved','execution.md','batch_control.py','recovery path/hash and blocker fingerprint','原状态不得假解除；恢复日志真实非空hash、指纹匹配，旧blocked和未读项保留'),
 ('venv','rules/worker-environment.md','必须保留实际可用的虚拟环境','preserved','execution.md','process_guard.py','parent verified startup','保留正确venv启动器真实import/sys.prefix，不以listener基础Python替换'),
 ('powershell51','rules/worker-environment.md','UTF-8 BOM','conditional-preserved','execution.md','process_guard.py','parent actual 5.1 validation','保留中文BOM和准确venv依赖/实跑，不只语法；hidden启动记录launcher/listener'),
 ('healthy-service','rules/worker-environment.md','不能先停再发现启动受限','preserved','execution.md','process_guard.py','parent health/ownership route','保持已拒启动时健康本案服务，先离线准备及合法恢复；不为录制重复重启'),
 ('full-source-read','rules/requirements.md','完整读正文','preserved','quality.md','contracts.py','builder guidance plus OOXML gate','正文/表格/文本框/页眉页脚/DrawingML/VML/嵌入/OMML和普通公式完整读，不能只摘要'),
 ('formula-count','rules/requirements.md','独立陈列公式组','preserved','quality.md','contracts.py','builder plus independent semantics','节点数不等源独立公式组；原无公式不补造，组/行内变量/文字规则分开登记'),
 ('source-trace','rules/requirements.md','raw_formula','preserved','quality.md','contracts.py','builder persisted trace','保留raw/normalized/变量单位边界/原位置/实施例/函数/测试/图映射及coverage/calculation trace'),
 ('formula-constraints','rules/deliverable-first.md','计算必须满足源定义','preserved','quality.md','contracts.py','real algorithm assertion and independent check','源约束/身份归属/代表值边界独立复算，不只是CSV与同程序相等'),
 ('narrative-numbers','rules/deliverable-first.md','说明里的数字','preserved','quality.md','contracts.py','builder plus independent semantics','冻结数值/原式复算，舍入不跨边界，0索引不误写自然位置，首次符号简释'),
 ('complete-web','rules/deliverable-first.md','其他模块可以暂时留空','partial-explicit-override','system-data.md','proflow.py','U1 complete business implementation','仅原两页/空模块例外改完整可部署中文Web；保留导航/业务状态/适用系统形态、非图墙'),
 ('matching-system','rules/case-design.md','使用者、业务对象','preserved','system-data.md','proflow.py','builder requirements','本案角色对象操作系统形态决定布局，已有正常功能保留，不套统一空壳'),
 ('local-workbench','rules/requirements.md','默认直接进入工作台','preserved','system-data.md','proflow.py','builder requirements','本地录制不让登录挡工作台，真实部署鉴权安全按用途实现，不冒充生产接入'),
 ('persisted-flow','rules/requirements.md','创建/导入→计算','preserved','system-data.md','proflow.py','six real checks gate','算法/API/重启持久化/浏览器/构建/最终ZIP启动真实链路命令与日志，不静态假响应'),
 ('state-consistency','rules/deliverable-first.md','两页中的状态','partial-explicit-override','system-data.md','record.cjs','U9 general actual state/action browser checks','原对象/工况/筛选切换同版本继续保留并推广每个授权案件：可见列表/详情/统计/摘要/日志同对象，保留筛选排序及合法分页，关闭抽屉不被迟到异步请求打开，不硬编码测试案业务'),
 ('material-permission','rules/material-sourcing.md','无需再请求','preserved','system-data.md','proflow.py','builder sourcing route','普通缺数据/标定/权重/协议自主补齐实际运行，真外部限制才blocked'),
 ('material-licenses','rules/material-sourcing.md','核对代码、模型权重、数据','preserved','system-data.md','package_policy.py','research plus attribution review','实际适用公开入口/版本/许可/下载hash与最小运行，不支付/上传私源/接受身份条款'),
 ('data-mechanism','rules/material-sourcing.md','同一样本身份','preserved','system-data.md','proflow.py','real constraints and internal provenance','物理/业务关联、时序因果、正常边界/异常；不复制行/任意插值/手填改善率'),
 ('data-nature','rules/material-sourcing.md','生成脚本路径/哈希','preserved','system-data.md','proflow.py','internal provenance gate','源/公开/构造输入/实际输出分开，假设/种子/确定性/日志/未验内部保存，不冒充实测或训练成功'),
 ('data-scale-clean','rules/material-sourcing.md','运行导入/生成','partial-explicit-override','system-data.md','proflow.py','U6 important CSV allowlist clean','加足领域规则数据，重要CSV白名单仅整列删生成/来源元数据，其他单元格顺序精度不改'),
 ('ui-copy','rules/web-visible-copy.md','全部网页及视频画面','preserved','system-data.md','package_policy.py','actual browser texts and semantic scan','保留原禁词含专利/权利要求及英文同义，扩大用户中文禁词，canvas/SVG图人工补录方法'),
 ('ui-audit','rules/web-visible-copy.md','真实浏览器逐路由','preserved','recording.md','record.cjs','observed DOM screenshot pairing','全部关键真实状态文字同截图hash，不源代码/预期替代，独立看真实视频/截图'),
 ('chart-value','rules/chart-quality.md','图数与公式数不绑定','preserved','quality.md','contracts.py','2-6 count gate plus semantic review','有独立价值2–6专业黑白数据图、图数不绑定公式，原图不计，禁止0/1/卡片/真值表换皮'),
 ('chart-scope','rules/chart-professional.md','既有批次','conditional-preserved','inheritance.md','audit_inheritance.py','frozen scope source and parent decisions','冻结professional/legend scope json和历史批ID，不自动返工其他历史；当前新案标准全保留'),
 ('chart-full-range','rules/chart-acceptance.md','数据充分，曲线完整','preserved','quality.md','contracts.py','actual independent normal-size review','完整代表周期/边界，真缺测断点、离散阶梯、真重合不偏移，不少点任意平滑造波动'),
 ('chart-legend','rules/chart-legend.md','每幅图、每个子图','preserved','quality.md','contracts.py','actual all PNG/Word five checks','每系列名称/数据/对象/工况/线型/点形/灰阶/纹理一致，真实绘图对象图例，错配必须返修'),
 ('chart-title','rules/chart-quality.md','图内无标题','partial-explicit-override','quality.md','contracts.py','U4 title declaration plus real review','强化无title/suptitle/表头/图N，图题仅Word图下；轴与必要图例和单位不删'),
 ('chart-units','rules/chart-quality.md','单位只在确有单位','preserved','quality.md','contracts.py','real labels/units review','无单位量仅业务名，不补无单位/a.u./1；确有单位依据保留，缺资料不猜无单位'),
 ('chart-symbols','rules/chart-legend.md','上下标在正确位置','preserved','quality.md','contracts.py','actual PNG and Word dimensions review','正常上下标/帽号/希腊/索引，不裸math代码/乱码；难排可选符号准确业务名保留内部映射'),
 ('red-context','rules/chart-quality.md','Word说明必须结合正文','partial-explicit-override','quality.md','contracts.py','U5 contextual deep explanation','保留前文红字后文实际阅读，详细讲工况读法算例数值原因判断；有原式用关键符号，无式仅实施例'),
 ('word-position','rules/requirements.md','所有新增图片及图题','preserved','quality.md','contracts.py','chart_snapshot original-block/caption/drawing gate','原文原式原图及位置不改、原顺序媒体保留，新增图/下图题全原文后，红字留实施例每图独立引用'),
 ('word-all-pages','rules/requirements.md','每一页打开检查','preserved','quality.md','contracts.py','parent final controlled render plus actual all-page review','最终修改后全页渲染逐页看；未变且真实已阅页hash合法继承，首次不能抽样'),
 ('chart-five','rules/chart-quality.md','meaning/data/legibility/layout/explanation','preserved','quality.md','contracts.py','strict actual review proof','各图五项具体证据，任一失败不pass；PNG/CSV/解释/Word上下文，缺图像能力不签'),
 ('rejected-versions','rules/chart-quality.md','用户明确否定','preserved','quality.md','contracts.py','frozen rejected hash gate plus review','用户否定版本/规则变更旧pass失效，冻结拒交hash，用户推进Word不等视觉认可'),
 ('record-minute','rules/requirements.md','每案约10秒','partial-explicit-override','recording.md','record.cjs','U2 55-75 actual recording','改约60秒完整平顺真实使用；无短版，非静态拼图/循环/变速/假响应/改业务DOM'),
 ('record-health-inputs','docs/capture-plan.md','application_files列出','preserved','recording.md','record.cjs','current listener and immutable inputs gate','启动固定version/health/OS身份、实际依赖代码和页面业务数据/可见图hash，前后不变'),
 ('record-transition','docs/capture-plan.md','观察真实导航期间','preserved','recording.md','record.cjs','builder actual transition and reviewer','保留旧业务内容至新页ready，ready非空壳，截图及视频真实不改DOM隐藏加载'),
 ('record-controlled','rules/requirements.md','完整时间线每 0.2 秒','preserved','recording.md','media_evidence.py','full decode/5fps/contact/frame hash gate','修原新版10秒抽一帧遗漏；完整5fps映射+首尾/每交互前后0.2s原帧，正常阅读静止不直接失败'),
 ('record-no-load','rules/execution-efficiency.md','不在此阶段录制','preserved','recording.md','batch_control.py','stage parent orchestration','ultra prepare/repair不占record槽，父固定程序录制，不与本案构建/大计算/渲染并行'),
 ('controlled-parent','docs/artifact-contract.md','由编排器运行controlled_evidence','preserved','execution.md','media_evidence.py','parent fixed render/media route','父受控原Word保留/最新全页/视频证据，worker不能自签；原controlled自动入口未移植标明等效'),
 ('short-evidence','rules/execution-efficiency.md','短review_id及E001','preserved','execution.md','evidence_index.py','actual ID index and coverage check','父生成索引/前后hash，review具体短结论/五项/已阅ID，减少模型抄hash非减少范围'),
 ('revise-blocked-pass','rules/execution-efficiency.md','advisory_only','preserved','execution.md','contracts.py','parent result preservation and strict pass','revise漏项仅advisory，blocked诊断保留未读/原错不内容付费修；pass完整覆盖无补签'),
 ('repair-unlimited','rules/requirements.md','不设固定两次上限','preserved','execution.md','contracts.py','parent ultra repair loop','可修问题一次完整清单自检复验至通过，无固定轮次，累计calls/usage不重置'),
 ('reuse-by-dependency','rules/deliverable-first.md','Word文字、红字分析','preserved','execution.md','proflow.py','hash-bound document/package revision','不变已阅按hash继承；Word专图不重录，画面代码数据变化重录，不变计算/测试不重做'),
 ('runtime-streams','docs/artifact-contract.md','持续stdout/stderr','preserved','execution.md','evidence_index.py','parent explicit frozen evidence list','持续流有限登记或.runtime，与冻结log/CSV/Word分开，不能忽略全部evidence逃审'),
 ('atomic-delivery','docs/architecture.md','原子改名','preserved','tools.md','proflow.py','publish intent plus same-volume whole-directory rename','修补原新版仅CSV/ZIP原子缺口：candidate finalize→冻结intent→逐文件hash→整案rename→当前run映射与独立publish receipt；未发布不可作父案，旧receipt/proof不改'),
 ('delivery-shape','skill/SKILL.md','成品固定为','partial-explicit-override','tools.md','proflow.py','U3 exact layout gate','原basename Word+本案模拟系统ZIP/CSV/video三项，外层无说明/图表，原件工作区不改'),
 ('package-no-docs','rules/material-sourcing.md','README清楚区分','partial-explicit-override','system-data.md','package_policy.py','U7 explicit exclusion and semantic scan','ZIP不放README/使用说明/制作来源构造说明/原件解析/模拟性质；内部事实完整保留，必要署名法律保留'),
 ('cleanup-order','rules/worker-environment.md','触发点是本案','partial-explicit-override','processes.md','process_guard.py','U8 after recording/online before clean','用户明确时机覆盖交付后清理；仍核所有归属/无在途依赖/实际退出端口，不停其他项目'),
 ('cleanup-safe','rules/worker-environment.md','持有同一Windows进程句柄','preserved','processes.md','process_guard.py','exact same-handle termination','PID创建/完整command/树/监听健康；不通用名杀，Get-Content/rg路径文本不算后台，失败保留pending'),
 ('cache-policy','AGENTS.md','TEMP/TMP/TMPDIR','preserved','execution.md','common.py','Enter-Environment and parent cache audit','仅进程D盘TEMP/cache，结束查本次C盘增量；备份核验才删确认缓存，保留链接/依赖/凭据/DB/session'),
 ('migration-authority','skill/SKILL.md','仅用户明确授权更替执行','conditional-preserved','execution.md','batch_control.py','parent authorized copy/hash route','迁移保全旧树/状态/调用/数据库，正常继承新副本逐文件核验，不rename猜ACL；原自动migrate未移植'),
 ('publication-boundary','docs/发布核验.md','没有启动、重启','conditional-preserved','inheritance.md','audit_inheritance.py','scope/test evidence disclosure','隔离测试不叫实际case端到端；本次不覆盖原skill/上传/自动知识维护，发布另需明确授权'),
 ('default-output-root','AGENTS.md','成果沿用用户指定的','partial-explicit-override','tools.md','proflow.py','U9 configured F root plus explicit output precedence','原D成果根仅冻结历史；新版默认F:\\研发图表按批次/案件集中，F同卷.staging候选，明确用户工作区/其他路径优先且执行/交付目录隔离，不静默回D/桌面；D:\\codex+缓存不变，旧成果不自动搬移'),
]

def route(relative,line):
    if any(k in relative for k in ('chart','requirements','artifact-contract')):
        guide='references/quality.md';entry='scripts/contracts.py';mode='guidance plus structural gate; semantic and visual checks by independent reviewer'
    elif 'capture-plan' in relative or 'efficient-pipeline' in relative:
        guide='references/recording.md';entry='scripts/record.cjs';mode='guidance plus real fixed browser recorder; original capture_runner not ported'
    elif 'material' in relative or 'case-design' in relative:
        guide='references/system-data.md';entry='scripts/proflow.py';mode='guidance plus explicit data/package commands; research and business implementation remain builder duties'
    elif 'web-visible' in relative:
        guide='references/system-data.md';entry='scripts/package_policy.py';mode='guidance plus delivery scan; real DOM/screenshots and video still required'
    elif 'worker' in relative:
        guide='references/execution.md';entry='scripts/process_guard.py';mode='guidance plus owned-process gate and parent zero-model environment route'
    else:
        guide='references/execution.md';entry='scripts/batch_control.py';mode='parent orchestration with frozen manifest, lock, state and shared slot tools; original CLI automatic runner not ported'
    if any(k in line for k in ('原文','OMML','源式','公式登记','上下标','图例','Word')):
        guide='references/quality.md';entry='scripts/contracts.py'
    return {'guidance':guide,'available_entry':entry,'implementation_status':mode,
            'frozen_full_source':snapshot_path(relative).relative_to(ROOT).as_posix()}

def disposition(relative,line):
    overrides=[]
    for key,needles in (
      ('U1-complete-system',('两个页面','两个业务页','两页','两个专业业务','其他模块内容可空','其他模块可以暂时留空','空模块','两页业务','只实现产生本案结果必需')),
      ('U2-minute-recording',('10秒','10 秒','8–12秒','8–12 秒','0–4秒','4–7秒','7–10秒','max_seconds','min_seconds','target_seconds','modules_max','modules_min')),
      ('U3-delivery-contents',('只含修订Word','只含修订Word','只交付Word和视频','只含修订 Word','word-video','不挤进客户成品','源码、数据库、日志')),
      ('U4-original-word-name',('修订文档.docx','修订Word','修订 Word')),
      ('U5-docs-stay-internal',('随成品交付','成品交付README','README随','README仍')),
      ('U6-cleanup-timing',('交付后','交付完成后','交付尚未完成时不关闭服务','收尾时及时处理')),
      ('U9-general-requirements-and-output-root',('D:\\研发图表','D:/研发图表','output_root')),
    ):
        if any(n in line for n in needles):overrides.append(key)
    # Names are changed only where delivery naming/content is prescribed, never
    # in unrelated archival or hashing clauses. Other duties in each row survive.
    if overrides:return 'partial-explicit-override',overrides,'Only the named user changes replace this row fragment; every other obligation in the quoted source remains.'
    conditional=('历史','旧批','生效','existing_batch_ids','effective_scope','2026-09-28登记','仅适用于','加急','迁移','安装','首次部署','新电脑','原件损坏')
    if any(n in line for n in conditional) or relative in {'开始使用.md','本机接手说明.md','docs/新电脑使用.md'}:
        return 'conditional-preserved',[],'Apply the original scope, historical precedence and explicit authorization; no automatic old-case rerun, migration or publication.'
    return 'preserved',[],'Retained at the cited full original source and routed to guidance or an actual available tool; no claim that the old runner was automatically ported.'

def freeze():
    if (ROOT/'references/original-sources.json').exists():raise ValueError('Existing frozen sources must not be overwritten; use validate/refresh or migrate-discovery')
    target=ROOT/'references/original';records=[];rows=[]
    for relative in SOURCES:
        source=ORIGINAL/relative;dest=snapshot_path(relative)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
        if digest(source)!=digest(dest):raise ValueError('Snapshot hash differs: '+relative)
        records.append({'source':str(source),'frozen':dest.relative_to(ROOT).as_posix(),'sha256':digest(source)})
        for index,line in enumerate(source.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip():continue
            status,changes,explanation=disposition(relative,line)
            rows.append({'id':'C'+str(len(rows)+1).zfill(4),'source':relative,'start_line':index,'end_line':index,
               'original':line,'status':status,'explicit_override_ids':changes,'scope_reason':explanation,
               'evidence':route(relative,line),'audit_level':'mechanical-index; semantic decisions are in inheritance-decisions.json',
               'semantic_verified_by_script':False})
    write_json(ROOT/'references/original-sources.json',{'schema_version':1,'source_root':str(ORIGINAL),'sources':records})
    write_json(ROOT/'references/inheritance-coverage.json',{'schema_version':1,'coverage_unit':'every nonblank source line including examples and applicability headings',
        'precedence':'Explicit user overrides only; otherwise original latest scoped clauses remain authoritative.',
        'rows':rows})
    decisions=[]
    for category,relative,needle,status,guide,entry,mode,repair in DECISIONS:
        lines=snapshot_path(relative).read_text(encoding='utf-8-sig').splitlines()
        matches=[{'start_line':i,'end_line':i,'original':line} for i,line in enumerate(lines,1) if needle in line]
        if not matches:raise ValueError('Semantic audit source clause not found: '+category+' '+needle)
        decisions.append({'requirement':category,'source':relative,'original_clauses':matches,'decision':status,
          'current_evidence':{'guidance':'references/'+guide,'entry':'scripts/'+entry,'status':mode},
          'gap_and_fix':repair,'verification':'Meaningful regression tests and actual dispatch/live case evidence are recorded in evidence; these decision rows do not self-sign an independent pass.'})
    write_json(ROOT/'references/inheritance-decisions.json',{'schema_version':1,'audit_type':'human maintained effective requirement decisions',
        'rows':decisions,'independent_review':'Pending actual separate ultra review of this frozen version.'})
    return validate()

def validate():
    if any(p.name in {'SKILL.md','AGENTS.md'} for p in (ROOT/'references/original').rglob('*')):
        raise ValueError('Normative snapshots must not be discoverable active SKILL.md or AGENTS.md instructions')
    sources=read_json(ROOT/'references/original-sources.json')['sources']
    rows=read_json(ROOT/'references/inheritance-coverage.json')['rows'];seen=set()
    for row in rows:
        relative=row['source'];key=(relative,row['start_line'])
        if key in seen:raise ValueError('Duplicate audit clause')
        seen.add(key)
        if row['end_line']!=row['start_line']:raise ValueError('Audit rows must retain exact source lines')
        source=snapshot_path(relative)
        lines=source.read_text(encoding='utf-8-sig').splitlines()
        if row['original']!=lines[row['start_line']-1]:raise ValueError('Quoted clause differs from frozen source')
        if row['status'] not in {'preserved','conditional-preserved','partial-explicit-override'}:raise ValueError('Audit clause lacks an explicit disposition')
        for key in ('guidance','available_entry','frozen_full_source'):
            if not (ROOT/row['evidence'][key]).is_file():raise ValueError('Audit route missing: '+row['evidence'][key])
    expected=set()
    for record in sources:
        frozen=ROOT/record['frozen']
        if digest(frozen)!=record['sha256']:raise ValueError('Frozen normative source hash changed')
        relative=Path(record['source']).relative_to(ORIGINAL).as_posix()
        for index,line in enumerate(frozen.read_text(encoding='utf-8-sig').splitlines(),1):
            if line.strip():expected.add((relative,index))
    if seen!=expected:raise ValueError('Clause coverage incomplete or contains unknown lines')
    return {'status':'complete-line-coverage','sources':len(sources),'clauses':len(rows),
            'counts':{s:sum(r['status']==s for r in rows) for s in ('preserved','conditional-preserved','partial-explicit-override')}}

def refresh():
    """Update active decisions only; previously frozen originals are immutable."""
    validate()
    coverage=read_json(ROOT/'references/inheritance-coverage.json')
    for row in coverage['rows']:
        status,changes,explanation=disposition(row['source'],row['original'])
        row.update(status=status,explicit_override_ids=changes,scope_reason=explanation)
    write_json(ROOT/'references/inheritance-coverage.json',coverage)
    decisions=[]
    for category,relative,needle,status,guide,entry,mode,repair in DECISIONS:
        lines=snapshot_path(relative).read_text(encoding='utf-8-sig').splitlines()
        matches=[{'start_line':i,'end_line':i,'original':line} for i,line in enumerate(lines,1) if needle in line]
        if not matches:raise ValueError('Semantic source clause missing: '+category)
        decisions.append({'requirement':category,'source':relative,'original_clauses':matches,'decision':status,
          'current_evidence':{'guidance':'references/'+guide,'entry':'scripts/'+entry,'status':mode},
          'gap_and_fix':repair,'verification':'Current applicable regression and independently recorded evidence; this table never self-signs pass.'})
    write_json(ROOT/'references/inheritance-decisions.json',{'schema_version':1,'audit_type':'human maintained effective requirement decisions',
        'rows':decisions,'user_overrides':['U1','U2','U3','U4','U5','U6','U7','U8','U9'],
        'independent_review':'Only a separately recorded actual ultra proof establishes acceptance of this frozen version.'})
    return dict(validate(),effective_requirement_decisions=len(decisions))

def migrate_discovery():
    """Rename two instruction-shaped snapshot paths; never changes source bytes."""
    index_path=ROOT/'references/original-sources.json';index=read_json(index_path)
    mapping_path=ROOT/'references/original-discovery-mapping.json'
    migration={'schema_version':1,'prior_index_sha256':digest(index_path),'mappings':[]}
    for record in index['sources']:
        relative=Path(record['source']).relative_to(ORIGINAL).as_posix()
        old=ROOT/'references/original'/relative;new=snapshot_path(relative)
        existing=old if old.exists() else new
        if digest(existing)!=record['sha256']:raise ValueError('Frozen source bytes changed before discovery migration')
        if old!=new:
            migration['mappings'].append({'old':old.relative_to(ROOT).as_posix(),'new':new.relative_to(ROOT).as_posix(),'sha256':record['sha256']})
    if not mapping_path.exists():write_json(mapping_path,migration)
    else:
        prior=read_json(mapping_path)
        if prior['mappings']!=migration['mappings']:raise ValueError('Frozen discovery migration differs')
    for item in migration['mappings']:
        old=ROOT/item['old'];new=ROOT/item['new']
        if old.exists():
            if new.exists():raise ValueError('Duplicate discovery snapshot paths; preserve both and diagnose')
            old.rename(new)
        if digest(new)!=item['sha256']:raise ValueError('Snapshot bytes changed during rename')
    for record in index['sources']:
        relative=Path(record['source']).relative_to(ORIGINAL).as_posix()
        record['frozen']=snapshot_path(relative).relative_to(ROOT).as_posix()
    write_json(index_path,index)
    coverage=read_json(ROOT/'references/inheritance-coverage.json')
    for row in coverage['rows']:
        row['evidence']['frozen_full_source']=snapshot_path(row['source']).relative_to(ROOT).as_posix()
    write_json(ROOT/'references/inheritance-coverage.json',coverage)
    return dict(validate(),discovery_mappings=read_json(mapping_path)['mappings'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['freeze','validate','refresh','migrate-discovery']);args=parser.parse_args()
    commands={'freeze':freeze,'refresh':refresh,'validate':validate,'migrate-discovery':migrate_discovery}
    print(json.dumps(commands[args.command](),ensure_ascii=False,indent=2))
