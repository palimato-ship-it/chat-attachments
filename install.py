"""Set up the image runtime, this plugin's cached MCP entry, and user timer."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-only', action='store_true', help='Complete setup after installing through Add a marketplace; do not re-register the marketplace.')
    parser.add_argument('--runtime-ready', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    package = root / 'plugins/chat-attachments'
    if not args.runtime_ready:
        environment = root / '.venv'
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not python.is_file():
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(python), '-m', 'pip', 'install', '--only-binary=:all:', '-r', str(root / 'requirements.txt')], check=True)
        command = [str(python), str(Path(__file__).resolve()), '--runtime-ready']
        if args.runtime_only:
            command.append('--runtime-only')
        return subprocess.run(command).returncode
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    cached = home / 'plugins/cache/peli-local/chat-attachments'
    if not args.runtime_only:
        codex = shutil.which('codex')
        if not codex:
            raise SystemExit('Put the Codex CLI on PATH, or install through the app and use --runtime-only.')
        subprocess.run([codex, 'plugin', 'marketplace', 'add', str(root), '--json'], check=True)
        if cached.is_dir():
            subprocess.run([codex, 'plugin', 'remove', 'chat-attachments@peli-local', '--json'], check=True)
        subprocess.run([codex, 'plugin', 'add', 'chat-attachments@peli-local', '--json'], check=True)
    # Bind this user's interpreter in the installed cache, never in tracked source.
    # Future marketplace updates may replace it; rerun --runtime-only afterwards.
    manifests = list(cached.glob('*/.codex-plugin/plugin.json')) if cached.is_dir() else []
    if not manifests:
        raise SystemExit('Install Chat Attachments from Peli Plugins in the app first, then rerun with --runtime-only.')
    for manifest in manifests:
        installed = manifest.parent.parent
        config = {'mcpServers': {'attachments': {'command': sys.executable,
                  'args': [str(installed / 'server.py')], 'env': {'PYTHONDONTWRITEBYTECODE': '1'},
                  'startup_timeout_sec': 30}}}
        (installed / '.mcp.json').write_text(json.dumps(config, indent=2) + '\n')
    subprocess.run([sys.executable, str(package / 'scheduler.py'), 'install'], check=True)
    print('Setup complete. Restart Codex, then say: Chat compression')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
