"""Durable waiting forms, including copies of session-scoped image inputs."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from uuid import uuid4

from .process_models import ProcessFormSnapshot, QueuedUploadFile
from ..installation.module_filesystem import atomic_json, safe_path


def save_pending(job, root, *, resolve_token, state='queued'):
    form = job['form']
    directory = safe_path(root, Path(form.temp_dir).relative_to(root).as_posix())
    tokens = {}
    for key, value in form.fields.items():
        if not value:
            continue
        if key.startswith('existing_slot_') and not key.startswith(('existing_slot_name_', 'existing_slot_preprocessed_')):
            source = Path(resolve_token(value))
            target = safe_path(directory, uuid4().hex + source.suffix)
            shutil.copyfile(source, target)
            tokens[key] = dict(path=target.name, staged=True, original=str(source))
            form.trusted_paths[key] = str(target)
            form.source_paths[key] = str(source)
        elif key.startswith('delete_local_slot_'):
            tokens[key] = dict(path=resolve_token(value, require_exists=False), staged=False)
            form.trusted_paths[key] = tokens[key]['path']
    payload = {key: job[key] for key in ('id', 'username', 'cache_scope', 'created_at', 'created_time')}
    payload.update(state=state, fields=form.fields, tokens=tokens,
                   uploads={key: dict(path=Path(value.path).relative_to(directory).as_posix(), filename=value.filename)
                            for key, value in form.uploads.items()})
    atomic_json(safe_path(directory, 'pending.json'), payload, replace=True)


def load_pending(root, *, issue_token, validate_original):
    root = Path(root)
    if not root.exists():
        return
    for candidate in sorted(root.glob('job-*/pending.json'), key=lambda p: p.stat().st_mtime):
        path = safe_path(root, candidate.relative_to(root).as_posix())
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload['state'] != 'queued':
            # A killed running job may already have committed external writes.
            # Never replay it automatically.
            continue
        fields = dict(payload['fields'])
        trusted_paths = {}
        source_paths = {}
        for key, value in payload['tokens'].items():
            target = safe_path(path.parent, value['path']) if value['staged'] else validate_original(value['path'])
            fields[key] = issue_token(str(target))
            trusted_paths[key] = str(target)
            if value.get('original'):
                source_paths[key] = str(validate_original(value['original']))
        uploads = {key: QueuedUploadFile(str(safe_path(path.parent, value['path'])), value['filename'])
                   for key, value in payload['uploads'].items()}
        payload['form'] = ProcessFormSnapshot(fields, uploads, str(path.parent), trusted_paths, source_paths)
        yield payload


def mark_started(form):
    mark_state(form, 'running')


def mark_state(form, state):
    path = safe_path(form.temp_dir, 'pending.json')
    if path.exists():
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['state'] = state
        atomic_json(path, payload, replace=True)
