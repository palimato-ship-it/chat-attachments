"""Inspect attachment payloads without treating truncated diagnostic snippets as files."""
import base64
import hashlib
import mimetypes
import re
import struct

IMAGE_MIMES = ('image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp',
               'image/bmp', 'image/tiff', 'image/heic', 'image/heif', 'image/avif', 'image/x-icon')

DATA_URI = re.compile(r'data:([^;,\s]+);base64,([A-Za-z0-9+/=]+)')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(value):
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None


def dimensions(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        return struct.unpack('>II', data[16:24])
    if data[:6] in (b'GIF87a', b'GIF89a') and len(data) >= 10:
        return struct.unpack('<HH', data[6:10])
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) >= 30:
        kind = data[12:16]
        if kind == b'VP8X':
            return (1 + int.from_bytes(data[24:27], 'little'), 1 + int.from_bytes(data[27:30], 'little'))
        if kind == b'VP8 ' and data[23:26] == b'\x9d\x01\x2a':
            return tuple(x & 0x3fff for x in struct.unpack('<HH', data[26:30]))
        if kind == b'VP8L' and data[20] == 0x2f:
            bits = int.from_bytes(data[21:25], 'little')
            return (1 + (bits & 0x3fff), 1 + ((bits >> 14) & 0x3fff))
    if not data.startswith(b'\xff\xd8'):
        return None
    pos = 2
    while pos + 3 < len(data):
        if data[pos] != 255:
            pos += 1
            continue
        while pos < len(data) and data[pos] == 255:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
            continue
        length = int.from_bytes(data[pos:pos + 2], 'big')
        if length < 2:
            break
        if marker in (0xc0, 0xc1, 0xc2) and pos + 7 <= len(data):
            height, width = struct.unpack('>HH', data[pos + 3:pos + 7])
            return width, height
        pos += length
    return None


def valid(mime, data):
    if not data:
        return False
    if mime == 'image/png':
        return data.startswith(b'\x89PNG\r\n\x1a\n') and data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82') and dimensions(data) is not None
    if mime in ('image/jpeg', 'image/jpg'):
        return data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9') and dimensions(data) is not None
    if mime == 'image/gif':
        return data[:6] in (b'GIF87a', b'GIF89a') and data.endswith(b';') and dimensions(data) is not None
    if mime == 'image/webp':
        return data[:4] == b'RIFF' and data[8:12] == b'WEBP' and int.from_bytes(data[4:8], 'little') + 8 == len(data)
    if mime in IMAGE_MIMES:
        return len(data) >= 16
    return not mime.startswith('image/')


def raw_blob(value):
    """Recognize structured binary bodies; do not guess that arbitrary text is base64."""
    if not isinstance(value, dict):
        return None
    kind = value.get('type')
    if kind == 'image' and isinstance(value.get('data'), str):
        return value.get('mimeType', 'application/octet-stream'), value['data'], 'data'
    if (kind == 'Extension' and value.get('kind') == 'image_gen.generation') or kind == 'imageGeneration':
        data = decode(value.get('result'))
        mime = 'image/png' if data and data.startswith(b'\x89PNG') else 'image/jpeg'
        return mime, value.get('result'), 'result'
    if kind in ('input_file', 'file') and isinstance(value.get('file_data'), str) and not value['file_data'].startswith('data:'):
        mime = mimetypes.guess_type(value.get('filename', ''))[0] or 'application/octet-stream'
        return mime, value['file_data'], 'file_data'
    return None


def blobs(value, location=()):
    """Yield (MIME, bytes, encoded bytes, JSON location), including repeated copies."""
    if isinstance(value, dict):
        blob = raw_blob(value)
        skip = None
        if blob:
            mime, encoded, key = blob
            data = decode(encoded)
            if data and valid(mime, data):
                yield mime, data, len(encoded), location + (key,)
                skip = key
        for key, child in value.items():
            if key != skip:
                yield from blobs(child, location + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from blobs(child, location + (index,))
    elif isinstance(value, str):
        for match in DATA_URI.finditer(value):
            mime, encoded = match.groups()
            data = decode(encoded)
            if data and valid(mime, data):
                yield mime, data, len(match.group(0)), location


def origin(record):
    payload = record.get('payload', {})
    if not isinstance(payload, dict):
        return 'unknown'
    item = payload.get('item', {})
    if payload.get('role') == 'user' or (isinstance(item, dict) and item.get('type') == 'UserMessage'):
        return 'user'
    if record.get('type') == 'compacted':
        return 'compacted-copy'
    if payload.get('role') == 'assistant' or payload.get('type') in ('item_completed', 'custom_tool_call_output', 'function_call_output'):
        return 'assistant'
    return 'unknown'
