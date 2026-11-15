# 统一制作与渲染入口

本Skill的普通DOCX任务由`scripts/contract_run.py`管理一次执行。它复用contract_docx.py和word_layout.py，不翻译文字、不修补成品，不代替法律复核。保留原件及默认中英上下对照格式。

## 普通调用

用inspect取得清单并完成本轮译文、必要的布局计划后：

```bash
python scripts/contract_run.py status source.docx
python scripts/contract_run.py run source.docx --translations translations.json --layout-plan layout-plan.json
```

简单无域文件可省略layout-plan。不要重新运行旧build/compose后另行渲染。预算默认1次渲染、累计30页、30次页图查看；宿主已有明确批准时，由执行层在任务开始前配置一次：

```bash
python scripts/contract_run.py init source.docx --max-renders 2 --max-pages 50 --max-views 50
```

init只能在尚无账本时使用；run/review不能增加预算。没有外部批次批准时不照抄此2次示例。已存在账本就复用，不删除、改写或复制原件到新目录重置。用户不需要提供命令或JSON；技能使用者负责把已批准范围带入执行，不能把另一个聊天的限制当成当前宿主已知。

每份原件在其所在目录使用固定`.contract-run-<源哈希前12位>/run.json`。跨进程加锁，渲染启动前预占次数；失败、超时、中断仍保留消耗并停止。原件、译文、布局及脚本/渲染配置绑定到每次版本。译文在首次成功结构检查后冻结，布局重试不能顺便重译。

## 检查与一次布局修正

run返回output、manifest、audit、pages_dir及page_count；状态visual_pending表示还未验收。逐页实际查看页图，核对文字、字号、断表、页码、空白及签署区。然后记录实际查看范围：

返回的`target_language_review_required`和`target_language_findings`来自该版本audit，缓存也透传。英文目标残留中文时，先按名称处理规则逐项纠正或在单独说明中交代位置、保留理由和确认状态；不能只看结构/视觉状态便宣称全文已译完。合理保留也会提示，人工说明并不由脚本自动核实；旧audit没有此字段表示尚未扫描。

```bash
python scripts/contract_run.py review source.docx --pages 1-21 --verdict pass --note '全部21页已实际查看；收款表及签署区完整，无缺字遮挡'
```

页数必须来自本次返回，不固定为21。分批查看可分别记页码，重复查看仍计次数。发现问题改用verdict fail，note写实际位置和问题；有失败的版本不能靠再次标pass洗掉失败。只有声明的布局输入改变、前版记录具体视觉失败且预算尚有余额，才允许再次run；从原件及冻结译文重建，不修改旧版成品。超出批准范围时停止，交付说明明确未完成项，不自行追加。

同一输入及相同渲染配置再次run时，只在DOCX、manifest、audit、PDF和全部页图字节摘要吻合时复用缓存，不再次调用渲染器。任何产物被改都拒绝复用。新布局即新版本，不沿用前版检查声明。complete仅是结构通过且当前全部页图已有查看声明；它不证明实际读图或法律准确性，仍需真实宿主轨迹及逐条语义复核。

## 环境和停止边界

macOS默认调用`~/.local/bin/codex-render-docx`及其CJK配置，指纹包含包装脚本、被分派的渲染脚本及Fontconfig。其他环境需在初始化时指定已有且支持`DOCX --output_dir DIR --emit_pdf`的可执行适配器；缺失时停止，不猜工具路径或循环安装。固定适配器配置不等于能检测所有系统字体或软件环境变化，环境实际改变时不要复用旧视觉结论。

页数只有导出后才准确取得，max-pages是累计事后停止条件，不能承诺从不多生成一页；超过则不批准、不继续。成功退出只表示当前操作完成，必须看status。CLI停止返回3。渲染日志、失败版本、输入快照及查看声明留在同一运行目录，供接续核对。

预算限制覆盖本入口。任意shell、编辑账本或另建目录的宿主仍可能绕过；严格阻断需要宿主工具权限/调度支持，不能声称Skill脚本已提供系统级权限控制。不得旁路后仍宣称本入口验收通过。复杂特征被构建器拒绝时保留原守卫，交付未完成说明，不能降级删除结构来通过。
