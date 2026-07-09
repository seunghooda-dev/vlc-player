"""
check_imports.py — 모듈 간 import 정합성 자동 검증
실행: python check_imports.py
모듈 분리 후, 새 기능 추가 후 항상 실행하세요.
"""
import re, ast, sys

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
        from video_panel import AudioMixPlayer, DIRECT_VLC_EXTS
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
            {'black': 'ok', 'mute': 'ok', 'freeze': ''},
            {'black': 'found', 'mute': 'ok', 'freeze': 'found'},
            {'black': 'found', 'mute': 'found', 'freeze': ''},
            {'black': 'ok', 'mute': 'error', 'freeze': ''},
            {'black': '', 'mute': '', 'freeze': ''},
        ])
        expected_qc_counts = {
            'total': 5,
            'normal': 1,
            'black': 2,
            'mute': 1,
            'freeze': 1,
            'both': 2,
            'error': 1,
            'pending': 1,
        }
        for key, expected in expected_qc_counts.items():
            if qc_counts.get(key) != expected:
                errors.append(f"  FAIL batch QC count {key}: {qc_counts.get(key)} != {expected}")
        status_summary = RightPanel._status_summary_text(Probe(), [
            {'black': 'ok', 'mute': 'ok', 'freeze': ''},
            {'black': 'found', 'mute': 'found', 'freeze': ''},
            {'black': 'found', 'mute': 'ok', 'freeze': 'found'},
        ])
        if "정상 1" not in status_summary:
            errors.append(f"  FAIL status summary normal count: {status_summary}")
        if "블랙/무음 1" not in status_summary:
            errors.append(f"  FAIL status summary black/mute count: {status_summary}")
        if "복합 문제 1" not in status_summary:
            errors.append(f"  FAIL status summary complex count: {status_summary}")
        qc_summary_cases = [
            (qc_summary_from_status('ok', 'ok', ''), '정상', 'black/mute ok'),
            (qc_summary_from_status('found', 'ok', ''), '블랙 있음', 'black found'),
            (qc_summary_from_status('found', 'found', ''), '블랙/무음 있음', 'black+mute found'),
            (qc_summary_from_status('found', 'ok', 'found'), '블랙/프리즈 있음', 'black+freeze found'),
            (qc_summary_from_status('ok', 'error', 'found'), '검사 오류', 'error priority'),
        ]
        for actual, expected, label in qc_summary_cases:
            if actual != expected:
                errors.append(f"  FAIL QC summary {label}: {actual} != {expected}")

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
