"""Product-v2 helpers. No model calls, old-runner mutation, or raw-data deletion."""
import argparse
import csv
from datetime import datetime, timezone
import io
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from common import (TEXT_SUFFIXES, META_COLUMNS, digest, file_map, forbidden, inside,
                    no_links, normalized, read_json, state, write_json)
from source_intake import source_figure_numbers
from contracts import ANALYTICAL_CHART_POLICY, BUILD_CHART_POLICY, chart_policy
from review_packet import execution_checks

ROOT = Path(__file__).resolve().parent.parent
SYSTEM = '模拟系统'
DEFAULT_OUTPUT_ROOT = r'D:\研发图表'
EXCLUDED_DIRS = {'.git','.product-v2','node_modules','.venv','venv','__pycache__',
                 '.pytest_cache','.cache','evidence','recording','recordings','logs',
                 'source-analysis','source_analysis','docx-extract','docx_extract',
                 'document-analysis','document_analysis','extracted','原文解析','文档解析',
                 '原件','原件备份','解析结果','解析文件','源文件解析'}
EXCLUDED_NAMES = {'formula_registry.json','formulas.json','source_trace.json','source-trace.json',
                  'source_text.txt','source-text.txt','document.xml','material-research.json',
                  'artifact-manifest.json','analysis.json','解析报告.md'}

def utc():
    return datetime.now(timezone.utc).isoformat()

def default_output_root():
    """Delivery policy only; explicit --output stays mandatory and authoritative."""
    configured=os.environ.get('SCB_PRO_OUTPUT_ROOT')
    if configured is None:
        path=ROOT/'local.config.json'
        configured=read_json(path).get('output_root',DEFAULT_OUTPUT_ROOT) if path.exists() else DEFAULT_OUTPUT_ROOT
    if not Path(configured).is_absolute():raise ValueError('Default delivery root must be absolute; no silent fallback')
    return no_links(configured)

def finalized_snapshot(output, receipt, allow_untracked=False, workspace=None):
    """Verify all receipt entries. Narrow revision-only exception never drops bytes."""
    current=file_map(output)
    registered=receipt.get('files',{})
    if receipt.get('delivery_state')=='verified-candidate':
        if workspace is None:raise ValueError('Verified candidates require an actual atomic publication receipt before inheritance')
        published=read_json(inside(workspace,'.product-v2/publish-receipt.json'))
        from common import product_location
        original_run=read_json(inside(workspace,'.product-v2/run.json'))
        if (original_run.get('status')!='published' or original_run.get('workspace')!=str(no_links(workspace))
                or published.get('status')!='published' or published.get('destination')!=original_run.get('output')
                or product_location(workspace,original_run)!=output
                or published.get('files')!=registered
                or published.get('source_receipt_sha256')!=digest(inside(workspace,'.product-v2/final-receipt.json'))):
            raise ValueError('Verified candidate is not a published finalized revision base')
    if receipt.get('status')!='complete' or not registered or any(current.get(k)!=v for k,v in registered.items()):
        raise ValueError('Revision base requires every finalized registered artifact unchanged')
    untracked={k:v for k,v in current.items() if k not in registered}
    if untracked and not allow_untracked:
        raise ValueError('Finalized base has untracked files; explicit revision-only allowance required')
    return untracked

def prepare(workspace, output, title, source_docx, revision_of=None, adopt_draft=False, revision_scope='document', allow_untracked_base=False):
    workspace, output = no_links(workspace), no_links(output)
    if not workspace.is_dir():
        raise ValueError('Existing case workspace required')
    if workspace == output or workspace in output.parents or output in workspace.parents:
        raise ValueError('Delivery and workspace must be disjoint')
    if not title.strip() or forbidden(title):
        raise ValueError('Use a meaningful business title without restricted words')
    source_docx = no_links(source_docx)
    if not source_docx.is_file() or source_docx.suffix.lower() != '.docx':
        raise ValueError('Explicit --source-docx must identify the original Word file')
    with zipfile.ZipFile(source_docx) as package:
        if 'word/document.xml' not in package.namelist():
            raise ValueError('Source is not a Word package')
    source_hash = digest(source_docx)
    source_numbers = source_figure_numbers(source_docx)
    base=None
    if allow_untracked_base and (not revision_of or revision_scope!='package'):
        raise ValueError('Untracked-base allowance is limited to explicit package revisions')
    if revision_of:
        base_workspace,base_output,base_run=state(revision_of)
        chart_policy(base_run)
        base_receipt=inside(base_workspace,'.product-v2/final-receipt.json')
        prior=read_json(base_receipt)
        frozen_source=prior.get('source_docx_sha256') or base_run.get('source_docx_sha256')
        if frozen_source and frozen_source!=source_hash:raise ValueError('Revision must preserve the previously finalized original Word source identity')
        untracked=finalized_snapshot(base_output,prior,allow_untracked_base,base_workspace)
        base={'workspace':str(base_workspace),'output':str(base_output),'receipt_sha256':digest(base_receipt),
              'system_files':{k[len(SYSTEM)+1:]:v for k,v in prior['files'].items() if k.startswith(SYSTEM+'/')}}
        if untracked: base['untracked_base_files']=untracked
        if revision_scope not in {'document','package'}:
            raise ValueError('Supported revision scope is document or package')
    record = workspace / '.product-v2/run.json'
    if record.exists():
        previous = read_json(record)
        chart_policy(previous)
        if previous.get('schema_version') != 2:
            raise ValueError('Legacy run is frozen; prepare a separate revision workspace and output')
        if (previous['output'] == str(output) and previous['title'] == title
                and previous['source_docx'] == str(source_docx) and previous['source_docx_sha256'] == source_hash
                and previous.get('revision_of')==base and previous.get('revision_scope','document')==revision_scope):
            return previous
        raise ValueError('Workspace already has a different product-v2 run; preserve it')
    adopted=None
    if output.exists():
        if not adopt_draft or not base:
            raise ValueError('Delivery directory already exists; choose a new version directory')
        from contracts import delivery_layout
        delivery_layout(output,{'schema_version':2,'word_name':source_docx.name})
        candidate=file_map(output/SYSTEM)
        same=(candidate==base['system_files']) if revision_scope=='document' else (
            {k:v for k,v in candidate.items() if k!='项目源码.zip'}==
            {k:v for k,v in base['system_files'].items() if k!='项目源码.zip'})
        if not same:
            raise ValueError('Adopted revision draft must preserve the complete finalized system snapshot')
        adopted=file_map(output)
    else:
        output.mkdir(parents=True)
    run = {'schema_version':2, 'profile':'product-v2', 'run_id':uuid.uuid4().hex,
           'workspace':str(workspace),'output':str(output),'title':title,'created_at':utc(),
           'source_docx':str(source_docx),'source_docx_sha256':source_hash,
           'word_name':source_docx.name,'word':str(output/source_docx.name),
           'data_dir':str(output/SYSTEM/'数据'),'source_zip':str(output/SYSTEM/'项目源码.zip'),
           'video':str(output/SYSTEM/'演示视频.mp4'),'status':'prepared'}
    if not base or revision_scope=='document':
        run['chart_policy']=BUILD_CHART_POLICY
    elif 'chart_policy' in base_run:
        run['chart_policy']=base_run['chart_policy']
    if base:
        for policy_key in ('recording_policy_version','data_policy_version'):
            if policy_key in base_run:run[policy_key]=base_run[policy_key]
    else:
        run['recording_policy_version']='flow-complete-v1'
        run['data_policy_version']='neutral-expanded-v1'
        from contracts import CONSTRUCTION_POLICY
        run['construction_check_policy_version']=CONSTRUCTION_POLICY
    # Historical finalized revisions keep their frozen numbering contract.
    if not base or base_run.get('chart_numbering_policy') == 'source-sequential-v1':
        run['chart_numbering_policy'] = 'source-sequential-v1'
    if base: run['revision_of']=base;run['revision_scope']=revision_scope
    if adopted is not None: run['adopted_draft_files']=adopted
    write_json(record, run)
    prompt = f'''使用 $software-case-batch-pro 继续完成本案，实际实施直到通过当前版本检查。
案件：{title}
原工作区：{workspace}
原技术Word（只读，冻结SHA256={source_hash}）：{source_docx}
交付Word必须保留原始完整文件名：{run['word']}
成品文件夹：{output}
数据交付位置：{run['data_dir']}
源码压缩包：{run['source_zip']}
最终视频：{run['video']}

父会话必须使用实际spawn_agent工具(fork_turns=none, model=gpt-6.1-sol, reasoning_effort=high)分派建设和自检，完成后另行分派独立只读验收(fork_turns=none, model=gpt-6.1-sol, reasoning_effort=ultra)。未支持明确目标时停在未验收状态，不静默降级、不用当前会话替代、不称自动caseflow接入。保存真实call_id、返回的独立task_name和原会话JSONL路径；按references/tools.md绑定当前产物哈希。建设者只写建设和自检记录，不写独立pass。
先从上述显式冻结的原技术Word盘点正文、原式、原图、实施例和输入约束；新案不依赖已有测试成品。同案同源哈希且已合格的图文、定义与代码才可复用，不能套用上一案件的业务、图或数据。原流程图、结构图和示意图全保留，不计入新增结果图数量；源正文和图题已占用的阿拉伯图号为{source_numbers}，新增结果图从图{max(source_numbers, default=0)+1}起连续编号；只有正文引用而无对应图题时先人工核对，仍保守占号，不改原文。逐图结合原技术实施例，读前文—新增红字—后文，详细自然讲清工况、读图、计算依据、可复核算例、结果原因和适用判断。有原式时自然引入相应关键符号并在首次出现就地简释，保留上下标、帽号和希腊字母；无公式只按实施例解释，不强塞数学，不凑字数。每图独立“请参考图N”，原文原式原图不动；仅新增图及图下图题放全部原文之后。PNG图内禁止顶部title/suptitle、表头、图N或说明框，轴与必要图例正常。PNG、图设计manifest、渲染及证据留工作区，不放成品根目录。
在原工作区对后端算法做尽可能深入的完善，补全领域约束、异常处理、持久化、批量处理和可验证业务闭环。Web 做成精细完整、内容丰富、中文为主、高交互且具备部署条件的业务系统；所有可见模块和按钮有效，不出现数学推导和过量英文。
实际检索同类型开源项目及原始数据，核对许可、字段、单位和分布，用项目领域机理进行可复现扩充；数据量按实体、时间、频率和代表工况充分覆盖，不用复制或无约束随机数凑行数。保留内部出处、参数、种子、日志和限制，不冒充现场实测。
完成图文、系统与数据后，再实际操作最终网页录制一分多钟，不录十秒版，按本案有效操作与结果阅读自然结束，不固定60秒、不为凑时长空等、加速或截断。展示筛选、详情、业务提交、结果、历史和导出等完整使用过程。连续真实浏览器录屏，不能拼图、循环或假响应。实际测试算法、接口、保存重启、浏览器、构建和压缩包解压后的启动。
录制就绪使用本案绝对.py启动文件登记launcher/listener，并确认process_guard inspect.owned含实际监听；high自检实际执行 & $env:SCB_PRO_NODE "{Path(__file__).with_name('record.cjs')}" --check-ready --workspace "{workspace}" --plan "{workspace/'.product-v2/record-plan.json'}"，只读核验计划、真实文件和服务/登记身份，检查通过后父再按既有槽/lease/Job进入capture。此检查不启动浏览器、不写录制状态、不代表录制或视觉通过，不替代真实登录及UI就绪实测，不新增模型或审批。
录制和在线验证结束后核实并关闭本案全部专属后台，保留Codex/MCP、共享服务及其他项目。之后仅把白名单重要CSV清洗到上述数据目录；每个CSV整列删除“生成数据”“数据来源”及明确同义元数据列，保留其他字段和值，数据目录仅CSV，不删原工作区数据或数据库。
本项目交付代码、Web和数据内容不得出现：模拟、虚拟、仿真、物理仿真、参考、源文件、公式、正文。固定容器目录“模拟系统”按用户指定保留；原技术Word原样保留，许可证单独核对。禁词命中按语义修复，不能转义藏词或破坏算法。
将实际可运行的项目源码压成上述ZIP，排除所有层级README及任何针对原技术文档的解析、抽取、原文映射和分析文件，同时排除原技术文档、过程证据、日志、缓存、依赖目录与凭据。使用明确打包白名单，不复制整个工作区；业务软件必需的导入解析模块保留。原工作区被排除内容仍保留。压缩包不得依赖被排除文件或旧绝对路径。
成品根目录只能有上述原名Word和“模拟系统”文件夹；模拟系统内只能有项目源码.zip、演示视频.mp4、数据/*.csv。使用/运行/安装/部署说明及制作/原件解析/数据构造来源说明留内部工作区，排除源码ZIP，不在外面交付图表、使用说明或其他文件。原Word名称即使包含禁词，只豁免这一冻结文件名和原Word，不扩大到代码、网页或数据。
按技能运行清洗、打包、扫描、真实录制与进程收尾工具，建设自检后由独立ultra实际检查最终Word页、图表、关键视频帧和完整交付，再执行finalize；只报告有证据的完成状态。当前任务不覆盖原技能、不改旧批次、不上传GitHub、不擅自公网部署。
'''
    if base:
        prompt=f'''使用 $software-case-batch-pro 执行本案文档专用修订（scope=document-revision）。
案件：{title}
本次修订工作区：{workspace}
本次新成品目录：{output}
原技术Word（只读，冻结SHA256={source_hash}）：{source_docx}
当前交付Word（保留原输入完整basename）：{run['word']}
继承软件的旧工作区：{base['workspace']}
旧完整交付目录：{base['output']}
冻结旧complete收据SHA256：{base['receipt_sha256']}

本次仅建设和自检Word、新增结果PNG、实施例红字说明、原式符号说明、图题和全页渲染。父会话实际分派spawn_agent(fork_turns=none, model=gpt-6.1-sol, reasoning_effort=high)，之后另一个明确gpt-6.1-sol/ultra独立会话只读审核当前修订；保存真实call_id、canonical task_name和原始session JSONL及当前产物hash，建设者只写建设自检事实，独立reviewer写review.json并在final给出其精确SHA256。调用目标不支持时不能静默降级或自行验收。
结合源技术实施例实际读前文—红字—后文，逐图详细自然解释工况、读图、计算依据、可复核结果、原因和适用判断；有对应原式时自然引入关键符号并首次就地简释，保留上下标、帽号和希腊字母；无公式按实施例解释，不强塞数学、不凑字数。每图独立“请参考图N”，原文原式原图及位置保持不动，仅新增图和对应图下图题按图号放全部原文之后。新增PNG图内无顶部title/suptitle、表头、图N或说明框，正常轴和必要图例保留；核对最终PNG及Word实际尺寸图例/符号与数据一致。
PNG、图设计manifest、原式与实施例映射、渲染和当前检查证据都留本次修订工作区。按references/tools.md生成内部.product-v2/chart-manifest.json，核对Word嵌图同字节PNG、独立引用、图下caption和全页衔接，供独立ultra实际审核。
旧系统按冻结system_files完整沿用：项目源码.zip、演示视频.mp4和全部数据CSV字节不变；旧源码、六类执行日志、ZIP启动证据、原充分清洗CSV及质量事实、原录制及技术证据、数据出处和旧complete收据均冻结继承；后续原始input_csv或data-plan变化不作废完成数据。旧软件的建设模型及执行身份保留历史事实，本轮high仅证明文档修订，不伪称旧软件由本轮high建设。无需新系统建设、重新取数或录制；原软件相关证据变化时此修订继承门禁拒绝通过，交负责人重新确定受影响范围。
成品根目录仅上述原名Word和模拟系统，系统内仅项目源码.zip、演示视频.mp4、数据/*.csv，与旧系统hash完全一致。所有PNG、证据及说明在工作区；此次Word-only修订软件字节继承原包；若用户还要求删ZIP说明必须另走package revision，不扩大本次范围。源Word完整basename即使含禁词仅豁免该Word，代码、Web和CSV豁免范围不扩大。
在本次修订及旧工作区核对本案后台退出记录（process_guard stop，保留Codex/MCP及其他项目），执行scan；独立ultra实际核验当前Word全部页、PNG、正文衔接及未变系统继承证据。它写当前reviewed_files/visual_notes/limitations/reviewer_agent_id/decision/chart_snapshot/chart_reviews；完成后仅执行finalize-document-revision --workspace "{workspace}" --evidence "独立ultra当前review.json绝对路径"。保留旧finalized run、旧收据及旧交付，在本次新工作区另存document-revision收据，不重写历史通过。只报告实际证据支持的完成状态。
'''
    if base and revision_scope=='package':
        prompt=f'''使用 $software-case-batch-pro 执行授权的源码包说明专用修订，scope=package-revision。
本次工作区：{workspace}
新成品目录：{output}
原技术Word只读：{source_docx}（SHA256={source_hash}）
明确冻结最近finalized父收据：{base['workspace']}（SHA256={base['receipt_sha256']}）
保留原根Word、PNG、完整真实已阅全页证据、全部CSV及一分钟视频每个字节；只在新ZIP排除README和使用/运行/安装/部署说明、制作过程、数据构造/来源说明及原件解析材料。内部真实来源、参数、种子、生成性质和未验证范围完整保留，不伪称实测。必要第三方署名/入口/DOI/许可URL及变更指示保留，非必要制作用语不藏入LICENSES。应用成员字节不改，源码完整可启动。
新版父会话真实分派gpt-6.1-sol/high建设自检；普通返修及录制准备修复另派gpt-6.1-sol/ultra，reviewer不实现；普通独立只读验收另一个gpt-6.1-sol/ultra。本次不启用Astra low。真实call_id/agent_id/session JSONL核验，配置不是执行证据。
沿最近文档revision的inherited_system逐级追溯原完整case六类检查/录制输入/CSV输入/真实来源/旧完整审查，保留旧收据及原模型事实；不扫描全盘猜父关系。记录未登记父输出文件但不复制/删除它们。新输出严格只有原名Word和模拟系统三项，旧输出不改。
对最终新ZIP在隔离目录真实解压安装/启动并验证业务核心、部署入口、数据与导出，绑定最终ZIPhash及command/exit_code/log/sha256；记录launcher/listener身份、健康run/workspace/version和实际PID。线上验证结束后只关闭本案已核归属后台，保留Codex/MCP/共享/其他项目。只读Get-Content/rg命令不算本案后台。
完整5fps视频接触页及frame_files映射、首尾和每交互前后0.2s原帧可对未变MP4解码补证据，无需重录；Word每页已有真实已阅按同hash继承，无需重新渲染。父保存短证据索引，独立ultra检查新ZIP、包启动实际log/结果/署名及完整继承链，声明本次实际打开与合法沿用范围，写review.json并final给精确proofhash。
只执行finalize-package-revision --workspace "{workspace}" --evidence "独立ultra当前review.json"。出现任何应用代码/业务字符串、Word/PNG/视频/CSV字节变化，此专用gate拒绝；由负责人安排ultra定向返修和相应完整执行验证，不能强改hash或扩大继承。
'''
    if run.get('chart_policy')==BUILD_CHART_POLICY and (not base or revision_scope=='document'):
        prompt+='''
本次冻结chart_policy=analytical-v2：建设开始在现有图manifest安排通常4—6张有效分析图，内容需要可更多，总数无上限；保留1—2张黑白结果图，专业模型、热力、矩阵、轨迹、调度等分析图占多数。每张独立图按analysis_role=baseline_result或professional_analysis及palette=monochrome或color登记，不能把原流程图或同图面板凑成多张。始终以真实数据或可复核计算支持为先，不因数量造数据；资料不足如实登记待补，不以单张图宣称完成。每张图使用figure_preflight在实际Word宽度检查文字与线、转折、轴框及边界的冲突，high逐张实际看PNG与最终尺寸并将当前PNG哈希和具体证据写入build_selfcheck；通过后再入Word，不把已知排版缺陷交给验收者首次发现。建设内自检调整仍由high完成，交验后返修由ultra。
新增图及图下caption均不得含“示意”。PNG内无顶部title/suptitle、表头、图N、解释墙或说明框；必要矩阵行列标签、轴、图例、色标及单位保留。原文原式原图包括原有“示意”均原样保留。
在现chart-manifest每图登记question（本图回答的具体问题）、data_source（可定位原件/数据/计算证据的来源）、chart_type和labels（只登记真实非空可见标签，不需抄自动数值刻度，不登记空轴标签或空字符串），不另建重复台账。high提交前实际运行contracts.chart_snapshot(workspace,Path(run['word']),run)，核对图清单与Word当前字节、嵌图和图题绑定；缺项在建设内修齐并重核。这是既有自检中的便宜结构核验，不新增模型、审批或渲染，不替代逐图/全页视觉。独立review必须绑定当前PNG，逐图给meaning/data/legibility/layout/explanation具体非空依据、no_schematic=true及no_schematic_evidence；meaning说明相对原图的新增价值，explanation说明实施例前文—红字—后文衔接。实际打开PNG与Word上下文检查无“示意”、布局和数据，不能把manifest文字扫描称为图片文字识别。
'''
    elif base and revision_scope=='package':
        prompt+='\n本次package revision沿用父chart_policy='+str(base_run.get('chart_policy','未标记历史2–6'))+'，不新增或重制图、不用新政策重写父通过。\n'
    prompt+=f'''\n以下均为以后每个授权案件的通用要求，不限于本次测试案：完整中文业务系统/领域算法和充分数据、原文原式原图保留、详细实施例红字和原式符号、图内无标题而Word图下有图题、一分多钟连续平顺真实实操、真实独立审核、录后核归属关闭后台再清洗重要CSV、源码ZIP排除使用说明及制作/原件解析/来源构造说明和模拟性质文案。
通用状态验收：任何业务状态操作后，按本项目实际可见项核对列表、详情、统计、摘要和日志属于同一对象/版本；刷新保持用户筛选、排序及合法当前分页，关闭详情抽屉后迟到异步请求不得重新打开，连续/逆向操作也核验。不硬编码某个测试案的业务字段或动作。
新版默认日常正式成果根：{default_output_root()}；按批次/案件集中，候选也在同卷私有.staging以便整案原子发布。当前显式指定的候选仍是{output}；用户明确指定其他目录时优先遵循。每周仅将已完成成品核验归档到F:\\研发图表；历史和活跃批次路径不改，归档按references/archive.md先复制校验、更新位置索引再清理对应源。TEMP和工具缓存仍D:\\codex+。
原模型角色继续保留：返修及录制准备修复必须另派gpt-6.1-sol/ultra，独立reviewer只读不实现；原high建设及每轮ultra真实调用/快照均保留。仅明确原加急模式且真实当前批/案user消息核验时才Astra/low；提速不换模型。本次普通ultra。finalize只冻结验收候选，随后父publish --destination 全新同卷正式目录进行整案原子发布，保留intent和独立publish receipt；未publish不称正式交付。
'''
    if run.get('data_policy_version')=='neutral-expanded-v1' and not base:
        prompt+='''\n建设开始在现有data-plan制定足量数据：对现有不足版本先统计清洗后主要明细有效规模，以约2倍作为扩容起点，按业务粒度和性能说明调整，维表不机械翻倍；新案按领域对象、时间跨度及关键事件覆盖安排。使用批量可复现计算，不复制换号凑行。导出文件名、表头、备注和单元格不得有真实或编造的地名、公司名称、人名，统一稳定编号，保持跨表与Web下载一致。原始来源、性质和映射只留内部，不伪称实测。先用data_preflight实际检查规模、引用和专名，再清洗输出并核对初始化、分页和导出；沿现有数据清洗记录绑定当前文件哈希，见references/system-data.md。\n'''
    if not base:
        prompt+='\n建设开始实际读取references/web-design.md和references/system-data.md：从本案原材料形成角色、核心任务、主工作区、关键交互的短设计画像，按业务主对象设计页面结构，不仅换颜色；沿已有source_trace、calculation_trace_map、coverage_matrix绑定原段/原式→实际函数→真实边界测试，不新增第二张台账。同一次high browser自检实际主页面、关键详情、空状态和错误提示的可见文字，调用现有record.cjs.auditUiText（共用references/ui-policy.json），在录制前修齐，不新增preflight模型；不展示“经计算生成数据”等制作过程说明，保留真实“生成报告/计算结果/预测结果”，不伪称实测或已上线，不自动改写原文或源码。建设自检在原有映射与六类检查中记录原定义→具体接受/拒绝断言→最终同引擎派生结果重算；先用最小业务闭环和关键反例调用真实最终函数，按源机制核验执行边界、集合门槛、真实输出误差和输入传递；同一次high内以当前部署入口实跑启动、健康身份、核心接口、必要持久化和停止/端口释放，通过后再扩量及制作依赖图文和录制；只前移便宜必要自检，不要求先完成全部后端，已有合格数据、计算和图文按原同hash规则复用，业务失败立即停止依赖生成、保留未变成果和独立验收，不以结构校验或成功状态代替业务正确，不新增台账或模型阶段。\n'
    if not base or revision_scope=='package':
        prompt+='''\n建设自检及最终源码ZIP解压验证沿既有检查核验部署生命周期：PowerShell输出CIM/JSON前在子进程内明确[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)，Python读取明确encoding='utf-8',errors='strict'并检查returncode；编码异常或非零退出如实失败，保留stdout/stderr，不用替换解码或吞错。启动返回后先保有Popen、PID、创建时间和本案entry归属再做探查，finally中失败也精确清退已核归属子树，无法核准时记录cleanup_pending，保留Codex/MCP及其他项目，不放宽process_guard边界。启动/停止使用同一真实entry，按当前部署目录解析绝对路径，入口变更时同步；建设内实际跑启动→停止→端口释放并核PID退出，最终ZIP解压后核对同一入口及清退效果、绑定ZIP哈希。命令、日志和哈希沿原有检查保存，不新增模型阶段、审批或全量重复测试。\n'''
    if not base:
        prompt+='''\n本次录制前必须在现有.product-v2/build-checks.json按references/tools.md绑定algorithm/api/persistence/browser/build五类真实日志，各自非空input_files含实际代码、测试脚本及固定夹具，test_files列实际测试入口；顶层run_id/source_docx_sha256/implementation_hashes绑定本案当前源与source-manifest。check-build只读核验，失败或陈旧在capture前拒绝，只重做依赖变化的检查。规范化反例必须走最终消费函数/API而非只测helper。父接续先proflow.py status读取收据：已capture进入evidence，technical_ready进入待完成独立审查，published未变结束；不反复录制、编码、解码或重看已实际验收且依赖未变的部分，finalize完整门禁保持。\n'''
    prompt+='\n充分清洗数据一版真实通过后按references/tools.md和U14完成成品规则复用，不因后续代码、data-plan、工具、解释器或原始input_csv变化重审/扩量/生成/清洗，不新增逐项复用表、不重写原收据；当前软件算法及派生复算使用内部隔离输入/结果，完成CSV不自动覆盖。首次质量仍完整，CSV自身损坏/缺失/变化或明确数据错误才针对处理。\n'
    (record.parent/'深化命令词.txt').write_text(prompt, encoding='utf-8')
    return run

def cleanup_ready(workspace):
    receipt = read_json(workspace/'.product-v2/cleanup.json')
    if receipt.get('status') != 'stopped' or receipt.get('remaining'):
        raise ValueError('Run process_guard stop and resolve cleanup_pending first')
    # A stale receipt cannot license cleanup while the service was restarted.
    from process_guard import owned_processes, inventory
    if owned_processes(workspace, inventory()):
        raise ValueError('Case processes are still live; cleanup receipt is stale')

def clean_csv(workspace, output, manifest_path):
    """Transactional, streaming CSV selection. Source bytes never change."""
    workspace, output = no_links(workspace), no_links(output)
    spec = read_json(manifest_path)
    entries = spec.get('files', [])
    if not entries:
        raise ValueError('An explicit important-CSV allowlist is required')
    system_dir = no_links(output/SYSTEM)
    system_dir.mkdir(parents=True, exist_ok=True)
    destination = no_links(system_dir/'数据')
    if destination.exists():
        raise ValueError('Clean data already exists; preserve it and choose a new delivery version')
    staging = no_links(workspace/'.product-v2/staging')
    staging.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='data-', dir=staging))
    receipts, names = [], set()
    try:
        for entry in entries:
            src = inside(workspace, entry['path'])
            name = entry.get('name', src.name)
            if Path(name).name != name or '/' in name or '\\' in name or ':' in name or not name.lower().endswith('.csv'):
                raise ValueError(f'CSV output must be a simple filename: {name}')
            if name.casefold() in names or forbidden(name):
                raise ValueError(f'Duplicate or restricted CSV name: {name}')
            names.add(name.casefold())
            if not str(entry.get('reason','')).strip():
                raise ValueError(f'Missing important-data reason: {name}')
            before = digest(src)
            encoding = entry.get('encoding','utf-8-sig')
            delimiter = entry.get('delimiter',',')
            if len(delimiter) != 1:
                raise ValueError('CSV delimiter must be one character')
            with src.open(encoding=encoding, newline='') as input_stream, (stage/name).open('w',encoding='utf-8-sig',newline='') as target:
                reader = csv.reader(input_stream, delimiter=delimiter, strict=True)
                header = next(reader, None)
                if not header or any(not normalized(x) for x in header) or len({normalized(x) for x in header}) != len(header):
                    raise ValueError(f'Empty/duplicate header: {src}')
                remove = [i for i,value in enumerate(header) if normalized(value) in META_COLUMNS]
                keep = [i for i in range(len(header)) if i not in remove]
                if not keep:
                    raise ValueError(f'No business columns remain: {src}')
                columns = [header[i] for i in keep]
                if any(forbidden(x) for x in columns):
                    raise ValueError(f'Restricted business header needs a semantic fix: {src}')
                keys = entry.get('primary_key', [])
                if not isinstance(keys, list) or not keys or any(k not in columns for k in keys):
                    raise ValueError(f'Explicit retained primary_key required: {src}')
                key_indices = [header.index(k) for k in keys]
                seen, count = set(), 0
                writer = csv.writer(target)
                writer.writerow(columns)
                for line_number, row in enumerate(reader, start=2):
                    if len(row) != len(header):
                        raise ValueError(f'Ragged CSV at {src}:{line_number}')
                    cleaned = [row[i] for i in keep]
                    for column, value in zip(columns,cleaned):
                        if forbidden(value):
                            raise ValueError(f'Restricted cell at {src}:{line_number}, column {column}')
                    key = tuple(row[i] for i in key_indices)
                    if any(not x.strip() for x in key) or key in seen:
                        raise ValueError(f'Empty/duplicate key at {src}:{line_number}')
                    seen.add(key)
                    writer.writerow(cleaned)
                    count += 1
                if count < max(1, int(entry.get('min_rows',1))):
                    raise ValueError(f'Insufficient rows: {src} ({count})')
            if digest(src) != before:
                raise ValueError(f'CSV changed during cleaning: {src}')
            receipts.append({'input':str(src),'input_sha256':before,'name':name,'rows':count,
                'columns':columns,'removed_columns':[header[i] for i in remove],
                'sha256':digest(stage/name),'reason':entry['reason']})
        # No existing tree is deleted or replaced, including on a retry.
        if destination.exists():
            raise ValueError('Data destination appeared during export')
        stage.rename(destination)
    except Exception:
        # Keep failed output for diagnosis; no partial data directory is published.
        raise
    receipt = {'at':utc(),'status':'cleaned','output':str(destination),'files':receipts}
    write_json(workspace/'.product-v2/data-cleaning.json',receipt)
    return receipt

def completed_data_quality(workspace,cleaning,current_files):
    """Reuse the original sufficient, cleaned CSV result; no new plan binding."""
    checks=workspace/'.product-v2/build-checks.json'
    if checks.is_file() and read_json(checks).get('data_material_error'):
        raise ValueError('Known material data error requires targeted correction')
    quality=cleaning.get('quality')
    if not isinstance(quality,dict) or quality.get('policy')!='neutral-expanded-v1':return None
    audit=quality.get('audit');expansion=quality.get('expansion')
    if (not isinstance(audit,dict) or not isinstance(expansion,dict) or
            audit.get('data_status')!='pass' or audit.get('findings') or
            expansion.get('expansion_status')!='pass' or expansion.get('failures')):return None
    recorded=audit.get('files')
    if not isinstance(recorded,dict) or not recorded or not all(isinstance(v,dict) for v in recorded.values()):return None
    if ({name:item.get('sha256') for name,item in recorded.items()}!=current_files or
            {f['name']:f['sha256'] for f in cleaning['files']}!=current_files):return None
    if 'result_sha256' in quality:
        original={key:quality.get(key) for key in ('policy','plan_sha256','audit','expansion')}
        actual=hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
        if quality['result_sha256']!=actual:return None
    return quality


def check_data_quality(workspace,output,update=False):
    """Completed CSVs retain their actual original pass; first audits stay full."""
    run=read_json(inside(workspace,'.product-v2/run.json'));policy=run.get('data_policy_version')
    if policy is None:
        checks=workspace/'.product-v2/build-checks.json'
        if checks.is_file() and read_json(checks).get('data_material_error'):
            raise ValueError('Known material data error requires targeted correction')
        return None
    if policy!='neutral-expanded-v1':raise ValueError('Unknown frozen data policy')
    cleaning_path=inside(workspace,'.product-v2/data-cleaning.json');cleaning=read_json(cleaning_path)
    if update and (workspace/'.product-v2/final-receipt.json').exists():raise ValueError('Finalized evidence is frozen')
    directory=no_links(output/SYSTEM/'数据');paths=sorted(directory.iterdir())
    if not paths or any(not p.is_file() or p.suffix.lower()!='.csv' for p in paths):
        raise ValueError('Selected important CSVs required for data quality checks')
    for path in paths:no_links(path)
    current_files={p.name:digest(p) for p in paths}
    completed=completed_data_quality(workspace,cleaning,current_files)
    if completed is not None:return completed
    from data_preflight import audit_csv_exports,check_expansion
    plan_path=inside(workspace,'.product-v2/data-plan.json');plan_bytes=plan_path.read_bytes()
    plan=json.loads(plan_bytes.decode('utf-8-sig'));plan_sha=hashlib.sha256(plan_bytes).hexdigest()
    audit=audit_csv_exports(paths,plan['export_schema'],known_names=plan.get('known_names',[]),
                            allowed_terms=plan.get('allowed_terms',[]),name_review=plan.get('name_review',{}))
    expansion=check_expansion(plan.get('baseline_metrics'),audit,plan['expansion_plan'])
    if audit.get('data_status')!='pass' or expansion.get('expansion_status')!='pass':
        raise ValueError('Construction data checks incomplete: '+json.dumps(
            {'status':audit.get('data_status'),'findings':audit.get('findings',[])[:10],
             'name_review_required':audit.get('name_review_required',[]),'expansion':expansion},ensure_ascii=False))
    if ({f['name']:f['sha256'] for f in cleaning['files']}!=current_files or
            {name:item['sha256'] for name,item in audit['files'].items()}!=current_files):
        raise ValueError('Data checks must bind the actual cleaned CSV snapshot')
    if digest(plan_path)!=plan_sha:raise ValueError('Data plan changed during quality verification')
    quality={'policy':policy,'plan_sha256':plan_sha,'audit':audit,'expansion':expansion}
    if update:
        cleaning['quality']=quality;write_json(cleaning_path,cleaning)
    elif cleaning.get('quality')!=quality:
        raise ValueError('Run check-data on the current exports before requesting independent acceptance')
    return quality


def excluded_source(relative, extra=()):
    from package_policy import excluded_delivery_document
    document_reason=excluded_delivery_document(relative)
    if document_reason: return document_reason
    path = PurePosixPath(relative.replace('\\','/'))
    parts = [p.casefold() for p in path.parts]
    name = parts[-1] if parts else ''
    if any(p in EXCLUDED_DIRS for p in parts) or any(p.startswith('readme') or p.startswith('read-me') for p in parts):
        return 'readme-or-internal-directory'
    if (name in EXCLUDED_NAMES or re.match(r'^(source[-_]analysis|docx[-_](extract|analysis)|extracted[-_]text|document[-_]text|原文解析|文档解析|解析报告)',name)
            or path.suffix.lower() in {'.docx','.doc','.pdf','.log','.pyc','.pyo','.db','.sqlite','.sqlite3','.pem','.key'}):
        return 'document-analysis-or-runtime-file'
    if name in {'.env','credentials.json','token.json','tokens.json','id_rsa','id_ed25519'}:
        return 'credential-file'
    for pattern in extra:
        if path.match(pattern) or relative == pattern or relative.startswith(pattern.rstrip('/')+'/'):
            return 'explicit-exclusion'
    return None

def pack_source(workspace, output, manifest_path):
    spec = read_json(manifest_path)
    files = spec.get('files',[])
    if not isinstance(files,list) or not files:
        raise ValueError('Explicit application file allowlist required')
    target = no_links(output/SYSTEM/'项目源码.zip')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        raise ValueError('Source archive exists; use a new delivery version')
    sources, omitted, names = [], [], set()
    for rel in files:
        rel = str(rel).replace('\\','/')
        src = inside(workspace,rel)
        why = excluded_source(rel,spec.get('exclude',[]))
        if why:
            omitted.append({'path':rel,'reason':why})
            continue
        if rel.casefold() in names or forbidden(rel):
            raise ValueError(f'Duplicate/restricted source path: {rel}')
        names.add(rel.casefold())
        legal=PurePosixPath(rel).name.upper().startswith(('LICENSE','NOTICE','COPYING')) or 'licenses' in [p.casefold() for p in PurePosixPath(rel).parts]
        if not legal and scan_text(rel,src.read_bytes()):
            raise ValueError('Source delivery text requires a semantic fix before packing: '+rel)
        sources.append((rel,src,digest(src)))
    if not sources:
        raise ValueError('No application files remain')
    staging=no_links(workspace/'.product-v2/staging');staging.mkdir(parents=True,exist_ok=True)
    temp_path = no_links(staging/('source-'+uuid.uuid4().hex+'.zip'))
    if temp_path.exists():
        raise ValueError('Partial archive exists; inspect it before retrying')
    with zipfile.ZipFile(temp_path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for rel,src,sha in sources:
            archive.write(src,rel)
            if digest(src) != sha:
                raise ValueError(f'Source changed while packing: {rel}')
    with zipfile.ZipFile(temp_path) as archive:
        if archive.testzip():
            raise ValueError('Archive CRC verification failed')
        import hashlib
        for rel,_,sha in sources:
            if hashlib.sha256(archive.read(rel)).hexdigest() != sha:
                raise ValueError(f'Archive content differs: {rel}')
    os.rename(temp_path,target)
    receipt={'at':utc(),'archive':str(target),'sha256':digest(target),
             'files':{rel:sha for rel,_,sha in sources},'excluded':omitted,
             'excluded_patterns':spec.get('exclude',[])}
    write_json(workspace/'.product-v2/source-package.json',receipt)
    return receipt

def scan_text(name,data):
    hits=[]
    suffix=Path(name).suffix.lower()
    if suffix in TEXT_SUFFIXES or Path(name).name.casefold() in {'dockerfile','makefile','procfile'}:
        try:
            text=data.decode('utf-8-sig')
        except UnicodeDecodeError:
            try: text=data.decode('gb18030')
            except UnicodeDecodeError:
                return [{'path':name,'error':'Text encoding is unreadable'}]
        from package_policy import audit_delivery_text
        hits.extend(audit_delivery_text(name,text))
        for number,line in enumerate(text.splitlines(),1):
            words=forbidden(line)
            if words: hits.append({'path':name,'line':number,'words':words})
    return hits

def scan_delivery(output, word_name=None):
    output=no_links(output)
    hits, licenses=[],[]
    for path in sorted(output.rglob('*')):
        no_links(path)
        if not path.is_file(): continue
        relative=path.relative_to(output).as_posix()
        # This exact fixed container is the user's explicit exception.
        checked='/'.join(p for i,p in enumerate(relative.split('/')) if not(i==0 and p==SYSTEM))
        original_word = word_name is not None and relative == word_name and path.suffix.lower()=='.docx'
        if not original_word and forbidden(checked): hits.append({'path':relative,'words':forbidden(checked)})
        if path.suffix.lower()=='.zip':
            with zipfile.ZipFile(path) as archive:
                seen=set()
                for member in archive.infolist():
                    rel=member.filename
                    p=PurePosixPath(rel)
                    if p.is_absolute() or '..' in p.parts or '\\' in rel or ':' in rel or rel.casefold() in seen or (member.external_attr >>16)&0o170000==0o120000:
                        hits.append({'path':relative+'!'+rel,'error':'Unsafe/duplicate archive member'})
                        continue
                    seen.add(rel.casefold())
                    if member.is_dir(): continue
                    why=excluded_source(rel)
                    if why: hits.append({'path':relative+'!'+rel,'error':why})
                    if forbidden(rel): hits.append({'path':relative+'!'+rel,'words':forbidden(rel)})
                    legal_name=p.name.upper().startswith(('LICENSE','NOTICE','COPYING')) or any(x.casefold()=='licenses' for x in p.parts)
                    if legal_name and p.suffix.lower() in {'','.txt','.md','.rst'}:
                        licenses.append(relative+'!'+rel)
                        # Required attribution is retained, but this container
                        # cannot hide unrelated production/data-construction prose.
                        from package_policy import audit_delivery_text
                        text=archive.read(member).decode('utf-8-sig')
                        hits.extend(audit_delivery_text(relative+'!'+rel,text))
                        continue
                    if p.suffix.lower() in {'.zip','.7z','.rar','.gz','.tar'}:
                        hits.append({'path':relative+'!'+rel,'error':'Nested archives must be unpacked for review'})
                        continue
                    hits.extend(scan_text(relative+'!'+rel,archive.read(member)))
        elif '数据' in path.relative_to(output).parts:
            if path.suffix.lower()!='.csv': hits.append({'path':relative,'error':'Data folder accepts only CSV'})
            hits.extend(scan_text(relative,path.read_bytes()))
            if path.suffix.lower()=='.csv':
                with path.open(encoding='utf-8-sig',newline='') as f:
                    header=next(csv.reader(f),[])
                    if any(normalized(c) in META_COLUMNS for c in header):
                        hits.append({'path':relative,'error':'Forbidden metadata column remains'})
        else:
            hits.extend(scan_text(relative,path.read_bytes()) if path.suffix.lower() in TEXT_SUFFIXES else [])
    return {'passed':not hits,'hits':hits,'license_exceptions':licenses,'files':file_map(output)}

def completed_recording(workspace,record,video,hash_file=digest):
    """Check completed media itself; later software/data edits do not stale it.

    This reuses original technical facts, never decodes/encodes or approves
    visuals. Current code/data correctness remains in its own existing gates.
    """
    if record.get('passed') is not True or record.get('errors') or record.get('sha256')!=hash_file(video):
        raise ValueError('Successful unchanged completed video required')
    checks_path=workspace/'.product-v2/build-checks.json'
    if checks_path.is_file():
        major=read_json(checks_path).get('video_material_change')
        if major:
            raise ValueError('Video requires replacement for a recorded major system/operation change: '+str(major))
    receipt=inside(workspace,'.product-v2/recording.json')
    controlled=read_json(inside(workspace,'.product-v2/controlled-video.json'))
    timeline=no_links(controlled['timeline'])
    if workspace not in timeline.parents or hash_file(timeline)!=controlled.get('sha256'):
        raise ValueError('Original completed video technical timeline missing or changed')
    facts=read_json(timeline);binding=facts.get('recording_receipt',{})
    if (facts.get('decode_ok') is not True or facts.get('sample_fps')!=5 or
            facts.get('video_sha256')!=record['sha256'] or
            binding.get('sha256')!=hash_file(receipt) or no_links(binding.get('path',''))!=receipt):
        raise ValueError('Original completed video technical/operation binding changed')
    return {'video_completed':True,'timeline':str(timeline),
            'scope':'Original completed video only; current source/data/Word and independent review keep their own checks.'}


def finalize(workspace, output, evidence_path):
    if (workspace/'.product-v2/final-receipt.json').exists():
        raise ValueError('Finalized receipt is immutable; create a separate revision')
    proof=read_json(evidence_path)
    if not isinstance(proof,dict):raise ValueError('Independent evidence must be a JSON object')
    execution_checks(proof.get('checks'))  # Fail before expensive artifact checks.
    from contracts import delivery_layout, chart_snapshot, model_review
    run=read_json(workspace/'.product-v2/run.json')
    record=read_json(workspace/'.product-v2/recording.json')
    from contracts import construction_checks
    current_checks=construction_checks(workspace,run,record.get('plan_path'))
    word=delivery_layout(output,run)
    charts=chart_snapshot(workspace,word,run)
    cleanup_ready(workspace)
    scanned=scan_delivery(output,run['word_name'])
    if not scanned['passed']: raise ValueError('Delivery scan failed: '+json.dumps(scanned['hits'][:10],ensure_ascii=False))
    clean=read_json(workspace/'.product-v2/data-cleaning.json')
    check_data_quality(workspace,output)
    actual=file_map(output/SYSTEM/'数据')
    if actual!={f['name']:f['sha256'] for f in clean['files']}: raise ValueError('Clean CSV snapshot changed')
    package=read_json(workspace/'.product-v2/source-package.json')
    if package['sha256']!=digest(output/SYSTEM/'项目源码.zip'): raise ValueError('Source archive changed')
    for rel,sha in package['files'].items():
        if digest(inside(workspace,rel))!=sha: raise ValueError('Source changed after packaging: '+rel)
    if current_checks['required']:
        captured_checks=record.get('construction_checks',{})
        if (captured_checks.get('status')!='ready' or captured_checks.get('run_id')!=run['run_id'] or
                captured_checks.get('source_docx_sha256')!=run['source_docx_sha256']):
            raise ValueError('Recording lacks its original current-run construction admission')
    from media_evidence import validate_recording_duration
    validate_recording_duration(record,run.get('recording_policy_version','legacy-fixed-v1'))
    if record.get('passed') is not True or record.get('sha256')!=digest(output/SYSTEM/'演示视频.mp4'):
        raise ValueError('Current successful one-minute recording required')
    proof=read_json(evidence_path)
    completed_recording(workspace,record,output/SYSTEM/'演示视频.mp4')
    controlled=read_json(workspace/'.product-v2/controlled-video.json')
    from media_evidence import validate as validate_video_evidence
    timeline=no_links(controlled['timeline'])
    if proof.get('video_timeline_sha256')!=controlled['sha256'] or digest(timeline)!=controlled['sha256']:
        raise ValueError('Final review must bind the complete controlled 5fps timeline')
    validate_video_evidence(workspace,timeline,output/SYSTEM/'演示视频.mp4',workspace/'.product-v2/recording.json')
    needed={'algorithm','api','persistence','browser','build','package_startup'}
    checks=proof.get('checks',[])
    execution_checks(checks)
    for check in checks:
        log=inside(workspace,check['log'])
        if check.get('exit_code')!=0 or not check.get('command') or log.stat().st_size==0 or check.get('sha256')!=digest(log):
            raise ValueError('Missing/failed/stale execution log: '+check['kind'])
    if proof.get('reviewed_files')!=scanned['files'] or not proof.get('visual_notes') or not proof.get('limitations'):
        raise ValueError('Current delivery snapshot, actual visual notes and limits required')
    # The reviewer must bind runtime tests to the current delivered archive too.
    if proof.get('source_zip_sha256')!=package['sha256']:
        raise ValueError('Package startup check is not bound to this archive')
    provenance=read_json(workspace/'.product-v2/data-provenance.json')
    if not provenance.get('nature') or not provenance.get('sources') or not provenance.get('validation'):
        raise ValueError('Internal data nature, sourcing attempts and validation record required')
    dispatch=model_review(workspace,proof,scanned['files'],charts,evidence_path)
    receipt={'status':'complete','delivery_state':'verified-candidate','at':utc(),'files':scanned['files'],
             'schema_version':2,'source_docx_sha256':run['source_docx_sha256'],
             'chart_snapshot':charts,'verified_dispatch':dispatch,
             'execution_evidence':str(evidence_path),'evidence_sha256':digest(evidence_path),
             'limitations':proof['limitations'],'checks':checks,'license_exceptions':scanned['license_exceptions']}
    write_json(workspace/'.product-v2/final-receipt.json',receipt)
    return receipt

def workflow_status(workspace,output,run,plan_path=None,evidence_path=None):
    """Summarize existing receipts, never perform a stage or sign a review.

    Hash each inspected path once per request. Media readiness is limited to
    receipt/video/timeline bindings; finalization still checks all frame bytes.
    """
    hashes={};steps={};pointers=[];prior_execution_doc={}
    def sha(path):
        path=no_links(path)
        if path not in hashes:hashes[path]=digest(path)
        return hashes[path]
    def receipt(name):
        path=workspace/'.product-v2'/name
        if not path.is_file():return None,path
        try:
            value=read_json(path)
            return (value if isinstance(value,dict) else {'_read_error':'Receipt must be a JSON object'}),path
        except (ValueError,OSError) as exc:return {'_read_error':str(exc)},path
    def bound(path,expected,root):
        path=no_links(path)
        if root not in path.parents:raise ValueError('Status dependency escaped its root')
        return path.is_file() and isinstance(expected,str) and sha(path)==expected
    def inputs_current(inputs):
        if not isinstance(inputs,dict) or not inputs:return ['missing immutable input bindings']
        changed=[]
        for rel,expected in inputs.items():
            path=inside(workspace,rel,must_exist=False)
            if not bound(path,expected,workspace):changed.append(rel)
        return changed
    def summarize(name,reader):
        try:steps[name]=reader()
        except (ValueError,OSError,KeyError,TypeError) as exc:
            steps[name]={'state':'unknown','reason':str(exc)}
    final,final_path=receipt('final-receipt.json')
    if final and '_read_error' in final:steps['independent_review']={'state':'unknown','reason':final['_read_error']}
    current_files=None
    if final and '_read_error' not in final:
        current_files={p.relative_to(output).as_posix():sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
        completed=False;proof_matches=False;review_error=None;proof={}
        try:
            proof_path=Path(final['execution_evidence'])
            proof_path=no_links(proof_path) if proof_path.is_absolute() else inside(workspace,proof_path)
            proof_matches=bound(proof_path,final.get('evidence_sha256'),workspace)
            if proof_matches:proof=read_json(proof_path)
            if (final.get('status')=='complete' and current_files==final.get('files') and proof_matches):
                from contracts import delivery_layout, final_review_binding
                if (not isinstance(proof,dict) or proof.get('reviewed_files')!=current_files or
                        not proof.get('visual_notes') or not proof.get('limitations') or
                        not isinstance(final.get('chart_snapshot'),dict)):
                    raise ValueError('Final receipt lacks its current independent review facts')
                scope=final.get('scope')
                if scope not in {None,'document-revision','package-revision'}:
                    raise ValueError('Unknown final review scope')
                checks=proof.get('checks',[])
                needed={'package_startup'} if scope=='package-revision' else {'algorithm','api','persistence','browser','build','package_startup'}
                if scope!='document-revision':
                    if (not isinstance(checks,list) or len(checks)!=len(needed) or
                            not all(isinstance(c,dict) for c in checks) or
                            {str(c.get('kind')) for c in checks}!=needed or final.get('checks')!=checks):
                        raise ValueError('Final review lacks its required execution checks')
                    for check in checks:
                        log=inside(workspace,check['log'])
                        if (type(check.get('exit_code')) is not int or check['exit_code']!=0 or
                                not check.get('command') or log.stat().st_size==0 or
                                not bound(log,check.get('sha256'),workspace)):
                            raise ValueError('Final review execution fact is missing/failed/changed: '+check['kind'])
                    if proof.get('source_zip_sha256')!=current_files.get(SYSTEM+'/项目源码.zip'):
                        raise ValueError('Final review archive binding changed')
                if scope is None:
                    controlled,_=receipt('controlled-video.json')
                    if (not controlled or proof.get('video_timeline_sha256')!=controlled.get('sha256') or
                            not bound(controlled['timeline'],controlled.get('sha256'),workspace)):
                        raise ValueError('Final review controlled timeline binding changed')
                elif not final.get('inherited_system') or not final.get('inherited_checks'):
                    raise ValueError('Final revision lacks its recorded inheritance')
                # Authenticate saved calls and the exact latest reviewer final;
                # use the frozen chart snapshot without inspecting charts/frames.
                dispatch=final_review_binding(workspace,proof,current_files,final['chart_snapshot'],proof_path,
                                              final.get('verified_dispatch'),hash_file=sha)
                if dispatch!=final.get('verified_dispatch'):
                    raise ValueError('Final receipt actual independent dispatch binding changed')
                delivery_layout(output,run)
                completed=sha(no_links(run['source_docx']))==run['source_docx_sha256']
        except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
            review_error=str(exc)
        publication,pub_path=receipt('publish-receipt.json')
        if (completed and run.get('status')=='published' and publication and publication.get('status')=='published' and
                publication.get('files')==current_files and publication.get('source_receipt_sha256')==sha(final_path)):
            return {'kind':'workflow-status','workspace':str(workspace),'run_id':run['run_id'],
                    'state':'published','next_actions':[],'last_completed':'published',
                    'independent_visual_review':'verified','receipt':str(pub_path),
                    'verification_scope':'Current published artifact hashes and recorded final-proof/publication bindings; no stage was rerun.'}
        changed_artifacts=[p for p in set(current_files)|set(final.get('files',{}))
                           if current_files.get(p)!=final.get('files',{}).get(p)]
        steps['independent_review']={'state':'verified' if completed else 'stale' if changed_artifacts or not proof_matches else 'unknown',
                                    'reason':review_error,
                                    'changed_artifacts':changed_artifacts,
                                    'proof_sha256':final.get('evidence_sha256')}
        if proof_matches and isinstance(proof,dict):
            prior_execution_doc=proof
            pointers.append({'path':str(proof_path),'sha256':sha(proof_path),'reviewer_agent_id':proof.get('reviewer_agent_id'),
                             'reviewed_evidence':proof.get('reviewed_evidence',[]),
                             'status':'recorded-final-proof','instruction':'Reuse only actually reviewed unchanged dependencies; changed product is not approved by this pointer.'})
    if evidence_path:
        path=no_links(evidence_path)
        if workspace not in path.parents:raise ValueError('Status review pointer must stay inside the workspace')
        proof=read_json(path)
        pointers.append({'path':str(path),'sha256':sha(path),'reviewer_agent_id':proof.get('reviewer_agent_id'),
                         'reviewed_evidence':proof.get('reviewed_evidence',[]),'decision':proof.get('decision'),
                         'status':'pointer-only-not-authenticated','instruction':'This pointer does not attest actual reading or independent acceptance.'})
    def data():
        value,path=receipt('data-cleaning.json')
        if not value:return {'state':'not_started'}
        if '_read_error' in value:return {'state':'unknown','reason':value['_read_error']}
        files=value.get('files',[])
        if value.get('status')!='cleaned' or not files:return {'state':'failed'}
        changed=[]
        for item in files:
            if not bound(output/SYSTEM/'数据'/item['name'],item['sha256'],output):changed.append('数据/'+item['name'])
        directory=output/SYSTEM/'数据'
        actual={p.name for p in directory.iterdir()} if directory.is_dir() else set()
        if actual!={item['name'] for item in files}:changed.append('CSV member set')
        if changed:return {'state':'stale','changed_dependencies':changed,'receipt':str(path)}
        policy=run.get('data_policy_version')
        if policy not in {None,'neutral-expanded-v1'}:raise ValueError('Unknown frozen data policy')
        quality=completed_data_quality(workspace,value,{item['name']:item['sha256'] for item in files})
        completed=policy is None or quality is not None
        return {'state':'completed' if completed else 'cleaned','data_completed':completed,
                'next_action':None if completed else 'check-data','changed_dependencies':[],'receipt':str(path)}
    def package():
        value,path=receipt('source-package.json')
        if not value:return {'state':'not_started'}
        if '_read_error' in value:return {'state':'unknown','reason':value['_read_error']}
        changed=inputs_current(value.get('files'))
        if not bound(output/SYSTEM/'项目源码.zip',value.get('sha256'),output):changed.append('项目源码.zip')
        return {'state':'stale' if changed else 'completed','changed_dependencies':changed,'receipt':str(path)}
    summarize('data',data);summarize('source_package',package)
    recording,recording_path=receipt('recording.json')
    pending,pending_path=receipt('capture-pending.json')
    capture=None
    def admission_current(value):
        if 'construction_check_policy_version' not in run:return True
        from contracts import CONSTRUCTION_POLICY
        if run['construction_check_policy_version']!=CONSTRUCTION_POLICY:
            raise ValueError('Unknown construction check policy')
        admission=value.get('construction_checks',{})
        return (isinstance(admission,dict) and admission.get('status')=='ready' and
                admission.get('run_id')==run['run_id'] and
                admission.get('source_docx_sha256')==run['source_docx_sha256'])
    def original_capture():
        nonlocal capture
        if not pending:return {'state':'unknown','reason':'No original capture receipt is available; do not repeat business automatically'}
        if '_read_error' in pending:return {'state':'unknown','reason':pending['_read_error']}
        if pending.get('status') not in {None,'captured'} or not pending.get('sha256'):
            return {'state':'unknown','reason':'Capture is still running or did not save a successful receipt'}
        path=no_links(pending['path'])
        if not bound(path,pending['sha256'],workspace):return {'state':'unknown','reason':'Capture receipt missing or changed'}
        capture=read_json(path)
        if capture.get('status')!='captured' or capture.get('errors'):
            return {'state':'failed','reason':'Capture has recorded failure; inspect actual business effects before retrying'}
        if capture.get('workspace')!=str(workspace) or capture.get('run_id')!=run['run_id']:
            return {'state':'unknown','reason':'Capture belongs to a different run'}
        if not admission_current(capture):
            return {'state':'unknown','reason':'Capture lacks its current-run construction admission; inspect before any business replay'}
        changed=inputs_current(capture.get('inputs'))
        if not bound(capture['rawPath'],capture.get('raw_sha256'),workspace):
            return {'state':'unknown','reason':'Original capture missing or changed; no automatic business replay','changed_dependencies':['raw capture']}
        active_plan=plan_path or capture.get('plan_path') or workspace/'.product-v2/record-plan.json'
        if capture.get('plan_sha256') and not bound(active_plan,capture['plan_sha256'],workspace):changed.append('recording plan')
        return {'state':'stale' if changed else 'captured','changed_dependencies':changed,'last_completed':'captured',
                'next_action':'capture' if changed else 'evidence','receipt':str(path)}
    def media():
        if recording:
            if '_read_error' in recording:return {'state':'unknown','reason':recording['_read_error']}
            if recording.get('passed') is not True or recording.get('errors'):return {'state':'failed','reason':'Recording receipt did not complete successfully'}
            if not admission_current(recording):
                return {'state':'unknown','reason':'Recording lacks its current-run construction admission; inspect before any business replay'}
            if not bound(run['video'],recording.get('sha256'),output):
                recovered=original_capture()
                if recovered['state']=='captured':
                    recovered.update(reason='Only final MP4 is missing or changed; original capture remains current',
                                     next_action='preserve-video-draft then evidence' if Path(run['video']).exists() else 'evidence')
                return recovered
            controlled,controlled_path=receipt('controlled-video.json')
            if not controlled:return {'state':'captured','next_action':'evidence','last_completed':'recorded'}
            timeline=no_links(controlled['timeline'])
            if not bound(timeline,controlled.get('sha256'),workspace):
                return {'state':'captured','next_action':'evidence','reason':'Controlled timeline missing or changed','last_completed':'recorded'}
            timeline_value=read_json(timeline);binding=timeline_value.get('recording_receipt',{})
            if (timeline_value.get('video_sha256')!=recording['sha256'] or timeline_value.get('decode_ok') is not True or
                    timeline_value.get('sample_fps')!=5 or binding.get('sha256')!=sha(recording_path) or
                    no_links(binding.get('path',''))!=no_links(recording_path)):
                return {'state':'captured','next_action':'evidence','reason':'Technical timeline bindings incomplete','last_completed':'recorded'}
            completed_recording(workspace,recording,output/SYSTEM/'演示视频.mp4',hash_file=sha)
            return {'state':'technical_ready','last_completed':'technical_evidence','receipt':str(recording_path),
                    'timeline':str(timeline),'video_completed':True,
                    'verification_scope':'Video, operation receipt and timeline hashes; frame files were not rechecked or visually viewed.'}
        return original_capture() if pending else {'state':'not_started'}
    summarize('recording',media)
    cleanup,cleanup_path=receipt('cleanup.json')
    steps['cleanup']={'state':'pending' if cleanup and cleanup.get('status')!='stopped' else 'unknown',
                      'last_completed':'stopped' if cleanup and cleanup.get('status')=='stopped' else None,
                      'reason':'Existing cleanup receipt only; current OS process identities were not queried.',
                      'receipt':str(cleanup_path) if cleanup else None}
    steps.setdefault('independent_review',{'state':'pending','reason':'No finalized independent acceptance is recorded'})
    remaining=[]
    for name,action in [('data','clean-data'),('source_package','pack-source')]:
        if steps[name]['state']!='completed':remaining.append(steps[name].get('next_action') or action)
    def execution():
        execution_doc=read_json(no_links(evidence_path)) if evidence_path else prior_execution_doc
        if not execution_doc and (workspace/'.product-v2/build-checks.json').is_file():execution_doc=read_json(workspace/'.product-v2/build-checks.json')
        if not isinstance(execution_doc,dict):return {'state':'unknown','reason':'Execution facts must be a JSON object'}
        checks=execution_doc.get('checks',{})
        if isinstance(checks,list):
            if not all(isinstance(c,dict) and isinstance(c.get('kind'),str) for c in checks):
                raise ValueError('Execution checks must contain objects with string kinds')
            checks={c['kind']:c for c in checks}
        kinds={'algorithm','api','persistence','browser','build','package_startup'}
        if not isinstance(checks,dict) or not kinds.issubset(checks):return {'state':'pending','reason':'Six current execution facts including final ZIP startup are not yet supplied'}
        for kind in kinds:
            check=checks[kind]
            if (type(check.get('exit_code')) is not int or check['exit_code']!=0 or not check.get('command') or
                    not bound(inside(workspace,check['log'],must_exist=False),check.get('sha256'),workspace)):
                return {'state':'stale','reason':'Current execution fact is missing/failed/changed: '+kind}
        package_hash=execution_doc.get('source_zip_sha256') or checks['package_startup'].get('source_zip_sha256')
        if not bound(output/SYSTEM/'项目源码.zip',package_hash,output):return {'state':'pending','reason':'ZIP startup facts are not bound to this final archive'}
        return {'state':'completed','scope':'Recorded current log/archive hashes only; no business or independent pass is inferred'}
    summarize('execution_evidence',execution)
    if steps['execution_evidence']['state']!='completed':remaining.append('final-zip-startup-and-execution-evidence')
    if steps['independent_review']['state']!='verified':remaining.append('independent-review-changed-or-unread-evidence')
    next_actions=[]
    video_state=steps['recording']['state']
    if video_state in {'not_started','stale'}:next_actions.append('check-build then capture')
    elif video_state=='captured':next_actions.append(steps['recording'].get('next_action','evidence'))
    elif video_state in {'unknown','failed'}:next_actions.append('inspect-recording-state-before-any-business-replay')
    elif video_state=='technical_ready':
        if steps['cleanup']['last_completed']!='stopped':next_actions=['cleanup-after-required-online-work']
        elif steps['data']['state']=='cleaned':next_actions=['check-data']
        elif steps['data']['state']!='completed':
            next_actions=['inspect-data-receipt'] if steps['data']['state']=='unknown' else ['preserve-data-draft then clean-data' if (output/SYSTEM/'数据').exists() else 'clean-data']
        elif steps['source_package']['state']!='completed':
            next_actions=['inspect-source-package-receipt'] if steps['source_package']['state']=='unknown' else ['preserve-source-draft then pack-source' if (output/SYSTEM/'项目源码.zip').exists() else 'pack-source']
        elif steps['execution_evidence']['state']!='completed':next_actions=['verify-final-zip-startup-and-execution-evidence']
        else:next_actions=['independent-review-changed-or-unread-evidence']
    if steps['independent_review']['state']=='verified':next_actions=['publish']
    return {'kind':'workflow-status','workspace':str(workspace),'run_id':run['run_id'],'steps':steps,
            'independent_visual_review':steps['independent_review']['state'],'review_pointers':pointers,'next_actions':next_actions,'remaining_stages':remaining,
            'finalized_scope':'Any recorded acceptance applies to frozen delivered artifacts. Workspace edits require their own authorized revision; this status does not approve new workspace code.',
            'verification_scope':'Read-only receipt and selected dependency hashes, memoized within this request. No commands, media processing, services, images, model calls or frame traversal performed.'}

def preserve_draft(workspace,output,artifact):
    """Move one exact generated draft into verified internal history for retry."""
    choices={'data':output/SYSTEM/'数据','source':output/SYSTEM/'项目源码.zip','video':output/SYSTEM/'演示视频.mp4'}
    current=no_links(choices[artifact])
    if not current.exists(): raise ValueError('No draft artifact to preserve')
    if (workspace/'.product-v2/final-receipt.json').exists():
        raise ValueError('This delivery has a final receipt; create a new case revision instead')
    history=no_links(workspace/'.product-v2/revisions'/uuid.uuid4().hex)
    history.mkdir(parents=True)
    target=no_links(history/current.name)
    # Both exact endpoints are resolved and confined before the move.
    if output not in current.parents or workspace not in target.parents: raise ValueError('Draft move escapes roots')
    before=file_map(current) if current.is_dir() else {current.name:digest(current)}
    current.rename(target)
    after=file_map(target) if target.is_dir() else {target.name:digest(target)}
    if before!=after: raise ValueError('Preserved draft verification failed')
    return {'preserved':str(target),'files':before}

def finalize_document_revision(workspace,output,evidence_path):
    """Accept new Word with unchanged previously delivered software evidence."""
    if (workspace/'.product-v2/final-receipt.json').exists():
        raise ValueError('Finalized receipt is immutable; create a separate revision')
    from contracts import delivery_layout,chart_snapshot,model_review
    run=read_json(workspace/'.product-v2/run.json')
    if run.get('revision_scope','document')!='document':
        raise ValueError('Package revisions must use their dedicated revision gate')
    base=run.get('revision_of')
    if not base: raise ValueError('Explicit prepare --revision-of is required')
    base_workspace,base_output,_=state(base['workspace'])
    receipt_path=inside(base_workspace,'.product-v2/final-receipt.json')
    prior=read_json(receipt_path)
    if digest(receipt_path)!=base['receipt_sha256']:
        raise ValueError('Finalized base receipt or artifact snapshot changed')
    finalized_snapshot(base_output,prior,workspace=base_workspace)
    word=delivery_layout(output,run);charts=chart_snapshot(workspace,word,run)
    if file_map(output/SYSTEM)!=base['system_files'] or file_map(base_output/SYSTEM)!=base['system_files']:
        raise ValueError('Document-only revision requires byte-identical source ZIP, video and CSV files')
    cleanup_ready(base_workspace)
    cleanup_ready(workspace)
    scanned=scan_delivery(output,run['word_name'])
    if not scanned['passed']: raise ValueError('Delivery scan failed')
    chain=revision_chain(workspace,base)
    runtime_base=chain[-1]['workspace']
    for entry in chain:cleanup_ready(entry['workspace'])
    # Retain the actual prior six checks and verify every original log, input,
    # package and recording binding. No new construction claim is made.
    runtime_receipt=chain[-1]['receipt']
    recorded_evidence=Path(runtime_receipt['execution_evidence'])
    if recorded_evidence.is_absolute():
        inherited_evidence=no_links(recorded_evidence)
        if runtime_base not in inherited_evidence.parents or not inherited_evidence.is_file():
            raise ValueError('Inherited execution evidence must be a regular file inside its original workspace')
    else:
        inherited_evidence=inside(runtime_base,recorded_evidence)
    previous_proof=read_json(inherited_evidence)
    if digest(inherited_evidence)!=runtime_receipt['evidence_sha256']:
        raise ValueError('Inherited execution evidence changed')
    checks=previous_proof.get('checks',[])
    if (not isinstance(checks,list) or len(checks)!=6 or not all(isinstance(c,dict) for c in checks)
            or {str(c.get('kind')) for c in checks}!={'algorithm','api','persistence','browser','build','package_startup'}):
        raise ValueError('Inherited six execution checks required')
    for check in checks:
        log=inside(runtime_base,check['log'])
        if check.get('exit_code')!=0 or not check.get('command') or digest(log)!=check.get('sha256') or log.stat().st_size==0:
            raise ValueError('Inherited execution log failed or changed')
    package=read_json(runtime_base/'.product-v2/source-package.json')
    if digest(chain[-1]['output']/SYSTEM/'项目源码.zip')!=package['sha256'] or previous_proof.get('source_zip_sha256')!=package['sha256']:
        raise ValueError('Inherited package startup archive changed')
    current_zip=digest(output/SYSTEM/'项目源码.zip')
    if current_zip!=package['sha256']:
        latest_package=next((entry for entry in chain if entry['receipt'].get('scope')=='package-revision'),None)
        if not latest_package or latest_package['proof'].get('source_zip_sha256')!=current_zip:
            raise ValueError('A changed inherited archive requires its own prior package revision startup proof')
        check=latest_package['proof']['checks'][0];log=inside(latest_package['workspace'],check['log'])
        if check.get('kind')!='package_startup' or check.get('exit_code')!=0 or not check.get('command') or digest(log)!=check.get('sha256'):
            raise ValueError('Inherited latest package startup failed or changed')
        package_only_delta(chain[-1]['output']/SYSTEM/'项目源码.zip',output/SYSTEM/'项目源码.zip')
    for rel,sha in package['files'].items():
        if digest(inside(runtime_base,rel))!=sha: raise ValueError('Inherited application source changed')
    recording=read_json(runtime_base/'.product-v2/recording.json')
    from media_evidence import validate_recording_duration
    validate_recording_duration(recording,run.get('recording_policy_version','legacy-fixed-v1'))
    if recording.get('passed') is not True or digest(output/SYSTEM/'演示视频.mp4')!=recording.get('sha256'):
        raise ValueError('Inherited successful recording changed')
    completed_recording(runtime_base,recording,output/SYSTEM/'演示视频.mp4')
    clean=read_json(runtime_base/'.product-v2/data-cleaning.json')
    if file_map(output/SYSTEM/'数据')!={f['name']:f['sha256'] for f in clean['files']}:
        raise ValueError('Inherited CSV snapshot changed')
    check_data_quality(runtime_base,output)
    provenance=read_json(runtime_base/'.product-v2/data-provenance.json')
    if not provenance.get('nature') or not provenance.get('sources') or not provenance.get('validation'):
        raise ValueError('Inherited data provenance required')
    proof=read_json(evidence_path)
    if proof.get('reviewed_files')!=scanned['files'] or not proof.get('visual_notes') or not proof.get('limitations'):
        raise ValueError('Current document revision review snapshot and limits required')
    dispatch=model_review(workspace,proof,scanned['files'],charts,evidence_path)
    receipt={'schema_version':2,'status':'complete','delivery_state':'verified-candidate','at':utc(),'scope':'document-revision',
        'files':scanned['files'],'chart_snapshot':charts,'verified_dispatch':dispatch,
        'execution_evidence':str(evidence_path),'evidence_sha256':digest(evidence_path),
        'inherited_system':base,'inherited_checks':checks,
        'limitations':proof['limitations'],'source_docx_sha256':run['source_docx_sha256']}
    write_json(workspace/'.product-v2/final-receipt.json',receipt)
    return receipt

def revision_chain(workspace, base):
    """Follow only explicit, hash-bound receipt relationships; never scan history."""
    chain=[];seen={str(no_links(workspace))};link=base
    while link:
        original,output,run=state(link['workspace'])
        if str(original) in seen: raise ValueError('Revision inheritance cycle')
        seen.add(str(original))
        receipt_path=inside(original,'.product-v2/final-receipt.json')
        receipt=read_json(receipt_path)
        # A parent recorded before its weekly archive keeps the original
        # publication path. A child prepared later records the verified locator.
        # Both identities are exact receipt-bound paths; arbitrary aliases fail.
        parent_paths={str(no_links(run['output'])),str(output)}
        if digest(receipt_path)!=link['receipt_sha256'] or link['output'] not in parent_paths:
            raise ValueError('Frozen revision receipt identity changed')
        untracked=finalized_snapshot(output,receipt,bool(link.get('untracked_base_files')),original)
        if untracked!=link.get('untracked_base_files',{}):
            raise ValueError('Untracked revision-base files changed after explicit freezing')
        proof_path=Path(receipt['execution_evidence'])
        proof_path=no_links(proof_path) if proof_path.is_absolute() else inside(original,proof_path)
        if original not in proof_path.parents or not proof_path.is_file() or digest(proof_path)!=receipt['evidence_sha256']:
            raise ValueError('Inherited review proof must remain inside its original workspace and unchanged')
        proof=read_json(proof_path)
        chain.append({'workspace':original,'output':output,'run':run,'receipt':receipt,'proof':proof,
                      'receipt_sha256':digest(receipt_path),'proof_sha256':digest(proof_path)})
        if receipt.get('scope') in {'document-revision','package-revision'}:
            link=receipt.get('inherited_system')
            if not link or run.get('revision_of')!=link:
                raise ValueError('Revision requires its exact persisted parent relationship')
        else: link=None
    return chain

def package_only_delta(old_zip,new_zip):
    """Restrict package revision to omitted documentation and legal notices."""
    from package_policy import excluded_delivery_document
    with zipfile.ZipFile(old_zip) as old,zipfile.ZipFile(new_zip) as new:
        before={i.filename:old.read(i) for i in old.infolist() if not i.is_dir()}
        after={i.filename:new.read(i) for i in new.infolist() if not i.is_dir()}
    if not after or set(after)-set(before): raise ValueError('Package-only revision cannot add application members')
    removed=[];amended=[]
    for name,data in before.items():
        if name not in after:
            reason=excluded_delivery_document(name)
            if not reason: raise ValueError('Package-only revision cannot remove application or legal files: '+name)
            removed.append({'path':name,'reason':reason})
        elif data!=after[name]:
            path=PurePosixPath(name)
            legal=path.name.upper().startswith(('LICENSE','NOTICE','COPYING')) or 'licenses' in [p.casefold() for p in path.parts]
            if not legal: raise ValueError('Package-only revision cannot change application bytes: '+name)
            text=data.decode('utf-8-sig').replace('\r\n','\n')
            current=after[name].decode('utf-8-sig').replace('\r\n','\n')
            header=text.split('\n\n',1)[0]
            urls=set(re.findall(r'https?://[^\s]+',text))
            if (not current.startswith(header+'\n') or not urls.issubset(set(re.findall(r'https?://[^\s]+',current)))
                    or not re.search(r'\b(modified|changes?)\b',current,re.I)):
                raise ValueError('Legal notice must retain complete original attribution header, URLs and change indication')
            amended.append({'path':name,'old_sha256':__import__('hashlib').sha256(data).hexdigest(),
                            'new_sha256':__import__('hashlib').sha256(after[name]).hexdigest(),
                            'retained_attribution_header':header,'retained_urls':sorted(urls)})
    return {'removed_documents':removed,'amended_legal_notices':amended,
            'unchanged_application_members':[n for n in after if before[n]==after[n]]}

def inherited_execution(root):
    original,output,proof=root['workspace'],root['output'],root['proof']
    run=read_json(original/'.product-v2/run.json')
    check_data_quality(original,output)
    checks=proof.get('checks',[])
    if (not isinstance(checks,list) or len(checks)!=6 or not all(isinstance(c,dict) for c in checks)
            or {str(c.get('kind')) for c in checks}!={'algorithm','api','persistence','browser','build','package_startup'}):
        raise ValueError('Inherited six execution checks required')
    for check in checks:
        log=inside(original,check['log'])
        if check.get('exit_code')!=0 or not check.get('command') or digest(log)!=check.get('sha256') or not log.stat().st_size:
            raise ValueError('Inherited execution log failed or changed')
    package=read_json(original/'.product-v2/source-package.json')
    if package['sha256']!=digest(output/SYSTEM/'项目源码.zip') or proof.get('source_zip_sha256')!=package['sha256']:
        raise ValueError('Inherited package and original startup proof changed')
    for rel,sha in package['files'].items():
        if digest(inside(original,rel))!=sha: raise ValueError('Inherited source changed: '+rel)
    recording=read_json(original/'.product-v2/recording.json')
    from media_evidence import validate_recording_duration
    validate_recording_duration(recording,run.get('recording_policy_version','legacy-fixed-v1'))
    if not recording.get('passed') or recording.get('sha256')!=digest(output/SYSTEM/'演示视频.mp4'):
        raise ValueError('Inherited recording changed')
    completed_recording(original,recording,output/SYSTEM/'演示视频.mp4')
    clean=read_json(original/'.product-v2/data-cleaning.json')
    if file_map(output/SYSTEM/'数据')!={f['name']:f['sha256'] for f in clean['files']}:
        raise ValueError('Inherited CSV output changed')
    provenance=read_json(original/'.product-v2/data-provenance.json')
    if not all(provenance.get(key) for key in ('nature','sources','validation')): raise ValueError('Inherited data provenance missing')
    return checks

def finalize_package_revision(workspace,output,evidence_path):
    """New archive startup with byte-identical Word/plots/video/CSV; no self-pass."""
    if (workspace/'.product-v2/final-receipt.json').exists(): raise ValueError('Finalized receipt is immutable')
    from contracts import delivery_layout,chart_snapshot,model_review
    run=read_json(workspace/'.product-v2/run.json')
    if run.get('revision_scope')!='package' or not run.get('revision_of'): raise ValueError('Explicit package revision prepare required')
    chain=revision_chain(workspace,run['revision_of']);base=chain[0];root=chain[-1]
    current=file_map(output);old=base['receipt']['files'];zip_name=SYSTEM+'/项目源码.zip'
    if {k:v for k,v in current.items() if k!=zip_name}!={k:v for k,v in old.items() if k!=zip_name}:
        raise ValueError('Package-only revision requires byte-identical Word, video and every CSV')
    word=delivery_layout(output,run);charts=chart_snapshot(workspace,word,run)
    if charts!=base['receipt'].get('chart_snapshot'):
        raise ValueError('Package revision cannot change previously reviewed Word charts or manifest')
    for entry in chain: cleanup_ready(entry['workspace'])
    cleanup_ready(workspace)
    inherited=inherited_execution(root)
    delta=package_only_delta(base['output']/zip_name,output/zip_name)
    scanned=scan_delivery(output,run['word_name'])
    if not scanned['passed']: raise ValueError('Delivery scan failed')
    package=read_json(workspace/'.product-v2/source-package.json')
    if package['sha256']!=digest(output/zip_name): raise ValueError('New source archive changed')
    for rel,sha in package['files'].items():
        if digest(inside(workspace,rel))!=sha: raise ValueError('New packaged source changed')
    proof=read_json(evidence_path);checks=proof.get('checks',[])
    from media_evidence import validate as validate_video_evidence
    timeline=inside(workspace,proof['video_timeline'])
    if proof.get('video_timeline_sha256')!=digest(timeline):raise ValueError('Package review must bind current complete video evidence')
    validate_video_evidence(workspace,timeline,output/SYSTEM/'演示视频.mp4',root['workspace']/'.product-v2/recording.json')
    if not isinstance(checks,list) or len(checks)!=1 or not isinstance(checks[0],dict) or checks[0].get('kind')!='package_startup': raise ValueError('New independent archive startup check required')
    check=checks[0];log=inside(workspace,check['log'])
    if not check.get('command') or check.get('exit_code')!=0 or check.get('sha256')!=digest(log) or not log.stat().st_size:
        raise ValueError('New archive startup log failed or changed')
    if (proof.get('source_zip_sha256')!=package['sha256'] or proof.get('reviewed_files')!=scanned['files']
            or not proof.get('visual_notes') or not proof.get('limitations')):
        raise ValueError('Current archive, inherited visual coverage and current review limits required')
    expected=[{'workspace':str(e['workspace']),'receipt_sha256':e['receipt_sha256'],'proof_sha256':e['proof_sha256']} for e in chain]
    if proof.get('inherited_evidence_chain')!=expected: raise ValueError('Review must bind the full explicit inheritance chain')
    dispatch=model_review(workspace,proof,scanned['files'],charts,evidence_path)
    receipt={'schema_version':2,'status':'complete','delivery_state':'verified-candidate','at':utc(),'scope':'package-revision','files':scanned['files'],
             'chart_snapshot':charts,'verified_dispatch':dispatch,'execution_evidence':str(evidence_path),
             'evidence_sha256':digest(evidence_path),'inherited_system':run['revision_of'],
             'inherited_checks':inherited,'checks':checks,'package_delta':delta,'inherited_evidence_chain':expected,
             'limitations':proof['limitations'],'source_docx_sha256':run['source_docx_sha256']}
    write_json(workspace/'.product-v2/final-receipt.json',receipt);return receipt

def publish(workspace,destination):
    """Atomic same-volume directory publication with durable, resumable intent."""
    workspace=no_links(workspace);destination=no_links(destination)
    run_path=inside(workspace,'.product-v2/run.json');run=read_json(run_path)
    if run['workspace']!=str(workspace):raise ValueError('Current run workspace identity differs')
    receipt_path=inside(workspace,'.product-v2/final-receipt.json');receipt=read_json(receipt_path)
    if receipt.get('status')!='complete' or receipt.get('delivery_state')!='verified-candidate':
        raise ValueError('Only a newly verified candidate can be atomically published; old finalized deliveries remain frozen')
    if destination==workspace or workspace in destination.parents or destination in workspace.parents:
        raise ValueError('Publication destination and workspace must be disjoint')
    publish_path=workspace/'.product-v2/publish-receipt.json';intent_path=workspace/'.product-v2/publish-intent.json'
    if publish_path.exists():
        prior=read_json(publish_path)
        if prior.get('destination')!=str(destination) or prior.get('files')!=file_map(destination):raise ValueError('Published destination/bytes changed')
        return prior
    if intent_path.exists():
        intent=read_json(intent_path)
        if (intent.get('destination')!=str(destination) or intent.get('source_receipt_sha256')!=digest(receipt_path)
                or intent.get('files')!=receipt['files']):raise ValueError('Publication intent mismatch; preserve the original candidate and destination')
        candidate=no_links(intent['candidate'])
        initial=intent.get('run_snapshot')
        if not isinstance(initial,dict):raise ValueError('Publication recovery requires the frozen initial run snapshot')
        expected=dict(initial)
        expected.update({'output':str(destination),'word':str(destination/initial['word_name']),
                         'data_dir':str(destination/SYSTEM/'数据'),'source_zip':str(destination/SYSTEM/'项目源码.zip'),
                         'video':str(destination/SYSTEM/'演示视频.mp4'),'status':'published'})
        if (intent.get('workspace')!=str(workspace) or initial.get('workspace')!=str(workspace)
                or candidate!=no_links(initial['output']) or candidate.anchor.casefold()!=destination.anchor.casefold()
                or candidate==destination or candidate==workspace or workspace in candidate.parents or candidate in workspace.parents):
            raise ValueError('Publication recovery identity, volume or disjoint candidate boundary changed')
        if digest(run_path)!=intent['run_sha256'] and run!=expected:
            raise ValueError('Publication run changed beyond the single intended post-rename path update')
        if digest(run_path)==intent['run_sha256'] and run!=initial:
            raise ValueError('Frozen publication run snapshot differs')
    else:
        candidate=no_links(run['output'])
        if candidate==destination or destination.exists():raise ValueError('Atomic publication requires a separate wholly new destination')
        if candidate.anchor.casefold()!=destination.anchor.casefold():raise ValueError('Candidate and destination must be on the same volume')
        if file_map(candidate)!=receipt['files']:raise ValueError('Candidate bytes changed after independent acceptance')
        cleanup_ready(workspace)
        intent={'schema_version':1,'candidate':str(candidate),'destination':str(destination),'workspace':str(workspace),
                'files':receipt['files'],'source_receipt_sha256':digest(receipt_path),'run_sha256':digest(run_path),'run_snapshot':run,'at':utc()}
        write_json(intent_path,intent)
    if candidate.exists():
        if destination.exists():raise ValueError('Destination exists while candidate remains; no overwrite or merge permitted')
        if file_map(candidate)!=intent['files']:raise ValueError('Publication candidate changed after intent freezing')
        cleanup_ready(workspace);destination.parent.mkdir(parents=True,exist_ok=True)
        candidate.rename(destination)
    elif not destination.exists():raise ValueError('Neither intended candidate nor intended destination exists; keep recovery intent')
    if file_map(destination)!=intent['files']:raise ValueError('Published file verification failed; keep intent and all files')
    run.update({'output':str(destination),'word':str(destination/run['word_name']),
                'data_dir':str(destination/SYSTEM/'数据'),'source_zip':str(destination/SYSTEM/'项目源码.zip'),
                'video':str(destination/SYSTEM/'演示视频.mp4'),'status':'published'})
    write_json(run_path,run)
    result={'schema_version':1,'status':'published','destination':str(destination),'candidate':str(candidate),
            'files':intent['files'],'source_receipt_sha256':digest(receipt_path),'intent_sha256':digest(intent_path),'at':utc()}
    write_json(publish_path,result);return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--workspace',required=True);prep.add_argument('--output',required=True);prep.add_argument('--title',required=True);prep.add_argument('--source-docx',required=True);prep.add_argument('--revision-of');prep.add_argument('--adopt-draft',action='store_true');prep.add_argument('--revision-scope',choices=['document','package'],default='document');prep.add_argument('--allow-untracked-base',action='store_true')
    for name in ('clean-data','check-data','check-build','status','pack-source','scan','record','finalize','finalize-document-revision','finalize-package-revision','publish','preserve-draft'):
        item=sub.add_parser(name);item.add_argument('--workspace',required=True)
        if name in ('check-build','status'):item.add_argument('--plan')
        if name=='status':item.add_argument('--evidence')
        if name in ('clean-data','pack-source'): item.add_argument('--manifest',required=True)
        if name=='record':
            item.add_argument('--plan');item.add_argument('--phase',choices=['full','capture','evidence'],default='full')
            item.add_argument('--batch-root');item.add_argument('--batch-id');item.add_argument('--case-id');item.add_argument('--record-token');item.add_argument('--media-token');item.add_argument('--owner-pid',type=int)
        if name in ('finalize','finalize-document-revision','finalize-package-revision'): item.add_argument('--evidence',required=True)
        if name=='preserve-draft': item.add_argument('--artifact',choices=['data','source','video'],required=True)
        if name=='publish': item.add_argument('--destination',required=True)
    args=p.parse_args(argv)
    try:
        if args.command=='prepare': result=prepare(args.workspace,args.output,args.title,args.source_docx,args.revision_of,args.adopt_draft,args.revision_scope,args.allow_untracked_base)
        elif args.command=='publish':result=publish(args.workspace,args.destination)
        else:
            workspace,output,run=state(args.workspace)
            if args.command=='check-build':
                from contracts import construction_checks
                result=construction_checks(workspace,run,args.plan)
            elif args.command=='status':result=workflow_status(workspace,output,run,args.plan,args.evidence)
            elif args.command=='clean-data':
                cleanup_ready(workspace);result=clean_csv(workspace,output,args.manifest)
            elif args.command=='check-data':result=check_data_quality(workspace,output,update=True)
            elif args.command=='pack-source': result=pack_source(workspace,output,args.manifest)
            elif args.command=='scan':
                result=scan_delivery(output,run.get('word_name'));write_json(workspace/'.product-v2/scan.json',result)
                if not result['passed']:
                    print(json.dumps(result,ensure_ascii=False,indent=2));return 2
            elif args.command=='record':
                node=os.environ.get('SCB_PRO_NODE')
                if not node: raise ValueError('Load Enter-Environment.ps1 first')
                if args.phase!='evidence' and not args.plan:raise ValueError('Capture requires --plan')
                command=[node,str(ROOT/'scripts/record.cjs'),'--workspace',str(workspace),'--phase',args.phase]
                if args.plan:command.extend(['--plan',str(Path(args.plan).resolve())])
                lease={'--batch-root':args.batch_root,'--batch-id':args.batch_id,'--case-id':args.case_id,
                       '--media-token':args.media_token or args.record_token,'--owner-pid':args.owner_pid}
                from batch_control import media_binding
                binding=media_binding(workspace)
                if binding and (args.phase=='full' or not all(v is not None for v in lease.values())):
                    raise ValueError('Registered batch workspace requires its capture/evidence lease')
                if any(v is not None for v in lease.values()):
                    if args.phase not in {'capture','evidence'} or not all(v is not None for v in lease.values()):raise ValueError('Complete batch lease requires capture or evidence phase')
                    for key,value in lease.items():command.extend([key,str(value)])
                done=subprocess.run(command)
                return done.returncode
            elif args.command=='preserve-draft': result=preserve_draft(workspace,output,args.artifact)
            elif args.command=='finalize-document-revision': result=finalize_document_revision(workspace,output,args.evidence)
            elif args.command=='finalize-package-revision': result=finalize_package_revision(workspace,output,args.evidence)
            else: result=finalize(workspace,output,args.evidence)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,UnicodeError,csv.Error,zipfile.BadZipFile) as e:
        print(f'ERROR: {e}',file=sys.stderr);return 2

if __name__=='__main__': sys.exit(main())
