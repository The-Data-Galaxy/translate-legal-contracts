# 一次公开虚构合同的实际运行

执行日期：2026-11-14。虚构数据，仅供展示，不用于签署。署名朱玲凤，本文及演示合同、译文、记录、截图采用CC BY 4.0；生成脚本采用Apache-2.0。

## 输入与结果

- 原件：[source.docx](source.docx)，1页，14个来源块、1张表。
- 输出：[bilingual.docx](bilingual.docx)，1页，中文原文后跟随对应英文。
- [原件截图](source-page-1.png)和[双语稿截图](bilingual-page-1.png)均由本次实际DOCX渲染，不是模拟界面。
- [run.json](run.json)记录输入、输出SHA256及三条CLI的退出码；[audit.json](audit.json)结构通过，errors与warnings均为空。
- [冻结译文](translations.json)、[布局输入](layout-plan.json)、[对应清单](alignment.json)随本次结果公开；不使用真实客户材料。

## 复跑同一个示例

在仓库根目录、Python 3.10+环境中执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r examples/requirements.txt
.venv/bin/python examples/run_demo.py --out-dir /tmp/contract-skill-demo
```

输出目录必须为空。脚本创建虚构原件，调用发布资源中的inspect、compose、audit；保持源哈希绑定，不对成品打补丁。源码见[run_demo.py](../../examples/run_demo.py)。

脚本使用固定译文，不调用模型。复跑结果的ZIP时间戳可能造成DOCX摘要变化，但每次运行仍记录输入/输出的真实摘要并核对原件未改。脚本不自带排版引擎；要复核页面，请用当前宿主可用的Word兼容渲染工具打开新输出并查看全部页面。此处公开截图对应2026-11-14保存的这一次输出。

## 本次检查了什么

原件未改变；14个来源块全部有英文对应；英文11pt；表格译文左对齐且false加粗未扩张；表格与签署区完整。原件与输出各渲染一次，共2页，两页均实际查看。

逐条对照检查了服务费CNY 12,000、候选人正式入职的收费条件、有效发票后10个工作日付款、书面异议金额的付款例外。含义与视觉检查由同一Agent完成，不是独立盲测。

该用例不含自动编号、目录、页码域、修订或批注，不覆盖这些特征的真实显示。本轮没有重跑既有16项组或历史真实合同，也不代表宿主安装发现已验收。
