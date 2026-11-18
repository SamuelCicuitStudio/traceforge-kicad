"""One exclusive component operation across research, assignment and manufacturing."""


class Gate:
    def __init__(self):
        self.owner = None
        self.label = ""

    def acquire(self, owner, label):
        if self.owner is not None and self.owner is not owner:
            return False
        self.owner, self.label = owner, label
        return True

    def release(self, owner):
        if self.owner is owner:
            self.owner, self.label = None, ""


def gate(components):
    if not hasattr(components, "_component_operation_gate"):
        components._component_operation_gate = Gate()
    return components._component_operation_gate
