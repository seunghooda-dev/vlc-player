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
        from constants import DEFAULT_SETTINGS, _normalize_settings
        from video_panel import AudioMixPlayer
    except Exception as e:
        return [f"  FAIL core logic import: {e}"]

    class Probe:
        _file_path_text = staticmethod(lambda value: str(value or ''))
        _path_exists = staticmethod(lambda value: True)
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

        if DEFAULT_SETTINGS.get('audio_channels') != [1, 2]:
            errors.append(f"  FAIL default audio channels: {DEFAULT_SETTINGS.get('audio_channels')}")
        normalized = _normalize_settings({'audio_channels': [1, 2, 9, 16, 2, 'bad']})
        if normalized.get('audio_channels') != [1, 2]:
            errors.append(f"  FAIL audio settings channel clamp: {normalized.get('audio_channels')}")

        audio_mix = AudioMixPlayer()
        audio_mix.set_channels([1, 2, 9, 16, 2, 'bad'])
        if audio_mix.channels != [1, 2]:
            errors.append(f"  FAIL audio mix channel clamp: {audio_mix.channels}")
        audio_mix.set_channels([8, 7])
        if audio_mix.channels != [8, 7]:
            errors.append(f"  FAIL audio mix channel upper bound: {audio_mix.channels}")
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
        print("  OK metadata QC and audio channel rules")

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
