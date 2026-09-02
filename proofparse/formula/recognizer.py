"""公式双识别：用独立的 Formula OCR 模型对公式区域重识别。

默认使用 PP-FormulaNet+（与 MinerU pipeline 默认的 UniMERNet 是不同模型，
构成真正的双模型交叉验证）；也可用环境变量切回 UniMERNet：
    PROOFPARSE_FORMULA_MODEL=unimernet_small | pp_formulanet_plus_m

设计要点：
- 模型只加载一次，整批论文共享，结束后显式卸载并清空显存
- 输入为页面渲染图的裁剪区域（numpy 数组），复用 MinerU 的
  batch_predict 接口，把每张裁剪图当作"整图 + 全覆盖 bbox"传入
- 权重路径用 MinerU 自己的解析器，自动兼容 huggingface/modelscope 缓存
"""
from __future__ import annotations

import os

import numpy as np

_MODEL_PATHS = {
    "unimernet_small": ("models/MFR/unimernet_hf_small_2503", "unimernet"),
    "pp_formulanet_plus_m": ("models/MFR/pp_formulanet_plus_m", "pp_formulanet"),
}


class FormulaOCR:
    def __init__(self, device: str = "cuda",
                 model_name: str | None = None):
        import torch  # 延迟导入，CPU 流程不背重依赖
        from mineru.utils.models_download_utils import auto_download_and_get_model_root_path

        self._torch = torch
        name = model_name or os.environ.get(
            "PROOFPARSE_FORMULA_MODEL", "pp_formulanet_plus_m")
        rel, kind = _MODEL_PATHS[name]
        weight_dir = f"{auto_download_and_get_model_root_path(rel)}/{rel}"
        if kind == "unimernet":
            from mineru.model.mfr.unimernet.Unimernet import UnimernetModel
            self.model = UnimernetModel(weight_dir, device)
        else:
            from mineru.model.mfr.pp_formulanet_plus_m.predict_formula import (
                FormulaRecognizer,
            )
            self.model = FormulaRecognizer(weight_dir, device)
        self.model_name = name
        self.device = device

    def recognize(self, crops: list[np.ndarray], batch_size: int = 64) -> list[str]:
        """对一组公式裁剪图批量识别，返回 LaTeX 列表。"""
        if not crops:
            return []
        mfd_list = []
        for img in crops:
            h, w = img.shape[:2]
            mfd_list.append([{"label": "display_formula",
                              "bbox": [0, 0, w - 1, h - 1], "latex": ""}])
        results = self.model.batch_predict(mfd_list, crops, batch_size=batch_size)
        return [items[0]["latex"] if items else "" for items in results]

    def unload(self) -> None:
        del self.model
        if self.device.startswith("cuda"):
            self._torch.cuda.empty_cache()


_INSTANCE: FormulaOCR | None = None


def get_formula_ocr(device: str = "cuda") -> FormulaOCR:
    """进程内单例：整批论文共享一次模型加载。"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = FormulaOCR(device)
    return _INSTANCE


def release_formula_ocr() -> None:
    global _INSTANCE
    if _INSTANCE is not None:
        _INSTANCE.unload()
        _INSTANCE = None
