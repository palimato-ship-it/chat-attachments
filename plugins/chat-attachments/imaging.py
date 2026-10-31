"""Portable JPEG previews: first frame, half dimensions, original bytes untouched."""
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from history import AttachmentError


def jpeg_preview(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                source.seek(0)
                frame = ImageOps.exif_transpose(source)
                size = frame.size
                rgba = frame.convert('RGBA')
                background = Image.new('RGB', size, 'white')
                background.paste(rgba, mask=rgba.getchannel('A'))
                small_size = (max(1, size[0] // 2), max(1, size[1] // 2))
                small = background.resize(small_size, Image.Resampling.LANCZOS)
                output = BytesIO()
                small.save(output, format='JPEG', quality=20, optimize=True)
                return output.getvalue(), size, small_size
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise AttachmentError('unsupported_image', 'This image cannot be decoded safely by the installed image library; history was preserved.') from None
