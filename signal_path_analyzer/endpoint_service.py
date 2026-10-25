"""Review and append selected-endpoint chains without replacing existing groups."""
from dataclasses import replace

from .chains import ChainDef, Config, GroupDef


def covered(config, path):
    if config:
        for group in config.groups:
            for chain in group.chains:
                if (set(path['nets']) <= set(chain.nets) and
                        set(path['series']) <= set(chain.series)):
                    return chain
    return None


class EndpointService:
    def __init__(self, session):
        self.session = session

    def detect(self, **payload):
        payload.setdefault('all_resistors', True)
        pairs = {}
        for group in self.session.config.groups if self.session.config else []:
            for chain in group.chains:
                mate = next((c for c in group.chains if c.name == chain.pair), None)
                if mate and len(chain.nets) == len(mate.nets):
                    pairs.update(zip(chain.nets, mate.nets))
        return self.session.native.call('endpoint_detect', pair_nets=pairs, **payload)

    def pick(self, prompt):
        return self.session.native.call('pick_item', mode='endpoint', prompt=prompt)

    def statuses(self, result):
        paths = [p for p in (result['primary'], result['partner']) if p]
        return [covered(self.session.config, path) for path in paths]

    def add(self, result, group_name, name):
        # Re-read these exact endpoints, never the path selection produced by highlighting.
        current = self.detect(endpoints=[e['id'] for e in result['primary']['endpoints']],
                              **result['settings'])
        def signature(r):
            return [(p['nets'], p['series'], p['ids']) for p in
                    (r['primary'], r['partner']) if p]
        if signature(current) != signature(result):
            raise ValueError('The routed path changed. Detect again and review before adding.')
        if current['pair_note'] and not current['partner']:
            raise ValueError('Resolve the differential partner, or turn off Include pair and '
                             'detect again to explicitly add only this signal.')
        group_name, name = group_name.strip(), name.strip()
        if not group_name or not name:
            raise ValueError('Enter a group and chain name.')
        config = self.session.config or Config([])
        paths = [p for p in (current['primary'], current['partner']) if p]
        existing = self.statuses(current)
        if all(existing):
            return 'Already included: ' + ', '.join(f'{c.group}/{c.name}' for c in existing)
        old_groups = {c.group for c in existing if c}
        if old_groups:
            if len(old_groups) != 1:
                raise ValueError('Existing pair members belong to different groups. '
                                 'Use Chain editor.')
            group_name = next(iter(old_groups))
        group = config.group(group_name) or GroupDef(group_name, ())
        members = list(group.chains)
        names = {c.name for c in members}
        additions = []
        for index, (path, found) in enumerate(zip(paths, existing)):
            if found:
                additions.append(found)
                continue
            base = name if index == 0 else name + ' partner'
            candidate, suffix = base, 2
            while candidate in names:
                candidate, suffix = f'{base} ({suffix})', suffix + 1
            names.add(candidate)
            chain = ChainDef(group_name, candidate, tuple(path['nets']), tuple(path['series']))
            members.append(chain)
            additions.append(chain)
        if len(additions) == 2:
            a, b = additions
            if (a.pair and a.pair != b.name) or (b.pair and b.pair != a.name):
                raise ValueError('A detected chain already has another partner. Use Chain editor.')
            members = [replace(c, pair=b.name if c.name == a.name else a.name)
                       if c.name in (a.name, b.name) else c for c in members]
        updated = replace(group, chains=tuple(members))
        groups = [updated if g.name == group_name else g for g in config.groups]
        if not config.group(group_name):
            groups.append(updated)
        self.session.save_config(Config(groups, config.pad_to_die_ps_per_mm))
        return 'Saved chain definition. Click Signals Refresh to calculate timing.'
