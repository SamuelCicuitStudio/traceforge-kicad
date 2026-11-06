"""Presentation of signal electrical type and tuning actions; independent of wx."""
def describe_signal(group,chain):
 mate=next((c for c in group.chains if c.name==chain.pair and c.pair==chain.name),None)
 if mate is None:
  if chain.pair:return {'label':'[INVALID PAIR] '+chain.name,'kind':'invalid','hint':'Missing reciprocal differential partner. Review chain definitions.'}
  return {'label':'[SE] '+chain.name,'kind':'single-ended','hint':f'{chain.name}: SINGLE-ENDED. KiCad 7: Tune Single Track Length. Bus budget: {group.skew_ps if group.skew_ps is not None else "unset"} ps.'}
 pair=group.pair_skew_ps if group.pair_skew_ps is not None else 'unset'
 bus=group.skew_ps if group.skew_ps is not None else 'unset'
 hint=(f'{chain.name} + {mate.name}: DIFFERENTIAL PAIR. KiCad 8: move P/N together; 9: correct P/N skew. '
       f'P/N limit: {pair} ps; group/bus budget: {bus} ps.')
 if len(chain.nets)>1 or len(mate.nets)>1:
  hint+=' Series parts split this path: local zero skew may not mean whole-chain zero skew. Check the whole-chain P/N value.'
 return {'label':f'[DIFF] {chain.name} (mate: {mate.name})','kind':'differential','hint':hint}
