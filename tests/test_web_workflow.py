"""Tests for the LAN web upload workflow."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from picsyncra.web_workflow import (
    Image,
    WebProductForm,
    WebUploadedSlot,
    WebProcessingOptions,
    _slot_category,
    processing_options_from_config,
    preprocess_cached_upload,
    process_web_uploads,
    slot_definitions_from_config,
    normalized_product_payload,
    validate_product_form,
)
from picsyncra.workflow_utils import build_product_directory, build_slot_filename


class WebWorkflowTests(unittest.TestCase):
    def _make_image(self, path: Path) -> None:
        if Image is None:
            self.skipTest("Pillow is not available")
        Image.new("RGB", (16, 16), "white").save(path)

    def test_process_web_uploads_saves_file_with_desktop_style_name(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.pdf"
            source.write_bytes(b"%PDF-1.4\n")
            output_root = Path(temp_dir) / "processed"

            result = process_web_uploads(
                base_output_dir=str(output_root),
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    color2="dab artisan",
                    extra="led_rgb",
                    ean="5901234567890",
                ),
                uploaded_slots=[
                    WebUploadedSlot(
                        prefix="03",
                        label="DETAIL_pic",
                        source_path=str(source),
                        original_filename="front.pdf",
                    )
                ],
            )

            self.assertEqual(result.ean, "5901234567890")
            self.assertEqual(len(result.saved_files), 1)
            saved = result.saved_files[0]
            self.assertEqual(
                saved.filename,
                "5901234567890_03_DETAIL_MAGGIORE_KOMODA_MA03_BIALY_DAB ARTISAN_LED-RGB.pdf",
            )
            self.assertTrue(Path(saved.path).is_file())
            self.assertTrue(str(saved.path).startswith(str(output_root)))

    def test_process_web_uploads_rejects_non_image_non_pdf(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.txt"
            source.write_text("not an image", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Dozwolone sa pliki graficzne oraz PDF"):
                process_web_uploads(
                    base_output_dir=str(Path(temp_dir) / "processed"),
                    form=WebProductForm(
                        name="Maggiore",
                        type_name="komoda",
                        model="MA03",
                        color1="bialy",
                        ean="5901234567890",
                    ),
                    uploaded_slots=[
                        WebUploadedSlot(
                            prefix="03",
                            label="DETAIL_pic",
                            source_path=str(source),
                            original_filename="front.txt",
                        )
                    ],
                )

    def test_process_web_uploads_accepts_avif_allowed_by_web_security_defaults(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.avif"
            source.write_bytes(b"avif-payload")

            result = process_web_uploads(
                base_output_dir=str(Path(temp_dir) / "processed"),
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    ean="5901234567890",
                ),
                uploaded_slots=[
                    WebUploadedSlot(
                        prefix="03",
                        label="DETAIL_pic",
                        source_path=str(source),
                        original_filename="front.avif",
                    )
                ],
            )

            self.assertEqual(result.saved_files[0].operation, "copy_unsupported_image")
            self.assertTrue(result.saved_files[0].filename.endswith(".avif"))

    def test_process_web_uploads_accepts_jfif_as_jpeg_alias(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source_jpg = Path(temp_dir) / "source.jpg"
            source = Path(temp_dir) / "source.jfif"
            self._make_image(source_jpg)
            source_jpg.rename(source)

            result = process_web_uploads(
                base_output_dir=str(Path(temp_dir) / "processed"),
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    ean="5901234567890",
                ),
                uploaded_slots=[
                    WebUploadedSlot(
                        prefix="03",
                        label="DETAIL_pic",
                        source_path=str(source),
                        original_filename="front.jfif",
                    )
                ],
                options=WebProcessingOptions(resize_enabled=False),
            )

            self.assertEqual(result.saved_files[0].operation, "process_image")
            self.assertTrue(result.saved_files[0].filename.endswith(".jpg"))

    def test_process_web_uploads_accepts_additional_image_aliases_and_variants(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        aliases = {"jpe": "jpg", "peg": "jpg"}
        passthrough = (
            "apng",
            "dib",
            "avifs",
            "heic",
            "heif",
            "hif",
            "jp2",
            "j2k",
            "jpc",
            "jpx",
            "ico",
            "cur",
            "tga",
            "ppm",
            "pgm",
            "pbm",
            "pnm",
            "pcx",
        )
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            for extension, saved_extension in [*aliases.items(), *((ext, ext) for ext in passthrough)]:
                with self.subTest(extension=extension):
                    source = Path(temp_dir) / f"source.{extension}"
                    if extension in aliases:
                        source_jpg = Path(temp_dir) / f"source-{extension}.jpg"
                        self._make_image(source_jpg)
                        source_jpg.rename(source)
                    else:
                        source.write_bytes(b"image-payload")

                    result = process_web_uploads(
                        base_output_dir=str(Path(temp_dir) / f"processed-{extension}"),
                        form=WebProductForm(
                            name="Maggiore",
                            type_name="komoda",
                            model="MA03",
                            color1="bialy",
                            ean="5901234567890",
                        ),
                        uploaded_slots=[
                            WebUploadedSlot(
                                prefix="03",
                                label="DETAIL_pic",
                                source_path=str(source),
                                original_filename=f"front.{extension}",
                            )
                        ],
                        options=WebProcessingOptions(resize_enabled=False),
                    )

                    self.assertTrue(result.saved_files[0].filename.endswith(f".{saved_extension}"))

    def test_process_web_uploads_accepts_default_graphic_passthrough_extensions(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            for extension in ("psd", "eps", "ai"):
                with self.subTest(extension=extension):
                    source = Path(temp_dir) / f"source.{extension}"
                    source.write_bytes(b"graphic-payload")

                    result = process_web_uploads(
                        base_output_dir=str(Path(temp_dir) / f"processed-{extension}"),
                        form=WebProductForm(
                            name="Maggiore",
                            type_name="komoda",
                            model="MA03",
                            color1="bialy",
                            ean="5901234567890",
                        ),
                        uploaded_slots=[
                            WebUploadedSlot(
                                prefix="03",
                                label="DETAIL_pic",
                                source_path=str(source),
                                original_filename=f"front.{extension}",
                            )
                        ],
                    )

                    saved = result.saved_files[0]
                    self.assertEqual(saved.operation, "copy_document")
                    self.assertTrue(saved.filename.endswith(f".{extension}"))

    def test_process_web_uploads_uses_filename_label_independent_from_display_label(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.pdf"
            source.write_bytes(b"%PDF-1.4\n")

            result = process_web_uploads(
                base_output_dir=str(Path(temp_dir) / "processed"),
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    ean="5901234567890",
                ),
                uploaded_slots=[
                    WebUploadedSlot(
                        prefix="03",
                        label="Front web",
                        filename_label="Front-2",
                        source_path=str(source),
                        original_filename="front.pdf",
                    )
                ],
            )

            saved = result.saved_files[0]
            self.assertEqual(saved.label, "Front web")
            self.assertEqual(saved.filename_label, "Front-2")
            self.assertIn("_03_FRONT-2_", saved.filename)
            self.assertNotIn("FRONT WEB", saved.filename)

    def test_process_web_uploads_normalizes_common_jpeg_extension_typo(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source_jpg = Path(temp_dir) / "source.jpg"
            source = Path(temp_dir) / "source.peg"
            self._make_image(source_jpg)
            source_jpg.rename(source)

            result = process_web_uploads(
                base_output_dir=str(Path(temp_dir) / "processed"),
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    ean="5901234567890",
                ),
                uploaded_slots=[
                    WebUploadedSlot(
                        prefix="03",
                        label="DETAIL_pic",
                        source_path=str(source),
                        original_filename="front.peg",
                    )
                ],
                options=WebProcessingOptions(resize_enabled=False),
            )

            self.assertTrue(result.saved_files[0].filename.endswith(".jpg"))

    def test_validate_product_form_rejects_invalid_ean(self) -> None:
        errors = validate_product_form(
            WebProductForm(
                name="Name",
                type_name="Type",
                model="Model",
                color1="Color",
                ean="123",
            )
        )
        self.assertIn("EAN musi miec 13 cyfr albo zostac pusty.", errors)

    def test_process_web_uploads_removes_exif_without_optional_processing(self) -> None:
        if Image is None:
            self.skipTest("Pillow is not available")
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.jpg"
            exif = Image.Exif()
            exif[0x010E] = "private description"
            Image.new("RGB", (24, 16), "white").save(source, format="JPEG", exif=exif)

            result = process_web_uploads(
                base_output_dir=str(Path(temp_dir) / "processed"),
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    ean="5901234567890",
                ),
                uploaded_slots=[
                    WebUploadedSlot(
                        prefix="03",
                        label="DETAIL_pic",
                        source_path=str(source),
                        original_filename="front.jpg",
                    )
                ],
                options=WebProcessingOptions(resize_enabled=False),
            )

            with Image.open(result.saved_files[0].path) as saved:
                self.assertEqual(dict(saved.getexif()), {})

    def test_validation_uses_custom_required_labels_and_ignores_disabled_fields(
        self,
    ) -> None:
        settings = {
            "name": {
                "label": "Kolekcja",
                "enabled": True,
                "required": True,
            },
            "type": {"enabled": False, "required": True},
            "model": {"enabled": True, "required": False},
            "color1": {"enabled": False, "required": True},
        }
        form = WebProductForm(
            name="",
            type_name="KOMODA",
            model="",
            color1="BIALY",
        )

        self.assertEqual(
            validate_product_form(form, settings),
            ["Pole „Kolekcja” jest wymagane."],
        )
        payload = normalized_product_payload(form, settings)
        self.assertEqual(payload["type_name"], "")
        self.assertEqual(payload["colors"], ["", "", ""])

    def test_disabled_ean_skips_format_validation(self) -> None:
        settings = {"ean": {"enabled": False, "required": True}}
        form = WebProductForm(
            name="N",
            type_name="T",
            model="M",
            color1="C",
            ean="123",
        )

        self.assertEqual(validate_product_form(form, settings), [])
        self.assertEqual(
            normalized_product_payload(form, settings)["ean"],
            "BRAK-EAN",
        )

    def test_process_web_uploads_allows_empty_change_when_requested(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            result = process_web_uploads(
                base_output_dir=str(Path(temp_dir) / "processed"),
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    ean="5901234567890",
                ),
                uploaded_slots=[],
                allow_empty=True,
            )

            self.assertEqual(result.ean, "5901234567890")
            self.assertEqual(result.saved_files, [])
            self.assertTrue(Path(result.output_dir).is_dir())

    def test_process_web_uploads_allows_existing_file_at_target_path(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            output_root = Path(temp_dir) / "processed"
            form = WebProductForm(
                name="Maggiore",
                type_name="komoda",
                model="MA03",
                color1="bialy",
                extra="NO-LED",
                ean="5901234567890",
            )
            payload = normalized_product_payload(form)
            output_dir = build_product_directory(
                str(output_root),
                payload["name"],
                payload["type_name"],
                payload["model"],
                payload["colors"],
                payload["extra"],
            )
            filename = build_slot_filename(
                payload["ean"],
                "03",
                _slot_category("DETAIL_pic"),
                payload["name"],
                payload["type_name"],
                payload["model"],
                payload["colors"],
                payload["extra"],
                ".pdf",
            )
            source = Path(output_dir) / filename
            source.parent.mkdir(parents=True)
            source.write_bytes(b"%PDF-1.4\n")

            result = process_web_uploads(
                base_output_dir=str(output_root),
                form=form,
                uploaded_slots=[
                    WebUploadedSlot(
                        prefix="03",
                        label="DETAIL_pic",
                        source_path=str(source),
                        original_filename=filename,
                    )
                ],
            )

            self.assertEqual(result.saved_files[0].path, str(source))
            self.assertEqual(source.read_bytes(), b"%PDF-1.4\n")

    def test_process_web_uploads_rejects_empty_change_by_default(self) -> None:
        with self.assertRaises(ValueError):
            process_web_uploads(
                base_output_dir="processed",
                form=WebProductForm(
                    name="Maggiore",
                    type_name="komoda",
                    model="MA03",
                    color1="bialy",
                    ean="5901234567890",
                ),
                uploaded_slots=[],
            )

    def test_process_web_uploads_uses_global_fit_as_default(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.png"
            self._make_image(source)

            with patch(
                "picsyncra.image_pipeline.fit_image_to_content",
                side_effect=lambda image: image,
            ) as fit:
                process_web_uploads(
                    base_output_dir=str(Path(temp_dir) / "processed"),
                    form=WebProductForm(
                        name="Maggiore",
                        type_name="komoda",
                        model="MA03",
                        color1="bialy",
                        ean="5901234567890",
                    ),
                    uploaded_slots=[
                        WebUploadedSlot(
                            prefix="03",
                            label="DETAIL_pic",
                            source_path=str(source),
                            original_filename="front.png",
                        )
                    ],
                    options=WebProcessingOptions(
                        resize_enabled=False,
                        auto_content_fit=True,
                    ),
                )

            fit.assert_called_once()

    def test_process_web_uploads_allows_fit_override_false(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.png"
            self._make_image(source)

            with patch(
                "picsyncra.image_pipeline.fit_image_to_content",
                side_effect=lambda image: image,
            ) as fit:
                process_web_uploads(
                    base_output_dir=str(Path(temp_dir) / "processed"),
                    form=WebProductForm(
                        name="Maggiore",
                        type_name="komoda",
                        model="MA03",
                        color1="bialy",
                        ean="5901234567890",
                    ),
                    uploaded_slots=[
                        WebUploadedSlot(
                            prefix="03",
                            label="DETAIL_pic",
                            source_path=str(source),
                            original_filename="front.png",
                            content_fit=False,
                        )
                    ],
                    options=WebProcessingOptions(
                        resize_enabled=False,
                        auto_content_fit=True,
                    ),
                )

            fit.assert_not_called()

    def test_processing_options_from_config_uses_web_processing_settings(self) -> None:
        options = processing_options_from_config(
            {
                "processing": {
                    "resize_enabled": False,
                    "max_dim": 1200,
                    "compress_enabled": True,
                    "compress_quality": 72,
                    "max_size_enabled": True,
                    "max_file_kb": 250,
                    "convert_enabled": True,
                    "target_format": "WEBP",
                },
                "auto_content_fit": True,
            }
        )

        self.assertFalse(options.resize_enabled)
        self.assertEqual(options.max_dim, 1200)
        self.assertTrue(options.compress_enabled)
        self.assertEqual(options.compress_quality, 72)
        self.assertTrue(options.max_size_enabled)
        self.assertEqual(options.max_file_kb, 250)
        self.assertTrue(options.convert_enabled)
        self.assertEqual(options.target_format, "WEBP")
        self.assertTrue(options.auto_content_fit)

    def test_preprocessed_upload_is_copied_without_second_resize(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "source.jpg"
            output_root = Path(temp_dir) / "processed"
            self._make_image(source)

            with patch("picsyncra.web_workflow.Image.open") as image_open:
                result = process_web_uploads(
                    base_output_dir=str(output_root),
                    form=WebProductForm(
                        name="Maggiore",
                        type_name="komoda",
                        model="MA03",
                        color1="bialy",
                        ean="5901234567890",
                    ),
                    uploaded_slots=[
                        WebUploadedSlot(
                            prefix="03",
                            label="DETAIL_pic",
                            source_path=str(source),
                            original_filename="front.jpg",
                            preprocessed=True,
                        )
                    ],
                    options=WebProcessingOptions(resize_enabled=True),
                )

            image_open.assert_not_called()
            self.assertTrue(Path(result.saved_files[0].path).is_file())
            self.assertEqual(result.saved_files[0].operation, "copy_preprocessed")
            self.assertTrue(result.saved_files[0].preprocessed)
            self.assertGreaterEqual(result.saved_files[0].elapsed_ms, 0)

    def test_preprocess_cached_upload_converts_cache_file_once(self) -> None:
        if Image is None:
            self.skipTest("Pillow is not available")
        workspace_tmp = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as temp_dir:
            source = Path(temp_dir) / "cache.jpg"
            self._make_image(source)

            path, name, processed = preprocess_cached_upload(
                str(source),
                "front.jpg",
                WebProcessingOptions(
                    resize_enabled=False,
                    convert_enabled=True,
                    target_format="PNG",
                ),
            )

            self.assertTrue(processed)
            self.assertTrue(path.endswith(".png"))
            self.assertEqual(name, "front.png")
            self.assertFalse(source.exists())
            self.assertTrue(Path(path).is_file())

    def test_slot_definitions_from_config_uses_defaults_when_missing(self) -> None:
        slots = slot_definitions_from_config({})

        self.assertGreaterEqual(len(slots), 1)
        self.assertEqual(slots[0]["prefix"], "01")


if __name__ == "__main__":
    unittest.main()
