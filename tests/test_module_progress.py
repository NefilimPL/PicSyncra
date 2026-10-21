from picsyncra.installation.module_progress import DownloadProgress


def test_progress_reports_speed_eta_and_retains_module_byte_counts():
    times = iter([10, 12, 14])
    tracker = DownloadProgress(clock=lambda: next(times))
    first = tracker.update(dict(downloaded_bytes=0, total_bytes=100, module_id='ocr_models'))
    assert first['bytes_per_second'] == 0 and first['eta_seconds'] is None
    next_value = tracker.update(dict(downloaded_bytes=40, total_bytes=100, module_id='ocr_models', module_downloaded_bytes=40, module_total_bytes=80))
    assert next_value['bytes_per_second'] == 20 and next_value['eta_seconds'] == 3
    assert next_value['module_total_bytes'] == 80


def test_progress_never_reports_negative_speed_during_a_file_retry():
    times = iter([0, 1, 2])
    tracker = DownloadProgress(clock=lambda: next(times))
    tracker.update(dict(downloaded_bytes=0, total_bytes=100))
    assert tracker.update(dict(downloaded_bytes=50, total_bytes=100))['bytes_per_second'] == 50
    retry = tracker.update(dict(downloaded_bytes=0, total_bytes=100))
    assert retry['bytes_per_second'] == 0 and retry['eta_seconds'] is None
