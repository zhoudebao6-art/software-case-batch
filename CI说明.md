# 公开源代码CI范围

原`.github/workflows/tests.yml`运行旧`requirements.txt`、`scripts/check_source_package.py`和`scripts/test.ps1`。根目录换成新版pro源代码后，这些不是新版对应入口，不能原样沿用或把旧CI绿灯解释成新版通过。候选workflow保留原有只读权限和已固定的Actions提交，换成新版实际Python/Node测试；仅使用公开依赖和无秘密的临时local.config。

Python完整发现并运行当前`tests/test_*.py`，包含Windows Job生命周期、资源队列、合同、打包、默认输出和环境加载等实际用例；Node运行`tests/test_record.cjs`。不按文件或方法排除任何用例。Python额外导入依赖只有Pillow；`requirements-ci.txt`固定本机当前已安装的12.3.0。CI不安装浏览器/FFmpeg，不调用付费模型，不执行live_smoke，不进行Word渲染或实际业务交付验收；生成配置中的媒体路径明确标注不供这些单元测试使用，不能用于实际录制。

发布前须合并独立修复：`test_defaults.DefaultPolicyTests.test_original_snapshot_and_r1_record_stay_unchanged`改为读取`tests/fixtures/original-snapshot-baseline.json`。该fixture仅从真实r1不可变快照提取原规范相对路径/hash及原sources索引hash，不含本机证据或绝对路径，原26源/78项检查全部保留。缺失fixture、hash不符或仍读取未发布内部evidence都必须让CI失败；不能用skip或合成通过快照隐藏发布缺陷。

GitHub Windows runner的真实Job准入及进程行为仍以首次Actions执行为准。若合法执行环境不支持，CI应直接失败并保存原因，不调整安全配置或把Windows测试静默跳过来制造green。候选没有在GitHub执行，不能声明远端已通过；本机相同测试集合通过也不是远端运行证明。

若父最终发布包未合并本说明、requirements-ci及新版workflow，应删除旧失效workflow，而不能继续展示与新版源代码无关的CI状态。删除只针对本次已授权公开发布包中的旧workflow，不删除Git历史或其他工作区配置；后续CI须恢复为真实可运行检查。
