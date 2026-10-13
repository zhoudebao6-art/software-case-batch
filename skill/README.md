# 原skill路径迁移

完整活动技能已移至[仓库根目录SKILL.md](../SKILL.md)，名称为`software-case-batch-pro`。本目录不保留旧十秒/两页合同，也不包含活动SKILL，避免整个仓库注册为pro时递归发现第二个旧名称入口。旧安装器、旧caseflow和旧setup说明不是新版部署方式；先按根目录README安装完整pro并配置本机环境。

若需要继续`$software-case-batch`名称，显式安装本目录两份模板到仓库外的用户技能目录。以下仅适用于**旧名称尚未安装**：从完整仓库根目录运行，先确认pro已安装且可读；已有旧入口按已授权升级方案备份核验后处理，不能用本示例强盖。

```powershell
$TaskRepo = (Resolve-Path -LiteralPath '.').Path
$TaskCodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$TaskSkillRoot = Join-Path $TaskCodexRoot 'skills'
$TaskPro = Join-Path $TaskSkillRoot 'software-case-batch-pro'
$TaskAlias = Join-Path $TaskSkillRoot 'software-case-batch'
if (-not (Test-Path -LiteralPath (Join-Path $TaskPro 'SKILL.md'))) { throw '先安装并核验完整pro技能。' }
if (Test-Path -LiteralPath $TaskAlias) { throw '已有旧名入口：先备份核验，不强盖。' }
New-Item -ItemType Directory -Path (Join-Path $TaskAlias 'agents') | Out-Null
Copy-Item -LiteralPath (Join-Path $TaskRepo 'skill\SKILL.compatibility.txt') -Destination (Join-Path $TaskAlias 'SKILL.md')
Copy-Item -LiteralPath (Join-Path $TaskRepo 'skill\openai.compatibility.txt') -Destination (Join-Path $TaskAlias 'agents\openai.yaml')
```

兼容入口依赖已安装pro，每次调用完整读取其真实目录的SKILL及阶段引用；pro缺失则保留未完成，不回退旧流程。本机既有旧名替换可使用本次已授权且独立验收后的本机兼容安装方案，不执行这组新安装命令。
