import fitz
from PIL import Image

from paper_media import TEASER_ASPECT_RATIO, _render_figure


def test_teaser_render_keeps_complete_crop_and_fixed_aspect(tmp_path):
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    original = fitz.Rect(80, 200, 520, 340)
    page.draw_rect(original, color=(1, 0, 0), fill=(1, 0.9, 0.9))
    output = tmp_path / "teaser.jpg"

    _render_figure(
        document,
        {"page_index": 0, "crop": original},
        output,
        target_aspect=TEASER_ASPECT_RATIO,
    )
    document.close()

    with Image.open(output) as image:
        assert abs(image.width / image.height - TEASER_ASPECT_RATIO) < 0.01
        # The fixed-ratio operation expands/pads instead of cutting the source crop.
        assert image.width > image.height
