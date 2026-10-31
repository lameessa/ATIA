"""Bounded Flickr-only retrieval with decoding and integrity validation."""
from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
import time
from urllib.parse import urljoin, urlparse
import warnings
import requests
from atia.collectors.flickr import FlickrError


class ImageUnavailable(RuntimeError):
    pass


@dataclass
class ImageAsset:
    image: object
    url: str
    sha256: str
    path: str
    width: int
    height: int


def safe_flickr_url(url):
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ''
        return (parsed.scheme == 'https' and (host == 'staticflickr.com' or host.endswith('.staticflickr.com'))
                and parsed.username is None and parsed.password is None and parsed.port in (None, 443))
    except (ValueError, TypeError):
        return False



class FlickrImageFetcher:
    def __init__(self, client, cache_dir='data/images', session=None, max_bytes=20*1024*1024, pause=time.sleep, preferred_edge=640):
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()
        self.max_bytes = max_bytes
        self.pause = pause
        self.preferred_edge = preferred_edge

    def resolve_url(self, record):
        # getSizes checks present API visibility rather than assuming old URLs work.
        try:
            payload = self.client.call('flickr.photos.getSizes', photo_id=record['photo_id'])
        except FlickrError as exc:
            if exc.code in {'1', '2'}:
                raise ImageUnavailable('Photo sizes inaccessible; current availability is unknown.') from None
            raise ImageUnavailable('Flickr size lookup failed; photo availability is unknown.') from None
        size_metadata = payload.get('sizes')
        sizes = size_metadata.get('size', []) if isinstance(size_metadata, dict) else []
        choices = []
        for size in sizes if isinstance(sizes, list) else []:
            if not isinstance(size, dict) or size.get('media', 'photo') != 'photo':
                continue
            try:
                width, height = int(size['width']), int(size['height'])
                url = size['source']
                if width >= 224 and height >= 224 and safe_flickr_url(url):
                    choices.append((max(width, height), url))
            except (KeyError, ValueError, TypeError):
                continue
        if not choices:
            raise ImageUnavailable('No accessible, sufficiently large Flickr photo size.')
        preferred = [item for item in choices if item[0] >= self.preferred_edge]
        return min(preferred or choices)[1]

    def download(self, url):
        started = time.monotonic()
        for attempt in range(3):
            try:
                current = url
                for redirect in range(4):
                    if not safe_flickr_url(current) or 'unavailable' in current.lower():
                        raise ImageUnavailable('Image URL is unsupported or unavailable.')
                    with self.session.get(current, timeout=(10, 25), stream=True, allow_redirects=False) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            current = urljoin(current, response.headers.get('Location', ''))
                            continue
                        if response.status_code == 429 or response.status_code >= 500:
                            raise requests.ConnectionError('Temporary image service failure')
                        if response.status_code != 200:
                            raise ImageUnavailable(f'Image inaccessible (HTTP {response.status_code}); cause unknown.')
                        if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                            raise ImageUnavailable('Response is not an image.')
                        chunks, size = [], 0
                        for chunk in response.iter_content(64*1024):
                            if time.monotonic() - started > 90:
                                raise ImageUnavailable('Image download exceeded time budget.')
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise ImageUnavailable('Image exceeds download size limit.')
                            chunks.append(chunk)
                        return b''.join(chunks), current
                raise ImageUnavailable('Image redirect limit exceeded.')
            except requests.RequestException:
                if attempt == 2:
                    raise ImageUnavailable('Image download failed after retries; availability unknown.') from None
                self.pause(2**attempt)

    def fetch(self, record):
        from PIL import Image, ImageOps, UnidentifiedImageError
        url = self.resolve_url(record)
        content, final_url = self.download(url)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as check:
                    if check.width * check.height > 25_000_000:
                        raise ImageUnavailable('Image pixel limit exceeded.')
                    check.verify()
                with Image.open(BytesIO(content)) as opened:
                    if opened.format not in {'JPEG', 'PNG', 'WEBP'}:
                        raise ImageUnavailable('Unsupported image format or placeholder image.')
                    if min(opened.size) < 64:
                        raise ImageUnavailable('Image is too small for analysis.')
                    image = ImageOps.exif_transpose(opened).convert('RGB')
                    image.load()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise ImageUnavailable('Image is broken or failed decoding validation.') from None
        digest = hashlib.sha256(content).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f'{digest}.img'
        path.write_bytes(content)
        return ImageAsset(image, final_url, digest, str(path), image.width, image.height)
