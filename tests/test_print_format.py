from PIL import Image
import unittest

from photo_agent.print_format import cm_to_px, format_image, spec_from_preset


class PrintFormatTests(unittest.TestCase):
    def test_print_image_has_expected_300_dpi_dimensions(self) -> None:
        source = Image.new("RGB", (1600, 1000), "white")
        result = format_image(source, spec_from_preset("10×15 см"))

        # Горизонтальная ориентация автоматически выбирает 15×10 см, плюс вылеты.
        expected_width = cm_to_px(15, 300) + 2 * cm_to_px(0.3, 300)
        expected_height = cm_to_px(10, 300) + 2 * cm_to_px(0.3, 300)
        self.assertEqual(result.image.size, (expected_width, expected_height))
