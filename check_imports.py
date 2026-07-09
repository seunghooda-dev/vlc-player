"""
check_imports.py — 모듈 간 import 정합성 자동 검증
실행: python check_imports.py
모듈 분리 후, 새 기능 추가 후 항상 실행하세요.
"""
import re, ast, sys, tempfile
from pathlib import Path

FILES = [
    'constants.py', 'db_models.py', 'threads.py',
    'meters.py', 'video_panel.py', 'right_panel.py', 'main.py'
]
MODULE_NAMES = set(f.replace('.py', '') for f in FILES)

def read_source(fname):
    return open(fname, encoding='utf-8').read()

def get_exports(fname):
    """__all__ 우선, 없으면 def/class/전역변수"""
    c = read_source(fname)
    m = re.search(r"__all__\s*=\s*\[([^\]]+)\]", c)
    if m:
        return set(re.findall(r"'([^']+)'", m.group(1)))
    tree = ast.parse(c)
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names

def check_cross_imports(exports):
    """각 파일의 from <local_module> import X 에서 X가 실제로 export되는지"""
    errors = []
    for fname in FILES:
        c = read_source(fname)
        tree = ast.parse(c)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            mod = node.module or ''
            if mod not in MODULE_NAMES:
                continue
            src_file = mod + '.py'
            available = exports.get(src_file, set())
            for alias in node.names:
                sym = alias.name
                if sym == '*':
                    continue
                if sym not in available:
                    errors.append(
                        f"  FAIL {fname} L{node.lineno}: "
                        f"'{sym}' not exported by {src_file}"
                    )
    return errors

def check_circular():
    deps = {}
    for fname in FILES:
        mod = fname.replace('.py', '')
        c = read_source(fname)
        deps[mod] = []
        tree = ast.parse(c)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                src = node.module or ''
                if src in MODULE_NAMES and src != mod and src not in deps[mod]:
                    deps[mod].append(src)

    def find_cycle(graph, start, path=None):
        if path is None: path = []
        if start in path:
            return path + [start]
        path = path + [start]
        for node in graph.get(start, []):
            result = find_cycle(graph, node, path)
            if result: return result
        return None

    cycles = []
    seen = set()
    for mod in MODULE_NAMES:
        c = find_cycle(deps, mod)
        if c:
            key = frozenset(c)
            if key not in seen:
                seen.add(key)
                cycles.append(' → '.join(c))
    return cycles

def check_syntax():
    errors = []
    for fname in FILES:
        try:
            ast.parse(read_source(fname))
        except SyntaxError as e:
            errors.append(f"  FAIL {fname} L{e.lineno}: {e.msg}")
    return errors

def check_core_logic():
    """UI를 띄우지 않고 방송 QC 핵심 판정만 회귀 검사."""
    errors = []
    try:
        from right_panel import RightPanel
        from constants import DEFAULT_SETTINGS, VIDEO_EXTS, _normalize_settings
        from db_models import frames_to_tc, is_df_fps, qc_summary_from_status, tc_to_frames
        from video_panel import AudioMixPlayer, DIRECT_VLC_EXTS, VideoPanel
    except Exception as e:
        return [f"  FAIL core logic import: {e}"]

    class Probe:
        vp = type('VP', (), {'cur_file': ''})()
        _file_path_text = staticmethod(lambda value: str(value or ''))
        _path_exists = staticmethod(lambda value: True)
        _file_status_badge = RightPanel._file_status_badge
        _is_standard_playback_resolution = staticmethod(RightPanel._is_standard_playback_resolution)
        _is_common_playback_fps = staticmethod(RightPanel._is_common_playback_fps)
        _is_ntsc_drop_frame_rate = staticmethod(RightPanel._is_ntsc_drop_frame_rate)

    class MissingFileProbe(Probe):
        _path_exists = staticmethod(lambda value: False)

    class FilterProbe(Probe):
        def __init__(self, key):
            self._filter_key = key

    try:
        status, issues = RightPanel._metadata_qc_summary(Probe(), {}, 'C:/sample/bad.mxf')
        if status != '확인 필요' or issues != ['메타데이터 확인 실패']:
            errors.append(f"  FAIL empty metadata summary: {status} / {issues}")

        base = {
            'filepath': 'C:/sample/good.mxf',
            'width': 1920,
            'height': 1080,
            'duration': 10,
            'channels': 2,
            'audio_stream_count': 1,
            'codec': 'MPEG2VIDEO',
            'timecode': '00:00:00:00',
        }

        status, issues = RightPanel._metadata_qc_summary(Probe(), dict(base, fps=30.0, df=False), '')
        if status != '정상' or issues:
            errors.append(f"  FAIL 30.000 NDF summary: {status} / {issues}")

        status, issues = RightPanel._metadata_qc_summary(
            Probe(),
            dict(base, fps=29.97, df=True, timecode='00:00:00;00'),
            '',
        )
        if status != '정상' or issues:
            errors.append(f"  FAIL 29.97 DF summary: {status} / {issues}")

        status, issues = RightPanel._metadata_qc_summary(Probe(), dict(base, fps=29.97, df=False), '')
        if 'DF 타임코드 아님' not in issues:
            errors.append(f"  FAIL 29.97 NDF detection: {status} / {issues}")

        qc_counts = RightPanel._batch_summary_counts(Probe(), [
            {'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
            {'black': 'ok', 'mute': 'ok', 'freeze': ''},
            {'black': 'found', 'mute': 'ok', 'freeze': 'found'},
            {'black': 'found', 'mute': 'found', 'freeze': ''},
            {'black': 'ok', 'mute': 'error', 'freeze': ''},
            {'black': '', 'mute': '', 'freeze': ''},
            {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
        ])
        expected_qc_counts = {
            'total': 7,
            'normal': 1,
            'partial_normal': 1,
            'black': 2,
            'mute': 1,
            'freeze': 1,
            'both': 2,
            'error': 1,
            'pending': 1,
            'missing': 1,
        }
        for key, expected in expected_qc_counts.items():
            if qc_counts.get(key) != expected:
                errors.append(f"  FAIL batch QC count {key}: {qc_counts.get(key)} != {expected}")
        status_summary = RightPanel._status_summary_text(Probe(), [
            {'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
            {'black': 'ok', 'mute': 'ok', 'freeze': ''},
            {'black': 'found', 'mute': 'found', 'freeze': ''},
            {'black': 'found', 'mute': 'ok', 'freeze': 'found'},
            {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
        ])
        if "정상 1" not in status_summary:
            errors.append(f"  FAIL status summary normal count: {status_summary}")
        if "블랙/무음 정상 1" not in status_summary:
            errors.append(f"  FAIL status summary black/mute normal count: {status_summary}")
        if "블랙/무음 1" not in status_summary:
            errors.append(f"  FAIL status summary black/mute count: {status_summary}")
        if "복합 문제 1" not in status_summary:
            errors.append(f"  FAIL status summary complex count: {status_summary}")
        if "파일 없음 1" not in status_summary:
            errors.append(f"  FAIL status summary missing-file count: {status_summary}")
        badge_cases = [
            ({'black': 'ok', 'mute': 'ok', 'freeze': ''}, '블랙/무음 정상', 'partial badge'),
            ({'black': 'ok', 'mute': 'ok', 'freeze': 'ok'}, '정상', 'normal badge'),
            ({'black': 'found', 'mute': 'ok', 'freeze': 'found'}, '블랙/프리즈 있음', 'multi issue badge'),
            ({'black': 'ok', 'mute': 'error', 'freeze': ''}, '검사 오류', 'error badge'),
            ({'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'}, '파일 없음', 'missing-file badge'),
        ]
        for file_state, expected, label in badge_cases:
            actual, _ = RightPanel._file_status_badge(Probe(), file_state)
            if actual != expected:
                errors.append(f"  FAIL {label}: {actual} != {expected}")
        filter_cases = [
            ('normal', {'black': 'ok', 'mute': 'ok', 'freeze': ''}, True, 'normal includes black/mute normal'),
            ('normal', {'black': 'ok', 'mute': 'ok', 'freeze': 'found'}, False, 'normal excludes freeze issue'),
            ('done', {'black': 'found', 'mute': 'ok', 'freeze': ''}, True, 'done includes black/mute completed'),
            ('done', {'black': 'ok', 'mute': '', 'freeze': ''}, False, 'done excludes mute pending'),
            ('pending', {'black': '', 'mute': '', 'freeze': ''}, True, 'pending includes untouched file'),
            ('pending', {'black': 'found', 'mute': '', 'freeze': ''}, True, 'pending includes partial analysis'),
            ('pending', {'black': 'ok', 'mute': 'ok', 'freeze': ''}, False, 'pending excludes completed black/mute'),
            ('pending', {'black': 'error', 'mute': 'ok', 'freeze': ''}, False, 'pending excludes completed error state'),
            ('issues', {'black': 'ok', 'mute': 'error', 'freeze': ''}, True, 'issues includes error'),
            ('issues', {'black': 'ok', 'mute': 'ok', 'freeze': ''}, False, 'issues excludes clean partial normal'),
            ('issues', {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'}, True, 'issues includes missing file'),
            ('freeze', {'black': 'ok', 'mute': 'ok', 'freeze': 'found'}, True, 'freeze filter includes freeze issue'),
            ('error', {'black': 'ok', 'mute': 'error', 'freeze': 'found'}, True, 'error filter includes any error'),
            ('error', {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'}, True, 'error filter includes missing file'),
            ('normal', {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'}, False, 'normal excludes missing file'),
            ('pending', {'filepath': 'C:/missing/file_not_available.mxf', 'black': '', 'mute': '', 'freeze': ''}, False, 'pending excludes missing file'),
        ]
        for key, file_state, expected, label in filter_cases:
            actual = RightPanel._file_matches_filter(FilterProbe(key), file_state)
            if actual is not expected:
                errors.append(f"  FAIL filter {label}: {actual} != {expected}")
        qc_summary_cases = [
            (qc_summary_from_status('ok', 'ok', ''), '블랙/무음 정상', 'black/mute ok without freeze'),
            (qc_summary_from_status('ok', 'ok', 'ok'), '정상', 'black/mute/freeze ok'),
            (qc_summary_from_status('found', 'ok', ''), '블랙 있음', 'black found'),
            (qc_summary_from_status('found', 'found', ''), '블랙/무음 있음', 'black+mute found'),
            (qc_summary_from_status('found', 'ok', 'found'), '블랙/프리즈 있음', 'black+freeze found'),
            (qc_summary_from_status('ok', 'error', 'found'), '검사 오류', 'error priority'),
        ]
        for actual, expected, label in qc_summary_cases:
            if actual != expected:
                errors.append(f"  FAIL QC summary {label}: {actual} != {expected}")
        report_summary = RightPanel._qc_summary_for_report(
            Probe(),
            {'black': 'found', 'mute': 'found', 'freeze': '', 'qc_summary': '미분석'},
            'fallback',
        )
        if report_summary != '블랙/무음 있음':
            errors.append(f"  FAIL report QC summary recompute: {report_summary}")
        partial_report_summary = RightPanel._qc_summary_for_report(
            Probe(),
            {'black': 'ok', 'mute': 'ok', 'freeze': '', 'qc_summary': '정상'},
            'fallback',
        )
        if partial_report_summary != '블랙/무음 정상':
            errors.append(f"  FAIL report partial QC summary: {partial_report_summary}")
        pending_report_summary = RightPanel._qc_summary_for_report(
            Probe(),
            {'black': '', 'mute': '', 'freeze': '', 'qc_summary': 'CUE'},
            'CUE',
        )
        if pending_report_summary != '미분석':
            errors.append(f"  FAIL report pending QC summary: {pending_report_summary}")
        missing_report_summary = RightPanel._qc_summary_for_report(
            Probe(),
            {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
            '정상',
        )
        if missing_report_summary != '파일 없음':
            errors.append(f"  FAIL report missing-file QC summary: {missing_report_summary}")
        if RightPanel._metadata_for_report(MissingFileProbe(), 'C:/missing/sample.mxf', 'sample.mxf') != ({}, ''):
            errors.append("  FAIL report metadata missing-file guard")

        class ReportIterProbe(Probe):
            _sort_key = 'name'
            _sort_asc = True
            def _file_records(self):
                return [
                    {'name': 'all-b.mxf', 'filepath': 'C:/all-b.mxf'},
                    {'name': 'all-a.mxf', 'filepath': 'C:/all-a.mxf'},
                ]

        all_report_names = [
            f.get('name') for f in RightPanel._iter_report_files(ReportIterProbe())
        ]
        if all_report_names != ['all-a.mxf', 'all-b.mxf']:
            errors.append(f"  FAIL report full-list sort: {all_report_names}")
        selected_report_names = [
            f.get('name') for f in RightPanel._iter_report_files(
                ReportIterProbe(),
                [{'name': 'selected-only.mxf', 'filepath': 'C:/selected-only.mxf'}],
            )
        ]
        if selected_report_names != ['selected-only.mxf']:
            errors.append(f"  FAIL selected report scope: {selected_report_names}")

        class FilteredReportProbe(Probe):
            _sort_key = 'name'
            _sort_asc = True
            _filter_key = 'issues'
            _iter_report_files = RightPanel._iter_report_files
            _file_matches_filter = RightPanel._file_matches_filter
            def _file_records(self):
                return [
                    {'name': 'clean.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': ''},
                    {'name': 'bad-b.mxf', 'black': 'ok', 'mute': 'found', 'freeze': ''},
                    {'name': 'bad-a.mxf', 'black': 'found', 'mute': 'ok', 'freeze': ''},
                ]

        filtered_report_names = [
            f.get('name') for f in RightPanel._filtered_file_records(FilteredReportProbe())
        ]
        if filtered_report_names != ['bad-a.mxf', 'bad-b.mxf']:
            errors.append(f"  FAIL filtered report scope: {filtered_report_names}")

        class SummaryCopyProbe:
            vp = type('VP', (), {'cur_file': ''})()

            def _file_path_text(self, value):
                return RightPanel._file_path_text(value)

            def _path_name(self, value, default='파일'):
                return RightPanel._path_name(value, default)

            def _qc_status_text(self, value, kind):
                return RightPanel._qc_status_text(self, value, kind)

            def _file_status_detail(self, f):
                return RightPanel._file_status_detail(self, f)

            def _ranges_report_text(self, ranges, limit=20):
                return RightPanel._ranges_report_text(self, ranges, limit)

            def _file_status_badge(self, f, is_cue=False):
                return qc_summary_from_status(f.get('black'), f.get('mute'), f.get('freeze')), '#fff'

        summary_text = RightPanel._qc_summary_clipboard_text(
            SummaryCopyProbe(),
            {
                'name': 'copy-me.mxf',
                'filepath': 'C:/qc/copy-me.mxf',
                'black': 'found',
                'mute': 'ok',
                'freeze': '',
                'black_count': 1,
                'mute_count': 0,
                'freeze_count': 0,
                'black_ranges': [{
                    'start': 1.0,
                    'end': 2.0,
                    'duration': 1.0,
                    'tc_start': '00:00:01;00',
                    'tc_end': '00:00:02;00',
                }],
            },
        )
        if '파일명: copy-me.mxf' not in summary_text or 'QC상태: 블랙 있음' not in summary_text:
            errors.append(f"  FAIL QC summary copy header: {summary_text}")
        if '상세: 블랙 있음 1 / 무음 정상 0 / 프리즈 미분석 0' not in summary_text:
            errors.append(f"  FAIL QC summary copy detail: {summary_text}")
        if '블랙구간: 00:00:01;00>00:00:02;00(1.000s)' not in summary_text:
            errors.append(f"  FAIL QC summary copy ranges: {summary_text}")
        if '경로: C:/qc/copy-me.mxf' not in summary_text:
            errors.append(f"  FAIL QC summary copy path: {summary_text}")

        class RemoveProbe(Probe):
            _is_video_file_path = staticmethod(RightPanel._is_video_file_path)
            _same_path_text = staticmethod(RightPanel._same_path_text)
            _path_name = staticmethod(RightPanel._path_name)
            _remove_file_records_by_paths = RightPanel._remove_file_records_by_paths
            _file_record_for_path = RightPanel._file_record_for_path

            def __init__(self):
                self.updated = 0
                self.vp = type('VP', (), {})()
                self.vp._files = [
                    {'filepath': 'C:/missing/remove_me.mxf', 'name': 'remove_me.mxf'},
                    {'filepath': 'C:/keep/keep_me.mxf', 'name': 'keep_me.mxf'},
                ]
                self.vp.cur_file = ''
                self.vp.cur_info = {}
                self.vp.cur_id = ''
                self.vp.refreshed = 0
                self.vp.ejected = 0
                self.vp._refresh_clip_list = lambda: setattr(self.vp, 'refreshed', self.vp.refreshed + 1)
                self.vp.eject_clip = lambda: setattr(self.vp, 'ejected', self.vp.ejected + 1)
                self.vp._remember_recent_file = lambda path: None

            def _update_explorer(self, info, clip_id):
                self.updated += 1

            def _file_records(self):
                return [f for f in self.vp._files if isinstance(f, dict) and f.get('filepath')]

            def _persist_relinked_qc(self, record):
                return None

        remove_probe = RemoveProbe()
        removed = RightPanel._remove_file_records_by_paths(remove_probe, ['C:/missing/remove_me.mxf'])
        if removed != 1 or len(remove_probe.vp._files) != 1:
            errors.append(f"  FAIL remove missing-file records: removed={removed} files={remove_probe.vp._files}")
        if remove_probe.vp.refreshed != 1 or remove_probe.updated != 1:
            errors.append("  FAIL remove missing-file records refresh path")

        remove_cue_probe = RemoveProbe()
        remove_cue_probe.vp.cur_file = 'C:/missing/remove_me.mxf'
        removed = RightPanel._remove_file_records_by_paths(remove_cue_probe, ['C:/missing/remove_me.mxf'])
        if removed != 1 or remove_cue_probe.vp.ejected != 1:
            errors.append("  FAIL remove current missing-file eject path")

        reset_probe = RemoveProbe()
        reset_probe.calls = []
        reset_probe.vp._files = [
            {
                'filepath': 'C:/sample/reset_me.mxf',
                'name': 'reset_me.mxf',
                'black': 'found',
                'mute': 'ok',
                'freeze': '',
            }
        ]
        reset_probe.vp._set_file_status = lambda filepath, **changes: reset_probe.calls.append((filepath, changes))
        if not RightPanel._has_qc_result(reset_probe, reset_probe.vp._files[0]):
            errors.append("  FAIL QC reset has-result detection")
        if RightPanel._has_qc_result(reset_probe, {'black': '', 'mute': '', 'freeze': ''}):
            errors.append("  FAIL QC reset empty-result detection")
        if not RightPanel._reset_file_qc(reset_probe, 'C:/sample/reset_me.mxf'):
            errors.append("  FAIL QC reset call result")
        if len(reset_probe.calls) != 1:
            errors.append(f"  FAIL QC reset call count: {len(reset_probe.calls)}")
        else:
            _, reset_changes = reset_probe.calls[0]
            for key in ('black', 'mute', 'freeze'):
                if reset_changes.get(key) != '':
                    errors.append(f"  FAIL QC reset status {key}: {reset_changes.get(key)!r}")
            for key in ('black_count', 'mute_count', 'freeze_count'):
                if reset_changes.get(key) != 0:
                    errors.append(f"  FAIL QC reset count {key}: {reset_changes.get(key)!r}")
            for key in ('black_ranges', 'mute_ranges', 'freeze_ranges'):
                if reset_changes.get(key) != []:
                    errors.append(f"  FAIL QC reset ranges {key}: {reset_changes.get(key)!r}")

        relink_probe = RemoveProbe()
        relink_probe.vp._files = [
            {
                'filepath': 'C:/missing/relink_me.mxf',
                'name': 'relink_me.mxf',
                'black': '',
                'mute': '',
                'freeze': '',
            }
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            relink_target = Path(tmp_dir) / 'relinked_target.mxf'
            relink_target.write_bytes(b'test')
            result = RightPanel._relink_file_record_path(
                relink_probe,
                'C:/missing/relink_me.mxf',
                str(relink_target),
            )
            record = relink_probe.vp._files[0]
            if result != 'relinked':
                errors.append(f"  FAIL relink missing-file result: {result}")
            if record.get('filepath') != str(relink_target) or record.get('name') != relink_target.name:
                errors.append(f"  FAIL relink missing-file target fields: {record}")
            if record.get('ext') != 'MXF' or record.get('size') != 4:
                errors.append(f"  FAIL relink missing-file metadata fields: {record}")
            if relink_probe.vp.refreshed != 1 or relink_probe.updated != 1:
                errors.append("  FAIL relink missing-file refresh path")

        duplicate_probe = RemoveProbe()
        with tempfile.TemporaryDirectory() as tmp_dir:
            duplicate_target = Path(tmp_dir) / 'already_listed.mxf'
            duplicate_target.write_bytes(b'test')
            duplicate_probe.vp._files = [
                {'filepath': 'C:/missing/relink_me.mxf', 'name': 'relink_me.mxf'},
                {'filepath': str(duplicate_target), 'name': 'already_listed.mxf'},
            ]
            result = RightPanel._relink_file_record_path(
                duplicate_probe,
                'C:/missing/relink_me.mxf',
                str(duplicate_target),
            )
            if result != 'duplicate-removed' or len(duplicate_probe.vp._files) != 1:
                errors.append(f"  FAIL relink duplicate handling: result={result} files={duplicate_probe.vp._files}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            existing_root = Path(tmp_dir)
            missing_nested = existing_root / 'missing' / 'child' / 'clip.mxf'
            resolved_dir = RightPanel._existing_dir_for_path(str(missing_nested))
            if resolved_dir != str(existing_root):
                errors.append(f"  FAIL existing dir fallback: {resolved_dir} != {existing_root}")
            exact_file = existing_root / 'clip.mxf'
            exact_file.write_bytes(b'test')
            resolved_dir = RightPanel._existing_dir_for_path(str(exact_file))
            if resolved_dir != str(existing_root):
                errors.append(f"  FAIL existing dir from file: {resolved_dir} != {existing_root}")

        if DEFAULT_SETTINGS.get('audio_channels') != [1, 2]:
            errors.append(f"  FAIL default audio channels: {DEFAULT_SETTINGS.get('audio_channels')}")
        normalized = _normalize_settings({'audio_channels': [1, 2, 9, 16, 2, 'bad']})
        if normalized.get('audio_channels') != [1, 2]:
            errors.append(f"  FAIL audio settings channel clamp: {normalized.get('audio_channels')}")
        damaged_settings = _normalize_settings({
            'volume': 250,
            'playback_rate': 9,
            'black_amount': 150,
            'black_threshold': 999,
            'mute_threshold': 12,
            'mute_duration': -5,
            'freeze_noise': -999,
            'freeze_duration': 0,
            'recent_files': [str(i) for i in range(60)],
            'recent_dirs': [str(i) for i in range(40)],
            'window_size': [1, 20000],
            'splitter_sizes': [0, 20000],
        })
        expected_settings = {
            'volume': 100,
            'playback_rate': 2.0,
            'black_amount': '100',
            'black_threshold': '255',
            'mute_threshold': '-50',
            'mute_duration': '0.1',
            'freeze_noise': '-120',
            'freeze_duration': '0.1',
            'window_size': [640, 10000],
            'splitter_sizes': [100, 10000],
        }
        for key, expected in expected_settings.items():
            if damaged_settings.get(key) != expected:
                errors.append(f"  FAIL settings clamp {key}: {damaged_settings.get(key)} != {expected}")
        if len(damaged_settings.get('recent_files', [])) != 50:
            errors.append(f"  FAIL recent_files limit: {len(damaged_settings.get('recent_files', []))}")
        if len(damaged_settings.get('recent_dirs', [])) != 30:
            errors.append(f"  FAIL recent_dirs limit: {len(damaged_settings.get('recent_dirs', []))}")

        audio_mix = AudioMixPlayer()
        audio_mix.set_channels([1, 2, 9, 16, 2, 'bad'])
        if audio_mix.channels != [1, 2]:
            errors.append(f"  FAIL audio mix channel clamp: {audio_mix.channels}")
        audio_mix.set_channels([8, 7])
        if audio_mix.channels != [8, 7]:
            errors.append(f"  FAIL audio mix channel upper bound: {audio_mix.channels}")
        hinted_layout = VideoPanel._provisional_audio_mix_layout({
            'metadata_hint': True,
            'audio_stream_count': 8,
            'channels': 8,
        })
        if hinted_layout != (8, 8):
            errors.append(f"  FAIL provisional hinted audio layout: {hinted_layout}")
        guessed_layout = VideoPanel._provisional_audio_mix_layout({
            'audio_stream_count': 8,
            'channels': 8,
        })
        if guessed_layout != (0, 0):
            errors.append(f"  FAIL provisional guessed audio layout: {guessed_layout}")

        required_video_exts = {'.mxf', '.mp4'}
        missing_video_exts = sorted(required_video_exts - set(VIDEO_EXTS))
        if missing_video_exts:
            errors.append(f"  FAIL required video extensions missing: {missing_video_exts}")
        missing_direct_exts = sorted(required_video_exts - set(DIRECT_VLC_EXTS))
        if missing_direct_exts:
            errors.append(f"  FAIL direct VLC extensions missing: {missing_direct_exts}")
        extra_direct_exts = sorted(set(DIRECT_VLC_EXTS) - set(VIDEO_EXTS))
        if extra_direct_exts:
            errors.append(f"  FAIL direct VLC extensions not supported: {extra_direct_exts}")
        malformed_exts = sorted(
            ext for ext in set(VIDEO_EXTS) | set(DIRECT_VLC_EXTS)
            if not isinstance(ext, str) or not ext.startswith('.') or ext != ext.lower()
        )
        if malformed_exts:
            errors.append(f"  FAIL malformed video extensions: {malformed_exts}")

        if not is_df_fps(30000 / 1001) or is_df_fps(30.0):
            errors.append("  FAIL 29.97 DF fps detection")
        if not is_df_fps(60000 / 1001) or is_df_fps(60.0):
            errors.append("  FAIL 59.94 DF fps detection")
        tc_cases = [
            (frames_to_tc(1800, 29.97, True), '00:01:00;02', '29.97 DF one minute'),
            (frames_to_tc(17982, 29.97, True), '00:10:00;00', '29.97 DF ten minutes'),
            (frames_to_tc(1800, 30.0, False), '00:01:00:00', '30.0 NDF one minute'),
            (frames_to_tc(3600, 59.94, True), '00:01:00;04', '59.94 DF one minute'),
            (frames_to_tc(35964, 59.94, True), '00:10:00;00', '59.94 DF ten minutes'),
        ]
        for actual, expected, label in tc_cases:
            if actual != expected:
                errors.append(f"  FAIL {label}: {actual} != {expected}")
        frame_cases = [
            (tc_to_frames('00:01:00;02', 29.97, True), 1800, '29.97 DF tc reverse'),
            (tc_to_frames('00:10:00;00', 29.97, True), 17982, '29.97 DF ten minute reverse'),
            (tc_to_frames('00:01:00:00', 30.0, False), 1800, '30.0 NDF tc reverse'),
            (tc_to_frames('00:01:00;04', 59.94, True), 3600, '59.94 DF tc reverse'),
            (tc_to_frames('00:10:00;00', 59.94, True), 35964, '59.94 DF ten minute reverse'),
        ]
        for actual, expected, label in frame_cases:
            if actual != expected:
                errors.append(f"  FAIL {label}: {actual} != {expected}")
    except Exception as e:
        errors.append(f"  FAIL core logic check: {e}")
    return errors

def main():
    print("=" * 55)
    print("  MXF QC Player - Import consistency check")
    print("=" * 55)
    all_ok = True

    print("\n[1] 문법 검사")
    syntax_errors = check_syntax()
    if syntax_errors:
        all_ok = False
        for e in syntax_errors: print(e)
    else:
        for f in FILES:
            n = len(read_source(f).splitlines())
            print(f"  OK {f} ({n} lines)")

    print("\n[2] 순환 import 검사")
    cycles = check_circular()
    if cycles:
        all_ok = False
        for c in cycles: print(f"  FAIL circular import: {c}")
    else:
        print("  OK no circular imports")

    print("\n[3] 모듈 간 심볼 정합성")
    exports = {f: get_exports(f) for f in FILES}
    errors = check_cross_imports(exports)
    if errors:
        all_ok = False
        for e in errors: print(e)
    else:
        print("  OK all imported symbols exist")

    print("\n[4] 핵심 QC 로직 회귀 검사")
    logic_errors = check_core_logic()
    if logic_errors:
        all_ok = False
        for e in logic_errors: print(e)
    else:
        print("  OK metadata QC, settings, audio channel, video extension, and timecode rules")

    print()
    print("=" * 55)
    if all_ok:
        print("  OK all checks passed")
    else:
        print("  FAIL issues found; fix and rerun")
    print("=" * 55)
    return 0 if all_ok else 1

if __name__ == '__main__':
    sys.exit(main())
