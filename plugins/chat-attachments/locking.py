"""Advisory process locks for Windows and POSIX; separate from Codex's writer."""
from contextlib import contextmanager
import os

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


@contextmanager
def exclusive(stream, blocking=True):
    if os.name == 'nt':
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        except OSError:
            raise BlockingIOError('The attachment operation lock is busy.') from None
    else:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    try:
        yield
    finally:
        if os.name == 'nt':
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream, fcntl.LOCK_UN)
