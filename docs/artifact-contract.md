# 案件证据合同

2026-09-24提速协议：下文八字段review-verdict是父执行器保存的规范化报告。新模型线上的返回采用review-response.schema.json：protocol、review_id、verdict、issues、chart_reviews、reviewed_evidence、coverage、limitations。chart_reviews条目是figure_id/checks/evidence_ids；证据用父执行器request.evidence内的短ID。父执行器验证当前快照未变、ID与覆盖和检查结果后绑定哈希，原始答复与request分别保留，不替模型改变结论。详情见rules/execution-efficiency.md。旧报告仍按旧摘要严格验证，不因提速自动纠正通过报告中的错误哈希。

编排器从每案 evidence/artifact-manifest.json 读取成果，以下路径都相对于该案工作区。路径不得越界、指向其他案件或使用符号链接绕过边界。source_sha256 与已冻结原件匹配。编排器的当前脚本校验为最终机械合同；附加字段由 独立验收者 结合证据检查。

```json
{
  "source_sha256": "原件SHA256",
  "readme": "README.md",
  "ui_text_audit": "evidence/ui-visible-text.json",
  "formula_registry": "evidence/formula_registry.json",
  "source_trace": "evidence/source_trace.json",
  "chart_design": "evidence/chart-design.json",
  "revised_docx": "deliverable/修订稿.docx",
  "charts": [
    {
      "figure_id": "fig-4",
      "formula_ids": ["F01"],
      "snapshot_id": "run-001",
      "png": "exports/fig-4.png",
      "csv": "exports/fig-4.csv",
      "explanation": "exports/fig-4.md"
    }
  ],
  "ui_screenshots": ["evidence/ui/overview.png"],
  "rendered_pages": ["evidence/docx-render/page-1.png"],
  "test_report": "evidence/verification.json",
  "preservation_report": "evidence/controlled-word/本次目录/preservation.json",
  "render_report": "evidence/controlled-word/本次目录/render.json",
  "video": "recording/final.mp4",
  "video_contact_sheets": ["recording/evidence/contact-001.jpg"],
  "video_timeline": "recording/evidence/timeline.json"
}
```

build 完成时 video 相关字段可为空，视频阶段需全部补齐。每个图的explanation、formula_registry、source_trace、真实测试日志为必需证据；零公式也要提交带结论和原因的台账。示例只有一页、一图仅为字段示意，实际列全：完整Word所有渲染页、至少两张按业务问题选择的图及其对应证据。页路径不能重复。没有大公式时不能捏造；charts 可以包含多组图，但必须说明哪些对应主公式，哪些是业务图。每案至少两张有意义且不同的图，不允许零图；一个公式可多图或不单独成图，formula_ids可为空或多项。

当前配置强制readme及ui_text_audit。README.md集中记录数据来源、演算性质和未验证范围，随成品交付；禁止在网页/视频重复这些标签。ui_text_audit的格式与采集规则见 [web-visible-copy.md](../rules/web-visible-copy.md)，须覆盖全部ui_screenshots并绑定当前截图哈希。父执行器扫描实际采集文字中的禁词；独立验收者仍须查看截图及视频，不能用文字报告代替视觉检查。

preservation_report和render_report由编排器运行controlled_evidence.py后填入。该脚本直接对照原Word正文、公式树、原媒体与最终PNG，再用固定render_docx.py重新渲染最新Word，按PDF实际页数验证连续页图和哈希，并替换rendered_pages。视频阶段也由编排器直接从最终MP4完整解码、提取首尾及5fps时间线，替换建设者的抽帧路径。受控证据的输入和文件指纹保存在案件目录外的状态文件中；相关文件改变后重新生成。建设者不能自签替代这些结果。

verification.json 至少说明：

以下四个字段由脚本强制校验，不能改名；其余证据由 独立验收者 结合源文件核验：
```json
{
  "source_sha256": "已冻结原件SHA256",
  "rendered_docx_sha256": "最新修订Word的SHA256",
  "rendered_page_count": 1,
  "tests": [{"command": "实际执行的测试命令", "exit_code": 0, "log": "evidence/test.log"}]
}
```

- 执行的测试命令、退出码、日志相对路径、检查时间、哪些已测/未测；真实失败不能写通过。
- render 页数与 DOCX SHA256、最终渲染目录，保证不是修改前的页图。
- 源文件哈希、正文保留、原公式与媒体保留、新增红字位置/颜色、figure_id与图号、嵌入媒体哈希。
- 每图的数据快照/后端计算/CSV/PNG/说明路径与哈希。
- 已验证的关键业务流程、路由与交互，实际浏览器截图与时间。
- 数据口径/来源、部署范围、训练/设备接入是否实际验证。
- 录制模块选择、启动命令、健康身份、进程归属记录。

独立验收者 返回结构化结果：
```json
{
  "rules_version": "2026-09-24",
  "chart_reviews": [{
    "figure_id": "fig-4", "png": "exports/fig-4.png", "png_sha256": "实际SHA256",
    "checks": {
      "meaning": {"passed": true, "evidence": "具体业务问题与图上可辨认结果"},
      "data": {"passed": true, "evidence": "实际核对的CSV范围、实施例或计算记录"},
      "legibility": {"passed": true, "evidence": "实际网页尺寸和Word页中的文字线条可读性"},
      "layout": {"passed": false, "evidence": "图例第二项的虚线与实际点线不一致"},
      "explanation": {"passed": true, "evidence": "本图说明中的具体算例、数值变化、原因与结论核验"}
    },
    "evidence_files": ["exports/fig-4.png", "exports/fig-4.csv", "exports/fig-4.md", "evidence/ui/chart-4.png", "evidence/docx-render/page-9.png"]
  }],
  "verdict": "revise",
  "issues": [{
    "severity": "major",
    "artifact": "exports/fig-4.png",
    "evidence": "图例第二项的虚线与实际点线不一致",
    "fix": "沿用当前数据和图形，仅同步图例线型"
  }],
  "reviewed_files": [{"path": "exports/fig-4.png", "sha256": "实际SHA256"}],
  "snapshot_sha256": "RUNNER_CONTEXT_JSON给出的快照标识",
  "coverage": "实际查看的原图、Word页面及视频采样时间范围和检查方式",
  "limitations": ["仅查看5fps采样及关键原帧，未逐帧观看原视频"]
}
```

上面每图和reviewed_files仅示意，实际列全当前manifest所有图和required_review_files。chart_reviews五项检查均须具体证据；任一passed=false不得总体pass。图证据含PNG、CSV、说明及显示该图的正常尺寸网页截图和Word页。旧协议和旧规则通过不能用于当前交付。

chart_design指定JSON必须含rules_version="2026-09-24"和figures数组。每图条目为：figure_id、business_question、reader_takeaway、chart_type、selection_reason、scenario_coverage、calculation_basis；explanation_outline含purpose、reading、calculation、findings、decision五个本图具体摘要，并含word_context记录源段落/实施例锚点及承前启后的具体安排；最终png_sha256、csv_sha256、explanation_sha256与清单文件一致。例：business_question应是“撤离后信号未释放会在哪一阶段禁止交接”，不能填“展示F01”。来源可以是实施例、业务过程、实际运行或公式，不强迫公式成图，不设说明字数限制。图或说明更新后同时刷新此证据，空字段不算准备完成。

允许 verdict 仅为 pass/revise/blocked，severity 仅为 blocker/major/minor。pass 不能带有 blocker 或 major 问题。issues 中给出可定位的图像、页、时间段和修复方式。reviewed_files 必须有真实读取/审查依据，不可抄哈希列表而不检查；path 不重复，覆盖 required_review_files。复验仅可对同规则版本且未被用户否定的未变化文件沿用此前实际审查与哈希绑定的证据，但coverage必须区分本次打开和沿用；变更文件及关联产物必须重查。每个对象使用固定字段，以满足严格结构化输出协议。编排器保存模型调用记录、审查输出和文件指纹；任何相关成果变化，旧 pass 失效。review 的输出由编排器保存，建设者不能替代 独立验收者 自签报告。文件哈希只保证版本对应，视觉合格仍依靠实际看图和证据判断。

默认combined_final只需一份final_review，覆盖视觉与视频所有证据；此前分开visual_review/video_review模式保留兼容。可修复问题循环Sol返修和独立验收者复验至通过。返修者在evidence/repair-status.json报告ready_for_review，或在确实需要外部输入时报告blocked、requires_user_input:true及具体reason；一般图表、排版、代码错误应继续修复。

用户2026-09-27授权数据与材料自动补齐，具体执行rules/material-sourcing.md。普通缺实测/标定/权重/设备回执时，用适用公开资源或可复现模拟输入完成实际运行，不写requires_user_input:true，不再请求数据授权。遇材料缺口记录evidence/material-research.json与README；生成数据时保存脚本/配置、假设、种子或确定性、输入输出哈希、真实运行日志。只有实现和自检完成后才写ready_for_review，来源限制不等于未完成状态；模型/额度/写入拒绝等真实外部故障保持原阻塞合同。父任务恢复已获继续授权的旧blocked案时，保留旧报告和调用，再以新规则交建设者处理，不直接改为通过。

video_evidence.py 对 MP4 解码和采样，输出 timeline.json、5fps的逐帧图片、首尾原帧和带时间 contact sheets。它只标记 pending_astra，不自动把技术检查当视频美观合格。调用它前先通过依赖工具取 bundled Python；示例：
```powershell
& "<bundled-python.exe>" -X utf8 <项目目录>\scripts\video_evidence.py "<本案MP4>" "<本案新的空证据目录>"
```

新登记efficient-v1批次建设时还需evidence/capture-plan.json，合同见[capture-plan.md](capture-plan.md)。父执行器补充capture_report、capture_plan、capture_ui_screenshots并绑定实际浏览器截图与文字；这些字段不替代video_timeline、受控证据或独立验收。旧批次无此新增要求。


## 2026-09-28 后续批次成品精简

用户明确要求以后批次的成品中不放“图表资料”“原始文件”和README。新登记批次冻结delivery_profile=word-video，最终每案成品只含修订Word和“模拟系统”目录中的视频；三类资料继续完整保存在案件工作区，原始材料保持原地不动。README仍记录来源、生成数据性质和未验证范围；图表PNG/CSV/详细说明、原件副本仍生成并核验，只是不复制到交付目录。不得删除工作区证据或减少验收。

旧清单未标记该profile时仍按原full合同交付；已做和正在执行的既有批次不自动删文件、不重打包。本文及引用文件中“随成品交付README/原件/图表资料”的旧表述仅适用于旧批次，对新批次以本条为准。


## 成品优先范围（2026-09-30）

新批 deliverable-first-v1 保留既有Word/图/CSV/源式/渲染/真实视频合同。图可只用于Word，ui_screenshots/ui_text_audit聚焦两个实际录制页面和网页导航框架，不要求其他模块有完整内容或图有网页副本；详细边界见[成品优先规则](../rules/deliverable-first.md)。capture-plan schema 2新增scene_data_files绑定两页真实计算结果；Word用图与视频输入分别追踪，不把Word图变更自动当作视频过期。通过结果仍对应当前文件，不伪造验收。

用户2026-09-30确定的长期交付规则：以后本项目所有案件与批次的成品交付均采用“每案根目录放修订Word、每案自己的模拟系统子目录放视频”。普通交付、加急交付、经用户授权的提前导出和返修后另存成品均遵循此结构，不限于0928批次。除非用户之后明确更改，不得将Word与MP4平铺，也不得把多案视频混放到批次共用目录。发布前核对最终相对路径与文件哈希并同步清单/收据；仅调整目录不触发重录、重验或内容返修，历史成品不因此自动重打包。
