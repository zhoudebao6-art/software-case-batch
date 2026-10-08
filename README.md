# 软通案件自动化

本地 Windows 批次流水线。明确确认一批 Word 后制作可追溯结果图、保留原文并标红增补的 Word、约十秒的真实业务网页视频；支持断点恢复、独立验收及保全式交付。

新流程以成品为目标：保留完整网页框架，优先实现两个符合案件属性的业务页面。工业控制案件应呈现工业控制台，其他案件匹配本身的业务形态，不能统一套图表墙。新增结果图按内容合理安排 2–6 张，不固定为两张，也不凑数量。

```text
批次成品目录/
└─ 案件名称/
   ├─ 修订文档.docx
   └─ 模拟系统/
      └─ 演示视频.mp4
```

## 新电脑安装

先读 [新电脑使用](docs/新电脑使用.md)。仓库仅含程序、规则、技能及测试；`config.json`、案件材料、工作区、成品、日志、凭据和运行环境不会随仓库上传。每台电脑使用自己的配置、Codex 登录和模型权限。

在有 Python 3.11+、Node.js 20+、Git、Codex CLI、LibreOffice、FFmpeg 和 Poppler 的 Windows 电脑上：

```powershell
git clone https://github.com/zhoudebao6-art/software-case-batch.git
cd software-case-batch
.\scripts\setup.ps1 -InstallDependencies -InstallSkill
.\scripts\caseflow.ps1 doctor --smoke
.\scripts\caseflow.ps1 plan 'D:\案件材料\本批'
# 读清单并明确确认后，使用 plan 返回的批次 ID
.\scripts\caseflow.ps1 run '<批次ID>'
```

若使用已有 Codex 桌面依赖，可先运行 `setup.ps1 -InstallSkill` 自动发现本机工具。安装器不覆盖现有 `config.json`；缺项按 doctor 报告在本机配置中修正。不会自动扫描或启动批次。

## 执行约定

- 建设 GPT-6.1 Sol high，返修 GPT-6.1 Sol ultra；普通独立验收 GPT-6.1 Sol ultra，用户明确加急才用 Astra low。实际模型参数固定，不静默降低。
- 默认 8 个建设/返修槽、3 个普通验收槽、1 个录制槽。槽位限额只覆盖同一台电脑的同一个工作区，不是跨电脑全局额度控制。
- 缺数据先补来源或可复现输入并实际计算；结果性质与未验证范围保留工作区。原文、源式、原图不丢失。
- plan/dry-run/doctor/单元测试均不代表真实案件交付完成。独立验收和当前文件哈希绑定。
- 新版配置开启运行前环境预检，先检查工具、Python 依赖、CLI 登录与浏览器二进制，再进入模型制作。`doctor --smoke` 额外启动隔离浏览器并实际渲染临时 Word，不调用模型。
- 权限/策略拒绝、文件锁、依赖故障与内存错误分开处理；安装脚本不调整 ACL、执行策略或审批设置。

详细规则见 [AGENTS.md](AGENTS.md)、[成品优先流程](rules/deliverable-first.md)、[成果合同](docs/artifact-contract.md)。

## 开发验证

```powershell
.\scripts\test.ps1
```

测试使用临时夹具与模拟执行器，不消耗模型额度、不修改真实案件。历史私有调研资料与现场验证记录不在仓库中；[发布核验说明](docs/发布核验.md)区分脚本测试、环境试运行和真实案件验证。
