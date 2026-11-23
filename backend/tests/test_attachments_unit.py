"""B5 CP4 unit tests (no database): image validation and metadata removal, local storage keys,
display file names."""
import io

import pytest
from PIL import Image, PngImagePlugin

from app.services.attachment_service import clean_file_name
from app.storage import FileNotAvailable, LocalDiskStorage
from app.utils.images import InvalidImage, sanitize


def _jpeg(mode="RGB", size=(30, 20), **save):
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, "JPEG", **save)
    return buf.getvalue()


def test_jpeg_metadata_is_removed_and_orientation_applied():
    exif = Image.Exif()
    exif[0x0112] = 6                       # rotate 90 degrees when displayed
    exif[0x010F] = "SecretCam"
    exif[0x8825] = {1: "N", 2: (30.0, 2.0, 40.0)}
    raw = _jpeg(exif=exif, comment=b"secret comment", xmp=b"<x:xmpmeta>secret xmp</x:xmpmeta>")
    clean = sanitize(raw)
    assert (clean.mime_type, clean.extension, clean.width, clean.height) == ("image/jpeg", ".jpg", 20, 30)
    assert not any(marker in clean.content for marker in (b"Exif", b"SecretCam", b"secret xmp", b"secret comment"))
    assert dict(Image.open(io.BytesIO(clean.content)).getexif()) == {}


def test_png_text_chunks_are_removed():
    info = PngImagePlugin.PngInfo()
    info.add_text("GPS", "30.0N 31.2E")
    info.add_itxt("Author", "secret author")
    buf = io.BytesIO()
    Image.new("P", (6, 6)).save(buf, "PNG", pnginfo=info)
    clean = sanitize(buf.getvalue())
    assert clean.mime_type == "image/png" and b"30.0N" not in clean.content and b"secret" not in clean.content


@pytest.mark.parametrize("mode", ["L", "CMYK"])
def test_other_jpeg_colour_modes_are_accepted(mode):
    assert sanitize(_jpeg(mode=mode)).mime_type == "image/jpeg"


def test_non_images_other_formats_truncated_files_and_bombs_are_refused():
    gif, webp = io.BytesIO(), io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    bomb = io.BytesIO()
    Image.new("1", (8000, 6000)).save(bomb, "PNG")      # 48 MP: tiny file, huge image
    for data in (b"", b"plain text", gif.getvalue(), _jpeg()[:100], bomb.getvalue(),
                 b"<svg xmlns='http://www.w3.org/2000/svg'/>"):
        with pytest.raises(InvalidImage):
            sanitize(data)


@pytest.mark.parametrize("given, ext, expected", [
    ("photo.JPEG", ".jpg", "photo.jpg"),
    ("C:\\Users\\nurse\\pump.png", ".png", "pump.png"),
    ("../../etc/passwd", ".jpg", "passwd.jpg"),
    ("evil.png", ".jpg", "evil.jpg"),            # the content decides the extension
    ("line\nbreak\x00.jpg", ".jpg", "linebreak.jpg"),
    ("", ".png", "photo.png"),
    (None, ".jpg", "photo.jpg"),
    ("...", ".jpg", "photo.jpg"),
    ("a" * 400 + ".jpg", ".jpg", "a" * 251 + ".jpg"),
])
def test_display_file_names(given, ext, expected):
    assert clean_file_name(given, ext) == expected


def test_local_storage_round_trip_and_key_safety(tmp_path):
    store = LocalDiskStorage(tmp_path / "files")
    key = store.save(b"abc", ".jpg")
    assert store.open(key) == b"abc" and (tmp_path / "files" / key).is_file()
    assert not list((tmp_path / "files").rglob(".upload-*"))      # no temporary file left behind
    store.delete(key)
    store.delete(key)                                              # deleting twice is fine
    with pytest.raises(FileNotAvailable):
        store.open(key)
    for bad in ("../../etc/passwd", "/etc/passwd", "ab/../../x.jpg", "ab/" + "0" * 32 + ".exe", ""):
        with pytest.raises(FileNotAvailable):
            store.open(bad)
        store.delete(bad)                                          # never raises, never touches anything
    with pytest.raises(ValueError):
        store.save(b"x", ".exe")


def _asgi(path, length, method="POST"):
    """Run the upload-limit middleware once; returns (status, inner_app_was_called)."""
    import asyncio

    from app.middleware.upload_limit import UploadSizeLimitMiddleware
    called, sent = [], []

    async def inner(scope, receive, send):
        called.append(True)

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover - never read by the middleware
        raise AssertionError("the body must not be read")

    headers = [(b"content-length", str(length).encode())] if length is not None else []
    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    asyncio.run(UploadSizeLimitMiddleware(inner)(scope, receive, send))
    return (sent[0]["status"] if sent else None), bool(called)


def test_upload_limit_middleware_refuses_only_oversized_photo_uploads():
    from app.core.config import get_settings
    big = get_settings().max_upload_bytes + 1024 * 1024
    assert _asgi("/api/v1/tickets/abc/attachments", big) == (413, False)
    assert _asgi("/api/v1/tickets/abc/attachments", 1000) == (None, True)          # within the limit
    assert _asgi("/api/v1/tickets/abc/attachments", None) == (None, True)          # chunked: the endpoint checks
    assert _asgi("/api/v1/tickets/abc/attachments", big, "GET") == (None, True)    # only uploads
    assert _asgi("/api/v1/tickets", big) == (None, True)                           # other routes untouched
