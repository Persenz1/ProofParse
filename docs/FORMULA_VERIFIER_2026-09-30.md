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

计数只能核对受支持的文字层，无法发现非乱码 Unicode 的错误 ToUnicode；这种误报会在正式混淆矩阵中保留。未改 check_latex，未改写或确认论文内容。

## 阶段 2：字体编码表

`proofparse/formula/fonttables.py` 增加白名单字体、OML 希腊字母编码、OMS 部分符号与字体样式。依据 [LaTeX Project 编码指南](https://tug.ctan.org/macros/latex/base/encguide.pdf)、[AMSFonts 字体表](https://tug.ctan.org/fonts/amsfonts/doc/amsfndoc.pdf)，并核对本地 TeX Live 的 oml/oms/umsb CMap。明确区分编码槽、Unicode 与子集 GID；没有真实编码槽的乱码不按 GID 猜码。修正 epsilon/varepsilon、phi/varphi 的经典 TeX 字形对应关系，归一化不抹去普通希腊变体。

`apply_glyph_map` 的确认映射优先于 font_table，冲突进入 findings；mapping_detail 与冲突进入哈希。README 和复查协议同步说明来源等级及旧清单重导出。

`proofparse/pdf/fontnames.py` 提供可选 TTF/OpenType/CFF GID→字形名路径，`pyproject.toml` 增加 fontnames extra。用 [fontTools 官方接口](https://fonttools.readthedocs.io/en/latest/ttLib/ttFont.html) 与 CFF charset；未安装、不嵌入或字形名无语义时明确降级。现有解释器没有 fontTools，未安装；真实字体名恢复路径未实跑，不宣称已验证恢复效果。`tests/test_font_tables.py` 覆盖全部字体族、编码槽、GID 不代替字符码及确认优先级。61 项测试中 60 通过、1 跳过、0 失败；跳过项是 fontTools 的嵌入 CFF 测试。

三篇真实 PDF 的全页字符统计位于 `output/verifier-eval-20260930/stage2-fonts.json`：均没有白名单字体，font_table 映射各 0、与已有确认映射一致/冲突各 0。因此 t05/t21 不能由白名单表自动解决；已有文档内 K/B 视觉映射可复用，但其效果不能记为新字体表的自动能力。Adv/STIX/Bembo/TeX_CM_Maths_* 名称不做无来源扩张。没有修改用户的映射文件。

## 阶段 3：几何结构

`proofparse/formula/geometry.py` 增加唯一符号的上下标路径对照和单个非嵌套矩阵的主基线行数核对；阈值固定为字号比 <0.85、基线偏移 >0.15×主体字号、聚类容差 0.3×字号。candidate_atoms 保留完整嵌套路径，分式/binom 内符号不参加上下标对照；矩阵含分式、多个/嵌套环境或边框不明确时明确跳过。末尾空行分隔符不计新行，以免普通 TeX 末尾换行产生误报。

真实 PDF 的 CMEX 文本 bbox 可能不覆盖实际伸长括号，且同字体还有重音/普通函数括号。实现仅选括号字形，按伸长跨度与配对区分边框，保留与目标相交但中心在外的扩展字形，并用目标纵向范围核对主基线。旋转写入方向不水平时明确 unreliable。`proofparse/pdf/native.py` 增加显示页坐标的书写方向，review 摘要包含 script_check/matrix_check，均进入哈希。

`tests/test_formula_geometry.py` 增加 6 项行为测试，包括嵌套角色、严格阈值、重复歧义、分式跳过、2×2 缺行及脚标不增行。最终 67 项中 66 通过、1 跳过、0 失败。开发中失败已修复，代表输出为：

```text
File "proofparse/formula/native.py", line 307
    else:
SyntaxError: invalid syntax
Ran 45 tests
FAILED (errors=17)

FAIL: test_missing_number_is_separate_from_body_font_and_prose
AssertionError: Lists differ: ['script_constraint', 'number_constraint', ...]
Ran 67 tests
FAILED (failures=1, skipped=1)
```

首个失败来自重复接入片段，已移除；第二个失败来自没有字体元数据的合成字形参与几何，已将这种证据明确降级。未通过修改旧测试断言掩盖失败。

88 路实测位于 `output/verifier-eval-20260930/stage3.json`。t11 B/M/L 的唯一符号 2 存在下标路径差异，得到 script_constraint。t13 A/B/M 主要由计数拦截；L 不按旧预设认定归属错误。t16 B/M 完全没有矩阵环境，不能用“仅一个矩阵环境”规则强猜行数，仍由计数抓到缺失 0/1；A/L 的 0→θ 仍由计数发现。完整误报在阶段5逐候选列出，几何路径只提供局部层级证据，不证明重复符号与具体主体的绑定。
