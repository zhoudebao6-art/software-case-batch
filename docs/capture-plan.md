# 可信录制计划

efficient-v1 和 deliverable-first-v1 批次需要。建设者生成 `evidence/capture-plan.json`，父执行器运行固定程序拍摄，不执行案件提供的任意录制脚本。旧 efficient-v1 使用下列 schema 1；新成品优先流程使用本文末尾的 schema 2，必须准备两个页面。

```json
{
  "schema_version": 1,
  "case_id": "context中的本案case_id",
  "base_url": "http://127.0.0.1:本案分配端口",
  "health_path": "/api/health",
  "version": "本次服务启动时冻结的版本",
  "application_files": {"app/server.py": "当前文件SHA256", "web/index.html": "当前文件SHA256"},
  "modules": [
    {"name": "任务总览", "route": "/overview", "heading": "任务总览", "ready_selectors": ["[data-ready='overview']"]},
    {"name": "处理结果", "route": "/results", "heading": "处理结果", "ready_selectors": ["[data-ready='results']"], "enter_selector": "a[href='/results']"}
  ]
}
```

用本案真实值替换示例，保留一个或两个模块。route必须是不含查询/fragment的本地相对路径；页面有且仅有一个匹配heading的可见H1。第二模块通过真实导航控件进入，禁止隐藏错误或用截图替代网页。ready_selectors需在数据、业务图表及必要动画完成后才可见，不能仅凭容器存在判断就绪。

health_path需返回JSON：case_id、workspace（本案绝对路径）、version。version从启动时加载的版本固定返回，不能每次健康请求读取变化中的磁盘版本。application_files列出实际影响所录页面的服务入口、业务逻辑和前端源码（1–200个），部署产物也要绑定。服务身份不匹配或文件变化就拒绝录制，交建设者修复。

使用config.json的runtime.python执行：`scripts/capture_runner.py probe "本案绝对路径" --case-id "本案ID" --port 本案端口 --config "<项目目录>\config.json"`。probe不录屏、不启动或停止服务，输出实际浏览器截图与DOM文字；建设者必须打开截图自检，不写独立验收结论。

父执行器先核对健康身份，再在录制槽内预热并真实录制1920×1080网页内容。通过连续实际帧与就绪截图比较定位开头，截取约10秒连续视频、编码H.264并完整解码。原视频、截图、操作时间、裁剪映射和结果保留在recording/capture-*。静态匹配仅证明技术上的起始就绪，切换质量、图表可读性和整体美观仍交Ultra检查。最终全视频5fps接触页及首尾/交互关键帧由既有受控证据流程生成。


## 成品优先 schema 2（2026-09-30）

新批次 deliverable-first-v1 使用 schema_version=2。沿用上述服务身份、application_files 和模块字段，必须恰好两个不同 route 的实际业务界面，第二页真实导航进入；网页的其他模块保留导航/路由/标题，内容允许留空，不纳入视频准备返修范围。新增非空 scene_data_files，形如 `{"data/recording-results.json":"实际SHA256"}`，登记两个业务页面实际读取的业务记录、任务状态、必要计算结果及可见图片；录制重点是系统业务界面和操作流程，不要求制作图表或结果看板。两类输入都绑定当前哈希并由录制前后校验，缺失/越界/版本不符拒绝；程序、真实业务数据或已显示图表变化仍重录。

文档专用图表无须网页展示，不放入录制依赖；未被页面引用的图或Word正文改变不触发重录。不得遗漏真正可见的图、共享逻辑或数据来逃避版本核验。输入值应来自源定义下实际计算，可使用有依据的推演输入，不手填输出。详见[成品优先规则](../rules/deliverable-first.md)。旧 schema 1 与旧批次不自动修改。

schema 2 的 probe、录制前预热和实际录制现在都观察真实导航期间的动画帧：至少一个业务页的H1与全部ready选择器须持续可见，不能清空整个根容器只显示“加载中”。建设时保留导航和旧业务页，数据准备完成后再切换；需要加载提示时放在框架内。ready选择器应指向有实际内容的业务区域，不指向永远存在的空壳。程序不改DOM、不隐藏加载、不拼接画面；失败记录在本次recording/capture-*/browser-failure.json，切页采样计数与首个问题帧时间保留在events。此检查只证明DOM就绪连续性，不能替代实际截图及视频的视觉检查，仍可能需要处理遮挡/样式等视觉缺陷。
