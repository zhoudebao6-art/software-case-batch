# 公开源代码CI范围

当前检查由[Public source contracts](.github/workflows/tests.yml)在Windows运行，使用只读权限、固定Actions提交、公开依赖和无秘密的临时配置。

- Python发现全部`tests/test_*.py`，覆盖Windows Job生命周期、队列、合同、打包、图表渲染、数据、归档、环境和收尾。
- Node运行`tests/test_record.cjs`，包括真实Chromium定位、清空和输入检查。
- 冻结规范的CI依据是`tests/fixtures/original-snapshot-baseline.json`，验证26份原规范及原索引哈希。历史证据保留，不因清理仓库而合成通过记录。

依赖版本以[requirements-ci.txt](requirements-ci.txt)和workflow为准。Playwright模块安装在`D:\codex+\dependencies\scb-ci`，浏览器、npm缓存及当前进程TEMP/TMP/TMPDIR位于`D:\codex+`。安装后核验模块版本和Chromium路径，失败立即退出。

CI不调用付费模型、不配置业务录制FFmpeg，不执行真实跨盘归档、完整Word视觉审查或案件交付验收。80.1秒真实编码夹具仅在本机显式设置`SCB_PRO_MEDIA_FIXTURE=1`时运行；CI默认如实显示该项跳过，其余已发现用例正常执行。实际业务、视频和文档质量仍须依技能要求核对。

判断一次发布是否通过，应核对Actions的提交SHA与所发布提交相同、状态completed且结论success。过去的绿灯或本机通过不能替代当前远端结果；失败日志保留，不能跳过失败用例或改变安全配置来制造通过。旧版本迁移和修复经过可通过Git历史及Actions记录追溯。
