"""Deterministic pair/group regressions; optionally exercise an extracted PCM archive."""
import argparse,sys,tempfile,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--package',type=Path);args=p.parse_args()
with tempfile.TemporaryDirectory(prefix='traceforge-matching-') as temp:
 if args.package:
  with zipfile.ZipFile(args.package) as z:z.extractall(temp)
  sys.path.insert(0,str(Path(temp)/'plugins'))
 else:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
 from signal_path_analyzer.chains import ChainDef,Config,GroupDef,NetDelay,NetGeometry,TrackSeg,evaluate,drc_rules
 chains=tuple(ChainDef('HDMI',n,(n,),pair=m)for n,m in [('A_P','A_N'),('A_N','A_P'),('B_P','B_N'),('B_N','B_P')])
 cfg=Config([GroupDef('HDMI',chains,skew_ps=30,pair_skew_ps=.7)])
 geo={c.name:NetGeometry('SE50',[TrackSeg('F.Cu',1)])for c in chains}
 def run(values):return evaluate(cfg,{n:NetDelay(v,0,0,True)for n,v in zip(geo,values)},geo)[0]
 g=run([100,100.5,120,120.5]);assert all(c.status=='ok'for c in g.chains) and g.spread_ps==20
 assert all(c.minimum_ps<=c.total_ps<=c.maximum_ps for c in g.chains)
 g=run([100,101,120,120]);assert [c.status for c in g.chains]==['short','long','ok','ok']
 g=run([100,100.5,145,145.5]);assert [c.status for c in g.chains]==['short','short','ok','ok']
 g=run([100,100.7,130,130.7]);assert all(c.status=='ok'for c in g.chains)
 assert 'XSIG HDMI A_P total' in drc_rules([g])
 # Native targets subtract fixed upstream-net delay, not just the total skew.
 offset=Config([GroupDef('PAIR',(ChainDef('PAIR','P',('fixed','p'),pair='N'),ChainDef('PAIR','N',('n',),pair='P')),pair_skew_ps=.7)])
 offset_geo={n:NetGeometry('SE50',[TrackSeg('F.Cu',1)]) for n in ['fixed','p','n']}
 result=evaluate(offset,{n:NetDelay(v,0,0,True)for n,v in [('fixed',40),('p',60),('n',100.5)]},offset_geo)[0]
 rule=drc_rules([result]);assert '(min 59.80ps)' in rule and '(max 61.20ps)' in rule
 geo['A_N']=NetGeometry('SE50');g=run([100,100,120,120]);assert g.chains[0].status=='routed' and g.chains[1].status=='pending'
 print('PASS: independent pair/group limits, legal tuning windows, boundary values and pending-partner handling'+(' in PCM package'if args.package else''))
