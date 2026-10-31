"""Optional CLI installation; the installed plugin also has its own setup action."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-only', action='store_true', help='Set up the local image runtime/timer without changing marketplace registration.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    package = root / 'plugins/chat-attachments'
    if not args.runtime_only:
        codex = shutil.which('codex')
        if not codex:
            raise SystemExit('Put the Codex CLI on PATH, or use the app marketplace and --runtime-only.')
        subprocess.run([codex, 'plugin', 'marketplace', 'add', str(root), '--json'], check=True)
        cached = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'plugins/cache/peli-local/chat-attachments'
        if cached.is_dir():
            subprocess.run([codex, 'plugin', 'remove', 'chat-attachments@peli-local', '--json'], check=True)
        subprocess.run([codex, 'plugin', 'add', 'chat-attachments@peli-local', '--json'], check=True)
    sys.path.insert(0, str(package))
    from runtime import setup_runtime
    result = setup_runtime(approved=True)
    if not result['ready']:
        raise SystemExit('Image runtime setup completed partially: ' + str(result.get('last_error')))
    print('Setup complete. Restart Codex and review/trust the plugin SessionStart hook for new-chat onboarding.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
