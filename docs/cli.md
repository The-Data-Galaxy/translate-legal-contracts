# 命令行辅助工具

本页面向希望单独运行Python工具的使用者。[用户入口与完整旅程](../README.md)。辅助工具不调用模型，译文需先由Agent或使用者填写。

## 能力边界

| 对象 | 实际能力 |
| --- | --- |
| Skill指令 | 指导支持文件工具的Agent执行中译英、英译中、双语排版与修复；需要宿主自身的语言与文档处理能力 |
| `contract_docx.py inspect` | 清点DOCX段落/部件和复杂特征，提供翻译映射起点 |
| `build` | 把已经填写的英文译文插入原文后，适用于受限简单DOCX；不调用模型、不自动翻译 |
| `compose` | 在源版本绑定的布局计划下，复用共享格式助手处理表格布局；额外支持受限页眉页脚PAGE/NUMPAGES域，其他复杂结构仍拒绝 |
| `audit` | 检查原文/译文对应、段落属性、解析器支持的继承编号及译文直接11 pt等；不判断法律含义或视觉质量 |

默认中文在前、英文紧随，保留原件及原中文格式。英译中、左右栏、复杂域/自动目录、修订、批注、文本框、插图等需按Skill改走宿主文档工具。构建器拒绝复杂结构时，不删除保护绕过。显示编号须先经实际排版引擎核对，脚本不计算Word最终显示值。

## 安装与调用补充

下载发布包后，将整个`translate-legal-contracts`文件夹放入宿主支持的Skill目录。Codex常用目录为`~/.codex/skills/translate-legal-contracts/`；已有同名目录时先确认版本，不直接合并覆盖。本版本尚未进行宿主安装/发现验证，其他宿主的安装方式及配置字段支持需分别核实。

示例请求：

> 请使用 $translate-legal-contracts 把这份合同做成中英文对照Word，保留原文和编号，英文11 pt；核对金额、条件和例外，并检查最终版式。

## 单独运行辅助脚本

需要Python 3.10+与lxml。在仓库根目录执行以下命令；确认`python3 --version`满足要求，不满足时换用实际安装的兼容解释器。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/contract_docx.py inspect source.docx --out inventory.json
```

将`inventory.json`中的`translation_template`对象另存为`translations.json`，保留源哈希、id与source_text，填写英文translation；对自动编号填已核验的display_number。它不是把inventory.json整个对象直接当翻译映射。

```bash
.venv/bin/python scripts/contract_docx.py build source.docx --translations translations.json --out bilingual.docx --manifest alignment.json
.venv/bin/python scripts/contract_docx.py audit bilingual.docx --manifest alignment.json --out audit.json
```

涉及关键小表整体分页、长表表头/行分页安排，或页眉页脚页码域时，按[布局计划](../references/layout-plan.md)准备layout-plan及字段槽，使用正式路径：

```bash
.venv/bin/python scripts/contract_docx.py compose source.docx --translations translations.json --layout-plan layout-plan.json --out bilingual.docx --manifest alignment.json
```

build仍拒绝所有复杂特征；compose也不处理TOC、正文域、修订/批注或图形对象。关键小表必须由当前文档的语义块定位，不能固定某章某页；长表保持流动。布局计划是声明的输入，生成后另打专用补丁不算Skill路径复测通过。

全部输入、DOCX输出、manifest和审计输出使用不同文件路径。路径保护会拒绝覆盖输入和输出间碰撞，包括已有文件的符号链接/硬链接别名；不抵御其他进程在检查与写入间恶意更换文件。已有独立输出可能被重写，需保留需用的历史版本。

退出码：0表示该命令完成；audit返回1表示结构检查失败；输入/路径等已处理错误返回2。inspect报告复杂特征不代表已构建；audit为0也不代表数字警告已解决、全文语义正确或页面已验收。原包manifest schema_version=1及字段保持兼容；缺少有效原始manifest时不声称已核验。

## 可运行的最小演示与回归

正常构建/核查演示使用临时合成Word，无需客户文件：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

固定16项行为及结果范围见[TESTS.md](../TESTS.md)、[EVAL.md](../EVAL.md)和[benchmark记录](../benchmark/README.md)。测试自动删除临时文件，不产生可对外签署的合同。

一个仅供说明的虚构片段：

> 原文：甲方应支付人民币100元；但对已书面提出争议的金额除外。
>
> 译文：Party A shall pay CNY 100, except for any amount disputed in writing.

实际任务仍须按上下文检查定义、条件与救济。此片段不是已通过完整合同翻译/视觉验收的展示案例。

