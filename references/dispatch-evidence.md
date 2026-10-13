# 桌面加密派发记录的证据绑定

`model_review` 保留明文派发的 token、dispatch_nonce、run_id、workspace 校验。只有真实父会话 `spawn_agent.arguments.message` 是完整、受支持的 `gAAAA...` 桌面信封时，才采用 `desktop-encrypted-spawn-v1`。识别信封格式不代表解密或验证其密码学真实性；工具不读取密钥、不恢复正文、不改写原始 JSONL。

加密派发仍必须有当前案件的不可变 review admission 和已验证 dispatch permit。许可的 `issued_ns` 不得早于 admission 的 `acquired_ns`，且必须不晚于父会话实际派发时间。父日志中指定 call_id 必须恰有一次真实调用和一次成功返回；模型、effort、fork_turns、角色独立性、当前产物与图表快照的既有检查继续执行。

父调用和返回必须具有带时区的实际日志时间。真实子会话必须有唯一 session_meta、不同于父会话的真实 ID、匹配的 parent_thread_id 和 agent_path；子会话创建时间必须位于该调用和返回之间。这项校验用于拒绝将旧子会话或旧调用嫁接到当前许可。若日志时间精度无法证明许可先于派发，保持拒绝；不要用容差、密文内未认证时间或父层文字摘要替代证据。

加密路径要求当前 review JSON 和该真实子会话的最新 assistant final 共同绑定以下完整对象：

```json
{
  "contract": "desktop-encrypted-spawn-v1",
  "token": "来自冻结 admission 的 token",
  "dispatch_nonce": "来自冻结 dispatch permit 的 nonce",
  "run_id": "来自冻结 admission 的 run_id",
  "workspace": "来自冻结 admission 的绝对 workspace",
  "parent_session_id": "真实父会话 session_meta.id",
  "call_id": "真实 spawn_agent call_id",
  "dispatch_message_sha256": "实际 arguments.message UTF-8 字节的 SHA256",
  "dispatch_event_sha256": "与门禁相同规范化方式计算的真实 call/result 事件 SHA256"
}
```

对象保存在 proof 的 `review_dispatch_binding` 字段，也原样包含在独立审查者的最终 JSON 中。最终 JSON 继续包含 `reviewer_agent_id` 和当前 proof 文件的 `review_evidence_sha256`；最终消息时间不得早于父调用成功返回。门禁核对传入 proof 对象与被签署文件内容一致，随后核对最终 proof SHA256。最新版 final 必须是完整 JSON，仅允许末尾附加规定的 memory citation XML；中间消息、父总结、任意 JSON 片段、签名后被修改的 proof 或旧 final 都不能代替此证据。

只读辅助 API：

```python
from contracts import review_dispatch_binding

binding = review_dispatch_binding(
    workspace, admission_reference, permit_reference, session_log, call_id
)
```

`workspace` 为当前执行目录；两个 reference 均是已有 `{"path": ..., "sha256": ...}` 对象；session_log/call_id 指向真实父调用。该 API 读取冻结 admission/permit 和真实调用/返回并返回绑定对象，不输出 `pass`、不验证审查内容、不写 proof、不修改日志，也不生成或补签最终消息。独立审查者在实际完成原有六类审核、全部图文/视频覆盖和当前产物检查后，自己决定结论并签署最终证据。

这条路径能证明真实已记录调用、许可时序和真实独立审查者最终声明之间的绑定，无法证明加密指令正文或信封的 MAC。若真实 child final 也只有不可读 encrypted_content，门禁继续拒绝；不尝试解密，不把已有父总结变成审查者签名。历史明文路径保持原规则，不以旧 schema 规避新批 admission/permit。
