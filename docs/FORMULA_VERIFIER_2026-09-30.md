# 公式确定性验收器实现与实测

## 评测口径

金标准复核由代理完成，不计为人工确认。目标是忠实转录 PDF 的目标数学片段，裁图外编号另行关联，不计入主体正确性。t20 源文确实缺上标右括号，保留原文；原任务书的“L 漏括号”假设不成立。

复用 `D:/DevTools/Conda/envs/litparse/python.exe`，Python 3.12.14、PyMuPDF 1.28.2。测试命令为 `python -m unittest discover -s tests`，临时文件位于仓库 `output/verifier-work-20260930-next/`。输出、论文、裁图和密钥不提交。

## 阶段 1：计数

- `proofparse/formula/native.py`：比较 ASCII 字母数字、希腊字母与指定标点的数量；支持减号、prime 和数学 Unicode 归一化，排除编号、扩展字形及重音，未知宏和乱码明确跳过。补充已知符号、内建运算符、字体声明和 array 列格式解析。
- `proofparse/review/native.py`：摘要包含 count_check，不可靠或未能检查的非空候选也生成复查裁图。
- `proofparse/review/collect.py`：计数不可靠或跳过仍保留待审，不以无 finding 当作通过。新增证据进入现有 evidence_hash/input_hash。
- `tests/test_formula_count.py`：增加 7 项直接行为测试。全量 54 项通过、0 跳过、0 失败。

88 路同裁图实测保存在本机 `output/verifier-eval-20260930/stage1.json`：t11 B/M 的额外 ξ 被计数抓到，L 的额外 0 也被抓到；t16 B/M 的缺下行表现为缺 0/1，A/L 的 0→θ 被抓到；t13 A/B/M 有符号缺失，L 无计数 finding。t10 A 的粗体 F 仍由原 font_constraint 抓到。t05 四路均有未映射乱码，计数 unreliable。t20 跳过所有定界符，没有括号 finding，且原文缺括号不应当作 L 错误。t21 L 的额外 1 可检出，但源层把逗号写成分号，所有候选都有标点冲突；不能把这些冲突都算真实转录错误。t22 有正文边界 finding，并有源编码 o 引起的计数冲突。

计数只能核对受支持的文字层，无法发现非乱码 Unicode 的错误 ToUnicode；这种误报会在正式混淆矩阵中保留。未改 check_latex，未改写或确认论文内容。阶段 2～5 待完成。
