#!/usr/bin/env python3
"""三赛道×八题组北大法宝 MCP 案例扩展：每个题组至少 5 个类似案例。"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, sys, time, urllib.request, urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parent.parent.parent
EP='https://apim-gateway.pkulaw.com/mcp-case'
TRACKS={
 'game':{'name':'游戏','must':[r'网络游戏|游戏广告|手游|页游|游戏充值|玩家|游戏运营|游戏推广|防沉迷|版号|代练']},
 'beauty':{'name':'化妆品/美妆','must':[r'化妆品|美妆|美容|医美|护肤品|面膜|润唇膏|口红|特殊用途化妆品|口腔护理产品|牙膏']},
 'health':{'name':'保健食品/食品医疗化','must':[r'保健食品|保健品|普通食品|食品宣传|食品广告|养生|理疗|食品销售者|食品经营者|食品生产经营者']},
}
TOPICS={
 'minor':('未成年人保护',[r'未成年|未成年人|儿童|小学生|幼儿园|青少年|不满十周岁|学生']),
 'license':('版号/防沉迷',[r'版号|防沉迷|实名制|未经审批|未经批准|上网出版|适龄提示|实名认证']),
 'platform':('平台规则',[r'直播|直播间|小红书|抖音|快手|天猫|淘宝|京东|拼多多|网店|电商|平台|短视频|信息流']),
 'endorsement':('广告代言',[r'代言|代言人|明星|网红|推荐官|体验官|推荐、证明|名义或者形象|患者名义|受益者']),
 'edible':('可食用/食品级宣称',[r'可食用|食品级|食用级|可以吃|可吃|口服|入口级']),
 'gift':('买赠/促销规则',[r'买一送一|买\s*\d+\s*得\s*\d+|买赠|赠品|满减|促销|赠送|限时立减|限时特价|返现|优惠|中奖名单']),
 'cashout':('游戏收益/提现',[r'提现|日赚|收益|赚钱|红包|奖励|充值即|无法兑现|诱导充值|回收变现']),
 'data':('数据引证',[r'数据|销量|销售状况|好评率|用户评价|下载量|排名|销冠|成交占比|TOP|临床|实验|无出处|无法提供|刷单|虚构交易|引证|检测报告']),
}
QUERIES={
 ('game','minor'):['网络游戏 未成年人 广告 充值','未成年人 游戏 防沉迷 广告','学生 游戏广告 诱导充值'],
 ('game','license'):['网络游戏 版号 行政处罚','未经审批 网络游戏 行政处罚','擅自上网出版网络游戏','网络游戏 防沉迷 实名制'],
 ('game','platform'):['抖音 游戏广告 虚假宣传','游戏推广 平台 虚假广告','网络游戏 电商平台 广告 纠纷'],
 ('game','endorsement'):['游戏广告 代言人 明星 推荐','网络游戏 广告代言 虚假宣传','游戏推广 网红 代言'],
 ('game','edible'):['游戏 食品级 广告 虚假宣传','游戏 可食用 广告 纠纷'],
 ('game','gift'):['游戏广告 充值 赠送 奖励','网络游戏 赠品 虚假宣传','游戏 充值奖励 广告'],
 ('game','cashout'):['游戏广告 提现 收益 日赚','红包游戏 提现 虚假宣传','网络游戏 诱导充值 虚假广告','游戏广告 无法兑现 奖励'],
 ('game','data'):['网络游戏 数据 虚假宣传 广告','游戏广告 下载量 排名 虚假','游戏 玩家数据 用户评价 虚假宣传'],
 ('beauty','minor'):['未成年人 化妆品 广告','儿童化妆品 广告 处罚','不满十周岁 未成年人 广告代言'],
 ('beauty','license'):['化妆品 备案 注册 广告 处罚','化妆品 未备案 虚假宣传','普通化妆品 特殊用途化妆品 广告'],
 ('beauty','platform'):['小红书 化妆品 虚假广告','抖音 美容 广告 处罚','天猫 化妆品 虚假宣传 网店'],
 ('beauty','endorsement'):['化妆品 广告代言 推荐证明','美容 广告 患者名义 形象','医美 明星代言 广告 处罚'],
 ('beauty','edible'):['化妆品 可食用 食品级 广告','儿童化妆品 可食用','润唇膏 食品级 广告','食品级口腔护理 虚假宣传','可以吃的化妆品 虚假宣传'],
 ('beauty','gift'):['化妆品 买赠 促销 广告','美容 赠品 虚假宣传','医美 满减 广告 处罚'],
 ('beauty','cashout'):['化妆品 返现 红包 广告','美容 收益 赚钱 虚假宣传'],
 ('beauty','data'):['化妆品 销量 数据 虚假广告','化妆品 临床数据 广告','美容 检测报告 广告 处罚','化妆品 刷单 用户评价'],
 ('health','minor'):['未成年人 保健食品 广告','学生 食品 医疗用语 广告','幼儿园 食品 虚假宣传'],
 ('health','license'):['保健食品 广告审查 处罚','普通食品 保健功能 未经审查','食品 批准文号 广告 处罚'],
 ('health','platform'):['直播带货 保健食品 虚假宣传','网店 普通食品 医疗用语','抖音 养生 食品 虚假广告'],
 ('health','endorsement'):['保健食品 广告代言 推荐证明','食品广告 患者名义 形象','保健品 专家消费者名义 广告'],
 ('health','edible'):['普通食品 可食用 功效 虚假宣传','食品级 保健食品 广告','食品 口服 医疗功效 广告'],
 ('health','gift'):['保健食品 买赠 促销 广告','药品 赠送 广告 处罚','食品 赠品 虚假宣传'],
 ('health','cashout'):['保健食品 返现 红包 虚假宣传','养生 赚钱 收益 广告','保健品 返利 促销 处罚'],
 ('health','data'):['保健食品 销量 用户评价 虚假广告','食品 临床数据 广告 处罚','养生 食品 检测报告 虚假宣传','刷单 食品 虚假宣传'],
}
@dataclass
class Hit:
 r:dict[str,Any]; raw_paths:set[str]=field(default_factory=set); queries:set[str]=field(default_factory=set); score:int=0; ev:list[str]=field(default_factory=list)
def now(): return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
def clean(x): return re.sub(r'\s+',' ',str(x or '').replace('<br>',' ')).strip()
def text(r):
 keys=['Title','CaseClassName','Category','Core','CaseGist','TrialAfter','PlaintiffClaims','Identified','Ascertain','RefereeBasis','RefereeResult']
 return '\n'.join(clean(r.get(k)) for k in keys)
def purl(r):
 m=re.search(r'\((https?://[^)]+)\)',str(r.get('Url') or ''));return m.group(1) if m else str(r.get('Url') or '')
def cid(track,topic,r): return 'pk_three_track_'+track+'_'+topic+'_'+hashlib.sha1((r.get('CaseFlag') or r.get('Url') or r.get('Title')).encode()).hexdigest()[:10]
def classify(r):
 title=' '.join([str(r.get('Title') or ''),str(r.get('CaseClassName') or ''),' '.join(r.get('Category') or [])])
 cf=str(r.get('CaseFlag') or '')
 if '刑' in title or re.search(r'刑(初|终)',cf):return 'criminal_reference'
 if '行政' in title or re.search(r'行(审|初|终|保|执)',cf):return 'administrative_judicial_reference'
 return 'civil_judicial_reference'
def evidence(t,terms):
 out=[]
 for pat in terms:
  m=re.search(pat,t,re.I)
  if m:
   s=max(0,m.start()-90); out.append(re.sub(r'\s+',' ',t[s:m.end()+180]))
 return out[:3]
class Client:
 def __init__(self,token,delay):self.h={'Content-Type':'application/json','Accept':'application/json, text/event-stream','Authorization':'Bearer '+token};self.delay=delay;self.i=0;self.inited=False
 def post(self,p):
  req=urllib.request.Request(EP,data=json.dumps(p,ensure_ascii=False).encode(),headers=self.h,method='POST')
  with urllib.request.urlopen(req,timeout=90) as resp:
   raw=resp.read().decode()
  for line in raw.splitlines():
   if line.startswith('data:'):return json.loads(line[5:])
  return json.loads(raw)
 def init(self):
  if self.inited:return
  self.i+=1;self.post({'jsonrpc':'2.0','id':self.i,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'adsure-three-track','version':'0.1'}}})
  try:self.post({'jsonrpc':'2.0','method':'notifications/initialized','params':{}})
  except Exception:pass
  self.inited=True
 def call(self,args):
  self.init();last=None
  for attempt in range(2):
   try:
    self.i+=1;b=self.post({'jsonrpc':'2.0','id':self.i,'method':'tools/call','params':{'name':'get_case_list','arguments':args}})
    if 'error' in b:return {'_rpc_error':b['error']}
    return json.loads(b['result']['content'][0]['text'])
   except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as e:
    last=e;time.sleep(2+attempt*2)
  return {'_transport_error':str(last)}
def score(track,topic,r):
 t=text(r); title=str(r.get('Title') or '')
 must=TRACKS[track]['must']; tpats=TOPICS[topic][1]
 if not any(re.search(p,t,re.I) for p in must):return 0,[]
 ms=[]
 for p in tpats:
  if re.search(p,t,re.I):ms.append(p)
 if not ms:return 0,[]
 sc=10+4*len(ms)
 for p in must:
  if re.search(p,t,re.I):sc+=8
 if re.search(r'广告法|反不正当竞争法|虚假广告|虚假宣传|医疗用语|广告审查|市场监督|工商行政|处罚',t):sc+=18
 if re.search(r'行(审|初|终)',str(r.get('CaseFlag') or '')):sc+=20
 if re.search(r'非诉|强制执行|行政处罚|市场监督管理局|工商行政',t):sc+=10
 if re.search(r'广告合同|侵害商标权|外观设计|劳动合同|特许经营|房屋租赁|物业服务|生命权|健康权|交通事故|行贿|帮助信息网络犯罪',title):sc-=35
 # 赛道专属降噪
 if track=='beauty' and not re.search(r'化妆品|美妆|美容|医美|护肤品|面膜|润唇膏|口红|口腔护理|牙膏',title+'\n'+t):sc-=30
 if track=='health' and not re.search(r'保健食品|保健品|普通食品|食品|养生|理疗',title+'\n'+t):sc-=30
 if topic=='edible' and not re.search(r'可食用|食品级|食用级|可以吃|可吃|口服|入口级',t):sc-=40
 return sc,evidence(t,tpats)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--batch',default='20260917_three_tracks');ap.add_argument('--target',type=int,default=5);ap.add_argument('--delay',type=float,default=1.2);a=ap.parse_args()
 token=os.environ.get('PKULAW_MCP_TOKEN','').removeprefix('Bearer ').strip()
 if not token:sys.exit('PKULAW_MCP_TOKEN missing')
 out=ROOT/'data/sources/pkulaw_three_tracks'/a.batch/'raw';out.mkdir(parents=True,exist_ok=True);rep=ROOT/'data/reports/source_verification';rep.mkdir(exist_ok=True)
 c=Client(token,a.delay); allhits:{tuple[str,str]:dict[str,Hit]}={}; querylog=[]
 for track in TRACKS:
  for topic in TOPICS:
   allhits[(track,topic)]={}
   for qi,q in enumerate(QUERIES[(track,topic)],1):
    args={'title':'广告' if not q.startswith(('未经审批','擅自上网','网络游戏 版号')) else '', 'fulltext':q,'documentAttr':['判决书','裁定书']}
    payload=c.call(args);body=json.dumps(payload,ensure_ascii=False,indent=2).encode()
    safe=re.sub(r'[^\w一-鿿-]+','_',q)[:60]; rp=out/f'{track}__{topic}__q{qi}__{safe}.json'
    rp.write_text(json.dumps({'fetched_at':now(),'request_arguments':args,'sha256':hashlib.sha256(body).hexdigest(),'response':payload},ensure_ascii=False,indent=2))
    recs=payload.get('Data') if isinstance(payload,dict) else []
    querylog.append({'track':track,'topic':topic,'query':q,'total':payload.get('Total') if isinstance(payload,dict) else None,'returned':len(recs or []),'raw_path':str(rp.relative_to(ROOT)),'error':payload.get('_rpc_error') or payload.get('_transport_error') or ''})
    for r in recs or []:
     sc,ev=score(track,topic,r)
     if sc<=0:continue
     key=r.get('CaseFlag') or r.get('Url') or r.get('Title')
     h=allhits[(track,topic)].setdefault(str(key),Hit(r))
     h.score=max(h.score,sc);h.raw_paths.add(str(rp.relative_to(ROOT)));h.queries.add(q);h.ev.extend(ev)
    print(track,topic,qi,q,'=>',len(recs or []),'kept',len(allhits[(track,topic)]),flush=True)
    time.sleep(a.delay)
 rows=[];coverage={}
 for (track,topic),hits in allhits.items():
  ordered=sorted(hits.values(),key=lambda x:(x.score,x.r.get('LastInstanceDate') or ''),reverse=True)[:max(a.target,8)]
  # 优先行政，其次民事，刑事仅在题目本身高度需要时保留
  admin=[h for h in ordered if classify(h.r)=='administrative_judicial_reference'];civil=[h for h in ordered if classify(h.r)=='civil_judicial_reference'];crim=[h for h in ordered if classify(h.r)=='criminal_reference']
  chosen=(admin+civil+crim)[:a.target]
  if len(chosen)<a.target: chosen=ordered[:a.target]
  coverage[f'{track}:{topic}']={'track':TRACKS[track]['name'],'topic':TOPICS[topic][0],'selected':len(chosen),'target':a.target,'meets_target':len(chosen)>=a.target,'candidate_pool':len(ordered)}
  for rank,h in enumerate(chosen,1):
   r=h.r;rows.append({'case_id':cid(track,topic,r),'track_id':track,'track_name':TRACKS[track]['name'],'topic_id':topic,'topic_name':TOPICS[topic][0],'rank':rank,'title':r.get('Title'),'case_number':r.get('CaseFlag'),'court':r.get('Court'),'decision_date':(r.get('LastInstanceDate') or '').replace('.','-'),'case_class_name':r.get('CaseClassName'),'category':r.get('Category') or [],'reference_classification':classify(r),'relevance_score':h.score,'source_name':'北大法宝（pkulaw.com，经 MCP 检索）','source_url':purl(r),'evidence_snippets':h.ev[:3],'identified_excerpt':clean(r.get('Identified') or r.get('Ascertain') or r.get('TrialAfter'))[:1600],'referee_basis':clean(r.get('RefereeBasis'))[:1000],'raw_text_paths':sorted(h.raw_paths),'queries':sorted(h.queries),'review_status':'pending_human_review','approved_for_rag':False,'source_tier_note':'法宝裁判案例/司法参考；不是行政机关原始处罚决定书，处罚事实需回溯官方公示。'})
 manifest={'generated_at':now(),'batch':a.batch,'target_per_topic':a.target,'coverage':coverage,'queries':querylog,'rows':rows,'compliance':{'serial_mcp_requests':True,'raw_saved':True,'reference_only':True,'approved_for_rag':False}}
 jp=rep/f'pkulaw_three_tracks_{a.batch}.json';jp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 cp=rep/f'pkulaw_three_tracks_{a.batch}.csv'
 fields=['case_id','track_id','track_name','topic_id','topic_name','rank','reference_classification','title','case_number','court','decision_date','source_url','raw_text_paths']
 with cp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fields);w.writeheader()
  for r in rows:w.writerow({k:(';'.join(r[k]) if isinstance(r.get(k),list) else r.get(k,'')) for k in fields})
 lines=['# 三赛道×八题组北大法宝类似案例扩展','',f'- 每个题组目标：{a.target} 条；共 {len(rows)} 行。','- 全部为 `pending_human_review`，仅作司法/行政参考，不替代官方行政处罚决定书。','']
 for track in TRACKS:
  lines += [f'## {TRACKS[track]["name"]}','']
  for topic,(tname,_) in TOPICS.items():
   rr=[x for x in rows if x['track_id']==track and x['topic_id']==topic]
   lines += [f'### {tname}（{len(rr)}/{a.target}）','']
   for x in rr:
    lines.append(f"{x['rank']}. [{x['title']}]({x['source_url']})；{x['court']}；{x['case_number']}；{x['decision_date']}；`{x['reference_classification']}`")
    if x['evidence_snippets']:lines.append('   - 证据片段：'+x['evidence_snippets'][0][:220])
    lines.append(f"   - 原始返回：`{x['raw_text_paths'][0]}`")
   lines.append('')
 mp=rep/f'pkulaw_three_tracks_{a.batch}.md';mp.write_text('\n'.join(lines))
 print(json.dumps({'rows':len(rows),'coverage':coverage,'json':str(jp),'csv':str(cp),'md':str(mp)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
