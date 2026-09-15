"""QC 第 3 层：多模态终审。

只读 qc.json + review_assets + document.json，不重新解析 PDF。
流程：collect（导出清单）-> 当前多模态 agent 看图 -> JSON 导入 -> apply（写回 + 重建 md）
     -> review_summary.json（每篇最终状态）
"""
