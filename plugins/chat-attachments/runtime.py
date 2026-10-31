"""Standard-library first-use setup; no Pillow import is needed to repair setup."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

from history import AttachmentError
from locking import exclusive

VERSION = '0.3.0'
PACKAGE = Path(__file__).resolve().parent


def home_path():
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).resolve()


def folder():
    return home_path() / 'chat-attachments'


def interpreter():
    return folder() / 'environment' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def requirement_hash():
    return hashlib.sha256((PACKAGE / 'requirements.txt').read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    os.replace(temporary, path)


def setup_status():
    path = folder() / 'setup.json'
    try:
        state = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        state = {}
    runtime_ready = bool(interpreter().is_file() and state.get('runtime_ready')
                         and state.get('requirements_hash') == requirement_hash())
    current = state.get('version') == VERSION and state.get('package') == str(PACKAGE)
    timer_ready = bool(current and state.get('timer_ready'))
    return {'ready': runtime_ready and timer_ready, 'runtime_ready': runtime_ready,
            'timer_ready': timer_ready, 'current_package': current, 'version': VERSION,
            'interpreter': str(interpreter()) if runtime_ready else None,
            'last_error': state.get('error'),
            'instruction': 'Use Set up Chat Attachments to install or repair the local image runtime and timer.'}


def setup_runtime(approved=False, force=True):
    if approved is not True:
        raise AttachmentError('approval_required', 'Request setup explicitly, or review and trust the plugin startup hook first.')
    root = folder()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise AttachmentError('unsafe_setup', 'The runtime directory must not be a symbolic link.')
    lock_path = root / 'setup.lock'
    with lock_path.open('a+b') as lock, exclusive(lock):
        os.chmod(lock_path, 0o600)
        current = setup_status()
        if not force and current['ready'] and current['current_package']:
            return {**current, 'status': 'already_ready'}
        state = {'version': VERSION, 'package': str(PACKAGE), 'attempted_at': time.time(),
                 'requirements_hash': requirement_hash(), 'runtime_ready': False, 'timer_ready': False}
        python = interpreter()
        try:
            if not python.is_file():
                # Prefer an available stable interpreter when the launcher's Python
                # is newer than the image-library wheels installed on this Mac.
                base = (shutil.which('python3.14') if sys.version_info >= (3, 15) else None) or sys.executable
                subprocess.run([base, '-m', 'venv', str(python.parent.parent)],
                               check=True, capture_output=True, timeout=90)
            subprocess.run([str(python), '-m', 'pip', 'install', '--only-binary=:all:',
                            '-r', str(PACKAGE / 'requirements.txt')],
                           check=True, capture_output=True, timeout=180)
            state['runtime_ready'] = True
        except (OSError, subprocess.SubprocessError):
            state['error'] = 'dependency_setup_failed'
            save(root / 'setup.json', state)
            raise AttachmentError('dependency_setup_failed', 'Python/Pillow setup failed. Check Python venv/pip availability and package-index access, then request setup again.') from None
        try:
            subprocess.run([str(python), str(PACKAGE / 'scheduler.py'), 'install', '--home', str(home_path())],
                           check=True, capture_output=True, timeout=45)
            state['timer_ready'] = True
        except (OSError, subprocess.SubprocessError):
            state['error'] = 'timer_setup_failed'
        if os.name == 'nt':
            # A Windows Python launcher can run the hook even when `python3` is
            # absent from PATH. Bind the installed cache to its known interpreter.
            cache = home_path() / 'plugins/cache/peli-local/chat-attachments'
            for manifest in cache.glob('*/.codex-plugin/plugin.json') if cache.is_dir() else []:
                installed = manifest.parent.parent
                save(installed / '.mcp.json', {'mcpServers': {'attachments': {
                    'command': str(python), 'args': [str(installed / 'server.py')],
                    'env': {'PYTHONDONTWRITEBYTECODE': '1'}, 'startup_timeout_sec': 30}}})
        save(root / 'setup.json', state)
        return {**setup_status(), 'status': 'ready' if state['timer_ready'] else 'partial',
                'policies_changed': False,
                'instruction': 'Runtime ready. Existing timer settings are preserved; no chats were enabled.' if state['timer_ready'] else 'Image runtime installed, but native timer registration failed. Manual scans/conversion remain available. Request setup again after checking the native user scheduler.'}


def automatic_setup():
    status = setup_status()
    if status['ready'] and status['current_package']:
        return status
    # One automatic attempt per version/package; do not retry failed downloads on
    # every chat. An explicit setup request can retry after the cause is fixed.
    if status['current_package'] and status['last_error']:
        return status
    try:
        return setup_runtime(approved=True, force=False)
    except AttachmentError as error:
        return {**setup_status(), 'last_error': error.code}


def invoke_worker(name, arguments):
    status = setup_status()
    if not status['runtime_ready']:
        raise AttachmentError('setup_required', 'Choose Set up Chat Attachments (menu option 8) before using image or timer tools.')
    python = interpreter()
    if Path(sys.prefix).resolve() == python.parent.parent.resolve():
        from service import Service
        return getattr(Service(), name)(**arguments)
    result = subprocess.run([str(python), str(PACKAGE / 'server.py'), '--invoke', name],
                            input=json.dumps(arguments), text=True, capture_output=True, timeout=600)
    try:
        response = json.loads(result.stdout)
    except ValueError:
        raise AttachmentError('runtime_failed', 'The image runtime could not start. Request Set up Chat Attachments to repair it.') from None
    if not response.get('ok'):
        error = response.get('error', {})
        raise AttachmentError(error.get('code', 'runtime_failed'), error.get('message', 'The local image operation failed.'))
    return response['value']
