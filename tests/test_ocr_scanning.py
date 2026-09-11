from picsyncra.services.ocr_scanning import scan_image
from picsyncra.services.ocr_values import OcrValue


class FakeDiscovery:
    def discover(self, _path):
        return [OcrValue("120/140", "120?140", 0.8, (1, 2, 30, 20))]


class FakeRefiner:
    def refine(self, _path, bbox):
        return OcrValue("120-140", "120?140", 0.95, bbox)


def test_scan_returns_fast_values_and_defers_cancelled_crop():
    result = scan_image(
        "image.png",
        discoverer=FakeDiscovery(),
        refiner=FakeRefiner(),
        cancel_requested=lambda: True,
    )

    assert [item.comparison for item in result.fast_values] == ["120?140"]
    assert result.refined_values == []
    assert result.deferred_bboxes == [(1, 2, 30, 20)]
