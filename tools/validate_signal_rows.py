"""Exercise differential/single-ended rows and raw selection keys in real wx controls."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wx
from signal_path_analyzer.chains import ChainDef,Config,GroupDef,NetDelay,NetGeometry,TrackSeg,evaluate
from signal_path_analyzer.hub_ui import TraceForgePanel,Tools
p=ChainDef('RAM','DQS_P',('/p',),pair='DQS_N');n=ChainDef('RAM','DQS_N',('/n',),pair='DQS_P');dq=ChainDef('RAM','DQ0',('/dq0',))
cfg=Config([GroupDef('RAM',(p,n,dq),skew_ps=3.5,pair_skew_ps=.6)])
geo={key:NetGeometry('DDR',[TrackSeg('F.Cu',1)])for key in ['/p','/n','/dq0']}
results=evaluate(cfg,{key:NetDelay(100,0,0,True)for key in geo},geo)
app=wx.App(False);TraceForgePanel.register_shortcuts=lambda *a:None
frame=TraceForgePanel(Tools(lambda:results,*([lambda *a:None]*6)))
try:
 frame.overlay.Stop();frame.activity_timer.Stop();frame.results=results;frame.render()
 assert frame.tree.GetItemText(frame.rows['RAM','DQS_P'])=='[DIFF] DQS_P (mate: DQS_N)'
 assert frame.tree.GetItemText(frame.rows['RAM','DQ0'])=='[SE] DQ0'
 frame.tree.SelectItem(frame.rows['RAM','DQS_P']);assert frame.selected()==('RAM','DQS_P')
 frame.render();assert frame.selected()==('RAM','DQS_P')
 print('PASS: hidden native wx table renders DIFF versus SE, preserves real chain IDs and refresh selection')
finally:
 frame.worker.shutdown(wait=False, cancel_futures=True);frame.Destroy()
