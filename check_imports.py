"""
check_imports.py — 모듈 간 import 정합성 자동 검증
실행: python check_imports.py
모듈 분리 후, 새 기능 추가 후 항상 실행하세요.
"""
import re, ast, sys, tempfile, csv
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

    try:
        main_source = read_source('main.py')
        if "('정지',           'S')" in main_source:
            errors.append("  FAIL stale S stop shortcut remains in help")
        if "('검수 취소',       'Esc')" not in main_source:
            errors.append("  FAIL Esc analysis cancel shortcut missing from help")
        if 'QShortcut(QKeySequence(Qt.Key.Key_Escape)' not in main_source:
            errors.append("  FAIL Esc analysis cancel shortcut missing")
    except Exception as e:
        errors.append(f"  FAIL shortcut source check: {e}")

    class Probe:
        vp = type('VP', (), {'cur_file': ''})()
        _file_path_text = staticmethod(lambda value: str(value or ''))
        _path_exists = staticmethod(lambda value: True)
        _file_status_badge = RightPanel._file_status_badge
        _file_matches_filter_key = staticmethod(RightPanel._file_matches_filter_key)
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
        filter_count_records = [
            {'black': 'ok', 'mute': 'ok', 'freeze': ''},
            {'black': '', 'mute': '', 'freeze': ''},
            {'black': 'found', 'mute': 'ok', 'freeze': ''},
            {'black': 'ok', 'mute': 'error', 'freeze': ''},
            {'black': 'ok', 'mute': 'ok', 'freeze': 'found'},
        ]
        filter_counts = RightPanel._filter_counts(filter_count_records)
        expected_filter_counts = {
            'all': 5,
            'done': 3,
            'pending': 1,
            'issues': 3,
            'black': 1,
            'mute': 0,
            'freeze': 1,
            'error': 1,
            'normal': 1,
        }
        for key, expected in expected_filter_counts.items():
            if filter_counts.get(key) != expected:
                errors.append(f"  FAIL filter count {key}: {filter_counts.get(key)} != {expected}")
            expected_by_filter = sum(
                1 for record in filter_count_records
                if RightPanel._file_matches_filter_key(record, key)
            )
            if filter_counts.get(key) != expected_by_filter:
                errors.append(
                    f"  FAIL filter count parity {key}: "
                    f"{filter_counts.get(key)} != {expected_by_filter}"
                )
        cached_availability = {id(record): '' for record in filter_count_records}
        cached_filter_counts = RightPanel._filter_counts(filter_count_records, cached_availability)
        for key, expected in filter_counts.items():
            if cached_filter_counts.get(key) != expected:
                errors.append(
                    f"  FAIL cached filter count parity {key}: "
                    f"{cached_filter_counts.get(key)} != {expected}"
                )
        missing_record = {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'}
        if RightPanel._file_matches_filter_key(missing_record, 'issues', unavailable='파일 없음') is not True:
            errors.append("  FAIL cached missing file issue filter")
        if RightPanel._filter_button_text('issues', 3) != '문제 3':
            errors.append("  FAIL filter button text issues")
        if RightPanel._filter_button_text('issues', 3, compact=True) != '문제3':
            errors.append("  FAIL compact filter button text issues")
        if RightPanel._filter_button_text('all', 0, compact=True) != '전체0':
            errors.append("  FAIL compact filter button text all-zero")
        if RightPanel._filter_button_text('mute', 0) != '무음':
            errors.append("  FAIL filter button text zero-detail")
        if RightPanel._filter_button_text('all', 0) != '전체 0':
            errors.append("  FAIL filter button text all-zero")
        if RightPanel._compact_filter_labels(429) is not True:
            errors.append("  FAIL compact filter width below threshold")
        if RightPanel._compact_filter_labels(430) is not False:
            errors.append("  FAIL compact filter width threshold")
        class EmptyFileListProbe(Probe):
            _filter_key = 'issues'
            _filter_label = RightPanel._filter_label
        empty_filter_text = RightPanel._empty_file_item_text(EmptyFileListProbe(), 5)
        if '표시할 파일이 없습니다' not in empty_filter_text or '현재 필터: 문제 / 전체 5개' not in empty_filter_text:
            errors.append(f"  FAIL empty filtered file item text: {empty_filter_text}")
        empty_all_text = RightPanel._empty_file_item_text(EmptyFileListProbe(), 0)
        if '파일을 추가하세요' not in empty_all_text or '영상 파일을 추가하면' not in empty_all_text:
            errors.append(f"  FAIL empty file item text: {empty_all_text}")
        empty_filter_html = RightPanel._empty_file_item_html(EmptyFileListProbe(), 5)
        if '표시할 파일이 없습니다' not in empty_filter_html or '현재 필터 문제 / 전체 5개' not in empty_filter_html:
            errors.append(f"  FAIL empty filtered file item html: {empty_filter_html}")
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
            _filtered_file_records = RightPanel._filtered_file_records
            _issue_file_records = RightPanel._issue_file_records
            _file_matches_filter = RightPanel._file_matches_filter
            _report_menu_state = RightPanel._report_menu_state
            _path_name = staticmethod(RightPanel._path_name)
            def _latest_report_path(self):
                return 'C:/reports/latest.csv'
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
        report_probe = FilteredReportProbe()
        report_menu_state = RightPanel._report_menu_state(report_probe)
        if report_menu_state.get('all_count') != 3 or report_menu_state.get('visible_count') != 2:
            errors.append(f"  FAIL report menu counts: {report_menu_state}")
        if report_menu_state.get('issue_count') != 2:
            errors.append(f"  FAIL report menu issue count: {report_menu_state}")
        issue_report_names = [
            f.get('name') for f in report_menu_state.get('issue_files', [])
        ]
        if issue_report_names != ['bad-a.mxf', 'bad-b.mxf']:
            errors.append(f"  FAIL report menu issue files: {issue_report_names}")
        if getattr(report_probe, '_filter_key', '') != 'issues':
            errors.append(f"  FAIL report menu filter restore: {getattr(report_probe, '_filter_key', '')}")
        if not report_menu_state.get('show_visible'):
            errors.append(f"  FAIL report menu visible scope: {report_menu_state}")
        if report_menu_state.get('latest_report_name') != 'latest.csv':
            errors.append(f"  FAIL report menu latest name: {report_menu_state}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            (base / 'a-old.csv').write_text('old', encoding='utf-8')
            (base / 'm-ignore.zip').write_text('zip', encoding='utf-8')
            (base / 'z-new.txt').write_text('new', encoding='utf-8')
            latest = RightPanel._latest_report_path_in(base)
            if Path(latest).name != 'z-new.txt':
                errors.append(f"  FAIL latest report path: {latest}")
            empty_dir = base / 'empty'
            empty_dir.mkdir()
            if RightPanel._latest_report_path_in(empty_dir) != '':
                errors.append("  FAIL latest report empty folder")
        if RightPanel._report_filename_token('bad <name>: 01?.mxf') != 'bad-_name_-01':
            errors.append("  FAIL report filename token sanitizing")
        class ReportPrefixProbe:
            _path_name = staticmethod(RightPanel._path_name)
            _report_filename_token = staticmethod(RightPanel._report_filename_token)
            _report_prefix_for_file = RightPanel._report_prefix_for_file
        prefix = RightPanel._report_prefix_for_file(
            ReportPrefixProbe(),
            {'name': 'long sample <bad>: 01.mxf'},
        )
        if prefix != 'qc-selected-long-sample-_bad_-01':
            errors.append(f"  FAIL selected report prefix: {prefix}")
        report_rows = [
            {
                '파일명': 'normal.mxf',
                'QC요약': '정상',
                '파일존재': 'Y',
                '블랙상태': '정상',
                '무음상태': '정상',
                '프리즈상태': '정상',
                '메타정합성': '정상',
            },
            {
                '파일명': 'partial.mxf',
                'QC요약': '블랙/무음 정상',
                '파일존재': 'Y',
                '블랙상태': '정상',
                '무음상태': '정상',
                '프리즈상태': '미분석',
                '메타정합성': '정상',
            },
            {
                '파일명': 'issue.mxf',
                'QC요약': '블랙/프리즈 있음',
                '파일존재': 'Y',
                '블랙상태': '있음',
                '블랙구간': '2',
                '무음상태': '정상',
                '프리즈상태': '있음',
                '프리즈구간': '1',
                '메타정합성': '확인 필요',
            },
            {
                '파일명': 'error.mxf',
                'QC요약': '검사 오류',
                '파일존재': 'Y',
                '블랙상태': '정상',
                '무음상태': '오류',
                '프리즈상태': '미분석',
                '메타정합성': '확인 필요',
            },
            {
                '파일명': 'missing.mxf',
                'QC요약': '파일 없음',
                '파일존재': 'N',
                '블랙상태': '정상',
                '무음상태': '정상',
                '프리즈상태': '정상',
                '메타정합성': '',
            },
            {'QC요약': '미분석', '파일존재': 'Y', '메타정합성': ''},
        ]
        report_counts = RightPanel._qc_report_summary_counts(report_rows)
        expected_report_counts = {
            'total': 6,
            'normal': 1,
            'partial_normal': 1,
            'issue_files': 3,
            'black': 1,
            'mute': 0,
            'freeze': 1,
            'complex': 1,
            'error': 1,
            'pending': 1,
            'missing': 1,
            'metadata_warn': 2,
        }
        for key, expected in expected_report_counts.items():
            if report_counts.get(key) != expected:
                errors.append(f"  FAIL report summary count {key}: {report_counts.get(key)} != {expected}")
        report_lines = RightPanel._qc_report_summary_lines(report_rows)
        if not any('문제파일 3' in line and '파일없음 1' in line for line in report_lines):
            errors.append(f"  FAIL report summary line issues: {report_lines}")
        if not any('복합문제 1' in line for line in report_lines):
            errors.append(f"  FAIL report summary line complex: {report_lines}")
        attention_lines = RightPanel._qc_report_attention_lines(report_rows)
        if '확인 필요 파일: 3개' not in attention_lines:
            errors.append(f"  FAIL report attention count: {attention_lines}")
        if not any('issue.mxf: 블랙 2, 프리즈 1, 메타 확인' in line for line in attention_lines):
            errors.append(f"  FAIL report attention issue detail: {attention_lines}")
        if not any('missing.mxf: 파일 없음' in line for line in attention_lines):
            errors.append(f"  FAIL report attention missing detail: {attention_lines}")
        clean_attention = RightPanel._qc_report_attention_lines([report_rows[0], report_rows[1]])
        if clean_attention != ['확인 필요 파일: 없음']:
            errors.append(f"  FAIL report clean attention: {clean_attention}")
        issue_fields = RightPanel._qc_report_attention_fields(report_rows[2])
        if issue_fields != {'확인필요': 'Y', '확인사유': '블랙 2, 프리즈 1, 메타 확인'}:
            errors.append(f"  FAIL report attention fields issue: {issue_fields}")
        clean_fields = RightPanel._qc_report_attention_fields(report_rows[0])
        if clean_fields != {'확인필요': 'N', '확인사유': ''}:
            errors.append(f"  FAIL report attention fields clean: {clean_fields}")
        meta_only_fields = RightPanel._qc_report_attention_fields({
            'QC요약': '정상',
            '파일존재': 'Y',
            '메타정합성': '확인 필요',
        })
        if meta_only_fields != {'확인필요': 'Y', '확인사유': '메타 확인'}:
            errors.append(f"  FAIL report attention fields metadata: {meta_only_fields}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            txt_path = report_dir / 'report.txt'
            csv_path = report_dir / 'report.csv'
            csv_rows = [
                dict(row, **RightPanel._qc_report_attention_fields(row))
                for row in report_rows[:3]
            ]
            RightPanel._write_qc_report_txt(RightPanel, txt_path, csv_rows)
            txt = txt_path.read_text(encoding='utf-8')
            if '검수요약:' not in txt or '확인 필요 파일: 1개' not in txt:
                errors.append(f"  FAIL TXT report summary smoke: {txt[:300]}")
            if 'issue.mxf: 블랙 2, 프리즈 1, 메타 확인' not in txt:
                errors.append(f"  FAIL TXT report attention smoke: {txt[:500]}")
            RightPanel._write_qc_report_csv(RightPanel, csv_path, csv_rows)
            with csv_path.open('r', encoding='utf-8-sig', newline='') as fh:
                saved_rows = list(csv.DictReader(fh))
            if not saved_rows or '확인필요' not in saved_rows[0] or '확인사유' not in saved_rows[0]:
                errors.append(f"  FAIL CSV report attention columns: {saved_rows[:1]}")
            elif saved_rows[2].get('확인필요') != 'Y' or saved_rows[2].get('확인사유') != '블랙 2, 프리즈 1, 메타 확인':
                errors.append(f"  FAIL CSV report attention values: {saved_rows[2] if len(saved_rows) > 2 else saved_rows}")

        class SummaryCopyProbe:
            _iter_report_files = RightPanel._iter_report_files
            _qc_issue_markers = RightPanel._qc_issue_markers
            _qc_issue_seek_times = RightPanel._qc_issue_seek_times
            _first_qc_issue_text = RightPanel._first_qc_issue_text
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
        if '첫문제: 블랙 00:00:01;00' not in summary_text:
            errors.append(f"  FAIL QC summary copy first issue: {summary_text}")
        if '블랙구간: 00:00:01;00>00:00:02;00(1.000s)' not in summary_text:
            errors.append(f"  FAIL QC summary copy ranges: {summary_text}")
        if '경로: C:/qc/copy-me.mxf' not in summary_text:
            errors.append(f"  FAIL QC summary copy path: {summary_text}")
        issue_summary_text = RightPanel._issue_summary_clipboard_text(
            SummaryCopyProbe(),
            [
                {
                    'name': 'bad-a.mxf',
                    'filepath': 'C:/qc/bad-a.mxf',
                    'black': 'found',
                    'mute': 'ok',
                    'freeze': '',
                    'black_count': 1,
                    'mute_count': 0,
                    'freeze_count': 0,
                    'black_ranges': [{'start': 4.0, 'tc_start': '00:00:04;00'}],
                },
                {
                    'name': 'bad-b.mxf',
                    'filepath': 'C:/qc/bad-b.mxf',
                    'black': 'ok',
                    'mute': 'error',
                    'freeze': '',
                    'black_count': 0,
                    'mute_count': 0,
                    'freeze_count': 0,
                },
            ],
        )
        if 'MXF QC Player 문제 파일 요약' not in issue_summary_text or '문제 2개' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy header: {issue_summary_text}")
        if 'bad-a.mxf: 블랙 있음 / 블랙 있음 1 / 무음 정상 0 / 프리즈 미분석 0 / 첫문제 블랙 00:00:04;00' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy black detail: {issue_summary_text}")
        if 'bad-b.mxf: 검사 오류 / 블랙 정상 0 / 무음 오류 0 / 프리즈 미분석 0' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy error detail: {issue_summary_text}")
        empty_issue_summary = RightPanel._issue_summary_clipboard_text(SummaryCopyProbe(), [])
        if '확인 필요 파일 없음' not in empty_issue_summary:
            errors.append(f"  FAIL issue summary copy empty: {empty_issue_summary}")
        first_issue_time = RightPanel._first_qc_issue_seek_time(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 4.0, 'end': 5.0, 'duration': 1.0}],
                'mute_ranges': [{'start': 1.25, 'end': 2.0, 'duration': 0.75}],
                'freeze_ranges': [{'start': 3.0, 'end': 4.0, 'duration': 1.0}],
            },
        )
        if abs((first_issue_time or 0) - 1.25) > 0.0001:
            errors.append(f"  FAIL first QC issue seek time: {first_issue_time}")
        issue_times = RightPanel._qc_issue_seek_times(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 4.0}, {'start': 1.25}],
                'mute_ranges': [{'start': 1.25}],
                'freeze_ranges': [{'start': 3.0}],
            },
        )
        if issue_times != [1.25, 3.0, 4.0]:
            errors.append(f"  FAIL QC issue seek times sorted: {issue_times}")
        next_issue_time = RightPanel._next_qc_issue_seek_time(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 4.0}],
                'mute_ranges': [{'start': 1.25}],
                'freeze_ranges': [{'start': 3.0}],
            },
            1.25,
        )
        if abs((next_issue_time or 0) - 3.0) > 0.0001:
            errors.append(f"  FAIL next QC issue seek time: {next_issue_time}")
        wrap_issue_time = RightPanel._next_qc_issue_seek_time(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 4.0}],
                'mute_ranges': [{'start': 1.25}],
                'freeze_ranges': [{'start': 3.0}],
            },
            4.5,
        )
        if abs((wrap_issue_time or 0) - 1.25) > 0.0001:
            errors.append(f"  FAIL next QC issue seek wrap: {wrap_issue_time}")
        prev_issue_time = RightPanel._previous_qc_issue_seek_time(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 4.0}],
                'mute_ranges': [{'start': 1.25}],
                'freeze_ranges': [{'start': 3.0}],
            },
            3.2,
        )
        if abs((prev_issue_time or 0) - 3.0) > 0.0001:
            errors.append(f"  FAIL previous QC issue seek time: {prev_issue_time}")
        prev_wrap_issue_time = RightPanel._previous_qc_issue_seek_time(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 4.0}],
                'mute_ranges': [{'start': 1.25}],
                'freeze_ranges': [{'start': 3.0}],
            },
            1.0,
        )
        if abs((prev_wrap_issue_time or 0) - 4.0) > 0.0001:
            errors.append(f"  FAIL previous QC issue seek wrap: {prev_wrap_issue_time}")
        if RightPanel._first_qc_issue_seek_time(SummaryCopyProbe(), {}) is not None:
            errors.append("  FAIL first QC issue seek empty")

        class ReanalyzeProbe:
            _file_path_text = staticmethod(RightPanel._file_path_text)
            _same_path_text = staticmethod(RightPanel._same_path_text)
            _path_name = staticmethod(RightPanel._path_name)
            _is_video_file_path = staticmethod(lambda value: bool(value))
            _can_reanalyze_current_file = RightPanel._can_reanalyze_current_file
            _run_context_reanalyze = RightPanel._run_context_reanalyze

            def __init__(self):
                self.calls = []
                self.messages = []
                self._analysis_active = None
                self.vp = type('VP', (), {})()
                self.vp.cur_file = 'C:/qc/current.mxf'
                self.vp._loading = False
                self.vp.status_changed = type(
                    'Signal',
                    (),
                    {'emit': lambda _, msg: self.messages.append(msg)},
                )()

            def _run_black_detect(self):
                self.calls.append('black')

            def _run_audio_analyze(self):
                self.calls.append('audio')

            def _run_freeze_detect(self):
                self.calls.append('freeze')

        reanalyze_probe = ReanalyzeProbe()
        if not RightPanel._can_reanalyze_current_file(reanalyze_probe, 'C:/qc/current.mxf'):
            errors.append("  FAIL context reanalyze current-file enabled")
        if RightPanel._can_reanalyze_current_file(reanalyze_probe, 'C:/qc/other.mxf'):
            errors.append("  FAIL context reanalyze other-file disabled")
        if not RightPanel._run_context_reanalyze(reanalyze_probe, 'audio', 'C:/qc/current.mxf'):
            errors.append("  FAIL context reanalyze run result")
        if reanalyze_probe.calls != ['audio']:
            errors.append(f"  FAIL context reanalyze runner call: {reanalyze_probe.calls}")
        if RightPanel._run_context_reanalyze(reanalyze_probe, 'black', 'C:/qc/other.mxf'):
            errors.append("  FAIL context reanalyze non-cue blocked")

        class CueBlockItem:
            def __init__(self, filepath):
                self.filepath = filepath

            def data(self, _role):
                return self.filepath

        class CueBlockProbe:
            _file_path_text = staticmethod(RightPanel._file_path_text)
            _is_video_file_path = staticmethod(lambda value: bool(value))
            _path_name = staticmethod(RightPanel._path_name)
            _cue_exp_item = RightPanel._cue_exp_item

            def __init__(self, active=None):
                self._analysis_active = active
                self.loaded = []
                self.messages = []
                self.refreshed = 0
                self.vp = type('VP', (), {})()
                self.vp.status_changed = type(
                    'Signal',
                    (),
                    {'emit': lambda _, msg: self.messages.append(msg)},
                )()
                self.vp.load_file = lambda fp: self.loaded.append(fp)

            def refresh_explorer(self):
                self.refreshed += 1

        cue_block_probe = CueBlockProbe(active='black')
        RightPanel._cue_exp_item(cue_block_probe, CueBlockItem('C:/qc/current.mxf'))
        if cue_block_probe.loaded:
            errors.append("  FAIL analysis-active cue should be blocked")
        if not any('CUE' in msg for msg in cue_block_probe.messages):
            errors.append(f"  FAIL analysis-active cue status message: {cue_block_probe.messages}")

        cue_allowed_probe = CueBlockProbe(active=None)
        RightPanel._cue_exp_item(cue_allowed_probe, CueBlockItem('C:/qc/current.mxf'))
        if cue_allowed_probe.loaded != ['C:/qc/current.mxf']:
            errors.append(f"  FAIL idle cue should load: {cue_allowed_probe.loaded}")

        class AnalysisCancelProbe:
            _cancel_current_analysis = RightPanel._cancel_current_analysis

            def __init__(self, active='audio', batch=False):
                self._analysis_active = active
                self._batch_active = batch
                self.cancelled = []
                self.refreshed = 0
                self.messages = []
                self.ai_text = []
                self.vp = type('VP', (), {})()
                self.vp.status_changed = type(
                    'Signal',
                    (),
                    {'emit': lambda _, msg: self.messages.append(msg)},
                )()
                self.vp.ai_lbl = type(
                    'Label',
                    (),
                    {'setText': lambda _, msg: self.ai_text.append(msg)},
                )()

            def _analysis_thread_running(self):
                return bool(self._analysis_active or self._batch_active)

            def cancel_active_analysis(self, reason):
                self.cancelled.append(reason)

            def refresh_explorer(self):
                self.refreshed += 1

        cancel_probe = AnalysisCancelProbe(active='audio', batch=False)
        RightPanel._cancel_current_analysis(cancel_probe)
        if cancel_probe.cancelled != ['검수 취소'] or cancel_probe.refreshed != 1:
            errors.append(f"  FAIL single analysis cancel: {cancel_probe.cancelled}/{cancel_probe.refreshed}")

        batch_cancel_probe = AnalysisCancelProbe(active='batch', batch=True)
        RightPanel._cancel_current_analysis(batch_cancel_probe)
        if batch_cancel_probe.cancelled != ['일괄 검수 취소']:
            errors.append(f"  FAIL batch analysis cancel: {batch_cancel_probe.cancelled}")

        idle_cancel_probe = AnalysisCancelProbe(active=None, batch=False)
        RightPanel._cancel_current_analysis(idle_cancel_probe)
        if idle_cancel_probe.cancelled or not idle_cancel_probe.messages:
            errors.append(f"  FAIL idle analysis cancel message: {idle_cancel_probe.cancelled}/{idle_cancel_probe.messages}")

        class ElapsedCancelProbe:
            _finish_cancel_elapsed_timer = RightPanel._finish_cancel_elapsed_timer

            def __init__(self):
                self.calls = []

            def _finish_black_elapsed_timer(self, prefix='BLACK'):
                self.calls.append(('black', prefix))

            def _finish_audio_elapsed_timer(self, prefix='MUTE'):
                self.calls.append(('audio', prefix))

            def _finish_freeze_elapsed_timer(self, prefix='FREEZE'):
                self.calls.append(('freeze', prefix))

        elapsed_cancel_probe = ElapsedCancelProbe()
        for kind in ('black', 'audio', 'freeze', 'batch', None):
            RightPanel._finish_cancel_elapsed_timer(elapsed_cancel_probe, kind)
        expected_elapsed_cancel = [
            ('black', 'BLACK STOP'),
            ('audio', 'MUTE STOP'),
            ('freeze', 'FREEZE STOP'),
        ]
        if elapsed_cancel_probe.calls != expected_elapsed_cancel:
            errors.append(f"  FAIL cancel elapsed timer routing: {elapsed_cancel_probe.calls}")

        class ClearAnalysisProbe:
            _clear_cancelled_analysis_state = RightPanel._clear_cancelled_analysis_state
            _file_path_text = staticmethod(RightPanel._file_path_text)
            _path_name = staticmethod(RightPanel._path_name)

            def __init__(self):
                self.cleared = []
                self.vp = type('VP', (), {})()
                self.vp._set_file_status = lambda fp, **changes: self.cleared.append((fp, changes))
                self.records = [
                    {'filepath': 'C:/qc/active.mxf', 'analysis': 'black'},
                    {'filepath': 'C:/qc/stale.mxf', 'analysis': 'mute'},
                    {'filepath': 'C:/qc/done.mxf', 'analysis': None},
                ]

            def _file_records(self):
                return self.records

        clear_probe = ClearAnalysisProbe()
        RightPanel._clear_cancelled_analysis_state(clear_probe, 'C:/qc/active.mxf')
        expected_clear = [
            ('C:/qc/active.mxf', {'analysis': None}),
            ('C:/qc/stale.mxf', {'analysis': None}),
        ]
        if clear_probe.cleared != expected_clear:
            errors.append(f"  FAIL clear cancelled analysis state: {clear_probe.cleared}")

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
        meter_multimono = VideoPanel._meter_channel_count(
            VideoPanel, {'audio_stream_count': 8, 'channels': 1}
        )
        if meter_multimono != 8:
            errors.append(f"  FAIL meter multi-mono channel count: {meter_multimono}")
        meter_stereo = VideoPanel._meter_channel_count(
            VideoPanel, {'audio_stream_count': 1, 'channels': 2}
        )
        if meter_stereo != 2:
            errors.append(f"  FAIL meter stereo channel count: {meter_stereo}")

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
