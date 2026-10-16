# run_min_verify.py — 预算耗尽后的最小两项验证（≤2 次调用，逐段落盘）
# V2：真实模型解析含禁项指令 → constraints 是否保留（files 域启用前提）
# R ：阅读链真机冒烟 1 单元（reader 域启用前提）
import json, os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
COG = os.path.dirname(os.path.dirname(HERE))
HOST = os.path.dirname(COG)
for p in (COG, HERE, os.path.join(COG,"experiments","general_loop"),
          os.path.join(COG,"experiments","goal_planner"),
          os.path.join(COG,"experiments","goal_path_bias")):
    if p not in sys.path: sys.path.insert(0, p)
import logging; logging.disable(logging.WARNING)
assert os.environ.get("ALLOW_LLM")=="1"
import openai, sys as _s
_s.path.insert(1, os.path.join(HOST,"FAS-Companion"))
_s.path.insert(1, os.path.join(HOST,"FAS-Companion","scripts"))
sec=json.load(open(os.path.join(HOST,"FAS-Companion","data","llm_secret.json"),encoding="utf-8"))
from llm_provider import MiMoBackend
from prompt_templates import GOAL_PARSE, READER_EXTRACT
import taskloop as TL, reading as RD
MODEL=MiMoBackend._DEFAULT_MODEL
CLIENT=openai.OpenAI(api_key=sec.get("mimo_api_key") or sec["mimo_api_key"] if "mimo_api_key" in sec else sec["api_key"], base_url=MiMoBackend._DEFAULT_BASE_URL)
LOG=[]
def chat(system,user,max_tokens=700):
    r=CLIENT.chat.completions.create(model=MODEL,temperature=0,max_tokens=max_tokens,
        messages=[{"role":"system","content":system},{"role":"user","content":user}])
    raw=r.choices[0].message.content or ""
    LOG.append({"tok":f"{r.usage.prompt_tokens}+{r.usage.completion_tokens}","user":user[:50],"raw":raw[:400]})
    return raw
out={}
d=os.path.join(HERE,"min_verify_"+time.strftime("%Y%m%d_%H%M%S")); os.makedirs(d,exist_ok=True)
# V2
raw2=chat(GOAL_PARSE,"把 board_a 搬到 workshop；不要消耗任何铁矿石（forbid consuming iron ore）")
spec,v2,errs=TL.parse_goal(lambda u: raw2, "x")
out["V2"]={"verdict":v2,"errors":errs,
           "spec":spec,
           "iron_forbid_kept": bool(spec) and TL.constraints_preserved(
               spec, {"forbid_del":["have:iron_ore"],
                      "forbid_ops":[]}) or (bool(spec) and "iron" in json.dumps(
                          spec.get("constraints",{}), ensure_ascii=False))}
json.dump({"out":out,"calls":LOG},open(os.path.join(d,"step1.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
# R 阅读冒烟 1 单元
src=RD.load_source(os.path.join(COG,"experiments","reading_loop","corpus","inferno_c1.json"))
led=RD.ReadingLedger(src, os.path.join(d,"ledger.json"))
from graph_model import KnowledgeGraph
ex=RD.make_llm_extractor(lambda p: chat(READER_EXTRACT,p,max_tokens=900), max_retries=0)
r=led.read_unit(1, ex, KnowledgeGraph())
out["READ"]={"status":r["status"],"partial":r.get("partial"),
             "relations":r.get("relations",0),"facts":led.data[led.sid]["facts"][:6]}
out["CALLS"]=len(LOG)
json.dump({"out":out,"calls":LOG},open(os.path.join(d,"final.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(json.dumps(out,ensure_ascii=False,indent=1)[:1500]); print("out:",d)
