"""Local session discovery, attachment inventory and preservation of byte boundaries."""
from pathlib import Path
import json
import re

from media import IMAGE_MIMES, blobs, digest, dimensions, origin


class AttachmentError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def read_history(path):
    data = path.read_bytes()
    if data and not data.endswith(b'\n'):
        raise AttachmentError('history_busy', 'The chat is writing a partial record. Try when it is idle.')
    lines = data.splitlines(keepends=True)
    try:
        records = [json.loads(line) for line in lines]
    except (ValueError, UnicodeError):
        raise AttachmentError('unsupported_history', 'The history contains an unreadable record; no conversion was applied.')
    return data, lines, records


def session(home, thread_id):
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', thread_id):
        raise AttachmentError('invalid_thread', 'Use the exact selected Codex chat ID.')
    paths = []
    for name in ('sessions', 'archived_sessions'):
        root = home / name
        if root.exists():
            paths.extend(root.rglob('*' + thread_id + '*.jsonl'))
    if len(paths) != 1:
        raise AttachmentError('session_not_unique', 'The selected local history was not found uniquely.')
    path = paths[0]
    data, lines, records = read_history(path)
    meta = next((row.get('payload', {}) for row in records if row.get('type') == 'session_meta'), {})
    if meta.get('id') != thread_id:
        raise AttachmentError('session_mismatch', 'The history ID differs from the selected chat.')
    return path, data, lines, records, meta


def state_path(project, thread_id):
    return project / 'attachments' / '.chat-attachments' / thread_id / 'index.json'


def existing_index(project, thread_id):
    path = state_path(project, thread_id)
    if path.is_file():
        try:
            state = json.loads(path.read_text())
            if state.get('thread_id') == thread_id:
                return state
        except (ValueError, OSError):
            raise AttachmentError('index_unreadable', 'The attachment index cannot be read; preserve it for recovery.')
    assets = {}
    # Read-only compatibility with the owner-approved Libre Chat experiments.
    trial = project / 'attachments' / '.trial'
    for name in ('thumbnail-manifest.json', 'jpeg-manifest.json', 'q20-half-manifest.json'):
        candidate = trial / name
        if not candidate.is_file():
            continue
        try:
            legacy = json.loads(candidate.read_text())
        except (ValueError, OSError):
            continue
        if legacy.get('session_id') != thread_id:
            continue
        for item in legacy.get('attachments', []):
            original = item.get('sha256')
            if not original or not item.get('original'):
                continue
            previous = assets.get(original, {})
            aliases = set(previous.get('preview_hashes', []))
            for key in ('thumbnail_sha256', 'compressed_sha256'):
                if item.get(key):
                    aliases.add(item[key])
            assets[original] = {
                **previous, 'original_sha256': original, 'original': item['original'],
                'name': item.get('name', Path(item['original']).name),
                'preview_hashes': sorted(aliases),
                'preview': item.get('compressed', item.get('thumbnail', previous.get('preview'))),
            }
    return {'version': 1, 'thread_id': thread_id, 'assets': assets}


def offsets(data):
    result, position = {}, 0
    for line in data.splitlines(keepends=True):
        row = json.loads(line)
        ordinal = row.get('ordinal')
        if isinstance(ordinal, int):
            result[ordinal] = (position, position + len(line))
        position += len(line)
    if result:
        result[max(result) + 1] = (position, position)
    return result


def translated(old, new, ordinal, position):
    if ordinal is None or position is None:
        return position
    if ordinal not in old or ordinal not in new:
        raise AttachmentError('index_boundary_missing', 'A display boundary is unavailable; conversion was stopped.')
    if position == old[ordinal][0]:
        return new[ordinal][0]
    if position == old[ordinal][1]:
        return new[ordinal][1]
    raise AttachmentError('index_out_of_sync', 'The display index is already out of sync; repair it before converting.')


EXTENSIONS = r'png|jpe?g|gif|webp|bmp|tiff?|heic|heif|avif|ico|pdf|docx?|xlsx?|pptx?|csv|txt|log|zip|mp3|wav|mp4|apk'
PATHS = re.compile(r'(?:/Users/|/tmp/|/home/)[^\s<>"\x27`\)\]\},;]*?\.(?:' + EXTENSIONS + r')(?=$|[\s<>"\x27`\)\]\},;:#?])', re.I)


def references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('path', 'file_path', 'filePath', 'filename', 'savedPath') and isinstance(child, str) and Path(child).is_absolute():
                if re.search(r'\.(' + EXTENSIONS + ')$', child, re.I):
                    yield child
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)
    elif isinstance(value, str):
        for path in re.findall(r'\]\(<?([A-Za-z]:[\\/][^\n]*?)>?\)', value):
            if re.search(r'\.(' + EXTENSIONS + ')$', path, re.I):
                yield path
        for match in PATHS.finditer(value):
            yield match.group(0)
        for path in re.findall(r'\]\(<?(/[^\n]*?)>?\)', value):
            if re.search(r'\.(' + EXTENSIONS + ')$', path, re.I):
                yield path


def inventory(records, index):
    aliases = {sha: sha for sha in index.get('assets', {})}
    optimized = set()
    for sha, asset in index.get('assets', {}).items():
        for preview in asset.get('preview_hashes', []):
            aliases[preview] = sha
            optimized.add(preview)
    found, refs = {}, set()
    for number, row in enumerate(records):
        payload = row.get('payload', {})
        source = origin(row)
        for mime, raw, encoded, location in blobs(payload):
            sha = digest(raw)
            entry = found.setdefault(sha, {
                'id': sha, 'mime': mime, 'bytes': len(raw), 'dimensions': dimensions(raw),
                'copies': 0, 'stored_encoded_bytes': 0, 'origins': set(), 'locations': [],
                'status': 'already_optimized' if sha in optimized else 'embedded',
                'original_id': aliases.get(sha, sha),
                'convertible': mime in IMAGE_MIMES and sha not in optimized,
            })
            entry['copies'] += 1
            entry['stored_encoded_bytes'] += encoded
            entry['origins'].add(source)
            entry['locations'].append({'record': number, 'json_path': list(location)})
        refs.update(references(payload))
    for entry in found.values():
        entry['origins'] = sorted(entry['origins'])
    external = []
    for value in sorted(refs):
        path = Path(value)
        try:
            exists = path.is_file()
            size = path.stat().st_size if exists else None
        except OSError:
            exists, size = False, None
        external.append({'path': value, 'exists': exists, 'bytes': size})
    return found, external
