"""Same-crop dedicated formula OCR pilot; one model load, no remote judging."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def prepare(original, pdf_dir, out):
    from proofparse.pdf.render import render_crop
    tasks = json.loads((original/'tasks.json').read_text(encoding='utf-8'))
    tasks = [t for t in tasks if t['kind'] in ('display','inline')]
    for task in tasks:
        crop = Path('crops') / (task['id'] + '.png')
        render_crop(pdf_dir/(task['paper']+'.pdf'), task['page'],
                    task['target_bbox_1000'], out/crop, scale=3.0, pad=4)
        task['ocr_crop'] = crop.as_posix()
    (out/'tasks.json').write_text(json.dumps(tasks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'prepared':len(tasks)}))


def run(out, backend, model_dir, name, batch_size):
    import numpy as np
    from PIL import Image
    from proofparse.formula.qc import check_latex
    tasks = json.loads((out/'tasks.json').read_text(encoding='utf-8'))
    crops = [np.array(Image.open(out/t['ocr_crop']).convert('RGB')) for t in tasks]
    start = time.perf_counter()
    if backend == 'mineru':
        import torch
        from mineru.model.mfr.pp_formulanet_plus_m.predict_formula import FormulaRecognizer
        model = FormulaRecognizer(str(model_dir), 'cuda')
        torch.cuda.synchronize()
        load_seconds = time.perf_counter()-start
        torch.cuda.reset_peak_memory_stats()
        owners = [[{'label':'display_formula','bbox':[0,0,c.shape[1]-1,c.shape[0]-1],'latex':''}] for c in crops]
        start = time.perf_counter()
        output = model.batch_predict(owners,crops,batch_size=batch_size)
        torch.cuda.synchronize()
        latex = [r[0]['latex'] for r in output]
        peak = torch.cuda.max_memory_allocated()/1024**2
    else:
        # Direct Paddle inference avoids importing a second CUDA framework via
        # PaddleX's model-download helpers. Reuse the same pre/postprocessing as M.
        import paddle
        import paddle.inference
        import yaml
        from mineru.model.mfr.pp_formulanet_plus_m.processors import (
            UniMERNetImgDecode, UniMERNetTestTransform, LatexImageFormat, ToBatch, UniMERNetDecode)
        spec = yaml.safe_load((model_dir/'inference.yml').read_text(encoding='utf-8'))
        shape = next(op['UniMERNetImgDecode']['input_size'] for op in spec['PreProcess']['transform_ops']
                     if 'UniMERNetImgDecode' in op)
        config = paddle.inference.Config(str(model_dir/'inference.json'), str(model_dir/'inference.pdiparams'))
        config.enable_use_gpu(100, 0)
        config.disable_mkldnn()
        config.disable_glog_info()
        config.enable_new_ir(True)
        config.enable_new_executor()
        model = paddle.inference.create_predictor(config)
        transforms = [UniMERNetImgDecode(input_size=tuple(shape)), UniMERNetTestTransform(),
                      LatexImageFormat(), ToBatch()]
        decoder = UniMERNetDecode(character_list=spec['PostProcess']['character_dict'])
        paddle.device.cuda.synchronize()
        load_seconds = time.perf_counter()-start
        start = time.perf_counter()
        latex = []
        for offset in range(0,len(crops),batch_size):
            batch = crops[offset:offset+batch_size]
            for transform in transforms: batch = transform(imgs=batch)
            handle = model.get_input_handle(model.get_input_names()[0])
            handle.reshape(batch[0].shape)
            handle.copy_from_cpu(batch[0])
            model.run()
            prediction = model.get_output_handle(model.get_output_names()[0]).copy_to_cpu()
            latex.extend(decoder([row.reshape([-1]) for row in prediction]))
            print(json.dumps({'completed':len(latex),'total':len(tasks)}),flush=True)
        paddle.device.cuda.synchronize()
        peak = paddle.device.cuda.max_memory_allocated()/1024**2
    seconds = time.perf_counter()-start
    if len(latex) != len(tasks): raise ValueError('Model output count mismatch')
    results = {'model':name,'backend':backend,'pre_postprocessing':'MinerU FormulaRecognizer processors','batch_size':batch_size,
               'load_seconds':round(load_seconds,3),'inference_seconds':round(seconds,3),
               'peak_allocated_mb':round(peak,1),'tasks':[
                   {'id':t['id'],'latex':s,'syntax_problems':check_latex(s)} for t,s in zip(tasks,latex)]}
    with (out/(name+'.json')).open('x',encoding='utf-8') as file:
        json.dump(results,file,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in results.items() if k!='tasks'}))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['prepare','run'])
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--original',type=Path,default=Path('output/mimo-flash-pilot-20260929'))
    ap.add_argument('--pdf-dir',type=Path,default=Path('E:/Agent Tmp WS/PDF/input'))
    ap.add_argument('--backend',choices=['mineru','paddle'],default='mineru')
    ap.add_argument('--model-dir',type=Path)
    ap.add_argument('--name',default='PP-FormulaNet_plus-M')
    ap.add_argument('--batch-size',type=int,default=1)
    args=ap.parse_args()
    if args.action=='prepare': prepare(args.original,args.pdf_dir,args.out)
    else: run(args.out,args.backend,args.model_dir,args.name,args.batch_size)


if __name__=='__main__': main()
