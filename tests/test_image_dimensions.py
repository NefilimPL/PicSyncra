from __future__ import annotations

import sys
import types

import picsyncra.services.image_dimensions as image_dimensions

from picsyncra.services.image_dimensions import (
    DimensionLine,
    ImageDimensionUnavailable,
    ImageDimensionRequest,
    OcrTextBox,
    analyze_image_dimensions,
    analyze_image_values,
    associate_dimension_hints,
    bundled_ocr_model_cache_path,
    image_ocr_runtime_info,
    ocr_model_cache_path,
    rotate_ocr_box_to_source,
    resolve_image_dimensions,
)


class FakeRecognizer:
    def __init__(self, boxes: list[OcrTextBox]):
        self.boxes = boxes
        self.calls = 0

    def detect(self, _path: str) -> list[OcrTextBox]:
        self.calls += 1
        return self.boxes


def test_paddle_recognizer_disables_mkldnn_for_cpu_predictor(tmp_path, monkeypatch):
    received_kwargs: dict[str, object] = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs: object) -> None:
            received_kwargs.update(kwargs)

    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path))
    monkeypatch.setitem(sys.modules, "cv2", types.ModuleType("cv2"))
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        types.SimpleNamespace(PaddleOCR=FakePaddleOCR),
    )

    image_dimensions.PaddleImageDimensionRecognizer()

    assert received_kwargs == {
        "text_detection_model_name": "PP-OCRv5_mobile_det",
        "text_recognition_model_name": "PP-OCRv5_mobile_rec",
        "enable_mkldnn": False,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }


def test_paddle_recognizer_uses_selected_offline_performance_profile(tmp_path, monkeypatch):
    received_kwargs: dict[str, object] = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs: object) -> None:
            received_kwargs.update(kwargs)

    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path))
    monkeypatch.setitem(sys.modules, "cv2", types.ModuleType("cv2"))
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        types.SimpleNamespace(PaddleOCR=FakePaddleOCR),
    )

    image_dimensions.PaddleImageDimensionRecognizer(profile_id="accurate")

    assert received_kwargs["text_detection_model_name"] == "PP-OCRv5_server_det"
    assert received_kwargs["text_recognition_model_name"] == "PP-OCRv5_server_rec"


def test_rotated_ocr_box_is_mapped_back_to_the_original_image_coordinates():
    clockwise = rotate_ocr_box_to_source(
        OcrTextBox("123", 0.91, (15, 20, 35, 50), angle=0),
        rotation="clockwise",
        source_width=100,
        source_height=60,
    )
    counterclockwise = rotate_ocr_box_to_source(
        OcrTextBox("123", 0.91, (15, 20, 35, 50), angle=0),
        rotation="counterclockwise",
        source_width=100,
        source_height=60,
    )

    assert clockwise.bbox == (20, 25, 50, 45)
    assert clockwise.angle == -90
    assert counterclockwise.bbox == (50, 15, 80, 35)
    assert counterclockwise.angle == 90


def test_fast_paddle_recognizer_scans_rotated_variants_for_vertical_text():
    class FakeImage:
        shape = (60, 100, 3)

    class FakeCv2:
        COLOR_BGR2GRAY = 1
        ROTATE_90_CLOCKWISE = 2
        ROTATE_90_COUNTERCLOCKWISE = 3

        @staticmethod
        def imread(_path):
            return FakeImage()

        @staticmethod
        def rotate(image, mode):
            return (image, mode)

        @staticmethod
        def cvtColor(image, _mode):
            return image

        @staticmethod
        def Canny(_image, _low, _high):
            return object()

        @staticmethod
        def HoughLinesP(*_args, **_kwargs):
            return None

    class FakeOcr:
        def predict(self, source):
            if source == "fixture.png":
                return []
            if isinstance(source, tuple) and source[1] == FakeCv2.ROTATE_90_CLOCKWISE:
                return [{
                    "res": {
                        "rec_texts": ["123"],
                        "rec_scores": [0.91],
                        "rec_polys": [[[15, 20], [35, 20], [35, 50], [15, 50]]],
                    }
                }]
            return []

    recognizer = object.__new__(image_dimensions.PaddleImageDimensionRecognizer)
    recognizer._cv2 = FakeCv2()
    recognizer._ocr = FakeOcr()
    recognizer.profile = types.SimpleNamespace(id="fast")

    boxes = recognizer.detect("fixture.png")

    assert boxes == [OcrTextBox("123", 0.91, (20, 25, 50, 45), "height", -90)]


def test_fast_paddle_recognizer_keeps_the_base_result_when_a_rotated_pass_fails():
    class FakeImage:
        shape = (60, 100, 3)

    class FakeCv2:
        COLOR_BGR2GRAY = 1
        ROTATE_90_CLOCKWISE = 2
        ROTATE_90_COUNTERCLOCKWISE = 3

        @staticmethod
        def imread(_path):
            return FakeImage()

        @staticmethod
        def rotate(image, mode):
            return (image, mode)

        @staticmethod
        def cvtColor(image, _mode):
            return image

        @staticmethod
        def Canny(_image, _low, _high):
            return object()

        @staticmethod
        def HoughLinesP(*_args, **_kwargs):
            return None

    class FakeOcr:
        def __init__(self):
            self.sources = []

        def predict(self, source):
            self.sources.append(source)
            if isinstance(source, tuple):
                raise RuntimeError("rotated input is unavailable")
            return [{
                "res": {
                    "rec_texts": ["123"],
                    "rec_scores": [0.91],
                    "rec_polys": [[[10, 10], [40, 10], [40, 30], [10, 30]]],
                }
            }]

    recognizer = object.__new__(image_dimensions.PaddleImageDimensionRecognizer)
    recognizer._cv2 = FakeCv2()
    recognizer._ocr = FakeOcr()
    recognizer.profile = types.SimpleNamespace(id="fast")

    boxes = recognizer.detect("fixture.png")

    assert [(box.text, box.bbox) for box in boxes] == [("123", (10, 10, 40, 30))]
    assert recognizer._ocr.sources == ["fixture.png"]


def test_fast_paddle_recognizer_retries_rotation_after_a_non_numeric_base_reading():
    class FakeImage:
        shape = (60, 100, 3)

    class FakeCv2:
        COLOR_BGR2GRAY = 1
        ROTATE_90_CLOCKWISE = 2
        ROTATE_90_COUNTERCLOCKWISE = 3

        @staticmethod
        def imread(_path):
            return FakeImage()

        @staticmethod
        def rotate(image, mode):
            return (image, mode)

        @staticmethod
        def cvtColor(image, _mode):
            return image

        @staticmethod
        def Canny(_image, _low, _high):
            return object()

        @staticmethod
        def HoughLinesP(*_args, **_kwargs):
            return None

    class FakeOcr:
        def __init__(self):
            self.sources = []

        def predict(self, source):
            self.sources.append(source)
            if source == "fixture.png":
                return [
                    {
                        "res": {
                            "rec_texts": ["-"],
                            "rec_scores": [0.0],
                            "rec_polys": [[[10, 10], [40, 10], [40, 30], [10, 30]]],
                        }
                    }
                ]
            if isinstance(source, tuple) and source[1] == FakeCv2.ROTATE_90_CLOCKWISE:
                return [
                    {
                        "res": {
                            "rec_texts": ["52,4"],
                            "rec_scores": [0.92],
                            "rec_polys": [[[15, 20], [35, 20], [35, 50], [15, 50]]],
                        }
                    }
                ]
            return []

    recognizer = object.__new__(image_dimensions.PaddleImageDimensionRecognizer)
    recognizer._cv2 = FakeCv2()
    recognizer._ocr = FakeOcr()
    recognizer.profile = types.SimpleNamespace(id="fast")

    boxes = recognizer.detect("fixture.png")

    assert [(box.text, box.bbox) for box in boxes] == [
        ("-", (10, 10, 40, 30)),
        ("52,4", (20, 25, 50, 45)),
    ]
    assert [source[1] for source in recognizer._ocr.sources[1:]] == [
        FakeCv2.ROTATE_90_CLOCKWISE,
        FakeCv2.ROTATE_90_COUNTERCLOCKWISE,
    ]


def test_accurate_paddle_recognizer_scans_both_rotations_for_a_tall_crop():
    class FakeImage:
        shape = (100, 60, 3)

    class FakeCv2:
        ROTATE_90_CLOCKWISE = 2
        ROTATE_90_COUNTERCLOCKWISE = 3

        @staticmethod
        def rotate(image, mode):
            return (image, mode)

    class FakeOcr:
        @staticmethod
        def predict(source):
            if isinstance(source, tuple) and source[1] == FakeCv2.ROTATE_90_COUNTERCLOCKWISE:
                return [
                    {
                        "res": {
                            "rec_texts": ["52,4"],
                            "rec_scores": [0.93],
                            "rec_polys": [[[10, 20], [35, 20], [35, 50], [10, 50]]],
                        }
                    }
                ]
            return []

    recognizer = object.__new__(image_dimensions.PaddleImageDimensionRecognizer)
    recognizer._cv2 = FakeCv2()
    recognizer._ocr = FakeOcr()
    recognizer.profile = types.SimpleNamespace(id="accurate")

    assert recognizer._rotated_boxes(FakeImage()) == [
        OcrTextBox("52,4", 0.93, (10, 10, 40, 35), angle=90)
    ]


def test_restore_lost_decimal_separator_preserves_the_decimal_in_154_5():
    components = [
        (0, 0, 6, 12, 72),
        (8, 0, 6, 12, 72),
        (16, 0, 6, 12, 72),
        (28, 0, 6, 12, 72),
        (24, 10, 2, 2, 4),
    ]

    assert image_dimensions._restore_lost_decimal_separator("1545", components) == "154,5"


def test_restore_lost_decimal_separator_keeps_four_digits_without_a_marker():
    components = [
        (0, 0, 6, 12, 72),
        (8, 0, 6, 12, 72),
        (16, 0, 6, 12, 72),
        (28, 0, 6, 12, 72),
    ]

    assert image_dimensions._restore_lost_decimal_separator("1545", components) == "1545"


def test_paddle_recognizer_restores_the_decimal_in_154_5_from_its_crop():
    class FakeCrop:
        shape = (20, 30, 3)

    class FakeImage:
        shape = (60, 100, 3)

        def __getitem__(self, _slice):
            return FakeCrop()

    class FakeCv2:
        COLOR_BGR2GRAY = 1
        INTER_CUBIC = 2
        THRESH_BINARY_INV = 4
        THRESH_OTSU = 8

        @staticmethod
        def imread(_path):
            return FakeImage()

        @staticmethod
        def cvtColor(image, _mode):
            return image

        @staticmethod
        def resize(image, _size, interpolation):
            assert interpolation == FakeCv2.INTER_CUBIC
            return image

        @staticmethod
        def threshold(_image, _low, _high, _mode):
            return None, object()

        @staticmethod
        def connectedComponentsWithStats(_binary, _connectivity):
            return (
                6,
                None,
                [
                    (0, 0, 0, 0, 0),
                    (0, 0, 6, 12, 72),
                    (8, 0, 6, 12, 72),
                    (16, 0, 6, 12, 72),
                    (28, 0, 6, 12, 72),
                    (24, 10, 2, 2, 4),
                ],
                None,
            )

        @staticmethod
        def Canny(_image, _low, _high):
            return object()

        @staticmethod
        def HoughLinesP(*_args, **_kwargs):
            return None

    class FakeOcr:
        @staticmethod
        def predict(source):
            if source == "fixture.png":
                return [
                    {
                        "res": {
                            "rec_texts": ["1545"],
                            "rec_scores": [1.0],
                            "rec_polys": [[[10, 10], [40, 10], [40, 30], [10, 30]]],
                        }
                    }
                ]
            return []

    recognizer = object.__new__(image_dimensions.PaddleImageDimensionRecognizer)
    recognizer._cv2 = FakeCv2()
    recognizer._ocr = FakeOcr()
    recognizer.profile = types.SimpleNamespace(id="fast")

    assert recognizer.detect("fixture.png")[0].text == "154,5"


def test_multi_profile_recognizer_combines_profiles_and_keeps_the_best_duplicate():
    """A regression in the profile runner must not silently use only fast OCR."""

    created_profiles: list[str] = []

    class ProfileRecognizer:
        def __init__(self, profile_id: str) -> None:
            created_profiles.append(profile_id)

        def detect(self, _path: str) -> list[OcrTextBox]:
            if created_profiles[-1] == "fast":
                return [
                    OcrTextBox("120 mm", 0.72, (4, 8, 80, 28)),
                    OcrTextBox("70 mm", 0.89, (90, 8, 160, 28)),
                ]
            return [
                OcrTextBox("120 mm", 0.96, (4, 8, 80, 28)),
                OcrTextBox("45 mm", 0.91, (170, 8, 240, 28)),
            ]

    recognizer = image_dimensions.MultiProfileImageDimensionRecognizer(
        ["fast", "accurate"],
        recognizer_factory=ProfileRecognizer,
    )

    boxes = recognizer.detect("fixture.png")

    assert created_profiles == ["fast", "accurate"]
    assert boxes == [
        OcrTextBox("120 mm", 0.96, (4, 8, 80, 28)),
        OcrTextBox("70 mm", 0.89, (90, 8, 160, 28)),
        OcrTextBox("45 mm", 0.91, (170, 8, 240, 28)),
    ]


def test_multi_profile_recognizer_keeps_distinct_text_at_the_same_position():
    """Different units are competing OCR readings, not duplicate boxes."""

    class ProfileRecognizer:
        def __init__(self, profile_id: str) -> None:
            self.profile_id = profile_id

        def detect(self, _path: str) -> list[OcrTextBox]:
            text = "120 mm" if self.profile_id == "fast" else "120 cm"
            return [OcrTextBox(text, 0.91, (4, 8, 80, 28))]

    recognizer = image_dimensions.MultiProfileImageDimensionRecognizer(
        ["fast", "accurate"],
        recognizer_factory=ProfileRecognizer,
    )

    assert recognizer.detect("fixture.png") == [
        OcrTextBox("120 mm", 0.91, (4, 8, 80, 28)),
        OcrTextBox("120 cm", 0.91, (4, 8, 80, 28)),
    ]


def test_resolves_decimal_comma_value_when_ocr_confidence_meets_threshold():
    recognizer = FakeRecognizer(
        [OcrTextBox("130,5 cm", 0.92, (0, 0, 80, 20), "width")]
    )

    values, warnings = resolve_image_dimensions(
        [ImageDimensionRequest("15", "width", 0.8)],
        {"15": "fixture.png"},
        recognizer=recognizer,
    )

    assert values == {"IMAGE_DIMENSION:15:WIDTH": "130.5"}
    assert warnings == []


def test_rejects_text_below_configured_confidence_threshold():
    recognizer = FakeRecognizer(
        [OcrTextBox("130,5", 0.74, (0, 0, 80, 20), "width")]
    )

    values, warnings = resolve_image_dimensions(
        [ImageDimensionRequest("15", "width", 0.8)],
        {"15": "fixture.png"},
        recognizer=recognizer,
    )

    assert values == {"IMAGE_DIMENSION:15:WIDTH": ""}
    assert warnings == [
        {
            "code": "image_dimension_low_confidence",
            "slot": "15",
            "message": "Odczyt 74% jest ponizej wymaganego progu 80%.",
        }
    ]


def test_reports_missing_slot_without_calling_ocr():
    recognizer = FakeRecognizer([])

    values, warnings = resolve_image_dimensions(
        [ImageDimensionRequest("15", "width", 0.8)],
        {},
        recognizer=recognizer,
    )

    assert values == {"IMAGE_DIMENSION:15:WIDTH": ""}
    assert warnings[0]["code"] == "image_dimension_missing_slot"
    assert recognizer.calls == 0


def test_template_resolution_confirms_ocr_attempt_when_no_dimension_was_assigned():
    values, warnings = resolve_image_dimensions(
        [ImageDimensionRequest("15", "height", 0.8)],
        {"15": "fixture.png"},
        recognizer=FakeRecognizer([OcrTextBox("80 cm", 0.99, (10, 10, 40, 40))]),
    )

    assert values == {"IMAGE_DIMENSION:15:HEIGHT": ""}
    assert warnings == [
        {
            "code": "image_dimension_not_found",
            "slot": "15",
            "message": (
                "OCR przeanalizowal 1 odczyt w slocie 15, ale nie przypisal zadnego do wysokosci."
            ),
        }
    ]


def test_uses_dimension_hint_to_select_height_value():
    recognizer = FakeRecognizer(
        [
            OcrTextBox("130,5", 0.92, (0, 0, 80, 20), "width"),
            OcrTextBox("85,8", 0.91, (90, 0, 160, 20), "height"),
        ]
    )

    values, warnings = resolve_image_dimensions(
        [ImageDimensionRequest("15", "height", 0.8)],
        {"15": "fixture.png"},
        recognizer=recognizer,
    )

    assert values == {"IMAGE_DIMENSION:15:HEIGHT": "85.8"}
    assert warnings == []


def test_uses_one_ocr_call_for_multiple_dimensions_from_one_slot():
    recognizer = FakeRecognizer(
        [
            OcrTextBox("130,5", 0.92, (0, 0, 80, 20), "width"),
            OcrTextBox("85,8", 0.91, (90, 0, 160, 20), "height"),
        ]
    )

    values, warnings = resolve_image_dimensions(
        [
            ImageDimensionRequest("15", "width", 0.8),
            ImageDimensionRequest("15", "height", 0.8),
        ],
        {"15": "fixture.png"},
        recognizer=recognizer,
    )

    assert values == {
        "IMAGE_DIMENSION:15:WIDTH": "130.5",
        "IMAGE_DIMENSION:15:HEIGHT": "85.8",
    }
    assert warnings == []
    assert recognizer.calls == 1


def test_associates_numeric_text_with_nearest_dimension_line_orientation():
    boxes = [
        OcrTextBox("130,5", 0.92, (40, 18, 100, 38)),
        OcrTextBox("85,8", 0.91, (180, 70, 220, 92)),
    ]
    lines = [
        DimensionLine(0, 45, 150, 45),
        DimensionLine(230, 0, 230, 160),
    ]

    associated = associate_dimension_hints(boxes, lines)

    assert associated[0].hint == "width"
    assert associated[1].hint == "height"


def test_associates_dimension_from_the_orientation_of_ocr_text_without_lines():
    boxes = [
        OcrTextBox("123,4", 0.99, (100, 30, 180, 50), angle=3),
        OcrTextBox("40", 0.98, (200, 50, 240, 80), angle=38),
        OcrTextBox("75,2", 0.99, (30, 100, 50, 180), angle=89),
    ]

    associated = associate_dimension_hints(boxes, [])

    assert [box.hint for box in associated] == ["width", "depth", "height"]


def test_associates_a_tall_dimension_label_as_height_when_ocr_angle_is_flat():
    box = OcrTextBox("52,4 cm", 0.65, (710, 180, 735, 300), angle=0)

    associated = associate_dimension_hints([box], [])

    assert associated[0].hint == "height"


def test_unit_labels_fall_back_to_box_shape_and_prefer_outer_dimensions():
    boxes = associate_dimension_hints(
        [
            OcrTextBox("75 cm", 0.99, (100, 20, 220, 48), angle=17),
            OcrTextBox("74 cm", 0.99, (120, 65, 235, 92), angle=17),
            OcrTextBox("36 cm", 0.99, (35, 35, 72, 72), angle=17),
            OcrTextBox("61 cm", 0.88, (700, 200, 728, 320), angle=17),
            OcrTextBox("44 cm", 0.94, (650, 220, 678, 315), angle=17),
        ],
        [],
    )

    result = analyze_image_dimensions(
        "fixture.png", minimum_text_confidence=0.8, recognizer=FakeRecognizer(boxes)
    )

    assert [box.hint for box in boxes] == ["width", "width", "depth", "height", "height"]
    assert result.dimensions == {"width": "75", "depth": "36", "height": "61"}


def test_unitless_dimension_labels_use_geometry_when_ocr_angle_is_uncertain():
    boxes = associate_dimension_hints(
        [
            OcrTextBox("80", 1.0, (400, 40, 480, 62), angle=17),
            OcrTextBox("80", 1.0, (125, 85, 165, 125), angle=45),
            OcrTextBox("78", 1.0, (690, 160, 712, 250), angle=73),
        ],
        [],
    )

    result = analyze_image_dimensions(
        "fixture.png", minimum_text_confidence=0.8, recognizer=FakeRecognizer(boxes)
    )

    assert [box.hint for box in boxes] == ["width", "depth", "height"]
    assert result.dimensions == {"width": "80", "depth": "80", "height": "78"}


def test_restores_decimal_separator_only_when_crop_has_a_small_middle_glyph():
    components = [
        (0, 1, 9, 18, 102),
        (11, 15, 3, 4, 10),
        (17, 1, 9, 18, 100),
    ]

    assert image_dimensions._restore_lost_decimal_separator("36", components) == "3,6"
    assert image_dimensions._restore_lost_decimal_separator("80", components[:1] + components[2:]) == "80"


def test_collects_glyphs_from_the_upscaled_ocr_crop():
    class FakeImage:
        shape = (40, 50, 3)

        def __getitem__(self, _slice):
            return self

    class FakeCv2:
        COLOR_BGR2GRAY = 1
        INTER_CUBIC = 2
        THRESH_BINARY_INV = 4
        THRESH_OTSU = 8

        @staticmethod
        def cvtColor(image, _mode):
            return image

        @staticmethod
        def resize(image, _size, interpolation):
            assert interpolation == 2
            return image

        @staticmethod
        def threshold(image, _threshold, _maximum, _mode):
            return 0, image

        @staticmethod
        def connectedComponentsWithStats(_image, _connectivity):
            return 4, None, [(0, 0, 1, 1, 0), (0, 1, 9, 18, 102), (11, 15, 3, 4, 10), (17, 1, 9, 18, 100)], None

    assert image_dimensions._text_components_from_crop(
        FakeImage(), (2, 3, 28, 24), FakeCv2()
    ) == [(0, 1, 9, 18, 102), (11, 15, 3, 4, 10), (17, 1, 9, 18, 100)]


def test_retries_a_low_confidence_unit_label_when_crop_recovers_missing_digit():
    class FakeCrop:
        shape = (80, 20, 3)

    class FakeImage:
        shape = (160, 160, 3)

        def __getitem__(self, _slice):
            return FakeCrop()

    class FakeCv2:
        ROTATE_90_CLOCKWISE = 1
        INTER_CUBIC = 2

        @staticmethod
        def rotate(image, _mode):
            return image

        @staticmethod
        def resize(image, _size, interpolation):
            assert interpolation == 2
            return image

    class FakeOcr:
        def predict(self, _image):
            return [
                {
                    "res": {
                        "rec_texts": ["73 cm"],
                        "rec_scores": [0.91],
                    }
                }
            ]

    original = OcrTextBox("3 cm", 0.76, (70, 20, 92, 120))

    recovered = image_dimensions._retry_low_confidence_dimension_label(
        original, FakeImage(), FakeCv2(), FakeOcr().predict
    )

    assert recovered.text == "73 cm"
    assert recovered.confidence == 0.91


def test_paddle_recognizer_uses_crop_retry_for_incomplete_unit_label():
    class FakeCrop:
        shape = (80, 20, 3)

    class FakeImage:
        shape = (160, 160, 3)

        def __getitem__(self, _slice):
            return FakeCrop()

    class FakeCv2:
        COLOR_BGR2GRAY = 1
        ROTATE_90_CLOCKWISE = 2
        INTER_CUBIC = 3

        @staticmethod
        def imread(_path):
            return FakeImage()

        @staticmethod
        def cvtColor(image, _mode):
            return image

        @staticmethod
        def rotate(image, _mode):
            return image

        @staticmethod
        def resize(image, _size, interpolation):
            assert interpolation == 3
            return image

        @staticmethod
        def Canny(_image, _low, _high):
            return object()

        @staticmethod
        def HoughLinesP(*_args, **_kwargs):
            return None

    class FakeOcr:
        def predict(self, source):
            if isinstance(source, str):
                return [
                    {
                        "res": {
                            "rec_texts": ["3 cm"],
                            "rec_scores": [0.76],
                            "rec_polys": [[[70, 20], [92, 20], [92, 120], [70, 120]]],
                        }
                    }
                ]
            return [{"res": {"rec_texts": ["73 cm"], "rec_scores": [0.91]}}]

    recognizer = object.__new__(image_dimensions.PaddleImageDimensionRecognizer)
    recognizer._cv2 = FakeCv2()
    recognizer._ocr = FakeOcr()

    boxes = recognizer.detect("fixture.png")

    assert boxes[0].text == "73 cm"
    assert boxes[0].confidence == 0.91


def test_paddle_recognizer_classifies_ocr_boxes_when_opencv_cannot_read_the_image():
    class FakeCv2:
        @staticmethod
        def imread(_path):
            return None

    class FakeOcr:
        @staticmethod
        def predict(_path):
            return [
                {
                    "res": {
                        "rec_texts": ["80 cm", "46 cm"],
                        "rec_scores": [0.99, 0.97],
                        "rec_polys": [
                            [[10, 20], [110, 20], [110, 45], [10, 45]],
                            [[30, 60], [52, 60], [52, 190], [30, 190]],
                        ],
                    }
                }
            ]

    recognizer = object.__new__(image_dimensions.PaddleImageDimensionRecognizer)
    recognizer._cv2 = FakeCv2()
    recognizer._ocr = FakeOcr()

    boxes = recognizer.detect("fixture.png")

    assert [(box.text, box.hint) for box in boxes] == [
        ("80 cm", "width"),
        ("46 cm", "height"),
    ]


def test_diagnostics_rejects_weight_and_prefers_a_dimension_with_units():
    recognizer = FakeRecognizer(
        [
            OcrTextBox("2 kg", 0.99, (100, 120, 150, 145), "width"),
            OcrTextBox("53,9 cm", 0.90, (20, 20, 180, 45), "width"),
        ]
    )

    result = analyze_image_dimensions(
        "fixture.png", minimum_text_confidence=0.8, recognizer=recognizer
    )

    assert result.dimensions["width"] == "53.9"
    assert result.candidates[0].accepted is False
    assert result.candidates[1].accepted is True


def test_diagnostics_classifies_boxes_and_applies_threshold():
    recognizer = FakeRecognizer(
        [
            OcrTextBox("130,5 cm", 0.91, (4, 8, 80, 28), "width"),
            OcrTextBox("40", 0.72, (90, 8, 120, 28), "depth"),
            OcrTextBox("tekst", 0.96, (130, 8, 180, 28)),
        ]
    )

    result = analyze_image_dimensions(
        "fixture.png", minimum_text_confidence=0.8, recognizer=recognizer
    )

    assert result.available is True
    assert result.dimensions == {"width": "130.5", "depth": "", "height": ""}
    assert result.candidates[0].accepted is True
    assert result.candidates[0].bbox == (4, 8, 80, 28)
    assert result.candidates[1].accepted is False
    assert result.candidates[1].dimension == "depth"
    assert result.candidates[2].value == ""


def test_value_diagnostics_keeps_every_numeric_ocr_box_without_dimension_assignment():
    result = analyze_image_values(
        "fixture.png",
        recognizer=FakeRecognizer(
            [
                OcrTextBox("120/140 mm", 0.91, (4, 8, 80, 28), "width"),
                OcrTextBox("tekst", 0.96, (90, 8, 120, 28)),
                OcrTextBox("120--140", 0.72, (130, 8, 180, 28), "height"),
            ]
        ),
    )

    assert result.available is True
    assert result.dimensions == {}
    assert [candidate.value for candidate in result.candidates] == ["120?140", "", "120??140"]
    assert [candidate.accepted for candidate in result.candidates] == [True, False, True]
    assert all(candidate.dimension is None for candidate in result.candidates)


def test_diagnostics_explains_unclassified_ocr_and_each_dimension_attempt():
    result = analyze_image_dimensions(
        "fixture.png",
        minimum_text_confidence=0.8,
        recognizer=FakeRecognizer(
            [OcrTextBox("80 cm", 0.99, (10, 10, 40, 40))]
        ),
    )

    assert result.dimensions == {"width": "", "depth": "", "height": ""}
    assert result.candidates[0].reason == (
        "Nie rozpoznano rodzaju wymiaru na podstawie orientacji tekstu ani linii wymiarowej."
    )
    assert result.attempts["width"] == (
        "OCR przeanalizowal 1 odczyt, ale nie przypisal zadnego do szerokosci."
    )
    assert result.attempts["height"] == (
        "OCR przeanalizowal 1 odczyt, ale nie przypisal zadnego do wysokosci."
    )


def test_diagnostics_always_selects_the_largest_value_for_one_dimension():
    result = analyze_image_dimensions(
        "fixture.png",
        minimum_text_confidence=0.8,
        recognizer=FakeRecognizer(
            [
                OcrTextBox("46 cm", 0.99, (10, 10, 30, 120), "height"),
                OcrTextBox("80", 0.81, (40, 10, 60, 140), "height"),
            ]
        ),
    )

    assert result.dimensions["height"] == "80"
    assert result.candidates[0].selected is False
    assert result.candidates[0].reason == (
        "Odrzucono: dla wysokosci wybrano wieksza wartosc 80."
    )
    assert result.candidates[1].selected is True
    assert result.attempts["height"] == "Wybrano 80 jako wysokosc."


def test_diagnostics_returns_a_message_instead_of_raising_when_ocr_is_broken():
    class BrokenRecognizer:
        def detect(self, _path: str) -> list[OcrTextBox]:
            raise RuntimeError("The pipeline (OCR) does not exist")

    result = analyze_image_dimensions("fixture.png", recognizer=BrokenRecognizer())

    assert result.available is False
    assert result.candidates == []
    assert "pipeline" in result.message


def test_diagnostics_keeps_the_ocr_unavailable_message():
    class UnavailableRecognizer:
        def detect(self, _path: str) -> list[OcrTextBox]:
            raise ImageDimensionUnavailable("Brak konfiguracji pipeline OCR.")

    result = analyze_image_dimensions("fixture.png", recognizer=UnavailableRecognizer())

    assert result.available is False
    assert result.message == "Brak konfiguracji pipeline OCR."


def test_template_resolution_returns_a_warning_when_ocr_initialization_crashes():
    class BrokenRecognizer:
        def detect(self, _path: str) -> list[OcrTextBox]:
            raise RuntimeError("The pipeline (OCR) does not exist")

    values, warnings = resolve_image_dimensions(
        [ImageDimensionRequest("15", "width", 0.8)],
        {"15": "fixture.png"},
        recognizer=BrokenRecognizer(),
    )

    assert values == {"IMAGE_DIMENSION:15:WIDTH": ""}
    assert warnings == [
        {
            "code": "ocr_unavailable",
            "slot": "15",
            "message": "Lokalny OCR jest niedostepny.",
        }
    ]


def test_ocr_runtime_info_has_stable_engine_and_github_metadata():
    info = image_ocr_runtime_info()

    assert info["engine"]["name"] == "PaddleOCR"
    assert info["github_url"].startswith("https://github.com/")
    assert isinstance(info["models"], list)
    assert info["models"][0]["version"] == "lang=en"


def test_ocr_runtime_info_accepts_the_opencv_contrib_runtime_used_by_the_exe(
    monkeypatch,
):
    versions = {
        "paddleocr": "3.7.0",
        "paddlepaddle": "3.3.1",
        "opencv-contrib-python": "4.10.0.84",
    }
    monkeypatch.setattr(
        image_dimensions,
        "_optional_package_version",
        lambda package: versions.get(package),
    )
    monkeypatch.setattr(image_dimensions.util, "find_spec", lambda _package: object())
    monkeypatch.setattr(
        image_dimensions, "_paddlex_ocr_pipeline_is_available", lambda: True
    )
    monkeypatch.setattr(
        image_dimensions, "_paddlex_ocr_core_is_available", lambda: True
    )

    info = image_ocr_runtime_info()

    assert info["available"] is True
    assert info["runtime"]["version"] == "3.3.1 / 4.10.0.84"


def test_ocr_runtime_info_uses_packaged_modules_when_pyinstaller_omits_metadata(
    monkeypatch,
):
    monkeypatch.setattr(
        image_dimensions, "_optional_package_version", lambda _package: None
    )
    monkeypatch.setattr(image_dimensions.util, "find_spec", lambda _package: object())
    monkeypatch.setattr(
        image_dimensions, "_paddlex_ocr_pipeline_is_available", lambda: True
    )
    monkeypatch.setattr(
        image_dimensions, "_paddlex_ocr_core_is_available", lambda: True
    )

    info = image_ocr_runtime_info()

    assert info["available"] is True


def test_ocr_runtime_info_does_not_treat_cache_control_directories_as_models(
    tmp_path, monkeypatch
):
    for name in ("func_ret", "locks", "temp"):
        (tmp_path / name).mkdir()
    package_root = tmp_path / "paddlex"
    pipeline_config = package_root / "configs" / "pipelines" / "OCR.yaml"
    pipeline_config.parent.mkdir(parents=True)
    pipeline_config.touch()
    package_origin = package_root / "__init__.py"
    package_origin.touch()
    monkeypatch.setattr(image_dimensions, "ocr_model_cache_path", lambda: str(tmp_path))
    monkeypatch.setattr(
        image_dimensions, "_optional_package_version", lambda _package: "1.0"
    )
    monkeypatch.setattr(
        image_dimensions.util,
        "find_spec",
        lambda package: type("Spec", (), {"origin": str(package_origin)})()
        if package == "paddlex"
        else object(),
    )
    monkeypatch.setattr(
        image_dimensions, "_paddlex_ocr_core_is_available", lambda: True
    )

    info = image_ocr_runtime_info()

    assert info["available"] is True
    assert info["models"][0]["id"] == "fast"
    assert info["models"][0]["status"] == "unavailable"


def test_ocr_runtime_info_marks_only_complete_offline_profiles_as_ready(
    tmp_path, monkeypatch
):
    """A generic Paddle cache must not advertise a missing selected profile."""
    profile_root = tmp_path / "official_models"
    (profile_root / "PP-OCRv5_mobile_det").mkdir(parents=True)
    (profile_root / "PP-OCRv5_mobile_rec").mkdir()
    for directory in profile_root.iterdir():
        (directory / "model.yml").touch()
    package_root = tmp_path / "paddlex"
    pipeline_config = package_root / "configs" / "pipelines" / "OCR.yaml"
    pipeline_config.parent.mkdir(parents=True)
    pipeline_config.touch()
    package_origin = package_root / "__init__.py"
    package_origin.touch()
    monkeypatch.setattr(image_dimensions, "ocr_model_cache_path", lambda: str(tmp_path))
    monkeypatch.setattr(image_dimensions, "_optional_package_version", lambda _package: "1.0")
    monkeypatch.setattr(
        image_dimensions.util,
        "find_spec",
        lambda package: type("Spec", (), {"origin": str(package_origin)})()
        if package == "paddlex"
        else object(),
    )
    monkeypatch.setattr(image_dimensions, "_paddlex_ocr_core_is_available", lambda: True)

    info = image_ocr_runtime_info()
    states = {model["id"]: model["status"] for model in info["models"]}

    assert states == {"fast": "ready", "accurate": "unavailable"}


def test_ocr_runtime_info_requires_the_paddlex_ocr_pipeline_configuration(
    tmp_path, monkeypatch
):
    package_root = tmp_path / "paddlex"
    package_root.mkdir()
    package_origin = package_root / "__init__.py"
    package_origin.touch()
    monkeypatch.setattr(
        image_dimensions, "_optional_package_version", lambda _package: "1.0"
    )
    monkeypatch.setattr(
        image_dimensions.util,
        "find_spec",
        lambda package: type("Spec", (), {"origin": str(package_origin)})()
        if package == "paddlex"
        else object(),
    )

    info = image_ocr_runtime_info()

    assert info["available"] is False


def test_ocr_runtime_info_requires_paddlex_ocr_core_dependencies(monkeypatch):
    monkeypatch.setattr(
        image_dimensions, "_optional_package_version", lambda _package: "1.0"
    )
    monkeypatch.setattr(image_dimensions.util, "find_spec", lambda _package: object())
    monkeypatch.setattr(
        image_dimensions, "_paddlex_ocr_pipeline_is_available", lambda: True
    )
    monkeypatch.setattr(
        image_dimensions,
        "_paddlex_ocr_core_is_available",
        lambda: False,
        raising=False,
    )

    info = image_ocr_runtime_info()

    assert info["available"] is False


def test_detects_embedded_ocr_model_cache_in_pyinstaller_bundle(tmp_path, monkeypatch):
    model_cache = tmp_path / "ocr_models"
    model_cache.mkdir()
    monkeypatch.setattr(image_dimensions.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert bundled_ocr_model_cache_path() == str(model_cache)


def test_uses_configured_local_model_cache_when_no_bundle_is_present(tmp_path, monkeypatch):
    monkeypatch.delattr(image_dimensions.sys, "_MEIPASS", raising=False)
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path))

    assert ocr_model_cache_path() == str(tmp_path)
