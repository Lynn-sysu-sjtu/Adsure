#!/usr/bin/env python3
"""基于已落盘北大法宝 MCP 返回，构建三赛道×八题组，每题至少 5 条。"""
from __future__ import annotations
import csv,glob,hashlib,html,json,re
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent.parent
REPORT=ROOT/'data/reports/source_verification'
GLOB_PATTERNS=[
 'data/sources/pkulaw_backfill/full_20260917/raw/*.json',
 'data/sources/pkulaw_gap_search/20260917_gap10/raw/*.json',
 'data/sources/pkulaw_gap_search/20260917_gap10_s05_s08/raw/*.json',
 'data/sources/pkulaw_gap_search/20260917_gap10_targeted/raw/*.json',
 'data/sources/pkulaw_three_tracks/20260917_three_tracks/raw/*.json',
 'data/sources/pkulaw_three_tracks/20260917_three_tracks/raw_narrow/*.json',
]
TRACKS={
 'game':{'name':'游戏','must':[r'网络游戏|游戏广告|手游|页游|游戏充值|玩家|游戏运营|游戏推广|防沉迷|版号|代练|游戏服务']},
 'beauty':{'name':'化妆品/美妆','must':[r'化妆品|美妆|美容|医美|护肤品|面膜|润唇膏|口红|特殊用途化妆品|牙膏|口腔护理']},
 'health':{'name':'保健食品/食品医疗化','must':[r'保健食品|保健品|普通食品|食品广告|食品宣传|养生|理疗|食品经营者|食品生产经营者|食品销售']},
}
TOPICS={
 'minor':('未成年人保护',[r'未成年|未成年人|儿童|小学生|幼儿园|青少年|不满十周岁|学生']),
 'license':('版号/资质/防沉迷',[r'版号|防沉迷|实名制|未经审批|未经批准|上网出版|适龄提示|实名认证|备案|注册|广告审查|批准文号']),
 'platform':('平台规则',[r'直播|直播间|小红书|抖音|快手|天猫|淘宝|京东|拼多多|网店|电商|平台|短视频|信息流']),
 'endorsement':('广告代言/推荐证明',[r'代言|代言人|明星|网红|推荐官|体验官|推荐、证明|名义或者形象|患者名义|受益者|专家|消费者']),
 'edible':('可食用/食品级/口服宣称',[r'可食用|食品级|食用级|可以吃|可吃|口服|入口级']),
 'gift':('买赠/促销规则',[r'买一送一|买\s*\d+\s*得\s*\d+|买赠|赠品|满减|促销|赠送|限时立减|限时特价|返现|优惠|中奖名单']),
 'cashout':('收益/提现/诱导充值',[r'提现|日赚|收益|赚钱|红包|奖励|充值即|无法兑现|诱导充值|回收变现|返利']),
 'data':('数据引证/销量评价/检测依据',[r'数据|销量|销售状况|好评率|用户评价|下载量|排名|销冠|成交占比|TOP|临床|实验|检测报告|无出处|无法提供|刷单|虚构交易|引证']),
}
# 手工锚定优先，保证题组可解释；其余由本地全文自动补位。
ANCHORS={
('game','minor'):['(2022)沪0115民初13290号之一','(2024)鄂0802行审14号','(2024)鄂0802行审13号','(2025)苏1003行审8号','(2025)川0104民初20301号'],
('game','license'):['(2025)苏1003行审8号','(2026)沪0114行审1号','(2025)沪02行终518号','(2024)沪0114执2986号','(2022)沪0115民初13290号之一'],
('game','platform'):['(2023)粤0192民初1448号','(2025)粤0192民初9279号','(2023)赣1104民初2952号','(2025)粤0305民初5978号','(2024)川14行终29号'],
('game','endorsement'):['(2023)粤0192民初1448号','(2020)粤0192民初22669号','(2025)粤0192民初9279号','(2020)鄂0103行审20号','(2018)鄂0103行审11号'],
('game','edible'):['(2016)粤0111民初6335号','(2016)粤0111民初6336号','(2014)杨民一(民)初字第4713号','(2023)粤0192民初1448号','(2017)鄂0103行审61号'],
('game','gift'):['(2025)粤0192民初9279号','(2023)粤0192民初1448号','(2022)粤0192民初12251号','(2020)粤0192民初22669号','(2019)浙0482民初402号'],
('game','cashout'):['(2025)粤0192民初9279号','(2026)京0491民初4964号','(2026)琼96民终807号','(2025)京04民终1390号','(2023)琼96民终6628号'],
('game','data'):['(2024)川14行终29号','(2023)粤0192民初1448号','(2023)赣1104民初2952号','(2024)浙0192民初1779号','(2025)琼9023民初5336号'],
('beauty','minor'):['(2021)苏03行终63号','(2020)苏8601行初134号','(2018)湘0724行审5号','(2025)豫行申1293号','(2020)鄂1223行审52号'],
('beauty','license'):['(2018)苏0508行初268号','(2025)苏0282行审5号','(2023)川0504行审1号','(2018)琼0105行初169号','(2020)鄂1223行审52号'],
('beauty','platform'):['(2024)沪7101行初94号','(2018)苏0508行初268号','(2016)粤0111民初9365号','(2019)鲁1424行审75号','(2017)豫1528行审92号'],
('beauty','endorsement'):['(2021)苏03行终63号','(2017)豫1528行审92号','(2019)鲁1424行审75号','(2018)苏0508行初268号','(2018)鄂0103行审29号'],
('beauty','edible'):['(2016)粤0111民初6335号','(2016)粤0111民初6336号','(2014)杨民一(民)初字第4713号','(2017)鄂0103行审61号','(2018)鄂0103行审46号'],
('beauty','gift'):['(2018)鄂0103行审29号','(2018)鄂0103行审47号','(2018)鄂0103行审30号','(2019)鲁1083民初5066号','(2019)浙0482民初402号'],
('beauty','cashout'):['(2019)鲁1424行审75号','(2020)鄂1223行审52号','(2017)鄂0103行审61号','(2016)京03民终10057号','(2019)浙0192民初1035号'],
('beauty','data'):['(2018)苏0508行初268号','(2024)沪7101行初94号','(2016)粤0111民初9365号','(2022)豫01行终792号','(2018)浙0108民初3781号'],
('health','minor'):['(2020)苏03行终63号','(2018)湘0724行审5号','(2025)豫行申1293号','(2019)琼0271行初308号','(2020)琼9701行初5号'],
('health','license'):['(2018)鄂0103行审21号','(2018)鄂0103行审11号','(2018)鄂0103行审12号','(2017)鄂0103行审32号','(2018)鄂0103行审47号'],
('health','platform'):['(2020)浙1102行初41号','(2020)浙1102行初42号','(2023)冀0929刑初154号','(2023)川3431刑初4号','(2020)粤0307刑初2702号'],
('health','endorsement'):['(2018)鄂0103行审47号','(2018)鄂0103行审20号','(2017)鄂0103行审32号','(2017)鄂0103行审61号','(2020)云2301行初88号'],
('health','edible'):['(2014)杨民一(民)初字第4713号','(2018)鄂0103行审20号','(2017)鄂0103行审61号','(2017)鄂0103行审32号','(2018)沪7101民初597号'],
('health','gift'):['(2016)沪0112行初10号','(2019)鄂0881行审17号','(2016)沪01行终473号','(2016)豫09行终68号','(2014)管行初字第9号'],
('health','cashout'):['(2016)京03民终10057号','(2019)鲁1083民初5066号','(2019)浙0192民初1035号','(2020)浙0881刑初17号','(2020)苏0681刑初170号'],
('health','data'):['(2020)浙1102行初41号','(2019)京0105行初623号','(2023)渝0101行初112号','(2019)粤71行终1769号','(2019)鄂1281行初20号'],
}
# 对天然弱相关题组，报告里显式说明。
NOTE={
('game','edible'):'游戏赛道无天然“可食用/食品级”题；前三条为食品级宣称高相似广告案例，后两条为游戏广告相邻参考。',
('beauty','license'):'化妆品题组的“资质/审查”以备案注册、特殊用途化妆品、医疗广告审查为主，不等同游戏版号。',
('beauty','cashout'):'化妆品赛道无天然“提现/日赚”题；以返现、收益式营销和促销误导相邻案例补足。',
('health','license'):'食品保健食品题组的“资质/审查”以广告审查、普通食品宣称保健功能为主，不等同游戏版号。',
('health','cashout'):'食品赛道无天然“游戏提现”题；以返现、红包、收益式营销和促销误导相邻案例补足。',
}
def norm(s):return re.sub(r'[\s()（）]','',str(s or ''))
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',str(s or '')))).strip()
def load_records():
 idx={}
 for pat in GLOB_PATTERNS:
  for p in map(Path,glob.glob(str(ROOT/pat))):
   try:d=json.loads(p.read_text())
   except Exception:continue
   arr=[]
   if isinstance(d.get('record'),dict):arr.append(d['record'])
   data=(d.get('response') or {}).get('Data')
   if isinstance(data,list):arr.extend(data)
   for r in arr:
    cf=norm(r.get('CaseFlag'))
    if cf and cf not in idx:idx[cf]=(r,p)
 return idx
def text(r):
 keys=['Title','Category','CaseClassName','Core','CaseGist','TrialAfter','PlaintiffClaims','Identified','Ascertain','RefereeBasis','RefereeResult']
 return '\n'.join(clean(r.get(k)) for k in keys)
def url(r):
 m=re.search(r'\((https?://[^)]+)\)',str(r.get('Url') or ''));return m.group(1) if m else str(r.get('Url') or '')
def classify(r):
 cf=str(r.get('CaseFlag') or ''); title=' '.join([str(r.get('Title') or ''),' '.join(r.get('Category') or [])])
 if '刑' in title or re.search(r'刑(初|终)',cf):return 'criminal_reference'
 if '行政' in title or re.search(r'行(审|初|终|保|执)',cf):return 'administrative_judicial_reference'
 return 'civil_judicial_reference'
def score(r,track,topic):
 t=text(r);must=TRACKS[track]['must'][0];pats=TOPICS[topic][1]
 sm=1 if re.search(must,t,re.I) else 0;sp=[p for p in pats if re.search(p,t,re.I)]
 if not sp:return 0
 score=10+8*sm+5*len(sp)
 if re.search(r'广告法|反不正当竞争法|虚假广告|虚假宣传|广告审查|医疗用语|市场监督|工商行政|处罚',t):score+=18
 if classify(r)=='administrative_judicial_reference':score+=20
 if sm:score+=25
 title=str(r.get('Title') or '')
 if re.search(r'广告合同|侵害商标权|外观设计|劳动合同|特许经营|房屋租赁|物业服务|交通事故|行贿|帮助信息网络犯罪',title):score-=30
 return score
def evidence(t,pats):
 for p in pats:
  m=re.search(p,t,re.I)
  if m:return t[max(0,m.start()-100):m.end()+220]
 return t[:300]
def main():
 idx=load_records();rows=[];coverage={}
 for track,tv in TRACKS.items():
  for topic,(tname,pats) in TOPICS.items():
   chosen=[];seen=set();missing=[]
   for flag0 in ANCHORS[(track,topic)]:
    key=norm(flag0);hit=idx.get(key) or next((v for k,v in idx.items() if key in k or k in key),None)
    if not hit:missing.append(flag0);continue
    r,p=hit;cf=norm(r.get('CaseFlag'))
    if cf in seen:continue
    seen.add(cf);chosen.append((r,p,999))
   # auto fill if needed
   if len(chosen)<5:
    pool=[]
    for r,p in idx.values():
     cf=norm(r.get('CaseFlag'))
     if cf in seen:continue
     sc=score(r,track,topic)
     if sc>0:pool.append((sc,r,p))
    for sc,r,p in sorted(pool,key=lambda x:x[0],reverse=True):
     cf=norm(r.get('CaseFlag'))
     if cf in seen:continue
     seen.add(cf);chosen.append((r,p,sc))
     if len(chosen)>=5:break
   for rank,(r,p,sc) in enumerate(chosen[:5],1):
    t=text(r)
    rows.append({'case_id':'pk3_'+track+'_'+topic+'_'+hashlib.sha1(norm(r.get('CaseFlag')).encode()).hexdigest()[:8],
      'track_id':track,'track_name':tv['name'],'topic_id':topic,'topic_name':tname,'rank':rank,
      'title':r.get('Title'),'case_number':r.get('CaseFlag'),'court':r.get('Court'),'decision_date':(r.get('LastInstanceDate') or '').replace('.','-'),
      'case_class_name':r.get('CaseClassName'),'reference_classification':classify(r),'relevance_score':sc,
      'source_name':'北大法宝（pkulaw.com，经 MCP 检索）','source_url':url(r),'evidence_snippet':evidence(t,pats),
      'applicability_note':NOTE.get((track,topic),'同赛道同题组案例。'),
      'raw_text_path':str(p.relative_to(ROOT)),'review_status':'pending_human_review','approved_for_rag':False,
      'source_tier_note':'法宝裁判案例/司法参考；不是行政机关原始处罚决定书。'})
   coverage[f'{track}:{topic}']={'track':tv['name'],'topic':tname,'selected':min(5,len(chosen)),'target':5,'meets_target':len(chosen)>=5,'missing_anchors':missing,'note':NOTE.get((track,topic),'')}
 manifest={'generated_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'target':5,'all_meet_target':all(v['meets_target'] for v in coverage.values()),'coverage':coverage,'rows':rows,'compliance':{'reference_only':True,'not_official_penalty_fact':True,'approved_for_rag':False}}
 jp=REPORT/'pkulaw_three_tracks_matrix_20260917.json';jp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 cp=REPORT/'pkulaw_three_tracks_matrix_20260917.csv'
 fields=['track_id','track_name','topic_id','topic_name','rank','reference_classification','title','case_number','court','decision_date','source_url','applicability_note','raw_text_path']
 with cp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fields);w.writeheader();w.writerows([{k:r.get(k,'') for k in fields} for r in rows])
 lines=['# 三赛道×八题组类似案例矩阵（每题至少 5 条）','','- 来源：北大法宝案例 MCP 已保存原始返回。','- 证据边界：法宝裁判案例仅作司法/行政参考；若要作为行政处罚事实入规则 RAG，必须回溯行政机关原始处罚公示。','- 弱相关题组已在 `applicability_note` 明示，不把相邻案例伪装成同赛道处罚事实。','']
 for track,tv in TRACKS.items():
  lines += [f'## {tv["name"]}','']
  for topic,(tname,_) in TOPICS.items():
   rr=[x for x in rows if x['track_id']==track and x['topic_id']==topic]
   lines += [f'### {tname}（{len(rr)}/5）','']
   note=NOTE.get((track,topic))
   if note:lines.append(f'> {note}')
   for x in rr:
    lines.append(f"{x['rank']}. [{x['title']}]({x['source_url']})；{x['court']}；{x['case_number']}；{x['decision_date']}；`{x['reference_classification']}`")
    lines.append('   - 证据：'+x['evidence_snippet'][:220])
    lines.append(f"   - 原始返回：`{x['raw_text_path']}`")
   lines.append('')
 mp=REPORT/'pkulaw_three_tracks_matrix_20260917.md';mp.write_text('\n'.join(lines))
 print(json.dumps({'rows':len(rows),'all_meet_target':all(v['meets_target'] for v in coverage.values()),'json':str(jp),'csv':str(cp),'md':str(mp)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
