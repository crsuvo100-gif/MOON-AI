import pytest

from app.tools.image_processing import ImageProcessingTool
from app.tools.local_media import MAX_MEDIA_FILE_BYTES, resolve_media_input
from app.tools.ocr import OcrTool
from app.tools.pdf_reader import PdfReaderTool


def test_media_input_is_confined_and_size_limited(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"image")

    with pytest.raises(ValueError, match="path escapes"):
        resolve_media_input(str(outside), root)

    large = root / "large.pdf"
    with large.open("wb") as handle:
        handle.truncate(MAX_MEDIA_FILE_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds"):
        resolve_media_input("large.pdf", root)


@pytest.mark.asyncio
async def test_document_and_ocr_tools_reject_paths_outside_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    pdf = PdfReaderTool(enabled=True, allowed_root=str(root))
    ocr = OcrTool(enabled=True, allowed_root=str(root))

    assert "path escapes" in await pdf.execute(path="../secret.pdf")
    assert "path escapes" in await ocr.execute(path="../secret.png")


@pytest.mark.asyncio
async def test_image_resize_is_bounded_and_never_overwrites(tmp_path):
    image_module = pytest.importorskip("PIL.Image")
    source = tmp_path / "input.png"
    image_module.new("RGB", (20, 10), color="red").save(source)
    tool = ImageProcessingTool(enabled=True, allowed_root=str(tmp_path))

    output = tmp_path / "input.png.resized.png"
    assert await tool.execute(path="input.png", action="resize", width=5) == str(output)
    assert output.is_file()
    assert "File exists" in await tool.execute(path="input.png", action="resize", width=5)
    assert "dimensions exceed limits" in await tool.execute(
        path="input.png", action="resize", width=5000
    )
    assert "path escapes" in await tool.execute(
        path="../outside.png", action="info"
    )
