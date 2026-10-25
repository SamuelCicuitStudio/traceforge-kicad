"""Cache tab revisions; failed checks are never retried in a background loop."""


class RefreshPolicy:
    def __init__(self):
        self.seen = {}

    def needs_refresh(self, tab, state):
        key = (state['board'], state['revision'],
               tuple(state['selection']) if tab == 2 else ())
        if self.seen.get(tab) == key:
            return False
        self.seen[tab] = key
        return True

    def invalidate(self, tab=None):
        if tab is None:
            self.seen.clear()
        else:
            self.seen.pop(tab, None)
