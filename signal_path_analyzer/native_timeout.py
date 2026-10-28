"""Keep native client and PCB Editor request deadlines in sync."""

LONG_OPERATIONS = ('stitch_', 'fanout_', 'tracefence_', 'endpoint_', 'pick_',
                   'cleanup_', 'fillet_')


def editor_timeout(operation):
    # Dense whole-board stitching includes a complete copper clearance preview
    # and, on apply, zone refill and native connectivity validation.
    if operation == 'stitch_apply':
        return 300
    if operation == 'stitch_preview':
        return 180
    # A whole-board cleanup checks connectivity on every copper layer. It can
    # outlast the short request deadline even when the editor is healthy.
    return 120 if operation.startswith(LONG_OPERATIONS) else 5


def client_timeout(operation):
    # Allow the editor time to send its result after its own deadline.
    return editor_timeout(operation) + (5 if operation.startswith(LONG_OPERATIONS) else 1)
