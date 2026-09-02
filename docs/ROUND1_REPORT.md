# 第一轮任务报告：proofparse 最小原型（MinerU pipeline）

日期：2026-09-02

## 1. 环境检查结果

| 项目 | 状态 |
|---|---|
| GPU | NVIDIA GeForce RTX 4060 Ti 8GB，驱动 32.0.16.1656，状态 OK |
| nvidia-smi | 在本 shell 中报 NVML 错误（CLI 问题），但 torch CUDA 实测可用 |
| torch | 2.14.0+cu126，`torch.cuda.is_available() = True`，识别 8GB 显存 |
| Python | 新建 conda 环境 `D:\DevTools\Conda\envs\litparse`（Python 3.12） |
| 说明 | 系统另有 MSYS2 Python 3.14（GCC ABI，不能装 PyTorch 官方 wheel，不可用）；base conda 3.13 超出 MinerU Windows 支持范围 |

## 2. MinerU vs Marker 调研结论

| 维度 | MinerU 3.4.5 | Marker（当前版） |
|---|---|---|
| Windows 原生 | ✅ pipeline 后端（Python 3.10–3.12） | ⚠️ 新版 surya 依赖 vLLM(docker)/llama.cpp 推理服务，原生 Windows 上更复杂 |
| 显存 | pipeline 最低 4GB | 每任务约 4–5GB |
| 公式 | 内置 MFR（UniMERNet 系），display + inline 都转 LaTeX | texify/surya 方程 OCR，inline math 需 `--ocr_inline_math` |
| 中间结构 | content_list.json：块类型 + bbox + page_idx | JSON 块 + bbox |
| 与本项目契合度 | MFR 即 UniMERNet，正好是候选 Formula OCR 之一，后续 QC 双识别可复用 | 需要再引一套公式模型 |

**选型：MinerU pipeline 后端作为第一版 parser**，Marker 保留为 adapter 备选。

## 3. 实际测试结果（3 篇真实论文，GPU 全速）

| 论文 | 页数 | 类型 | 块保留 | display eq | inline math | QC 警告 |
|---|---|---|---|---|---|---|
| resnet_cvpr2016 | 12 | 双栏 CVPR | 95/177 | 2 | 26 | 0 |
| attention_is_all_you_need | 15 | 单栏公式密集 | 107/141 | 5 | 54 | 0 |
| ddpm_neurips2020 | 25 | 数学密集 | 88/184 | 16 | 109 | 1（真实 OCR 错误） |

验证通过项：
- Abstract / section / subsection 结构正确，双栏阅读顺序正确（左栏→右栏）
- References 确定性截断：3 篇全部正确截断，无误删正文（Acknowledgments 保留）
- Figure / Table / caption / 页眉页脚页码全部过滤
- display equation 含 `\tag{n}`、underbrace、KL、分数、根号、上下标均正确
- inline math 大部分正确：`$d_k$`、`$\sqrt{d_k}$`、`$\alpha_t := 1-\beta_t$`、`$\bar\alpha_t$` 等
- QC 机制有效：DDPM 一个跨行复合公式 brace 不匹配（66 vs 64）被自动捕获，
  并用 page+bbox 成功渲染裁剪出复核图（`eq_45_check.png`）

## 4. 发现的错误与已知问题（按优先级）

1. **部分行内数学丢失数学模式**（影响最大，符合任务书预警）：
   - Attention：`LayerNorm(x + Sublayer(x))`、`matrices K and V`、`position i` 未进 `$...$`
   - ResNet：`3 3 filters`（应为 3×3）、`8 deeper`（应为 8×）、`(x) + x`（丢失 \mathcal{F}）
   - 原因：PDF text layer 对这些短符号不可见/不可靠，pipeline 的 inline 判定未覆盖
   - 对策：Step 2 的专用 Formula OCR 对比机制正是为此设计
2. **MinerU 3.x content_list.json 的 bbox 是 1000×1000 归一化坐标**（非 PDF 点），
   裁剪时必须换算；已在 README 记录
3. **year 提取不可靠**：Attention 论文被提取为 2014（来自摘要 "WMT 2014"，实际 2017）
4. **authors 行粗糙**：混入单位、邮箱、`<sup>` 标签（front matter 中未清理 sup 标签）
5. **出版商标注泄漏**：Attention 首页顶部 Google 授权声明作为段落进入正文开头
6. **标题层级扁平**：MinerU 把 section/subsection 都标为同一级（3.2.1 与 3.2 同级 #）
7. MinerU 3.4.5 pip 包漏声明依赖 `six`，需手动补装

## 5. 追加测试：A Survey of Motion Planning and Control（IEEE 双栏，23 页）

用户提供样本，2026-09-02 实测：301/409 块保留，58 个 display eq，213 处 inline math，1 条真实 QC 警告。

新增确认的问题：

8. **IEEE 首段 drop-cap 丢字**：正文第一句 "THE last three decades have seen steadily
   increasing research efforts ... towards" 整段丢失，输出直接从 "developing driverless
   vehicle technology." 开始。原因：IEEE 期刊首段大号首字母 + 特殊排版未被 layout 模型
   正确检测。这是召回类错误，比格式问题更严重，需要专门对策（如首段区域二次检测）
9. **DOI 在 dropped 块里**：`Digital Object Identifier 10.1109/TIV.2016.2578706` 被分类为
   页脚过滤了，元数据提取应同时扫描 dropped 块找 DOI/年份
10. **作者名变音符号损坏**：`Michal Čáp` 输出为 `Michal C<sup>ˇ</sup> ap`（front matter）
    和 `Michal Cˇ ap`（正文），IEEE 特殊字体编码导致
11. QC 再次验证有效：eq_111 分段函数 brace 不匹配（24 vs 23）被捕获，
    裁剪图确认该区域为三分段复杂公式，识别结果大体正确但多/少一个花括号

## 6. 下一步建议（对应任务书 Step 2）

1. 接入专用 Formula OCR 做双识别比对。MinerU 自带 UniMERNet，可直接复用其 MFR 模型
   对 equation bbox 区域重识别，与 pipeline 结果做归一化相似度比较 → PASS/REVIEW
2. review_assets：对所有 QC 警告块自动生成裁剪图（坐标换算已验证）
3. 补充异常 PDF 样本（扫描件、老论文）测试 OCR 路径
4. 修复 year/authors 提取启发式

---

# 第二轮：QC 漏斗第 1 层落地（2026-09-02 下午）

目标：尽可能减少 Agent 干预，确定性问题本地自动发现/自动修复，
只有无法判定的才标记 needs_review 并配裁剪图。

## 已实现模块

1. **位置感知文本覆盖率检查**（`normalize/coverage.py`）
   - pypdf `visitor_text` 提取带坐标的文字层 → 换算到 MinerU 1000×1000
     归一化空间 → 按 bbox 把文字块指派给最小包含 block
   - 落在 figure/table/caption/footnote 等 dropped 块内的文字不参与检查
   - 判定指标：difflib matching_blocks 累计的**缺失字符数 ≥40** 才报警
     （不能用最长公共子串——零散差异会高估缺失；也不能用相似度——
     长段落丢一整句 similarity 仍 >0.9）
   - **自动补回**：parser 输出是文字层后缀（IEEE drop-cap 丢首句场景）时，
     把缺失前缀从文字层补回；保护条件——待补内容字母占比 ≥90%，
     防止把表格残渣补进正文（实测发生过）
2. **元数据抢救**：DOI/year 扫描全部块（含 dropped）；year 只从版权行
   `© 2016 IEEE` 提取，不再从摘要猜。综述实测：year 2014→2016 ✓，
   DOI `10.1109/TIV.2016.2578706` 从被过滤页脚抢救成功 ✓
3. **LaTeX 检查修正**：花括号配对只统计非转义 `{}`——`\left\{ \right.`
   分段函数属合法写法，此前 7 条警告全是这类误报
4. **复核图自动生成**（`pdf/render.py`）：每条 needs_review 警告配裁剪图
   （bbox 换算：x_px = bbox/1000 × page_pt × scale），文件名带序号防同页冲突，
   重跑自动清理残留
5. **qc.json v2**：fixes / warnings 分级，summary.status = auto_pass | needs_review

## 最终实测（6 篇论文）

| 论文 | auto-fixed | needs-review | 状态 |
|---|---|---|---|
| A_Survey_of_Motion_Planning (IEEE 双栏 23p) | 1（drop-cap 首句） | 11 | needs_review |
| attention_is_all_you_need (15p) | 0 | 0 | **auto_pass** |
| ddpm_neurips2020 (25p 数学密集) | 0 | 1 | needs_review |
| resnet_cvpr2016 (双栏 12p) | 0 | 2 | needs_review |
| Visual_Servo_Control_Part_I (9p) | 0 | 2 | needs_review |
| What_Is_Robotics (33p) | 0 | 0 | **auto_pass** |

剩余 16 条警告抽检：全部是**行内公式表示分歧**（文字层 Σ→P、α→a 等替换字符
vs parser 的规范 LaTeX），parser 输出实际更准——已按 similarity 分类为
`math_divergence`（这类段落的行内公式正是后续 Formula OCR 双识别的目标）。
误报率从第一版的 ~750 条降到 16 条有效提示。

## 性能实测（RTX 4060 Ti 8GB）

- 单篇 60~70 秒端到端（含 ~15 秒模型加载；MinerU 每篇一个子进程）
- 6 篇连续批处理无 OOM；覆盖率检查/裁剪为 CPU 操作，秒级完成

## 下一步

1. Step 2：公式双识别（复用 MinerU 自带 UniMERNet 对 equation bbox 重识别，
   归一化相似度比对），重点覆盖 math_divergence 段落的行内公式
2. 第 3 层 VLM 终审接口：输入格式已标准化（裁剪图 + 双候选 + 上下文）
3. 回归测试集：6 篇论文 + 已知错误清单固化

---

# 第三轮：公式双识别闭环（Step 2，2026-09-02）

## 实现

- `formula/recognizer.py`：独立 Formula OCR 封装。默认 **PP-FormulaNet+**
  （与 pipeline 的 UniMERNet 是不同模型，构成真正双模型交叉验证；
  实测同模型复核 0 REVIEW，毫无鉴别力，故弃用同源自检）。
  权重复用 MinerU 缓存解析器，进程内单例，批处理结束卸载+清显存
- `formula/compare.py`：LaTeX 归一化 + difflib 相似度，阈值 0.90。
  归一化规则经三轮真实分歧迭代：环境名归一（array/aligned/matrix/cases…）、
  对齐符 `&`/换行 `\`、列格式、字体命令、`\log` vs `\operatorname{log}`、
  `\left/\right`、`\tag{}`、单 token 花括号
- `formula/double_check.py`：display equation 全量复核 +
  math_divergence 段落内的 inline span 逐条复核（middle.json 提取，
  bbox 为 PDF 点空间）。全部 span PASS 的段落警告自动升级为 auto_pass
- REVIEW 条目自动配裁剪图进 review_assets/

## 最终实测（6 篇，PP-FormulaNet+ 交叉验证）

| 论文 | 状态 | auto-fix | 文本警告 | display eq REVIEW | inline REVIEW |
|---|---|---|---|---|---|
| 运动规划综述 | needs_review | 1 | 11 | 13/58 | 29/47* |
| 视觉伺服（上） | needs_review | 0 | 2 | 9/32 | 8/11* |
| What Is Robotics | **auto_pass** | 0 | 0 | - | - |
| Attention | **auto_pass** | 0 | 0 | 0/5 | - |
| DDPM | needs_review | 0 | 1 | 1/16 | 3/7* |
| ResNet | needs_review | 0 | 2 | 0/2 | - |

*inline 只复核 math_divergence 段落（已是可疑样本，REVIEW 率高属预期）。

- 保留下来的 REVIEW 抽检为真实分歧（如 arg min + subj. to 多行约束结构），
  双候选 + 裁剪图齐备，正是多模态终审该处理的内容
- 至此漏斗闭环：确定性规则（免费）→ 双模型交叉（本地 GPU）→ 终审清单
  （qc.json + review_assets，按条计费式地消耗 Agent/多模态资源）
