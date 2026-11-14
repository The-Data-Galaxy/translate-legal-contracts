# 正式布局路径

`build`仍只接受简单、无域DOCX。需要布局计划，或文件仅额外含页眉/页脚PAGE、NUMPAGES域时，使用同目录`contract_docx.py compose`。有目录、正文域、修订、批注、文本框、图形、对象或其他复杂特征时仍走完整文档工具，不移除保护。

## 输入

继续使用inspect产生的翻译映射，保留全部id、source_text、source_sha256。包含页码域的段落另加`field_template`，例如其translation为`Page  of `时，对应`Page {PAGE} of {NUMPAGES}`。占位的字段顺序/数量必须与来源相同，静态文字必须等于translation。只保留原字段语义，不把页码值写死。

另存layout-plan.json：

```json
{
  "source_sha256": "与inspect一致的源文件摘要",
  "tables": [
    {
      "table_index": 1,
      "policy": "new_page_block",
      "start_before": "从inspect选择的语义块首段id",
      "reason": "该关键业务小表需连同标题和引导文字保持完整"
    }
  ]
}
```

示例值是字段说明，使用时必须由当前文件实际清单填写，不是固定表号/章节规则。table_index为正文顶层表格从0起的序号；start_before对应原文中的块首段，如该表的章节标题，且应在该表之前、不跨其他语义块。

短表策略仅用于关键且实际可容纳一页的块，当前助手保守限制最多4行，块首段与表之间不超过12个正文节点。它在整个块之前插入明确分页，不更改原段落文本、字体或编号。不能凭行数认定长单元格一定容得下一页；无法容纳时选择流动表格或宿主工具。

块首已是正文起点、带显式pageBreakBefore，或前一段仅含显式分页符时，复用已有边界，不再插一次分页。先查看原件已有分页；签署表行数超出短表范围时仍可按flow并保留原分页，不能额外打补丁强行适配。

长表或无需单页保持的表格用：

```json
{"table_index": 0, "policy": "flow", "repeat_header_rows": 1, "prevent_row_split": true}
```

长表不强制整表同页；按业务含义选择重复表头行数。只在一行本身可容纳一页时使用prevent_row_split，极长单元格允许合理跨页。flow只调整表头/行分页属性，不改变列、合并关系或业务文字。

## 执行与验证

### 经用户允许取消一处独立分页

用户允许原件某个独立块随前文排版时，在同一个源版本绑定的计划中增加：

```json
"page_breaks": [
  {"before": "从当前清单选取的来源段落ID", "policy": "allow_flow",
   "reason": "记录用户允许改变这一分页安排的决定"}
]
```

`before`必须是正文顶层的有内容原段落。助手只移除它紧邻前方、仅含一个显式分页符的空段落；不改该锚点的原文或格式，不删任何文字、书签、域、脚注引用、节分隔，也不修改段前分页。条件不满足、锚点重复、理由为空或同一锚点又要求new_page_block时拒绝。未提供page_breaks时所有原分页保持。

这不是按合同名称、签署字样或页码自动删分页。独立签署页等原件意图须先遵循用户选择；不能只为减少页数擅自启用。计划变化后从原件及既有译文重新compose，生成后不得再修补Word；仍需按授权范围渲染验证是否出现断表或签署区拆分。

```bash
python scripts/contract_docx.py compose source.docx --translations translations.json --layout-plan layout-plan.json --out bilingual.docx --manifest alignment.json
python scripts/contract_docx.py audit bilingual.docx --manifest alignment.json --out audit.json
```

正文、表格译文均经共享word_layout.py生成：显式11pt；表格英文左对齐；正确解释on/off值，段落/字符样式的加粗toggle与直接格式覆盖；不复制源pageBreakBefore到对应译文。混合局部强调不扩张为整段加粗，需逐词强调时由文档工具处理。助手不解析全部条件表格样式或全部Word排版能力。

页眉/页脚译文保留其原段落样式，显式使用单倍行距、零段前后距并取消网格吸附，避免回退到正文精确行距；英文仍为11pt，原文与动态域不改。可用高度、复杂页脚仍需实际渲染，不保证任意页边距都能容纳新增内容。

新schema_version=1清单附带`generated_layout_sha256`，审计会核对生成时各段属性/分页和表格属性快照。成品被临时脚本或编辑器改过这些布局时审计失败，应从原件和声明计划重建；不得篡改清单消除失败。它不禁止用户后续编辑Word，也不代替视觉检查；后续编辑稿和生成时证据分开。旧schema1清单仍可读取，但没有这个快照证明；无关未用样式的字体变化不触发该检查。

Microsoft说明：[Bold/toggle及直接false](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.bold?view=openxml-3.0.1)、[On/Off值](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/a75c8fb9-134d-433a-9ce6-8e3905566a30)。属性节点存在不能代替其实际值。

结构audit不计算真实分页。生成后按既定渲染验收；不能假定keepNext已让整个表同页，不能给所有表硬插分页。发现重复问题应修共享助手/规则并从原件重建。Skill复测只能使用正式入口及声明的输入计划，不允许再用任务专用输出补丁作为Skill已修复证据。
