#!/usr/bin/env python3
"""从已落盘的北大法宝 MCP 原始返回中精选 8 个缺口场景，每场景 10 条。"""
from __future__ import annotations
import csv, glob, hashlib, html, json, os, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = ROOT/'data/reports/source_verification'
RAW_GLOBS = [
 'data/sources/pkulaw_backfill/full_20260917/raw/*.json',
 'data/sources/pkulaw_gap_search/20260917_gap10/raw/*.json',
 'data/sources/pkulaw_gap_search/20260917_gap10_s05_s08/raw/*.json',
 'data/sources/pkulaw_gap_search/20260917_gap10_targeted/raw/*.json',
]
SCENARIOS = [
 ('s01_minor_protection','未成年人保护'),('s02_game_license_antiaddiction','版号/防沉迷'),
 ('s03_platform_rules','平台规则类'),('s04_endorsement','广告代言'),
 ('s05_edible_cosmetics','化妆品可食用'),('s06_gift_promotion','买赠规则'),
 ('s07_game_cashout','游戏收益/提现'),('s08_data_citation','数据引证')]
LISTS = {
's01_minor_protection':['(2020)苏8601行初134号','(2021)苏03行终63号','(2018)湘0724行审5号','(2025)豫行申1293号','(2018)豫0102行初107号','(2022)沪0115民初13290号之一','(2025)川0104民初20301号','(2025)京04民终1390号','(2023)粤0192民初1448号','(2024)浙0192民初1779号'],
's02_game_license_antiaddiction':['(2025)苏1003行审8号','(2026)沪0114行审1号','(2025)沪02行终518号','(2024)沪0114执2986号','(2022)沪0115民初13290号之一','(2023)苏民终280号','(2021)沪0115行保1号','(2022)京73民终2463号','(2023)粤0192民初1448号','(2024)浙0192民初1779号'],
's03_platform_rules':['(2024)沪7101行初94号','(2018)苏0508行初268号','(2016)粤0111民初9365号','(2023)粤0192民初1448号','(2025)粤0192民初9279号','(2023)赣1104民初2952号','(2023)川3431刑初4号','(2020)粤0307刑初2702号','(2020)粤0192民初22669号','(2022)粤0192民初12251号'],
's04_endorsement':['(2018)鄂0103行审47号','(2018)鄂0103行审46号','(2018)鄂0103行审29号','(2018)鄂0103行审30号','(2018)鄂1123行审103号','(2018)鄂0103行审20号','(2018)鄂0103行审21号','(2018)鄂0103行审11号','(2018)鄂0103行审12号','(2017)鄂0103行审61号'],
's05_edible_cosmetics':['(2016)粤0111民初6335号','(2016)粤0111民初6336号','(2014)杨民一(民)初字第4713号','(2017)豫1528行审92号','(2018)苏0508行初268号','(2020)鄂1223行审52号','(2025)苏0282行审5号','(2016)粤0111民初9365号','(2017)鄂0103行审61号','(2018)鄂0103行审46号'],
's06_gift_promotion':['(2016)沪0112行初10号','(2019)鄂0881行审17号','(2016)沪01行终473号','(2016)豫09行终68号','(2014)管行初字第9号','(2015)台行初字第00024号','(2019)鲁1083民初5066号','(2016)京03民终10057号','(2019)浙0192民初1035号','(2019)浙0482民初402号'],
's07_game_cashout':['(2025)粤0192民初9279号','(2026)京0491民初4964号','(2026)琼96民终807号','(2025)京04民终1390号','(2023)琼96民终6628号','(2023)粤0192民初1448号','(2022)粤0192民初12251号','(2020)粤0192民初22669号','(2020)粤民终763号','(2021)浙0683民初2001号'],
's08_data_citation':['(2020)浙1102行初41号','(2019)京0105行初623号','(2023)渝0101行初112号','(2019)粤71行终1769号','(2019)鄂1281行初20号','(2020)辽0105行初86号','(2018)冀0981行初14号','(2018)鄂1223行初3号','(2017)鄂0103行审86号','(2020)浙1102行初42号'],
}
STRONG_S05 = {'(2016)粤0111民初6335号','(2016)粤0111民初6336号','(2014)杨民一(民)初字第4713号'}
EVIDENCE_TERMS = {
 's01_minor_protection':['未成年人','不满十周岁','中小学校','幼儿园','防沉迷','儿童'],
 's02_game_license_antiaddiction':['版号','未经审批','未经批准','防沉迷','实名制','适龄提示','上网出版网络游戏'],
 's03_platform_rules':['直播','小红书','抖音','淘宝','天猫','拼多多','网店','电商','虚假广告','虚假宣传'],
 's04_endorsement':['代言','推荐','证明','名义','形象'],
 's05_edible_cosmetics':['食品级','可食用','可以吃','口腔护理','化妆品','虚假广告','医疗用语'],
 's06_gift_promotion':['买一送一','赠品','赠送','满减','促销','限时','价格'],
 's07_game_cashout':['游戏','充值','提现','红包','奖励','收益','诱导','虚假广告'],
 's08_data_citation':['销量','销售状况','用户评价','刷单','引证','数据','排名','成交占比','无出处','虚构'],
}
def norm(s): return re.sub(r'[\s()（）]','',str(s or ''))
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',str(s or '')))).strip()
def record_text(r):
 keys=['Title','TrialAfter','PlaintiffClaims','DefenseViewpoint','Identified','Ascertain','RefereeBasis','RefereeResult','Core','CaseGist']
 return '\n'.join(clean(r.get(k,'')) for k in keys)
def url_of(r):
 m=re.search(r'\((https?://[^)]+)\)',str(r.get('Url') or ''));return m.group(1) if m else str(r.get('Url') or '')
def load_index():
 idx={}
 for pattern in RAW_GLOBS:
  for p in map(Path,glob.glob(str(ROOT/pattern))):
   try:d=json.loads(p.read_text())
   except Exception:continue
   records=[]
   if isinstance(d.get('record'),dict): records=[d['record']]
   data=(d.get('response') or {}).get('Data')
   if isinstance(data,list): records.extend(data)
   for r in records:
    cf=norm(r.get('CaseFlag'))
    if cf and cf not in idx: idx[cf]=(r,p)
 return idx
def classify(r):
 title=' '.join(map(str,[r.get('Title'),r.get('CaseClassName'),' '.join(r.get('Category') or [])]))
 if '刑' in title:return 'criminal_reference'
 if '行政' in title or re.search(r'行(审|初|终|保|执)',str(r.get('CaseFlag') or '')):return 'administrative_judicial_reference'
 return 'civil_judicial_reference'
def snippet(text,terms):
 for term in terms:
  i=text.find(term)
  if i>=0:return text[max(0,i-110):i+260]
 return text[:360]
def main():
 idx=load_index();rows=[];missing=[]
 for sid,name in SCENARIOS:
  for rank,flag0 in enumerate(LISTS[sid],1):
   key=norm(flag0); hit=idx.get(key)
   if not hit:
    # tolerate one-char/date variants by substring over normalized flags
    hit=next((v for k,v in idx.items() if key in k or k in key),None)
   if not hit:missing.append((sid,flag0));continue
   r,path=hit;text=record_text(flag=flag0) if False else record_text(r)
   level='strong_specific_match'
   if sid=='s05_edible_cosmetics' and norm(flag0) not in {norm(x) for x in STRONG_S05}:level='adjacent_cosmetic_advertising_case'
   if sid=='s01_minor_protection' and norm(flag0)==norm('(2018)豫0102行初107号'):level='adjacent_school_context_absolute_terms_case'
   cid='pkulaw_curated_'+sid+'_'+hashlib.sha1(key.encode()).hexdigest()[:10]
   rows.append({'case_id':cid,'scenario_id':sid,'scenario_name':name,'scenario_rank':rank,
    'title':r.get('Title'),'case_number':r.get('CaseFlag'),'court':r.get('Court'),'decision_date':(r.get('LastInstanceDate') or '').replace('.','-'),
    'case_class_name':r.get('CaseClassName'),'category':r.get('Category') or [],'document_attr':r.get('DocumentAttr') or [],
    'reference_classification':classify(r),'relevance_level':level,'source_name':'北大法宝（pkulaw.com，经 MCP 检索）','source_url':url_of(r),
    'source_tier_note':'法宝裁判案例/司法参考，不是行政机关原始处罚决定书；如作为处罚事实入RAG，必须回溯官方处罚公示。',
    'matched_terms':[t for t in EVIDENCE_TERMS[sid] if t in text],'evidence_snippet':snippet(text,EVIDENCE_TERMS[sid]),
    'referee_basis':clean(r.get('RefereeBasis'))[:1000],'referee_result':clean(r.get('RefereeResult'))[:1000],
    'identified_excerpt':clean(r.get('Identified') or r.get('Ascertain') or r.get('TrialAfter'))[:1800],
    'raw_text_path':str(path.relative_to(ROOT)),'review_status':'pending_human_review','approved_for_rag':False})
 coverage={sid:{'name':name,'selected':sum(1 for x in rows if x['scenario_id']==sid),'target':10,'meets_target':sum(1 for x in rows if x['scenario_id']==sid)>=10} for sid,name in SCENARIOS}
 manifest={'generated_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'source':'PKULaw MCP saved responses','coverage':coverage,'missing_requested_cases':missing,'rows':rows,'compliance':{'reference_only':True,'not_official_penalty_fact':True,'approved_for_rag':False}}
 REPORT_DIR.mkdir(parents=True,exist_ok=True)
 jp=REPORT_DIR/'pkulaw_gap_case_curated_20260917.json';jp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 cp=REPORT_DIR/'pkulaw_gap_case_curated_20260917.csv'
 fields=['case_id','scenario_id','scenario_name','scenario_rank','reference_classification','relevance_level','title','case_number','court','decision_date','source_url','raw_text_path']
 with cp.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fields);w.writeheader();w.writerows([{k:(';'.join(v) if isinstance(v,list) else v) for k,v in x.items() if k in fields} for x in rows])
 lines=['# 北大法宝 MCP 八类缺口精选案例（每类 10 条）','', '- 证据来源：本轮及今日已落盘的北大法宝案例 MCP 原始返回。','- 用途边界：均为裁判/司法/行政参考；不等同于行政机关原始行政处罚决定书。','- 状态：全部 `pending_human_review`，`approved_for_rag=false`。','']
 for sid,name in SCENARIOS:
  lines += [f'## {name}','']
  for x in [z for z in rows if z['scenario_id']==sid]:
   lines.append(f"{x['scenario_rank']}. [{x['title']}]({x['source_url']})；{x['court']}；{x['case_number']}；{x['decision_date']}；`{x['reference_classification']}`；`{x['relevance_level']}`")
   lines.append(f"   - 证据片段：{x['evidence_snippet'][:220]}")
   lines.append(f"   - 原始返回：`{x['raw_text_path']}`")
  lines.append('')
 mp=REPORT_DIR/'pkulaw_gap_case_curated_20260917.md';mp.write_text('\n'.join(lines))
 print(json.dumps({'rows':len(rows),'missing':missing,'coverage':coverage,'json':str(jp),'csv':str(cp),'md':str(mp)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
