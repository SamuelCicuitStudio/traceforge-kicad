"""Keep native client and PCB Editor request deadlines in sync."""

LONG_OPERATIONS = ('stitch_', 'fanout_', 'tracefence_', 'endpoint_', 'pick_',
                   'cleanup_')


def editor_timeout(operation):
    # A whole-board cleanup checks connectivity on every copper layer. It can
    # outlast the short request deadline even when the editor is healthy.
    return 120 if operation.startswith(LONG_OPERATIONS) else 5


def client_timeout(operation):
    # Allow the editor time to send its result after its own deadline.
    return editor_timeout(operation) + (5 if operation.startswith(LONG_OPERATIONS) else 1)
