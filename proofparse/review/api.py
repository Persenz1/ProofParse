"""Optional OpenAI-compatible image API. Explicit opt-in, saved responses, no blind retries."""
import base64
import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.request

from .agent import FileVLM, REVIEW_INSTRUCTIONS


class APIReviewer:
    def __init__(self, root, url, model, max_requests=20, max_tokens=4096):
        self.url, self.model = url.rstrip('/'), model
        self.key = os.environ.get("PROOFPARSE_REVIEW_API_KEY", "")
        if not self.key: raise ValueError("Set PROOFPARSE_REVIEW_API_KEY before API review")
        self.path = Path(root) / "api_verdicts.json"
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.lock = threading.Lock()
        self.remaining, self.max_tokens = max_requests, max_tokens
        self.config_hash = hashlib.sha256((self.url + self.model + REVIEW_INSTRUCTIONS).encode()).hexdigest()

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.cache,ensure_ascii=False,indent=2),encoding="utf-8")
        tmp.replace(self.path)

    def adjudicate(self,item,image_path):
        cache_key = item.uid + "::" + item.input_hash + "::" + self.config_hash
        with self.lock:
            saved = self.cache.get(cache_key)
            if saved:
                if saved.get("state") != "done":
                    raise ValueError("Previous request has uncertain/failed outcome; inspect api_verdicts.json before retrying")
                return saved["verdict"]
            if self.remaining <= 0: raise ValueError("API request limit reached; remaining items are still open")
            self.remaining -= 1
            self.cache[cache_key] = {"state":"in_flight", "uid":item.uid}
            self.save()
        image = base64.b64encode(Path(image_path).read_bytes()).decode('ascii')
        task = {"uid":item.uid,"input_hash":item.input_hash,"kind":item.kind,"page":item.page,
                "candidate_A_parser":item.candidate_a,"candidate_B":item.candidate_b,"context":item.extra}
        mime = "image/jpeg" if Path(image_path).suffix.lower() in (".jpg", ".jpeg") else "image/png"
        payload={"model":self.model,"max_tokens":self.max_tokens,"messages":[
            {"role":"system","content":REVIEW_INSTRUCTIONS},
            {"role":"user","content":[{"type":"image_url","image_url":{"url":f"data:{mime};base64,{image}"}},
             {"type":"text","text":json.dumps(task,ensure_ascii=False)}]}]}
        try:
            req=urllib.request.Request(self.url+'/chat/completions',data=json.dumps(payload).encode(),
                headers={"Content-Type":"application/json","Authorization":"Bearer "+self.key})
            with urllib.request.urlopen(req,timeout=180) as response: data=json.load(response)
            choice=data['choices'][0]
            if choice.get('finish_reason') != 'stop': raise ValueError("API output did not finish normally")
            raw=choice['message']['content'].strip()
            if raw.startswith('```'): raw='\n'.join(raw.splitlines()[1:-1])
            result=json.loads(raw)
            validator=object.__new__(FileVLM)
            validator.verdicts=result
            verdict=validator.adjudicate(item,image_path)
            verdict['model']=self.model
            with self.lock:
                self.cache[cache_key]={"state":"done","uid":item.uid,"verdict":verdict,"usage":data.get('usage')}
                self.save()
            return verdict
        except Exception:
            with self.lock:
                self.cache[cache_key]['state']='needs_attention'
                self.save()
            raise
