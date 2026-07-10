"""
check_imports.py — 모듈 간 import 정합성 자동 검증
실행: python check_imports.py
모듈 분리 후, 새 기능 추가 후 항상 실행하세요.
"""
import re, ast, sys, tempfile, csv, time
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
        import right_panel as rpm
        import video_panel as vpm
        from right_panel import FILE_FILTER_TIPS, RightPanel
        from constants import C, DEFAULT_SETTINGS, VIDEO_EXTS, _normalize_settings
        import db_models as dbm
        from db_models import frames_to_tc, is_df_fps, qc_summary_from_status, sanitize_qc_ranges, tc_to_frames
        from threads import AudioAnalyzeThread, TranscodeThread
        from video_panel import AudioMixPlayer, DIRECT_VLC_EXTS, QCMarkerSlider, VideoPanel
    except Exception as e:
        return [f"  FAIL core logic import: {e}"]

    try:
        main_source = read_source('main.py')
        right_source = read_source('right_panel.py')
        video_source = read_source('video_panel.py')
        threads_source = read_source('threads.py')
        if "('정지',           'S')" in main_source:
            errors.append("  FAIL stale S stop shortcut remains in help")
        if "('검수 취소',       'Esc')" not in main_source:
            errors.append("  FAIL Esc analysis cancel shortcut missing from help")
        if 'QShortcut(QKeySequence(Qt.Key.Key_Escape)' not in main_source:
            errors.append("  FAIL Esc analysis cancel shortcut missing")
        if 'vp._retire_loudness_analysis()' not in main_source:
            errors.append("  FAIL closeEvent should retire loudness analysis")
        if "rp._freeze_thread" not in main_source or "'freeze_thread'" not in main_source:
            errors.append("  FAIL closeEvent should include freeze analysis thread cleanup")
        if "restore_runtime=False" not in main_source:
            errors.append("  FAIL closeEvent should cancel analysis without restoring runtime")
        if "def _finish_analysis_mode(self, restore_runtime=True)" not in right_source:
            errors.append("  FAIL analysis finish restore_runtime guard missing")
        if 'win.vp.toggle_play()' not in main_source:
            errors.append("  FAIL MXF smoke test should use the real transport play path")
        if 'def _ensure_unpaused(self, seq=None)' not in video_source or 'self._player.set_pause(0)' not in video_source:
            errors.append("  FAIL VLC play should explicitly resume after CUE preroll pause")
        if 'def pause(self):\n        self._next_op()' not in video_source:
            errors.append("  FAIL VLC pause should invalidate delayed resume callbacks")
        if "'no_audio': False" not in threads_source:
            errors.append("  FAIL audio analysis normal result should include no_audio=False")
    except Exception as e:
        errors.append(f"  FAIL shortcut source check: {e}")

    class Probe:
        vp = type('VP', (), {'cur_file': ''})()
        _file_path_text = staticmethod(lambda value: str(value or ''))
        _path_exists = staticmethod(lambda value: True)
        _file_status_badge = RightPanel._file_status_badge
        _path_name = staticmethod(lambda value, fallback='파일': Path(str(value or '')).name or fallback)
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
        class FakeProbeLog:
            def __init__(self):
                self.warnings = []

            def warning(self, msg):
                self.warnings.append(str(msg))

            def debug(self, msg):
                pass

        class FakeRunResult:
            def __init__(self, stdout='', stderr='', returncode=0):
                self.stdout = stdout
                self.stderr = stderr
                self.returncode = returncode

        original_run = dbm.subprocess.run
        original_log = dbm.log
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.mxf', delete=False) as tmp_media:
                tmp_path = tmp_media.name
                tmp_media.write(b'not real media')
            fake_log = FakeProbeLog()
            dbm.log = fake_log
            dbm._PROBE_CACHE.clear()
            dbm._PROBE_CACHE_ORDER.clear()
            dbm.subprocess.run = lambda *a, **k: FakeRunResult(stdout=None, stderr='')
            if dbm.probe(tmp_path) != {} or not any('empty json' in msg for msg in fake_log.warnings):
                errors.append(f"  FAIL probe empty json guard: {fake_log.warnings}")
            fake_log.warnings.clear()
            dbm.subprocess.run = lambda *a, **k: FakeRunResult(stdout='{bad json', stderr='')
            if dbm.probe(tmp_path) != {} or not any('invalid json' in msg for msg in fake_log.warnings):
                errors.append(f"  FAIL probe invalid json guard: {fake_log.warnings}")
        finally:
            dbm.subprocess.run = original_run
            dbm.log = original_log
            dbm._PROBE_CACHE.clear()
            dbm._PROBE_CACHE_ORDER.clear()
            try:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        class FakeSnapshotLog:
            def __init__(self):
                self.debugs = []

            def debug(self, msg):
                self.debugs.append(str(msg))

            def warning(self, msg):
                pass

        original_snapshot = dbm._safe_file_snapshot
        original_log = dbm.log
        try:
            fake_log = FakeSnapshotLog()
            dbm.log = fake_log
            dbm._safe_file_snapshot = lambda fp: {"size": 200, "mtime_ns": 20}
            if not dbm._snapshot_mismatch('C:/sample/replaced.mxf', 100, 20, context='QC status'):
                errors.append("  FAIL QC snapshot size mismatch")
            if not any('QC status ignored size mismatch' in msg for msg in fake_log.debugs):
                errors.append(f"  FAIL QC snapshot mismatch log: {fake_log.debugs}")
            fake_log.debugs.clear()
            if not dbm._snapshot_mismatch('C:/sample/replaced.mxf', 200, 10, context='metadata hint'):
                errors.append("  FAIL metadata snapshot mtime mismatch")
            if dbm._snapshot_mismatch('C:/sample/replaced.mxf', 200, 20, context='QC status'):
                errors.append("  FAIL snapshot false positive")
            if dbm._snapshot_mismatch('C:/sample/replaced.mxf', 0, 0, context='QC status'):
                errors.append("  FAIL snapshot missing stored values false positive")
        finally:
            dbm._safe_file_snapshot = original_snapshot
            dbm.log = original_log

        parse_audio_streams = AudioAnalyzeThread._audio_streams_from_probe_output
        audio_probe_json = '{"streams":[{"codec_type":"video"},{"codec_type":"audio","channels":2},{"codec_type":"audio","channels":1}]}'
        if parse_audio_streams(audio_probe_json, 0, '') != [2, 1]:
            errors.append("  FAIL audio analyze probe stream parse")
        if parse_audio_streams('{"streams":[]}', 0, '') != []:
            errors.append("  FAIL audio analyze empty audio stream parse")
        for stdout, returncode, stderr, label in (
            (None, 0, '', 'empty stdout'),
            ('{bad json', 0, '', 'invalid json'),
            ('{}', 1, 'bad input', 'ffprobe failure'),
        ):
            try:
                parse_audio_streams(stdout, returncode, stderr)
                errors.append(f"  FAIL audio analyze probe guard did not raise: {label}")
            except RuntimeError:
                pass

        repaired_ranges = sanitize_qc_ranges([
            {'start': 1.25, 'duration': 0.75},
            {'start': 4.0, 'end': 5.5},
        ])
        if repaired_ranges[0].get('end') != 2.0:
            errors.append(f"  FAIL QC range end repair: {repaired_ranges}")
        if repaired_ranges[1].get('duration') != 1.5:
            errors.append(f"  FAIL QC range duration repair: {repaired_ranges}")
        slider_ranges = QCMarkerSlider._clean_ranges([
            {'start': 2.0, 'duration': 1.25},
            {'start': 4.0, 'end': 5.0},
        ])
        if slider_ranges[0].get('end') != 3.25:
            errors.append(f"  FAIL slider QC range end repair: {slider_ranges}")
        if abs(slider_ranges[1].get('duration', 0.0) - 1.0) > 0.0001:
            errors.append(f"  FAIL slider QC range duration repair: {slider_ranges}")

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

        class MetadataRestoreProbe(Probe):
            _restore_metadata_qc_from_hint = RightPanel._restore_metadata_qc_from_hint
            _clear_stale_record_state = RightPanel._clear_stale_record_state
            _ensure_record_file_snapshot = RightPanel._ensure_record_file_snapshot
            _snapshot_check_due = RightPanel._snapshot_check_due
            _record_file_snapshot_changed = RightPanel._record_file_snapshot_changed
            _record_file_snapshot = lambda self, record: getattr(self, '_snapshot', (0, 0))
            _same_path_text = staticmethod(lambda a, b: str(a or '').lower() == str(b or '').lower())

        original_hint_loader = rpm.load_clip_metadata_hint
        try:
            rpm.load_clip_metadata_hint = lambda fp: dict(
                base,
                filepath=fp,
                fps=29.97,
                df=True,
                channels=0,
                audio_stream_count=0,
            )
            restore_record = {'filepath': 'C:/sample/no_audio_cached.mxf'}
            if not RightPanel._restore_metadata_qc_from_hint(MetadataRestoreProbe(), restore_record):
                errors.append(f"  FAIL metadata QC restore result: {restore_record}")
            if restore_record.get('meta_status') != '확인 필요' or '오디오 없음' not in restore_record.get('meta_issues', []):
                errors.append(f"  FAIL metadata QC restore record: {restore_record}")
        finally:
            rpm.load_clip_metadata_hint = original_hint_loader

        original_hint_loader = rpm.load_clip_metadata_hint
        try:
            rpm.load_clip_metadata_hint = lambda fp: {}
            stale_probe = MetadataRestoreProbe()
            stale_probe._snapshot = (200, 20)
            stale_probe.vp = type(
                'VP',
                (),
                {
                    'cur_file': 'C:/sample/replaced.mxf',
                    'marker_refreshes': 0,
                    '_apply_qc_markers': lambda self: setattr(self, 'marker_refreshes', self.marker_refreshes + 1),
                },
            )()
            stale_record = {
                'filepath': 'C:/sample/replaced.mxf',
                'size': 100,
                'mtime_ns': 10,
                'meta_status': '확인 필요',
                'meta_issues': ['오디오 없음'],
                '_meta_qc_hint_checked': True,
                'black': 'found',
                'mute': 'ok',
                'freeze': 'found',
                'black_count': 2,
                'mute_count': 0,
                'freeze_count': 1,
                'black_ranges': [{'start': 1.0}],
                'mute_ranges': [],
                'freeze_ranges': [{'start': 2.0}],
                'qc_summary': '블랙/프리즈 있음',
                'qc_updated_at': 'cached',
                'analysis': 'black',
            }
            if RightPanel._restore_metadata_qc_from_hint(stale_probe, stale_record):
                errors.append(f"  FAIL stale metadata QC restore result: {stale_record}")
            if stale_record.get('meta_status') or stale_record.get('meta_issues'):
                errors.append(f"  FAIL stale metadata QC clear: {stale_record}")
            if stale_record.get('size') != 200 or stale_record.get('mtime_ns') != 20:
                errors.append(f"  FAIL stale record snapshot refresh: {stale_record}")
            for key in ('black', 'mute', 'freeze'):
                if stale_record.get(key) != '':
                    errors.append(f"  FAIL stale QC status clear {key}: {stale_record}")
            for key in ('black_count', 'mute_count', 'freeze_count'):
                if stale_record.get(key) != 0:
                    errors.append(f"  FAIL stale QC count clear {key}: {stale_record}")
            for key in ('black_ranges', 'mute_ranges', 'freeze_ranges'):
                if stale_record.get(key) != []:
                    errors.append(f"  FAIL stale QC ranges clear {key}: {stale_record}")
            if stale_record.get('qc_summary') != '미분석' or stale_record.get('analysis') is not None:
                errors.append(f"  FAIL stale QC summary/analysis clear: {stale_record}")
            if stale_probe.vp.marker_refreshes != 1:
                errors.append(f"  FAIL stale current marker refresh: {stale_probe.vp.marker_refreshes}")

            throttled_record = {
                'filepath': 'C:/sample/throttled.mxf',
                'size': 100,
                'mtime_ns': 10,
                'black': 'found',
                '_snapshot_checked_at': time.monotonic(),
            }
            if RightPanel._clear_stale_record_state(stale_probe, throttled_record):
                errors.append(f"  FAIL stale snapshot throttle: {throttled_record}")
            if throttled_record.get('black') != 'found':
                errors.append(f"  FAIL stale snapshot throttle mutated record: {throttled_record}")
            forced_record = {
                'filepath': 'C:/sample/forced.mxf',
                'size': 100,
                'mtime_ns': 10,
                'black': 'found',
                'black_count': 1,
                'black_ranges': [{'start': 1.0}],
                '_snapshot_checked_at': time.monotonic(),
            }
            if not RightPanel._clear_stale_record_state(stale_probe, forced_record, force=True):
                errors.append(f"  FAIL stale snapshot force bypass: {forced_record}")
            if forced_record.get('black') != '' or forced_record.get('black_count') != 0 or forced_record.get('black_ranges') != []:
                errors.append(f"  FAIL stale snapshot force clear: {forced_record}")

            legacy_record = {
                'filepath': 'C:/sample/legacy.mxf',
                'black': 'found',
                'black_count': 1,
                'black_ranges': [{'start': 1.0}],
            }
            stale_probe._snapshot = (321, 33)
            if RightPanel._clear_stale_record_state(stale_probe, legacy_record, force=True):
                errors.append(f"  FAIL legacy snapshot should backfill without clearing: {legacy_record}")
            if legacy_record.get('size') != 321 or legacy_record.get('mtime_ns') != 33:
                errors.append(f"  FAIL legacy snapshot backfill: {legacy_record}")
            if legacy_record.get('black') != 'found':
                errors.append(f"  FAIL legacy snapshot backfill mutated QC: {legacy_record}")
            stale_probe._snapshot = (400, 44)
            if not RightPanel._clear_stale_record_state(stale_probe, legacy_record, force=True):
                errors.append(f"  FAIL legacy snapshot subsequent stale clear: {legacy_record}")
            if legacy_record.get('black') != '' or legacy_record.get('black_count') != 0 or legacy_record.get('black_ranges') != []:
                errors.append(f"  FAIL legacy snapshot subsequent clear values: {legacy_record}")
        finally:
            rpm.load_clip_metadata_hint = original_hint_loader

        status, issues = RightPanel._metadata_qc_summary(
            Probe(),
            dict(base, fps=29.97, df=True, channels=0, audio_stream_count=0),
            '',
        )
        if '오디오 없음' not in issues or '오디오 1/2CH 확인 필요' in issues:
            errors.append(f"  FAIL no-audio metadata detection: {status} / {issues}")

        class MetadataStoreProbe(Probe):
            _same_path_text = staticmethod(lambda a, b: str(a or '').lower() == str(b or '').lower())
            _record_file_snapshot = lambda self, record: (100, 10)

            def __init__(self):
                self.vp = type('VP', (), {'_files': [{'filepath': 'C:/sample/no_audio.mxf'}]})()

        store_probe = MetadataStoreProbe()
        stored_status, stored_issues = RightPanel._store_metadata_qc_for_file(
            store_probe,
            'C:/sample/no_audio.mxf',
            dict(base, filepath='C:/sample/no_audio.mxf', fps=29.97, df=True, channels=0, audio_stream_count=0),
        )
        stored_record = store_probe.vp._files[0]
        if stored_status != '확인 필요' or '오디오 없음' not in stored_issues:
            errors.append(f"  FAIL metadata store result: {stored_status} / {stored_issues}")
        if stored_record.get('meta_status') != '확인 필요' or '오디오 없음' not in stored_record.get('meta_issues', []):
            errors.append(f"  FAIL metadata store record: {stored_record}")

        status, issues = RightPanel._metadata_qc_summary(
            Probe(),
            dict(base, fps=29.97, df=True, channels=1, audio_stream_count=1),
            '',
        )
        if '오디오 1/2CH 확인 필요' not in issues or '오디오 없음' in issues:
            errors.append(f"  FAIL mono audio metadata detection: {status} / {issues}")

        qc_counts = RightPanel._batch_summary_counts(Probe(), [
            {'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
            {'black': 'ok', 'mute': 'ok', 'freeze': ''},
            {'black': 'ok', 'mute': 'ok', 'freeze': '', 'meta_status': '확인 필요'},
            {'black': 'found', 'mute': 'ok', 'freeze': 'found'},
            {'black': 'found', 'mute': 'found', 'freeze': ''},
            {'black': 'ok', 'mute': 'error', 'freeze': ''},
            {'black': '', 'mute': '', 'freeze': ''},
            {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
        ])
        expected_qc_counts = {
            'total': 8,
            'attention': 6,
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
        batch_summary_text = RightPanel._batch_summary_text(8, qc_counts, 12.34)
        if '파일접근 1' not in batch_summary_text or '파일없음' in batch_summary_text:
            errors.append(f"  FAIL batch QC summary file access label: {batch_summary_text}")
        status_summary = RightPanel._status_summary_text(Probe(), [
            {'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
            {'black': 'ok', 'mute': 'ok', 'freeze': ''},
            {'black': 'ok', 'mute': 'ok', 'freeze': '', 'meta_status': '확인 필요'},
            {'black': 'found', 'mute': 'found', 'freeze': ''},
            {'black': 'found', 'mute': 'ok', 'freeze': 'found'},
            {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'},
        ])
        if "정상 1" not in status_summary:
            errors.append(f"  FAIL status summary normal count: {status_summary}")
        if "확인 필요 4" not in status_summary:
            errors.append(f"  FAIL status summary attention count: {status_summary}")
        if "블랙/무음 정상 1" not in status_summary:
            errors.append(f"  FAIL status summary black/mute normal count: {status_summary}")
        if "블랙/무음 1" not in status_summary:
            errors.append(f"  FAIL status summary black/mute count: {status_summary}")
        if "복합 문제 1" not in status_summary:
            errors.append(f"  FAIL status summary complex count: {status_summary}")
        if "파일 없음 1" not in status_summary:
            errors.append(f"  FAIL status summary missing-file count: {status_summary}")
        class HtmlStatusProbe(Probe):
            _qc_piece_html = RightPanel._qc_piece_html
            _file_status_detail_html = RightPanel._file_status_detail_html
            _qc_status_has_count = staticmethod(RightPanel._qc_status_has_count)

            def _qc_status_text(self, value, kind):
                return RightPanel._qc_status_text(self, value, kind)

        detail_html = RightPanel._file_status_detail_html(
            HtmlStatusProbe(),
            {'black': 'ok', 'mute': 'found', 'freeze': '', 'black_count': 0, 'mute_count': 2},
        )
        if '무음 있음 2' not in detail_html or f"color:{C['red']}" not in detail_html:
            errors.append(f"  FAIL QC detail html issue color/count: {detail_html}")
        if '프리즈 미분석' not in detail_html or '프리즈 미분석 0' in detail_html:
            errors.append(f"  FAIL QC detail html pending count: {detail_html}")
        if f"color:{C['text2']}" not in detail_html:
            errors.append(f"  FAIL QC detail html pending color: {detail_html}")
        missing_detail_html = RightPanel._file_status_detail_html(
            HtmlStatusProbe(),
            {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'found', 'black_count': 1},
        )
        if '파일 접근 상태: 파일 없음' not in missing_detail_html or '블랙 있음' in missing_detail_html:
            errors.append(f"  FAIL missing file detail html: {missing_detail_html}")
        class FileItemHtmlProbe(HtmlStatusProbe):
            _path_name = staticmethod(RightPanel._path_name)
            _breakable_name_html = RightPanel._breakable_name_html
            _file_item_html = RightPanel._file_item_html
            _file_first_issue_hint_html = RightPanel._file_first_issue_hint_html
            _file_meta_issue_hint_html = RightPanel._file_meta_issue_hint_html
            _first_qc_issue_text = RightPanel._first_qc_issue_text
            _qc_issue_markers = RightPanel._qc_issue_markers
            _metadata_issue_text = staticmethod(RightPanel._metadata_issue_text)

        meta_item_html = RightPanel._file_item_html(
            FileItemHtmlProbe(),
            {
                'name': 'meta.mxf',
                'filepath': 'C:/qc/meta.mxf',
                '_availability_override': '',
                'black': 'ok',
                'mute': 'ok',
                'freeze': '',
                'meta_status': '확인 필요',
                'meta_issues': ['DF 타임코드 아님'],
            },
            '',
            '블랙/무음 정상',
            C['green'],
        )
        if f"color:{C['yellow']}" not in meta_item_html or '메타 확인: DF 타임코드 아님' not in meta_item_html:
            errors.append(f"  FAIL file item metadata warning html: {meta_item_html}")
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
            ('normal', {'black': 'ok', 'mute': 'ok', 'freeze': '', 'meta_status': '확인 필요'}, False, 'normal excludes metadata warning'),
            ('done', {'black': 'found', 'mute': 'ok', 'freeze': ''}, True, 'done includes black/mute completed'),
            ('done', {'black': 'ok', 'mute': '', 'freeze': ''}, False, 'done excludes mute pending'),
            ('attention', {'black': '', 'mute': '', 'freeze': ''}, True, 'attention includes untouched file'),
            ('attention', {'black': 'ok', 'mute': 'ok', 'freeze': ''}, False, 'attention excludes clean partial normal'),
            ('attention', {'black': 'ok', 'mute': 'ok', 'freeze': '', 'meta_status': '확인 필요'}, True, 'attention includes metadata warning'),
            ('attention', {'black': 'ok', 'mute': 'ok', 'freeze': 'found'}, True, 'attention includes freeze issue'),
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
            ('attention', {'filepath': 'C:/missing/file_not_available.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': 'ok'}, True, 'attention includes missing file'),
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
            {'black': 'ok', 'mute': 'ok', 'freeze': '', 'meta_status': '확인 필요'},
        ]
        filter_counts = RightPanel._filter_counts(filter_count_records)
        expected_filter_counts = {
            'all': 6,
            'done': 4,
            'attention': 5,
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
        if RightPanel._filter_button_text('attention', 4) != '확인 4':
            errors.append("  FAIL filter button text attention")
        if RightPanel._filter_button_text('issues', 3, compact=True) != '문제3':
            errors.append("  FAIL compact filter button text issues")
        if RightPanel._filter_button_text('attention', 4, compact=True) != '확인4':
            errors.append("  FAIL compact filter button text attention")
        if RightPanel._filter_button_text('all', 0, compact=True) != '전체0':
            errors.append("  FAIL compact filter button text all-zero")
        if RightPanel._filter_button_text('mute', 0) != '무음':
            errors.append("  FAIL filter button text zero-detail")
        if RightPanel._filter_button_text('all', 0) != '전체 0':
            errors.append("  FAIL filter button text all-zero")
        if '메타 확인' not in FILE_FILTER_TIPS.get('attention', ''):
            errors.append(f"  FAIL attention filter tooltip metadata scope: {FILE_FILTER_TIPS.get('attention')}")
        if '파일 접근' not in FILE_FILTER_TIPS.get('attention', '') or '파일 접근' not in FILE_FILTER_TIPS.get('issues', ''):
            errors.append(
                f"  FAIL filter tooltip file access scope: "
                f"attention={FILE_FILTER_TIPS.get('attention')} issues={FILE_FILTER_TIPS.get('issues')}"
            )
        if '확인 필요가 없는' not in FILE_FILTER_TIPS.get('normal', ''):
            errors.append(f"  FAIL normal filter tooltip attention exclusion: {FILE_FILTER_TIPS.get('normal')}")
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
            _attention_file_records = RightPanel._attention_file_records
            _file_needs_report_attention = staticmethod(RightPanel._file_needs_report_attention)
            _file_matches_filter = RightPanel._file_matches_filter
            _filter_label = RightPanel._filter_label
            _report_menu_state = RightPanel._report_menu_state
            _path_name = staticmethod(RightPanel._path_name)
            def _latest_report_path(self):
                return 'C:/reports/latest.csv'
            def _file_records(self):
                return [
                    {'name': 'clean.mxf', 'black': 'ok', 'mute': 'ok', 'freeze': ''},
                    {'name': 'pending.mxf', 'black': '', 'mute': '', 'freeze': ''},
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
        if report_menu_state.get('all_count') != 4 or report_menu_state.get('visible_count') != 2:
            errors.append(f"  FAIL report menu counts: {report_menu_state}")
        if report_menu_state.get('issue_count') != 2:
            errors.append(f"  FAIL report menu issue count: {report_menu_state}")
        issue_report_names = [
            f.get('name') for f in report_menu_state.get('issue_files', [])
        ]
        if issue_report_names != ['bad-a.mxf', 'bad-b.mxf']:
            errors.append(f"  FAIL report menu issue files: {issue_report_names}")
        if report_menu_state.get('attention_count') != 3:
            errors.append(f"  FAIL report menu attention count: {report_menu_state}")
        attention_report_names = [
            f.get('name') for f in report_menu_state.get('attention_files', [])
        ]
        if attention_report_names != ['bad-a.mxf', 'bad-b.mxf', 'pending.mxf']:
            errors.append(f"  FAIL report menu attention files: {attention_report_names}")
        if getattr(report_probe, '_filter_key', '') != 'issues':
            errors.append(f"  FAIL report menu filter restore: {getattr(report_probe, '_filter_key', '')}")
        if not report_menu_state.get('show_visible'):
            errors.append(f"  FAIL report menu visible scope: {report_menu_state}")
        if report_menu_state.get('visible_label') != '문제':
            errors.append(f"  FAIL report menu visible label: {report_menu_state}")
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
            {
                '파일명': 'unsupported.txt',
                'QC요약': '지원 안함',
                '파일존재': 'Y',
                '블랙상태': '정상',
                '무음상태': '정상',
                '프리즈상태': '정상',
                '메타정합성': '',
            },
            {'QC요약': '미분석', '파일존재': 'Y', '메타정합성': ''},
        ]
        report_counts = RightPanel._qc_report_summary_counts(report_rows)
        expected_report_counts = {
            'total': 7,
            'attention': 5,
            'normal': 1,
            'partial_normal': 1,
            'issue_files': 4,
            'black': 1,
            'mute': 0,
            'freeze': 1,
            'complex': 1,
            'error': 1,
            'pending': 1,
            'missing': 2,
            'metadata_warn': 2,
        }
        for key, expected in expected_report_counts.items():
            if report_counts.get(key) != expected:
                errors.append(f"  FAIL report summary count {key}: {report_counts.get(key)} != {expected}")
        report_lines = RightPanel._qc_report_summary_lines(report_rows)
        if not any('확인필요 5' in line and '문제파일 4' in line and '파일접근 2' in line for line in report_lines):
            errors.append(f"  FAIL report summary line issues: {report_lines}")
        if not any('복합문제 1' in line for line in report_lines):
            errors.append(f"  FAIL report summary line complex: {report_lines}")
        attention_lines = RightPanel._qc_report_attention_lines(report_rows)
        if '확인 필요 파일: 5개' not in attention_lines:
            errors.append(f"  FAIL report attention count: {attention_lines}")
        if not any('issue.mxf: 블랙 2, 프리즈 1, 메타 확인' in line for line in attention_lines):
            errors.append(f"  FAIL report attention issue detail: {attention_lines}")
        if not any('missing.mxf: 파일 없음' in line for line in attention_lines):
            errors.append(f"  FAIL report attention missing detail: {attention_lines}")
        if not any('unsupported.txt: 지원 안함' in line for line in attention_lines):
            errors.append(f"  FAIL report attention unsupported detail: {attention_lines}")
        if not any('파일: 미분석' in line for line in attention_lines):
            errors.append(f"  FAIL report attention pending detail: {attention_lines}")
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
        pending_fields = RightPanel._qc_report_attention_fields({
            'QC요약': '미분석',
            '파일존재': 'Y',
            '블랙상태': '미분석',
            '무음상태': '미분석',
            '프리즈상태': '미분석',
            '메타정합성': '',
        })
        if pending_fields != {'확인필요': 'Y', '확인사유': '미분석'}:
            errors.append(f"  FAIL report attention fields pending: {pending_fields}")
        unsupported_fields = RightPanel._qc_report_attention_fields(report_rows[5])
        if unsupported_fields != {'확인필요': 'Y', '확인사유': '지원 안함'}:
            errors.append(f"  FAIL report attention fields unsupported: {unsupported_fields}")
        freeze_pending_only_fields = RightPanel._qc_report_attention_fields(report_rows[1])
        if freeze_pending_only_fields != {'확인필요': 'N', '확인사유': ''}:
            errors.append(f"  FAIL report attention fields freeze-only pending: {freeze_pending_only_fields}")
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

            _qc_status_has_count = staticmethod(RightPanel._qc_status_has_count)

            def _qc_piece_text(self, label, state, count):
                return RightPanel._qc_piece_text(self, label, state, count)

            def _file_status_detail(self, f, unavailable=None):
                return RightPanel._file_status_detail(self, f, unavailable=unavailable)

            def _ranges_report_text(self, ranges, limit=20):
                return RightPanel._ranges_report_text(self, ranges, limit)

            def _file_status_badge(self, f, is_cue=False, unavailable=None):
                if unavailable:
                    return unavailable, '#f00'
                return qc_summary_from_status(f.get('black'), f.get('mute'), f.get('freeze')), '#fff'

        summary_text = RightPanel._qc_summary_clipboard_text(
            SummaryCopyProbe(),
            {
                'name': 'copy-me.mxf',
                'filepath': 'C:/qc/copy-me.mxf',
                '_availability_override': '',
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
                'meta_status': '확인 필요',
                'meta_issues': ['DF 타임코드 아님', '소스 TC 없음', '오디오 8CH 초과'],
            },
        )
        if '파일명: copy-me.mxf' not in summary_text or 'QC상태: 블랙 있음' not in summary_text:
            errors.append(f"  FAIL QC summary copy header: {summary_text}")
        if '상세: 블랙 있음 1 / 무음 정상 0 / 프리즈 미분석' not in summary_text:
            errors.append(f"  FAIL QC summary copy detail: {summary_text}")
        if '프리즈 미분석 0' in summary_text:
            errors.append(f"  FAIL QC summary copy unanalyzed count should be hidden: {summary_text}")
        if '첫문제: 블랙 00:00:01;00' not in summary_text:
            errors.append(f"  FAIL QC summary copy first issue: {summary_text}")
        if '메타: DF 타임코드 아님, 소스 TC 없음 외 1' not in summary_text:
            errors.append(f"  FAIL QC summary copy metadata issue: {summary_text}")
        if '블랙구간: 00:00:01;00>00:00:02;00(1.000s)' not in summary_text:
            errors.append(f"  FAIL QC summary copy ranges: {summary_text}")
        if '경로: C:/qc/copy-me.mxf' not in summary_text:
            errors.append(f"  FAIL QC summary copy path: {summary_text}")
        missing_summary_text = RightPanel._qc_summary_clipboard_text(
            SummaryCopyProbe(),
            {
                'name': 'missing-copy.mxf',
                'filepath': 'C:/missing/missing-copy.mxf',
                'black': 'found',
                'mute': 'ok',
                'freeze': '',
                'black_count': 1,
                'black_ranges': [{'start': 1.0, 'tc_start': '00:00:01;00'}],
                'meta_status': '확인 필요',
                'meta_issues': ['DF 타임코드 아님'],
            },
        )
        if 'QC상태: 파일 없음' not in missing_summary_text or '상세: 파일 접근 상태: 파일 없음' not in missing_summary_text:
            errors.append(f"  FAIL missing QC summary copy status: {missing_summary_text}")
        if '첫문제:' in missing_summary_text or '블랙구간:' in missing_summary_text or '메타:' in missing_summary_text:
            errors.append(f"  FAIL missing QC summary copy stale details hidden: {missing_summary_text}")

        class StaleSummaryCopyProbe(SummaryCopyProbe):
            def __init__(self):
                self.stale_refreshes = 0

            def _clear_stale_record_state(self, record, force=False):
                self.stale_refreshes += 1 if force else 0
                record['black'] = ''
                record['mute'] = ''
                record['freeze'] = ''
                record['black_count'] = 0
                record['black_ranges'] = []
                record['qc_summary'] = '미분석'
                return True

        stale_summary_probe = StaleSummaryCopyProbe()
        stale_summary_record = {
            'name': 'stale-copy.mxf',
            'filepath': 'C:/qc/stale-copy.mxf',
            '_availability_override': '',
            'black': 'found',
            'mute': 'ok',
            'freeze': '',
            'black_count': 1,
            'black_ranges': [{'start': 1.0, 'tc_start': '00:00:01;00'}],
        }
        stale_summary_text = RightPanel._qc_summary_clipboard_text(stale_summary_probe, stale_summary_record)
        if stale_summary_probe.stale_refreshes != 1:
            errors.append(f"  FAIL QC summary copy stale refresh count: {stale_summary_probe.stale_refreshes}")
        if 'QC상태: 미분석' not in stale_summary_text or '블랙구간:' in stale_summary_text:
            errors.append(f"  FAIL QC summary copy stale refresh text: {stale_summary_text}")

        issue_summary_text = RightPanel._issue_summary_clipboard_text(
            SummaryCopyProbe(),
            [
                {
                    'name': 'bad-a.mxf',
                    'filepath': 'C:/qc/bad-a.mxf',
                    '_availability_override': '',
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
                    '_availability_override': '',
                    'black': 'ok',
                    'mute': 'error',
                    'freeze': '',
                    'black_count': 0,
                    'mute_count': 0,
                    'freeze_count': 0,
                },
                {
                    'name': 'pending.mxf',
                    'filepath': 'C:/qc/pending.mxf',
                    '_availability_override': '',
                    'black': '',
                    'mute': '',
                    'freeze': '',
                    'black_count': 0,
                    'mute_count': 0,
                    'freeze_count': 0,
                },
                {
                    'name': 'meta.mxf',
                    'filepath': 'C:/qc/meta.mxf',
                    '_availability_override': '',
                    'black': 'ok',
                    'mute': 'ok',
                    'freeze': '',
                    'black_count': 0,
                    'mute_count': 0,
                    'freeze_count': 0,
                    'meta_status': '확인 필요',
                    'meta_issues': ['DF 타임코드 아님'],
                },
            ],
        )
        if 'MXF QC Player 확인 필요 파일 요약' not in issue_summary_text or '확인 필요 4개' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy header: {issue_summary_text}")
        if 'bad-a.mxf: 블랙 있음 / 블랙 있음 1 / 무음 정상 0 / 프리즈 미분석 / 첫문제 블랙 00:00:04;00' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy black detail: {issue_summary_text}")
        if 'bad-b.mxf: 검사 오류 / 블랙 정상 0 / 무음 오류 0 / 프리즈 미분석' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy error detail: {issue_summary_text}")
        if 'pending.mxf: 미분석 / 블랙 미분석 / 무음 미분석 / 프리즈 미분석' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy pending detail: {issue_summary_text}")
        if 'meta.mxf: 블랙/무음 정상 / 블랙 정상 0 / 무음 정상 0 / 프리즈 미분석 / 메타 확인: DF 타임코드 아님' not in issue_summary_text:
            errors.append(f"  FAIL issue summary copy metadata detail: {issue_summary_text}")
        if '프리즈 미분석 0' in issue_summary_text:
            errors.append(f"  FAIL issue summary copy unanalyzed count should be hidden: {issue_summary_text}")
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
        adjacent_next_issue_time = RightPanel._next_qc_issue_seek_time(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 1.0}],
                'mute_ranges': [{'start': 1.034}],
                'freeze_ranges': [{'start': 1.067}],
            },
            1.0,
        )
        if abs((adjacent_next_issue_time or 0) - 1.034) > 0.0001:
            errors.append(f"  FAIL adjacent-frame next QC issue seek time: {adjacent_next_issue_time}")
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
        adjacent_prev_issue_time = RightPanel._previous_qc_issue_seek_time(
            SummaryCopyProbe(),
            {
                'black_ranges': [{'start': 1.0}],
                'mute_ranges': [{'start': 1.034}],
                'freeze_ranges': [{'start': 1.067}],
            },
            1.034,
        )
        if abs((adjacent_prev_issue_time or 0) - 1.0) > 0.0001:
            errors.append(f"  FAIL adjacent-frame previous QC issue seek time: {adjacent_prev_issue_time}")
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

        class QcIssueSeekProbe:
            _file_path_text = staticmethod(RightPanel._file_path_text)
            _same_path_text = staticmethod(RightPanel._same_path_text)
            _path_name = staticmethod(RightPanel._path_name)
            _can_seek_current_qc_issue_file = RightPanel._can_seek_current_qc_issue_file
            _seek_first_qc_issue = RightPanel._seek_first_qc_issue
            _first_qc_issue_seek_time = RightPanel._first_qc_issue_seek_time
            _qc_issue_seek_times = RightPanel._qc_issue_seek_times
            _qc_issue_markers = RightPanel._qc_issue_markers

            def __init__(self, ready=True, loading=False):
                self.messages = []
                self.seeked = []
                self.vp = type('VP', (), {})()
                self.vp.cur_file = 'C:/qc/current.mxf'
                self.vp._loading = loading
                self.vp._metadata_ready = False
                self.vp._cue_ready = ready
                self.vp._media_transport_ready = lambda: bool(ready)
                self.vp.status_changed = type(
                    'Signal',
                    (),
                    {'emit': lambda _, msg: self.messages.append(msg)},
                )()
                self.seek_requested = type(
                    'Signal',
                    (),
                    {'emit': lambda _, sec: self.seeked.append(sec)},
                )()

        seek_record = {
            'filepath': 'C:/qc/current.mxf',
            'black_ranges': [{'start': 4.0}],
            'mute_ranges': [],
            'freeze_ranges': [],
        }
        seek_ready_probe = QcIssueSeekProbe(ready=True)
        if not RightPanel._can_seek_current_qc_issue_file(seek_ready_probe, 'C:/qc/current.mxf'):
            errors.append("  FAIL QC issue seek current ready")
        if not RightPanel._seek_first_qc_issue(seek_ready_probe, seek_record, 'C:/qc/current.mxf'):
            errors.append("  FAIL QC issue seek first ready result")
        if seek_ready_probe.seeked != [4.0]:
            errors.append(f"  FAIL QC issue seek emit: {seek_ready_probe.seeked}")
        seek_not_ready_probe = QcIssueSeekProbe(ready=False)
        if RightPanel._can_seek_current_qc_issue_file(seek_not_ready_probe, 'C:/qc/current.mxf'):
            errors.append("  FAIL QC issue seek should wait for cue")
        if RightPanel._seek_first_qc_issue(seek_not_ready_probe, seek_record, 'C:/qc/current.mxf'):
            errors.append("  FAIL QC issue seek should be blocked before cue")
        if seek_not_ready_probe.seeked:
            errors.append(f"  FAIL blocked QC issue seek emitted: {seek_not_ready_probe.seeked}")

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
            _file_access_block_status = staticmethod(
                lambda value, action='CUE': RightPanel._file_access_block_status(value, action)
            )
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

        class CueUnavailableProbe(CueBlockProbe):
            _is_video_file_path = staticmethod(lambda value: False)

        cue_unavailable_probe = CueUnavailableProbe(active=None)
        RightPanel._cue_exp_item(cue_unavailable_probe, CueBlockItem(str(Path(__file__))))
        if cue_unavailable_probe.loaded:
            errors.append("  FAIL unavailable cue should not load")
        if not any('지원 안함' in msg and 'CUE 불가' in msg for msg in cue_unavailable_probe.messages):
            errors.append(f"  FAIL unavailable cue reason status: {cue_unavailable_probe.messages}")
        if cue_unavailable_probe.refreshed != 1:
            errors.append(f"  FAIL unavailable cue should refresh once: {cue_unavailable_probe.refreshed}")

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

        class BatchAudioDoneProbe:
            _on_batch_audio_done = RightPanel._on_batch_audio_done
            _analysis_matches = RightPanel._analysis_matches
            _log_stale_analysis = RightPanel._log_stale_analysis
            _path_name = staticmethod(lambda value, default='파일': Path(str(value or '')).name or default)

            def __init__(self):
                self._batch_active = True
                self._batch_current = 'C:/qc/no_audio.mxf'
                self._batch_queue = ['C:/qc/next.mxf']
                self._batch_total = 3
                self._analysis_seq = 42
                self._analysis_seq_kind = 'audio'
                self._analysis_seq_file = self._batch_current
                self._audio_thread = None
                self.timeout_stopped = 0
                self.next_calls = 0
                self.status_calls = []
                self.ai_text = []
                self.vp = type('VP', (), {})()
                self.vp._set_file_status = lambda fp, **changes: self.status_calls.append((fp, changes))
                self.vp.ai_lbl = type(
                    'Label',
                    (),
                    {'setText': lambda _, msg: self.ai_text.append(msg)},
                )()

            def _stop_analysis_timeout(self):
                self.timeout_stopped += 1

            def _start_next_batch_file(self):
                self.next_calls += 1

        batch_audio_probe = BatchAudioDoneProbe()
        single_shots = []
        original_qtimer = rpm.QTimer
        try:
            class DummyQTimer:
                @staticmethod
                def singleShot(ms, callback):
                    single_shots.append(ms)

            rpm.QTimer = DummyQTimer
            RightPanel._on_batch_audio_done(batch_audio_probe, {'mutes': [], 'no_audio': True}, seq=42)
        except Exception as e:
            errors.append(f"  FAIL batch no-audio completion exception: {e}")
        finally:
            rpm.QTimer = original_qtimer
        if not batch_audio_probe.status_calls:
            errors.append("  FAIL batch no-audio status not stored")
        elif batch_audio_probe.status_calls[0][1].get('analysis') is not None:
            errors.append(f"  FAIL batch no-audio analysis not cleared: {batch_audio_probe.status_calls}")
        if not batch_audio_probe.ai_text or '2/3' not in batch_audio_probe.ai_text[-1] or '오디오 없음' not in batch_audio_probe.ai_text[-1]:
            errors.append(f"  FAIL batch no-audio ai text: {batch_audio_probe.ai_text}")
        if batch_audio_probe.timeout_stopped != 1 or single_shots != [80]:
            errors.append(f"  FAIL batch no-audio completion timing: stop={batch_audio_probe.timeout_stopped} shots={single_shots}")

        class AnalysisRestoreButton:
            def __init__(self):
                self.enabled = None

            def setEnabled(self, value):
                self.enabled = bool(value)

        class AnalysisRestoreProbe:
            _set_transport_enabled = RightPanel._set_transport_enabled
            _analysis_transport_ready = RightPanel._analysis_transport_ready
            _analysis_cue_button_ready = RightPanel._analysis_cue_button_ready
            _restore_transport_after_analysis = RightPanel._restore_transport_after_analysis

            def __init__(self, current=True, media_ready=True, loading=False, records=True):
                self.current = current
                self.media_ready = media_ready
                self.records = records

                class VP:
                    def __init__(self, owner):
                        self.owner = owner
                        self._loading = loading
                        for name in (
                            'btn_folder', 'btn_m1', 'btn_gos', 'btn_rew', 'btn_play',
                            'btn_stop', 'btn_fwd', 'btn_goe', 'btn_p1', 'btn_cue',
                        ):
                            setattr(self, name, AnalysisRestoreButton())

                    def _media_transport_ready(self):
                        return self.owner.media_ready

                self.vp = VP(self)

            def _current_video_file(self):
                return 'C:/qc/current.mxf' if self.current else ''

            def _video_file_records(self):
                return [{'filepath': 'C:/qc/current.mxf'}] if self.records else []

        ready_restore = AnalysisRestoreProbe(current=True, media_ready=True, loading=False, records=True)
        RightPanel._restore_transport_after_analysis(ready_restore)
        if ready_restore.vp.btn_play.enabled is not True or ready_restore.vp.btn_cue.enabled is not True:
            errors.append(
                f"  FAIL analysis restore ready buttons: play={ready_restore.vp.btn_play.enabled} cue={ready_restore.vp.btn_cue.enabled}"
            )

        missing_restore = AnalysisRestoreProbe(current=False, media_ready=True, loading=False, records=True)
        RightPanel._restore_transport_after_analysis(missing_restore)
        if missing_restore.vp.btn_play.enabled is not False or missing_restore.vp.btn_cue.enabled is not True:
            errors.append(
                f"  FAIL analysis restore missing-current buttons: play={missing_restore.vp.btn_play.enabled} cue={missing_restore.vp.btn_cue.enabled}"
            )

        loading_restore = AnalysisRestoreProbe(current=True, media_ready=True, loading=True, records=True)
        RightPanel._restore_transport_after_analysis(loading_restore)
        if loading_restore.vp.btn_play.enabled is not False or loading_restore.vp.btn_cue.enabled is not False:
            errors.append(
                f"  FAIL analysis restore loading buttons: play={loading_restore.vp.btn_play.enabled} cue={loading_restore.vp.btn_cue.enabled}"
            )

        class AnalysisFinishProbe:
            _finish_analysis_mode = RightPanel._finish_analysis_mode

            def __init__(self):
                self._analysis_active = 'black'
                self._analysis_paused_playback = True
                self._analysis_paused_meters = True
                self.restored = 0
                self.buttons_busy = []
                self.current_calls = 0
                self._analysis_cancel_buttons = [AnalysisRestoreButton()]

            def _restore_transport_after_analysis(self):
                self.restored += 1

            def _set_analysis_buttons_busy(self, kind=None, busy=False):
                self.buttons_busy.append((kind, busy))

            def _current_video_file(self):
                self.current_calls += 1
                return 'C:/qc/current.mxf'

        shutdown_finish_probe = AnalysisFinishProbe()
        RightPanel._finish_analysis_mode(shutdown_finish_probe, restore_runtime=False)
        if shutdown_finish_probe.restored or shutdown_finish_probe.buttons_busy or shutdown_finish_probe.current_calls:
            errors.append(
                "  FAIL shutdown analysis finish should not restore transport/meters"
            )
        if (
            shutdown_finish_probe._analysis_active is not None
            or shutdown_finish_probe._analysis_paused_playback
            or shutdown_finish_probe._analysis_paused_meters
            or shutdown_finish_probe._analysis_cancel_buttons[0].enabled is not False
        ):
            errors.append("  FAIL shutdown analysis finish should clear analysis flags")

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
            _prune_recent_files_by_paths = RightPanel._prune_recent_files_by_paths
            _file_record_for_path = RightPanel._file_record_for_path

            def __init__(self):
                self.updated = 0
                self.saved_recent = None
                self._settings = {
                    'recent_files': [
                        'C:/missing/remove_me.mxf',
                        'C:/keep/keep_me.mxf',
                        'C:/other/other.mxf',
                    ]
                }
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
                self.vp.remembered_recent = []
                self.vp._settings = dict(self._settings)
                self.vp._refresh_clip_list = lambda: setattr(self.vp, 'refreshed', self.vp.refreshed + 1)
                self.vp.eject_clip = lambda: setattr(self.vp, 'ejected', self.vp.ejected + 1)
                self.vp._remember_recent_file = lambda path: self.vp.remembered_recent.append(path)

            def _update_explorer(self, info, clip_id):
                self.updated += 1

            def _file_records(self):
                return [f for f in self.vp._files if isinstance(f, dict) and f.get('filepath')]

            def _save_recent_files(self, recent_files):
                self.saved_recent = list(recent_files or [])
                self._settings['recent_files'] = self.saved_recent
                self.vp._settings = dict(self._settings)

            def _persist_relinked_qc(self, record):
                return None

        remove_probe = RemoveProbe()
        removed = RightPanel._remove_file_records_by_paths(remove_probe, ['C:/missing/remove_me.mxf'])
        if removed != 1 or len(remove_probe.vp._files) != 1:
            errors.append(f"  FAIL remove missing-file records: removed={removed} files={remove_probe.vp._files}")
        if remove_probe.vp.refreshed != 1 or remove_probe.updated != 1:
            errors.append("  FAIL remove missing-file records refresh path")
        if remove_probe.saved_recent != ['C:/keep/keep_me.mxf', 'C:/other/other.mxf']:
            errors.append(f"  FAIL remove missing-file records recent prune: {remove_probe.saved_recent}")

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
        relink_probe._settings = {
            'recent_files': [
                'C:/missing/relink_me.mxf',
                'C:/keep/keep_me.mxf',
            ]
        }
        relink_probe.vp._settings = dict(relink_probe._settings)
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
            if record.get('ext') != 'MXF' or record.get('size') != 4 or not record.get('mtime_ns'):
                errors.append(f"  FAIL relink missing-file metadata fields: {record}")
            if relink_probe.vp.refreshed != 1 or relink_probe.updated != 1:
                errors.append("  FAIL relink missing-file refresh path")
            if relink_probe.saved_recent != ['C:/keep/keep_me.mxf']:
                errors.append(f"  FAIL relink old recent prune: {relink_probe.saved_recent}")
            if relink_probe.vp.remembered_recent != [str(relink_target)]:
                errors.append(f"  FAIL relink new recent remember: {relink_probe.vp.remembered_recent}")

        current_relink_probe = RemoveProbe()
        current_relink_probe.vp._files = [
            {
                'filepath': 'C:/missing/current_relink.mxf',
                'name': 'current_relink.mxf',
                'black': '',
                'mute': '',
                'freeze': '',
            }
        ]
        current_relink_probe.vp.cur_file = 'C:/missing/current_relink.mxf'
        current_relink_probe.vp.loaded = []

        def _load_current_relink(path):
            current_relink_probe.vp.loaded.append(path)
            current_relink_probe.vp.cur_file = path

        current_relink_probe.vp.load_file = _load_current_relink
        with tempfile.TemporaryDirectory() as tmp_dir:
            relink_target = Path(tmp_dir) / 'current_relinked_target.mxf'
            relink_target.write_bytes(b'test')
            result = RightPanel._relink_file_record_path(
                current_relink_probe,
                'C:/missing/current_relink.mxf',
                str(relink_target),
            )
            if result != 'relinked':
                errors.append(f"  FAIL relink current-file result: {result}")
            if current_relink_probe.vp.ejected != 1:
                errors.append("  FAIL relink current-file eject")
            if current_relink_probe.vp.loaded != [str(relink_target)]:
                errors.append(f"  FAIL relink current-file reload: {current_relink_probe.vp.loaded}")
            if current_relink_probe.vp.cur_file != str(relink_target):
                errors.append(f"  FAIL relink current-file cur_file: {current_relink_probe.vp.cur_file}")

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

            class ContextActionProbe:
                _file_path_text = staticmethod(RightPanel._file_path_text)
                _file_unavailable_badge = staticmethod(RightPanel._file_unavailable_badge)
                _existing_dir_for_path = staticmethod(RightPanel._existing_dir_for_path)
                _file_context_action_state = RightPanel._file_context_action_state

            existing_mxf = existing_root / 'context-ok.mxf'
            existing_mxf.write_bytes(b'test')
            ok_state = RightPanel._file_context_action_state(ContextActionProbe(), str(existing_mxf))
            if not ok_state.get('can_cue') or ok_state.get('can_relink') or not ok_state.get('can_open_location'):
                errors.append(f"  FAIL context menu state valid file: {ok_state}")
            missing_state = RightPanel._file_context_action_state(ContextActionProbe(), str(existing_root / 'missing.mxf'))
            if missing_state.get('can_cue') or not missing_state.get('can_relink') or not missing_state.get('can_open_location'):
                errors.append(f"  FAIL context menu state missing file: {missing_state}")
            unsupported_file = existing_root / 'not-video.txt'
            unsupported_file.write_text('text', encoding='utf-8')
            unsupported_state = RightPanel._file_context_action_state(ContextActionProbe(), str(unsupported_file))
            if unsupported_state.get('can_cue') or unsupported_state.get('unavailable') != '지원 안함':
                errors.append(f"  FAIL context menu state unsupported file: {unsupported_state}")

            class RecentMenuProbe:
                _file_path_text = staticmethod(RightPanel._file_path_text)
                _path_name = classmethod(RightPanel._path_name.__func__)
                _file_unavailable_badge = classmethod(RightPanel._file_unavailable_badge.__func__)
                _recent_dir_unavailable_badge = classmethod(RightPanel._recent_dir_unavailable_badge.__func__)
                _recent_menu_entry_state = RightPanel._recent_menu_entry_state
                _recent_unavailable_count = RightPanel._recent_unavailable_count
                _clean_recent_entries = RightPanel._clean_recent_entries

            missing_recent = existing_root / 'recent-missing.mxf'
            recent_files, recent_dirs = RightPanel._clean_recent_entries(RecentMenuProbe(), {
                'recent_files': [str(existing_mxf), str(missing_recent), str(unsupported_file)],
                'recent_dirs': [str(existing_root), str(existing_root / 'missing-dir')],
            })
            if str(missing_recent) not in recent_files:
                errors.append(f"  FAIL recent missing file preserved: {recent_files}")
            if str(unsupported_file) in recent_files:
                errors.append(f"  FAIL recent unsupported file kept: {recent_files}")
            if str(existing_root / 'missing-dir') not in recent_dirs:
                errors.append(f"  FAIL recent missing dir preserved: {recent_dirs}")
            recent_ok = RightPanel._recent_menu_entry_state(RecentMenuProbe(), "file", str(existing_mxf))
            recent_missing = RightPanel._recent_menu_entry_state(RecentMenuProbe(), "file", str(missing_recent))
            recent_dir_missing = RightPanel._recent_menu_entry_state(RecentMenuProbe(), "dir", str(existing_root / 'missing-dir'))
            if not recent_ok.get('available') or recent_ok.get('badge'):
                errors.append(f"  FAIL recent valid file state: {recent_ok}")
            if recent_missing.get('available') or recent_missing.get('badge') != '파일 없음':
                errors.append(f"  FAIL recent missing file state: {recent_missing}")
            if recent_dir_missing.get('available') or recent_dir_missing.get('badge') != '폴더 없음':
                errors.append(f"  FAIL recent missing dir state: {recent_dir_missing}")
            unavailable_count = RightPanel._recent_unavailable_count(RecentMenuProbe(), recent_files, recent_dirs)
            if unavailable_count != 2:
                errors.append(f"  FAIL recent unavailable count: {unavailable_count}")

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
        audio_mix.set_channels([])
        if audio_mix.channels != []:
            errors.append(f"  FAIL audio mix explicit empty channels: {audio_mix.channels}")
        audio_mix.set_channels(None)
        if audio_mix.channels != [1, 2]:
            errors.append(f"  FAIL audio mix default channels after None: {audio_mix.channels}")
        audio_mix.set_channels(['bad'])
        if audio_mix.channels != [1, 2]:
            errors.append(f"  FAIL audio mix invalid channel fallback: {audio_mix.channels}")
        transcode = TranscodeThread('C:/qc/no_audio.mxf', [(1, 2)])
        if transcode._build_filter([], [(1, 2)]) is not None:
            errors.append("  FAIL no-audio transcode filter should be video-only")
        fallback_audio_fc = transcode._build_filter(None, [(1, 2)])
        if not fallback_audio_fc or '[0:a]' not in fallback_audio_fc:
            errors.append(f"  FAIL unknown-audio transcode fallback: {fallback_audio_fc}")
        no_audio_cmd = transcode._make_cmd('C:/qc/out.mp4', None, duration=1)
        if '-an' not in no_audio_cmd or '[aout]' in no_audio_cmd:
            errors.append(f"  FAIL no-audio transcode command: {no_audio_cmd}")
        no_audio_remux = transcode._make_remux_cmd('C:/qc/out.mov', None)
        if '-an' not in no_audio_remux or '[aout]' in no_audio_remux:
            errors.append(f"  FAIL no-audio remux command: {no_audio_remux}")
        feedback_new = VideoPanel._file_add_feedback_text(3, 3)
        if feedback_new != '✓ 파일 3개 추가 — CUE 또는 더블클릭으로 원본 파일을 바로 재생합니다':
            errors.append(f"  FAIL file add feedback new: {feedback_new}")
        feedback_mixed = VideoPanel._file_add_feedback_text(3, 1, action_hint='첫 파일 CUE')
        if feedback_mixed != '✓ 파일 1개 추가 / 중복 2개 — 첫 파일 CUE':
            errors.append(f"  FAIL file add feedback mixed: {feedback_mixed}")
        feedback_duplicate = VideoPanel._file_add_feedback_text(2, 0, action_hint='')
        if feedback_duplicate != '↺ 이미 목록에 있는 파일 2개':
            errors.append(f"  FAIL file add feedback duplicate: {feedback_duplicate}")
        feedback_invalid_mixed = VideoPanel._file_add_feedback_text(4, 1, 2, action_hint='')
        if feedback_invalid_mixed != '✓ 파일 1개 추가 / 중복 1개 / 지원 안 함 2개':
            errors.append(f"  FAIL file add feedback invalid mixed: {feedback_invalid_mixed}")
        feedback_invalid_only = VideoPanel._file_add_feedback_text(2, 0, 2, action_hint='')
        if feedback_invalid_only != '⚠ 지원 안 함 2개':
            errors.append(f"  FAIL file add feedback invalid only: {feedback_invalid_only}")
        class CueStatusProbe:
            _quick_file_preflight = VideoPanel._quick_file_preflight
            _cue_block_status_text = VideoPanel._cue_block_status_text
            _display_file_name = staticmethod(VideoPanel._display_file_name)
            _path_access_hint = VideoPanel._path_access_hint

        cue_block_text = VideoPanel._cue_block_status_text(CueStatusProbe(), str(Path(__file__)))
        if '지원하지 않는 파일 형식입니다' not in cue_block_text or 'CUE 불가' not in cue_block_text:
            errors.append(f"  FAIL CUE block status unsupported reason: {cue_block_text}")
        class RuntimeFlagProbe:
            _clear_file_runtime_flags = VideoPanel._clear_file_runtime_flags

            def __init__(self):
                self._files = [
                    {'filepath': 'C:/qc/clean.mxf', 'cue': True, 'playing': True, 'black': 'ok', 'mute': 'ok'},
                    {'filepath': 'C:/qc/issue.mxf', 'cue': True, 'playing': False, 'black': 'found', 'mute': 'ok'},
                    {'filepath': 'C:/qc/idle.mxf', 'cue': False, 'playing': True},
                ]

        runtime_probe = RuntimeFlagProbe()
        if not VideoPanel._clear_file_runtime_flags(runtime_probe, clear_cue=True):
            errors.append("  FAIL runtime flag clear should report change")
        if any(f.get('cue') or f.get('playing') for f in runtime_probe._files):
            errors.append(f"  FAIL runtime flag clear should clear all cue/playing flags: {runtime_probe._files}")
        runtime_probe = RuntimeFlagProbe()
        VideoPanel._clear_file_runtime_flags(runtime_probe, clear_cue=False)
        if runtime_probe._files[0].get('playing') or not runtime_probe._files[0].get('cue'):
            errors.append(f"  FAIL runtime flag clear without cue should keep cue only: {runtime_probe._files}")

        class CurrentUnavailableProbe:
            _handle_unavailable_current_file = VideoPanel._handle_unavailable_current_file
            _display_file_name = staticmethod(VideoPanel._display_file_name)
            _video_file_path = lambda self, _fp: None

            def __init__(self):
                self.cur_file = 'C:/missing/current.mxf'
                self.cur_info = {'filename': 'current.mxf'}
                self._metadata_ready = True
                self._cue_ready = True
                self.ejected = 0
                self.messages = []
                self.status_changed = type(
                    'Signal',
                    (),
                    {'emit': lambda _, msg: self.messages.append(msg)},
                )()

            def eject_clip(self):
                self.ejected += 1
                self.cur_file = None
                self.cur_info = {}
                self._metadata_ready = False
                self._cue_ready = False

        unavailable_current_probe = CurrentUnavailableProbe()
        class FakeVideoPanelLog:
            def __init__(self):
                self.warnings = []
                self.debugs = []

            def warning(self, msg):
                self.warnings.append(str(msg))

            def debug(self, msg):
                self.debugs.append(str(msg))

        original_vpm_log = vpm.log
        fake_vpm_log = FakeVideoPanelLog()
        try:
            vpm.log = fake_vpm_log
            handled_unavailable_current = VideoPanel._handle_unavailable_current_file(unavailable_current_probe)
        finally:
            vpm.log = original_vpm_log
        if not handled_unavailable_current:
            errors.append("  FAIL unavailable current file should be handled")
        if not any('current cue file became unavailable' in msg for msg in fake_vpm_log.warnings):
            errors.append(f"  FAIL unavailable current file warning capture: {fake_vpm_log.warnings}")
        if unavailable_current_probe.ejected != 1 or unavailable_current_probe.cur_file is not None:
            errors.append(
                f"  FAIL unavailable current file should eject: "
                f"ejected={unavailable_current_probe.ejected} cur={unavailable_current_probe.cur_file}"
            )
        if not any('CUE 파일 접근 불가' in msg for msg in unavailable_current_probe.messages):
            errors.append(f"  FAIL unavailable current file status: {unavailable_current_probe.messages}")

        class ClearClipsProbe:
            clear_clips = VideoPanel.clear_clips

            def __init__(self):
                self._files = [{'filepath': 'C:/qc/current.mxf'}]
                self.cur_file = 'C:/qc/current.mxf'
                self.ejected = 0
                self.eject_seen_files = None
                self.messages = []
                self.clip_list = type(
                    'ClipList',
                    (),
                    {'clear': lambda inner: setattr(self, 'clip_cleared', True)},
                )()
                self.status_changed = type(
                    'Signal',
                    (),
                    {'emit': lambda _, msg: self.messages.append(msg)},
                )()

            def eject_clip(self):
                self.ejected += 1
                self.eject_seen_files = list(self._files)
                self.cur_file = None

        clear_clips_probe = ClearClipsProbe()
        VideoPanel.clear_clips(clear_clips_probe)
        if clear_clips_probe._files or clear_clips_probe.eject_seen_files:
            errors.append(
                f"  FAIL clear clips should empty files before eject: "
                f"files={clear_clips_probe._files} seen={clear_clips_probe.eject_seen_files}"
            )
        if clear_clips_probe.ejected != 1 or clear_clips_probe.cur_file is not None:
            errors.append(
                f"  FAIL clear clips should eject current state: "
                f"ejected={clear_clips_probe.ejected} cur={clear_clips_probe.cur_file}"
            )
        if not getattr(clear_clips_probe, 'clip_cleared', False):
            errors.append("  FAIL clear clips should clear clip list")
        if not any('파일 목록 비움' in msg for msg in clear_clips_probe.messages):
            errors.append(f"  FAIL clear clips status message: {clear_clips_probe.messages}")

        class RecentPruneProbe:
            _settings_entries = staticmethod(VideoPanel._settings_entries)
            _prune_recent_entries = VideoPanel._prune_recent_entries

            def __init__(self, settings):
                self._settings = settings

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            existing_recent = tmp_path / 'existing.mxf'
            unsupported_recent = tmp_path / 'notes.txt'
            existing_recent.write_bytes(b'test')
            unsupported_recent.write_text('test', encoding='utf-8')
            missing_recent = tmp_path / 'moved_clip.mxf'
            existing_dir = tmp_path / 'media'
            existing_dir.mkdir()
            missing_dir = tmp_path / 'missing_media'
            recent_probe = RecentPruneProbe({
                'recent_files': [
                    str(existing_recent),
                    str(missing_recent),
                    str(unsupported_recent),
                    str(existing_recent),
                ],
                'recent_dirs': [
                    str(existing_dir),
                    str(missing_dir),
                    str(existing_dir),
                ],
            })
            saved_recent_settings = []
            original_save_settings = vpm.save_settings
            try:
                def fake_save_settings(**kwargs):
                    saved_recent_settings.append(kwargs)
                    recent_probe._settings.update(kwargs)
                    return dict(recent_probe._settings)

                vpm.save_settings = fake_save_settings
                VideoPanel._prune_recent_entries(recent_probe)
            finally:
                vpm.save_settings = original_save_settings
            expected_recent_files = [str(existing_recent), str(missing_recent)]
            expected_recent_dirs = [str(existing_dir), str(missing_dir)]
            if not saved_recent_settings:
                errors.append("  FAIL recent prune should persist normalized settings")
            else:
                saved = saved_recent_settings[-1]
                if saved.get('recent_files') != expected_recent_files:
                    errors.append(f"  FAIL recent prune files: {saved.get('recent_files')}")
                if saved.get('recent_dirs') != expected_recent_dirs:
                    errors.append(f"  FAIL recent prune dirs: {saved.get('recent_dirs')}")

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
        class ChannelControlProbe:
            _safe_int_value = staticmethod(VideoPanel._safe_int_value)
            cur_info = {}
            cur_file = 'C:/qc/pending_metadata.mxf'
            _selected_chs = [1, 2]
        pending_channel_controls = VideoPanel._audio_channel_control_count(ChannelControlProbe())
        if pending_channel_controls != 2:
            errors.append(f"  FAIL pending metadata channel controls: {pending_channel_controls}")
        ready_channel_controls = VideoPanel._audio_channel_control_count(
            ChannelControlProbe(), {'audio_stream_count': 8, 'channels': 1}
        )
        if ready_channel_controls != 8:
            errors.append(f"  FAIL ready metadata channel controls: {ready_channel_controls}")
        class ChannelDisplayProbe:
            _safe_int_value = staticmethod(VideoPanel._safe_int_value)
            _audio_source_count_from_info = staticmethod(VideoPanel._audio_source_count_from_info)
            _audio_channel_display_text = VideoPanel._audio_channel_display_text
        display_probe = ChannelDisplayProbe()
        if VideoPanel._audio_channel_display_text(display_probe, {'audio_stream_count': 16, 'channels': 1}) != '8CH/16CH':
            errors.append("  FAIL capped source channel display text")
        if VideoPanel._audio_channel_display_text(display_probe, {'audio_stream_count': 8, 'channels': 1}) != '8CH':
            errors.append("  FAIL 8-channel display text")
        if VideoPanel._audio_channel_display_text(display_probe, {'audio_stream_count': 0, 'channels': 0}) != '0CH':
            errors.append("  FAIL no-audio channel display text")
        if VideoPanel._audio_source_count_from_info({'audio_stream_count': 0, 'channels': 0}) != 0:
            errors.append("  FAIL no-audio source count")
        if VideoPanel._audio_source_count_from_info({'audio_stream_count': 4, 'channels': 1}) != 4:
            errors.append("  FAIL multi-stream source count")
        provisional_display_info = VideoPanel._provisional_audio_display_info(
            {'audio_stream_count': 16, 'channels': 1},
            8,
        )
        if VideoPanel._audio_channel_display_text(display_probe, provisional_display_info) != '8CH/16CH':
            errors.append("  FAIL provisional capped source channel display text")
        provisional_unknown_info = VideoPanel._provisional_audio_display_info({}, 8)
        if VideoPanel._audio_channel_display_text(display_probe, provisional_unknown_info) != '8CH':
            errors.append("  FAIL provisional unknown channel display text")
        provisional_no_audio_info = VideoPanel._provisional_audio_display_info(
            {'metadata_hint': True, 'audio_stream_count': 0, 'channels': 0},
            8,
        )
        if VideoPanel._audio_channel_display_text(display_probe, provisional_no_audio_info) != '0CH':
            errors.append("  FAIL provisional no-audio hint display text")
        if not VideoPanel._metadata_hint_says_no_audio({'metadata_hint': True, 'audio_stream_count': 0, 'channels': 0}):
            errors.append("  FAIL metadata hint no-audio detection")
        if VideoPanel._metadata_hint_says_no_audio({'metadata_hint': True, 'audio_stream_count': 1, 'channels': 0}):
            errors.append("  FAIL metadata hint with audio misdetected as no-audio")
        class AudioRestartProbe:
            _safe_int_value = staticmethod(VideoPanel._safe_int_value)
            _metadata_audio_restart_required = VideoPanel._metadata_audio_restart_required

            def __init__(self, selected):
                self.selected = selected

            def _get_selected_audio_channels(self):
                return list(self.selected)

        audio_restart = AudioRestartProbe([1, 2])
        class AudioExpectedProbe:
            _safe_int_value = staticmethod(VideoPanel._safe_int_value)
            _audio_source_count_from_info = staticmethod(VideoPanel._audio_source_count_from_info)
            _metadata_hint_says_no_audio = staticmethod(VideoPanel._metadata_hint_says_no_audio)
            _audio_mix_expected = VideoPanel._audio_mix_expected

            def __init__(self, metadata_ready, info, selected=None):
                self.cur_file = 'C:/qc/audio_expected.mxf'
                self._metadata_ready = metadata_ready
                self.cur_info = dict(info or {})
                self.selected = [1, 2] if selected is None else list(selected)

            def _get_selected_audio_channels(self):
                return list(self.selected)

        if VideoPanel._audio_mix_expected(
            AudioExpectedProbe(True, {'audio_stream_count': 0, 'channels': 0})
        ):
            errors.append("  FAIL no-audio metadata should not expect audio mix")
        if not VideoPanel._audio_mix_expected(
            AudioExpectedProbe(True, {'audio_stream_count': 1, 'channels': 2})
        ):
            errors.append("  FAIL audio metadata should expect audio mix")
        if not VideoPanel._audio_mix_expected(
            AudioExpectedProbe(False, {'audio_stream_count': 0, 'channels': 0})
        ):
            errors.append("  FAIL pending metadata should keep fallback audio expected")
        if VideoPanel._audio_mix_expected(
            AudioExpectedProbe(False, {'metadata_hint': True, 'audio_stream_count': 0, 'channels': 0})
        ):
            errors.append("  FAIL no-audio metadata hint should not expect fallback audio")
        class PlayWatchAudioProbe(AudioExpectedProbe):
            _play_start_audio_expected = VideoPanel._play_start_audio_expected

        if not VideoPanel._play_start_audio_expected(
            PlayWatchAudioProbe(False, {'audio_stream_count': 0, 'channels': 0})
        ):
            errors.append("  FAIL play watchdog should expect fallback audio before metadata")
        if VideoPanel._play_start_audio_expected(
            PlayWatchAudioProbe(False, {'metadata_hint': True, 'audio_stream_count': 0, 'channels': 0})
        ):
            errors.append("  FAIL play watchdog should not expect no-audio hint")
        no_selected_watch_probe = PlayWatchAudioProbe(False, {'audio_stream_count': 0, 'channels': 0}, selected=[])
        if VideoPanel._play_start_audio_expected(no_selected_watch_probe):
            errors.append("  FAIL play watchdog should ignore empty audio selection")
        class FakeAudioCheck:
            def __init__(self, checked, enabled):
                self._checked = bool(checked)
                self._enabled = bool(enabled)
            def isChecked(self):
                return self._checked
            def isEnabled(self):
                return self._enabled

        class AudioSelectionProbe:
            _audio_source_count_from_info = staticmethod(VideoPanel._audio_source_count_from_info)
            _metadata_hint_says_no_audio = staticmethod(VideoPanel._metadata_hint_says_no_audio)
            _audio_selection_unavailable = VideoPanel._audio_selection_unavailable
            _get_selected_audio_channels = VideoPanel._get_selected_audio_channels

            def __init__(self, metadata_ready, info, checks):
                self._metadata_ready = metadata_ready
                self.cur_info = dict(info or {})
                self._ch_checks = list(checks or [])

        if VideoPanel._get_selected_audio_channels(AudioSelectionProbe(
            True,
            {'audio_stream_count': 0, 'channels': 0},
            [(FakeAudioCheck(False, False), 1), (FakeAudioCheck(False, False), 2)],
        )) != []:
            errors.append("  FAIL no-audio selected channels should be empty")
        if VideoPanel._get_selected_audio_channels(AudioSelectionProbe(
            False,
            {},
            [(FakeAudioCheck(False, False), 1), (FakeAudioCheck(False, False), 2)],
        )) != [1, 2]:
            errors.append("  FAIL unknown-audio selected channels fallback")
        if VideoPanel._get_selected_audio_channels(AudioSelectionProbe(
            True,
            {'audio_stream_count': 2, 'channels': 1},
            [(FakeAudioCheck(True, True), 1), (FakeAudioCheck(False, True), 2)],
        )) != [1]:
            errors.append("  FAIL enabled checked audio channel selection")
        if VideoPanel._audio_channel_label([]) != '오디오 없음':
            errors.append("  FAIL empty audio channel label")
        if VideoPanel._audio_channel_label([1, '2', 2, 9, 'bad']) != '1,2':
            errors.append("  FAIL cleaned audio channel label")
        if VideoPanel._audio_channel_status_label([]) != '오디오 없음':
            errors.append("  FAIL empty audio channel status label")
        if VideoPanel._audio_channel_status_label([1, 2]) != 'CH 1,2':
            errors.append("  FAIL prefixed audio channel status label")
        if VideoPanel._metadata_audio_restart_required(
            audio_restart,
            {'audio_stream_count': 1, 'channels': 2},
            True,
            {'running': True, 'active_layout_known': False},
        ):
            errors.append("  FAIL fallback 1/2 audio should stay running after metadata")
        if not VideoPanel._metadata_audio_restart_required(
            audio_restart,
            {'audio_stream_count': 8, 'channels': 1},
            True,
            {'running': True, 'active_layout_known': False},
        ):
            errors.append("  FAIL fallback multi-mono audio should restart after metadata")
        if VideoPanel._metadata_audio_restart_required(
            audio_restart,
            {'audio_stream_count': 8, 'channels': 1},
            False,
            {
                'running': True,
                'active_layout_known': True,
                'audio_stream_count': 8,
                'channel_count': 1,
                'channels': (1, 2),
            },
        ):
            errors.append("  FAIL matching known audio layout should not restart after metadata")
        if not VideoPanel._metadata_audio_restart_required(
            audio_restart,
            {'audio_stream_count': 8, 'channels': 1},
            False,
            {
                'running': True,
                'active_layout_known': True,
                'audio_stream_count': 1,
                'channel_count': 2,
                'channels': (1, 2),
            },
        ):
            errors.append("  FAIL changed known audio layout should restart after metadata")
        class TransportReadyProbe:
            _metadata_ready = False
            _cue_ready = False
        transport_probe = TransportReadyProbe()
        if VideoPanel._metadata_or_cue_ready(transport_probe):
            errors.append("  FAIL transport ready before cue/metadata")
        transport_probe._cue_ready = True
        if not VideoPanel._metadata_or_cue_ready(transport_probe):
            errors.append("  FAIL transport ready after cue")
        transport_probe._cue_ready = False
        transport_probe._metadata_ready = True
        if not VideoPanel._metadata_or_cue_ready(transport_probe):
            errors.append("  FAIL transport ready after metadata")
        class MediaTransportProbe:
            _metadata_or_cue_ready = VideoPanel._metadata_or_cue_ready
            cur_file = ''
            _metadata_ready = False
            _cue_ready = False
        media_transport_probe = MediaTransportProbe()
        if VideoPanel._media_transport_ready(media_transport_probe):
            errors.append("  FAIL media transport ready without file")
        media_transport_probe.cur_file = 'C:/qc/sample.mxf'
        if VideoPanel._media_transport_ready(media_transport_probe):
            errors.append("  FAIL media transport ready before cue/metadata")
        media_transport_probe._cue_ready = True
        if not VideoPanel._media_transport_ready(media_transport_probe):
            errors.append("  FAIL media transport ready with file and cue")
        class AnalysisButtonsReadyProbe:
            _metadata_or_cue_ready = VideoPanel._metadata_or_cue_ready
            _media_transport_ready = VideoPanel._media_transport_ready
            _analysis_buttons_ready = VideoPanel._analysis_buttons_ready
            cur_file = 'C:/qc/sample.mxf'
            _metadata_ready = False
            _cue_ready = False
        analysis_buttons_probe = AnalysisButtonsReadyProbe()
        if VideoPanel._analysis_buttons_ready(analysis_buttons_probe):
            errors.append("  FAIL analysis buttons ready before cue/metadata")
        analysis_buttons_probe._cue_ready = True
        if not VideoPanel._analysis_buttons_ready(analysis_buttons_probe):
            errors.append("  FAIL analysis buttons should enable after cue before metadata")
        analysis_buttons_probe.cur_file = ''
        if VideoPanel._analysis_buttons_ready(analysis_buttons_probe):
            errors.append("  FAIL analysis buttons need current file")

        class FrameRefreshTimer:
            def __init__(self):
                self.active = False
                self.started = 0
                self.stopped = 0

            def isActive(self):
                return self.active

            def start(self):
                self.active = True
                self.started += 1

            def stop(self):
                self.active = False
                self.stopped += 1

        class FrameRefreshProbe:
            _refresh_frame_clock_after_metadata = VideoPanel._refresh_frame_clock_after_metadata

            def __init__(self):
                self._frame_display_timer = FrameRefreshTimer()
                self._display_frame = 999
                self._last_display_dur_frames = 999
                self._last_slider_value = 999
                self._clock_anchor_frame = 999
                self._clock_anchor_time = 999.0
                self._frame_clock_active = False
                self.synced_ms = None
                self.set_frame = None
                self.interval_syncs = 0

            def _sync_frame_timer_interval(self):
                self.interval_syncs += 1

            def _sync_frame_clock(self, ms=None):
                self.synced_ms = ms
                self._display_frame = 123

            def _set_display_frame(self, frame):
                self.set_frame = frame
                self._display_frame = frame

        playing_frame_probe = FrameRefreshProbe()
        VideoPanel._refresh_frame_clock_after_metadata(playing_frame_probe, True, 2500)
        if (
            not playing_frame_probe._frame_clock_active
            or playing_frame_probe.synced_ms != 2500
            or playing_frame_probe._frame_display_timer.started != 1
            or playing_frame_probe._frame_display_timer.stopped != 0
        ):
            errors.append(
                "  FAIL metadata refresh should preserve active frame clock during playback"
            )
        idle_frame_probe = FrameRefreshProbe()
        VideoPanel._refresh_frame_clock_after_metadata(idle_frame_probe, False, 2500)
        if (
            idle_frame_probe._frame_clock_active
            or idle_frame_probe.set_frame != 0
            or idle_frame_probe._frame_display_timer.started != 0
            or idle_frame_probe._frame_display_timer.stopped != 1
        ):
            errors.append(
                "  FAIL metadata refresh should reset frame clock while idle"
            )

        class DropUrl:
            def __init__(self, path):
                self.path = path

            def toLocalFile(self):
                return self.path

        class DropPathProbe:
            _safe_int_value = staticmethod(VideoPanel._safe_int_value)
            _same_path = VideoPanel._same_path
            _video_file_path = VideoPanel._video_file_path
            _drop_url_texts = staticmethod(VideoPanel._drop_url_texts)
            _video_file_drop_info_from_texts = VideoPanel._video_file_drop_info_from_texts
            _video_file_paths_from_texts = VideoPanel._video_file_paths_from_texts
            _video_file_paths_from_urls = VideoPanel._video_file_paths_from_urls
            _cached_video_drop_info_from_urls = VideoPanel._cached_video_drop_info_from_urls
            _cached_video_file_paths_from_urls = VideoPanel._cached_video_file_paths_from_urls
            _clear_drag_url_cache = VideoPanel._clear_drag_url_cache
            _has_video_file_urls = VideoPanel._has_video_file_urls

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first = tmp_path / 'first.mxf'
            second = tmp_path / 'second.mp4'
            invalid = tmp_path / 'memo.txt'
            for path in (first, second, invalid):
                path.write_bytes(b'test')
            drop_paths = VideoPanel._video_file_paths_from_urls(
                DropPathProbe(),
                [DropUrl(str(first)), DropUrl(str(second)), DropUrl(str(invalid)), DropUrl(str(first))],
            )
            expected_drop_paths = [str(first), str(second)]
            if drop_paths != expected_drop_paths:
                errors.append(f"  FAIL multi-file drop path filter: {drop_paths} != {expected_drop_paths}")
            drop_info = VideoPanel._video_file_drop_info_from_texts(
                DropPathProbe(),
                [str(first), str(second), str(invalid), str(first)],
            )
            if drop_info != {'paths': expected_drop_paths, 'invalid': 1}:
                errors.append(f"  FAIL multi-file drop info: {drop_info}")
            if not VideoPanel._has_video_file_urls(DropPathProbe(), [DropUrl(str(invalid)), DropUrl(str(first))]):
                errors.append("  FAIL supported drag urls should be accepted")
            if VideoPanel._has_video_file_urls(DropPathProbe(), [DropUrl(str(invalid))]):
                errors.append("  FAIL unsupported-only drag urls should be ignored")
            class DropCacheProbe(DropPathProbe):
                def __init__(self):
                    self.calls = 0

                def _video_file_path(self, filepath):
                    self.calls += 1
                    return VideoPanel._video_file_path(self, filepath)

            cache_probe = DropCacheProbe()
            urls = [DropUrl(str(first)), DropUrl(str(second)), DropUrl(str(invalid))]
            cached_info = VideoPanel._cached_video_drop_info_from_urls(cache_probe, urls)
            if cached_info != {'paths': expected_drop_paths, 'invalid': 1}:
                errors.append(f"  FAIL drag URL cache info: {cached_info}")
            first_cached = VideoPanel._cached_video_file_paths_from_urls(cache_probe, urls)
            calls_after_first = cache_probe.calls
            second_cached = VideoPanel._cached_video_file_paths_from_urls(cache_probe, urls)
            if first_cached != expected_drop_paths or second_cached != expected_drop_paths:
                errors.append(f"  FAIL drag URL cache result: {first_cached}/{second_cached}")
            if cache_probe.calls != calls_after_first:
                errors.append("  FAIL drag URL cache reused paths should not rescan")
            VideoPanel._clear_drag_url_cache(cache_probe)
            VideoPanel._cached_video_file_paths_from_urls(cache_probe, urls)
            if cache_probe.calls <= calls_after_first:
                errors.append("  FAIL drag URL cache clear should allow rescan")

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
