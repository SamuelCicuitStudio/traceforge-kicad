"""Exercise the localhost single-instance tab shortcut without KiCad UI."""
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signal_path_analyzer.single_instance import listen, try_activate_existing  # noqa: E402

with socket.socket() as temporary:
    temporary.bind(('127.0.0.1', 0))
    port = temporary.getsockname()[1]

received = []
listener = listen(port, received.append)
try:
    assert try_activate_existing(port, tab=4)
    assert try_activate_existing(port, tab=1)
    assert try_activate_existing(port)
    deadline = time.monotonic() + 2
    while len(received) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert received == [4, 1, None], received
finally:
    listener.stop()

print('Quick access: rotation, Via Tools, and default panel activation OK')
