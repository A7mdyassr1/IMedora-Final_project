"""Photo uploads (B5, Decision 5): accept only real JPEG / PNG images and strip their metadata.

- The type comes from the CONTENT (Pillow's decoder), never from the file name or the client's
  Content-Type. Anything Pillow cannot decode as JPEG or PNG is refused.
- Decompression bombs are refused: more than MAX_PIXELS pixels is an error, not a warning.
- The image is re-encoded from its pixels only. EXIF (incl. GPS position, camera, time), XMP, IPTC,
  comments and PNG text chunks are dropped; the EXIF orientation is applied to the pixels first
  so photos still display upright. The ICC colour profile is kept (it is colour data, not personal
  data). JPEG quality 90.
"""
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 40_000_000          # ~ a 48 MP phone photo is 8064 x 6048 = 48.8 MP; 40 MP covers 12-24 MP cameras
JPEG_QUALITY = 90
ALLOWED = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png")}


class InvalidImage(ValueError):
    """Not a JPEG / PNG image this API accepts (the message is safe to show)."""


@dataclass(frozen=True)
class CleanImage:
    content: bytes
    mime_type: str
    extension: str
    width: int
    height: int


def _open(data: bytes) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(data))
            if img.format not in ALLOWED:
                raise InvalidImage("Only JPEG and PNG images are accepted.")
            if img.width * img.height > MAX_PIXELS:
                raise InvalidImage("The image has too many pixels.")
            return img
        except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise InvalidImage("The file is not a valid JPEG or PNG image.") from None


def sanitize(data: bytes) -> CleanImage:
    """Validate and re-encode; raises InvalidImage."""
    if not data:
        raise InvalidImage("The file is empty.")
    try:
        probe = _open(data)
        fmt = probe.format
        probe.verify()                      # structural check of the whole file
        img = _open(data)                   # verify() leaves the image unusable: open again
        img.load()                          # decode every pixel now (truncated files fail here)
        img = ImageOps.exif_transpose(img)  # keep photos upright once the EXIF orientation is gone
    except InvalidImage:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvalidImage("The file is not a valid JPEG or PNG image.") from exc

    icc = img.info.get("icc_profile")
    img.info = {}                           # nothing from the original file is copied by default
    out = io.BytesIO()
    if fmt == "JPEG":
        if img.mode not in ("RGB", "L", "CMYK"):
            img = img.convert("RGB")
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, **({"icc_profile": icc} if icc else {}))
    else:
        img.save(out, "PNG", optimize=True, **({"icc_profile": icc} if icc else {}))
    mime, extension = ALLOWED[fmt]
    return CleanImage(out.getvalue(), mime, extension, img.width, img.height)
