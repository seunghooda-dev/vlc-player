# 실행 도구(FFmpeg/FFprobe/FFplay/VLC) 탐색과 실행 환경 점검
import os
import shutil
import subprocess
import sys
from pathlib import Path

import constants as _c
from process_registry import _hidden_subprocess_flags, heavy_analysis_status, runtime_child_process_status


def _tool_candidates(name):
    exe_name = f'{name}.exe' if os.name == 'nt' and not name.lower().endswith('.exe') else name
    for root in (_c.APP_DIR, _c.APP_DIR / 'tools', _c.APP_DIR / 'bin', _c.RESOURCE_DIR, _c.RESOURCE_DIR / 'tools', _c.RESOURCE_DIR / 'bin'):
        yield root / name
        yield root / exe_name

def resolve_tool_command(name):
    for path in _tool_candidates(name):
        if path.exists():
            return str(path)
    found = shutil.which(name)
    return found or name

FFMPEG     = resolve_tool_command("ffmpeg")
FFPROBE    = resolve_tool_command("ffprobe")
FFPLAY     = resolve_tool_command("ffplay")

_RUNTIME_TOOL_META = {
    'FFmpeg': {
        'command': lambda: FFMPEG,
        'role': '오디오 미터, 블랙/뮤트 검출, 선택 채널 믹스',
        'hint': r'ffmpeg.exe를 앱 폴더의 tools\ 안에 넣거나 Windows PATH에 등록하세요.',
    },
    'FFprobe': {
        'command': lambda: FFPROBE,
        'role': 'MXF/MP4 메타데이터, 길이, 해상도, 오디오 채널 확인',
        'hint': r'ffprobe.exe를 앱 폴더의 tools\ 안에 넣거나 Windows PATH에 등록하세요.',
    },
    'FFplay': {
        'command': lambda: FFPLAY,
        'role': '체크된 오디오 채널 실제 출력',
        'hint': r'ffplay.exe를 앱 폴더의 tools\ 안에 넣거나 Windows PATH에 등록하세요.',
    },
    'VLC': {
        'command': lambda: VLC_DIR,
        'role': 'MXF/MP4 원본 영상 재생',
        'hint': r'VLC를 설치하거나 libvlc.dll이 포함된 VLC 폴더를 앱 폴더\VLC 또는 C:\Program Files\VideoLAN\VLC에 두세요.',
    },
}

def _runtime_search_paths():
    paths = []
    seen = set()
    for path in (_c.APP_DIR, _c.APP_DIR / 'tools', _c.APP_DIR / 'bin', _c.RESOURCE_DIR, _c.RESOURCE_DIR / 'tools', _c.RESOURCE_DIR / 'bin'):
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            paths.append(str(path))
    paths.append('Windows PATH')
    return paths

def runtime_package_check():
    """배포본에서 tools/저장 위치가 분리된 상태인지 안내용으로 점검한다."""
    checks = []
    frozen = bool(getattr(sys, 'frozen', False))
    checks.append({
        'name': '실행 형태',
        'ok': True,
        'message': '패키지 EXE' if frozen else '개발 실행',
        'path': str(_c.APP_DIR),
        'hint': '',
    })
    tools_dir = _c.APP_DIR / 'tools'
    tools_ok = tools_dir.exists() and tools_dir.is_dir()
    checks.append({
        'name': 'tools 폴더',
        'ok': tools_ok,
        'message': '있음' if tools_ok else ('없음 (개발 실행은 PATH 사용 가능)' if not frozen else '없음'),
        'path': str(tools_dir),
        'severity': 'warning' if frozen else 'advisory',
        'hint': r'다른 PC 배포 시 ffmpeg.exe / ffprobe.exe / ffplay.exe를 tools 폴더에 포함하는 것을 권장합니다.',
    })
    for exe_name, resolved in (
        ('ffmpeg.exe', FFMPEG),
        ('ffprobe.exe', FFPROBE),
        ('ffplay.exe', FFPLAY),
    ):
        source = _classify_runtime_source(resolved) if resolved else '찾을 수 없음'
        bundled = source in ('앱 tools 폴더', '내장 tools 폴더')
        checks.append({
            'name': exe_name,
            'ok': bool(resolved and Path(str(resolved)).exists()),
            'message': '패키지 포함' if bundled else source,
            'path': str(resolved or ''),
            'hint': '' if bundled else r'배포 안정성을 높이려면 tools 폴더에 포함하세요. PATH 의존은 PC마다 달라질 수 있습니다.',
        })
    checks.append({
        'name': 'VLC',
        'ok': bool(VLC_DIR and (Path(VLC_DIR) / 'libvlc.dll').exists()),
        'message': _classify_runtime_source(VLC_DIR) if VLC_DIR else '찾을 수 없음',
        'path': str(VLC_DIR or ''),
        'hint': r'다른 PC에는 VLC 설치 또는 libvlc.dll 포함 경로가 필요합니다.',
    })
    separated = _c._path_key(_c.APP_DIR) != _c._path_key(_c.USER_DATA_DIR)
    checks.append({
        'name': '사용자 데이터 분리',
        'ok': separated,
        'message': 'EXE 폴더와 사용자 데이터 폴더 분리됨' if separated else 'EXE 폴더와 사용자 데이터 폴더가 같습니다',
        'path': str(_c.USER_DATA_DIR),
        'hint': '배포본은 설정/DB/log/tmp를 LOCALAPPDATA에 저장하는 구성이 안전합니다.',
    })
    return checks

def _runtime_tool_state(name):
    canonical = next((key for key in _RUNTIME_TOOL_META if key.lower() == str(name).lower()), str(name))
    meta = _RUNTIME_TOOL_META.get(canonical)
    if not meta:
        return {
            'name': canonical,
            'ok': False,
            'path': '',
            'role': '',
            'hint': '알 수 없는 실행 도구입니다.',
        }
    if canonical == 'VLC':
        ok = bool(VLC_DIR and (Path(VLC_DIR) / 'libvlc.dll').exists())
        return {
            'name': canonical,
            'ok': ok,
            'path': str(VLC_DIR or ''),
            'role': meta['role'],
            'hint': meta['hint'],
        }
    command = str(meta['command']() or '')
    exe = str(command) if command and Path(command).exists() else shutil.which(command)
    return {
        'name': canonical,
        'ok': bool(exe),
        'path': exe or '',
        'role': meta['role'],
        'hint': meta['hint'],
    }

def missing_runtime_tools(names):
    return [item for item in (_runtime_tool_state(name) for name in names) if not item.get('ok')]

def runtime_tools_ok(names):
    return not missing_runtime_tools(names)

def format_missing_runtime_tools(names):
    missing = missing_runtime_tools(names)
    if not missing:
        return ''
    lines = [f"필수 실행 도구가 없습니다: {', '.join(item['name'] for item in missing)}"]
    lines.append('영향:')
    for item in missing:
        lines.append(f"- {item['name']}: {item.get('role') or '-'}")
    lines.append('조치:')
    for item in missing:
        lines.append(f"- {item.get('hint') or '설치 또는 경로 등록이 필요합니다.'}")
    lines.append('상단 ENV 버튼에서 전체 실행 환경을 다시 확인할 수 있습니다.')
    return '\n'.join(lines)

def _candidate_vlc_dirs():
    seen = set()
    candidates = []
    for env_name in ('VLC_HOME', 'VLC_PATH'):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw))
    for root in (_c.APP_DIR, _c.RESOURCE_DIR):
        candidates.extend([
            root,
            root / 'VLC',
            root / 'vlc',
            root / 'VideoLAN' / 'VLC',
        ])
    for env_name in ('ProgramFiles', 'ProgramFiles(x86)'):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw) / 'VideoLAN' / 'VLC')
    vlc_exe = shutil.which('vlc') or shutil.which('vlc.exe')
    if vlc_exe:
        candidates.append(Path(vlc_exe).parent)
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            yield path

def resolve_vlc_dir():
    for path in _candidate_vlc_dirs():
        if (path / 'libvlc.dll').exists():
            return path
    return None

VLC_DIR = resolve_vlc_dir()

def _classify_runtime_source(path):
    try:
        p = Path(path).resolve()
    except Exception:
        return '알 수 없음'
    checks = [
        (_c.APP_DIR / 'tools', '앱 tools 폴더'),
        (_c.APP_DIR / 'bin', '앱 bin 폴더'),
        (_c.APP_DIR, '앱 폴더'),
        (_c.RESOURCE_DIR / 'tools', '내장 tools 폴더'),
        (_c.RESOURCE_DIR / 'bin', '내장 bin 폴더'),
        (_c.RESOURCE_DIR, '내장 리소스 폴더'),
    ]
    for root, label in checks:
        try:
            p.relative_to(root.resolve())
            return label
        except Exception:
            pass
    return 'Windows PATH / 시스템 설치'

def _check_command(name, command, role='', required=True):
    exe = str(command) if Path(str(command)).exists() else shutil.which(command)
    if not exe:
        return {
            'name': name,
            'ok': False,
            'path': '',
            'message': f'{command} 실행 파일을 PATH 또는 앱 폴더/tools에서 찾을 수 없습니다.',
            'version': '',
            'source': '찾을 수 없음',
            'role': role,
            'required': required,
            'hint': f'{command}.exe를 앱 폴더의 tools\\ 안에 넣거나 Windows PATH에 등록하세요.',
        }
    try:
        proc = subprocess.run(
            [exe, '-version'],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_hidden_subprocess_flags(),
        )
        first_line = (proc.stdout or proc.stderr or '').splitlines()
        return {
            'name': name,
            'ok': proc.returncode == 0,
            'path': exe,
            'message': first_line[0] if first_line else exe,
            'version': first_line[0] if first_line else '',
            'source': _classify_runtime_source(exe),
            'role': role,
            'required': required,
            'hint': '',
        }
    except Exception as e:
        return {
            'name': name,
            'ok': False,
            'path': exe,
            'message': str(e),
            'version': '',
            'source': _classify_runtime_source(exe),
            'role': role,
            'required': required,
            'hint': f'{exe} 실행 권한이나 손상 여부를 확인하세요.',
        }

def check_runtime_environment():
    items = [
        _check_command('FFmpeg', FFMPEG, _RUNTIME_TOOL_META['FFmpeg']['role'], True),
        _check_command('FFprobe', FFPROBE, _RUNTIME_TOOL_META['FFprobe']['role'], True),
        _check_command('FFplay', FFPLAY, _RUNTIME_TOOL_META['FFplay']['role'], True),
    ]
    if VLC_DIR:
        items.append({
            'name': 'VLC',
            'ok': True,
            'path': str(VLC_DIR),
            'message': str(VLC_DIR / 'libvlc.dll'),
            'version': str(VLC_DIR / 'libvlc.dll'),
            'source': _classify_runtime_source(VLC_DIR),
            'role': _RUNTIME_TOOL_META['VLC']['role'],
            'required': True,
            'hint': '',
        })
    else:
        items.append({
            'name': 'VLC',
            'ok': False,
            'path': '',
            'message': r'C:\Program Files\VideoLAN\VLC\libvlc.dll 을 찾을 수 없습니다.',
            'version': '',
            'source': '찾을 수 없음',
            'role': _RUNTIME_TOOL_META['VLC']['role'],
            'required': True,
            'hint': _RUNTIME_TOOL_META['VLC']['hint'],
        })
    missing = [item['name'] for item in items if not item['ok']]
    missing_required = [item['name'] for item in items if not item['ok'] and item.get('required')]
    storage = _c.check_runtime_storage()
    storage_issues = [item['name'] for item in storage if not item['ok'] and item.get('required', True)]
    storage_warnings = [item['name'] for item in storage if not item['ok'] and not item.get('required', True)]
    problems = missing + storage_issues
    return {
        'ok': not problems,
        'items': items,
        'storage_policy': _c.runtime_storage_policy(),
        'package_check': runtime_package_check(),
        'migration': _c.runtime_migration_events(),
        'migration_log': _c.runtime_migration_log_info(),
        'legacy_data': _c.runtime_legacy_root_data_status(),
        'storage': storage,
        'missing': missing,
        'missing_required': missing_required,
        'storage_issues': storage_issues,
        'storage_warnings': storage_warnings,
        'problems': problems,
        'can_start': 'VLC' not in missing_required,
        'search_paths': _runtime_search_paths(),
        'child_processes': runtime_child_process_status(),
        'heavy_analysis': heavy_analysis_status(),
        'state_timeline': _c.runtime_state_timeline(40),
    }

def format_runtime_environment(runtime=None):
    runtime = runtime or check_runtime_environment()
    lines = []
    lines.append(f'MasterQC v{_c.APP_VERSION} 실행 환경 진단')
    lines.append('=' * 42)
    lines.append(f"상태: {'정상' if runtime.get('ok') else '확인 필요'}")
    if runtime.get('problems'):
        lines.append(f"문제: {', '.join(runtime.get('problems', []))}")
    else:
        lines.append('문제: 없음')
    lines.append('')
    lines.append('구성 요소')
    lines.append('-' * 42)
    for item in runtime.get('items', []):
        mark = 'OK' if item.get('ok') else 'MISSING'
        lines.append(f"[{mark}] {item.get('name', '')}")
        lines.append(f"  역할: {item.get('role') or '-'}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  출처: {item.get('source') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        if item.get('hint'):
            lines.append(f"  조치: {item.get('hint')}")
        lines.append('')
    lines.append('저장 정책')
    lines.append('-' * 42)
    for item in runtime.get('storage_policy', []):
        lines.append(f"[{item.get('name', '')}]")
        lines.append(f"  역할: {item.get('role') or '-'}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  상태: {item.get('status') or '-'}")
        lines.append('')
    lines.append('배포 실행본 점검')
    lines.append('-' * 42)
    for item in runtime.get('package_check', []):
        mark = 'OK' if item.get('ok') else 'CHECK'
        lines.append(f"[{mark}] {item.get('name', '')}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        if item.get('hint'):
            lines.append(f"  참고: {item.get('hint')}")
        lines.append('')
    legacy_groups = runtime.get('legacy_data') or []
    lines.append('레거시 루트 데이터')
    lines.append('-' * 42)
    if legacy_groups:
        lines.append('정책: 앱은 사용자 데이터 폴더만 사용합니다. 아래 항목은 자동 삭제/이동하지 않습니다.')
        lines.append('조치: 필요하면 사용자가 확인 후 백업 위치로 수동 이동하세요.')
        lines.append('')
        for group in legacy_groups:
            lines.append(f"[{group.get('label') or '레거시 위치'}]")
            lines.append(f"  위치: {group.get('root') or '-'}")
            lines.append(f"  정책: {group.get('policy') or '-'}")
            for item in group.get('items', []):
                details = [item.get('kind') or '항목']
                if item.get('size') is not None:
                    details.append(_c.format_bytes(item.get('size')))
                if item.get('children') is not None:
                    details.append(f"항목 {item.get('children')}개")
                if item.get('modified'):
                    details.append(f"수정 {item.get('modified')}")
                if item.get('error'):
                    details.append(f"확인 오류: {item.get('error')}")
                lines.append(f"  - {item.get('name')}: {', '.join(details)}")
                lines.append(f"    {item.get('path')}")
            lines.append('')
    else:
        lines.append('발견된 레거시 루트 데이터 없음')
        lines.append('')
    lines.append('데이터 이전')
    lines.append('-' * 42)
    for item in runtime.get('migration', []):
        lines.append(f"[{item.get('status', '').upper()}] {item.get('name', '')}")
        lines.append(f"  시간: {item.get('timestamp') or '-'}")
        lines.append(f"  원본: {item.get('source') or '-'}")
        lines.append(f"  대상: {item.get('target') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        lines.append('')
    migration_log = runtime.get('migration_log') or {}
    lines.append('마이그레이션 로그')
    lines.append('-' * 42)
    lines.append(f"경로: {migration_log.get('path') or '-'}")
    errors = migration_log.get('errors') or []
    if errors:
        lines.append(f"상태: 기록 실패 ({'; '.join(errors)})")
    else:
        lines.append('상태: 기록 가능')
    lines.append('')
    lines.append('저장 위치')
    lines.append('-' * 42)
    for item in runtime.get('storage', []):
        mark = 'OK' if item.get('ok') else 'FAILED'
        lines.append(f"[{mark}] {item.get('name', '')}")
        lines.append(f"  역할: {item.get('role') or '-'}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        if item.get('hint'):
            lines.append(f"  조치: {item.get('hint')}")
        lines.append('')
    audio = runtime.get('audio_mix') or {}
    lines.append('오디오 자식 프로세스')
    lines.append('-' * 42)
    if audio:
        lines.append(f"예상 상태: {'필요' if audio.get('expected') else '불필요'}")
        lines.append(f"재생 플래그: {audio.get('playing')}")
        lines.append(f"파일: {audio.get('file') or '-'}")
        lines.append(f"채널: {audio.get('channels') or '-'}")
        lines.append(f"재생 속도: {audio.get('rate')}")
        lines.append(f"볼륨: {audio.get('volume_percent')}%")
        lines.append(f"FFmpeg: {audio.get('ffmpeg')}  pid={audio.get('ffmpeg_pid') or '-'}")
        lines.append(f"FFplay: {audio.get('ffplay')}  pid={audio.get('ffplay_pid') or '-'}")
        if audio.get('last_error'):
            lines.append(f"최근 오류: {audio.get('last_error')}")
    else:
        lines.append('오디오 믹스 상태 없음')
    lines.append('')
    children = runtime.get('child_processes') or []
    lines.append('등록된 자식 프로세스')
    lines.append('-' * 42)
    if children:
        for child in children:
            lines.append(
                f"[{child.get('state')}] pid={child.get('pid')} "
                f"{child.get('label') or 'process'}"
            )
            if child.get('command'):
                lines.append(f"  명령: {child.get('command')}")
    else:
        lines.append('등록된 자식 프로세스 없음')
    lines.append('')
    heavy = runtime.get('heavy_analysis') or {}
    lines.append('무거운 분석 슬롯')
    lines.append('-' * 42)
    if heavy.get('running'):
        lines.append(f"진행 중: {heavy.get('owner') or '-'} ({_c._safe_float_value(heavy.get('elapsed'), 0.0):.1f}s)")
    else:
        lines.append('진행 중인 무거운 분석 없음')
    lines.append('')
    timeline = runtime.get('state_timeline') or _c.runtime_state_timeline(20)
    lines.append('최근 상태 타임라인')
    lines.append('-' * 42)
    if timeline:
        for row in timeline[-20:]:
            extra = [
                f"{k}={v}" for k, v in row.items()
                if k not in ('ts', 'category', 'message') and v not in ('', None)
            ]
            lines.append(
                f"{row.get('ts')} | {row.get('category')} | {row.get('message')}"
                + (f" | {' '.join(extra)}" if extra else '')
            )
    else:
        lines.append('상태 기록 없음')
    lines.append('')
    lines.append('검색 위치')
    lines.append('-' * 42)
    for path in runtime.get('search_paths', []):
        lines.append(f"- {path}")
    lines.append('')
    lines.append('기능 영향')
    lines.append('-' * 42)
    lines.append('- VLC 누락: 원본 영상 재생 불가')
    lines.append('- FFmpeg 누락: 오디오 미터, 블랙/뮤트 검출, 채널 믹스 제한')
    lines.append('- FFprobe 누락: 파일 길이/해상도/채널 정보 확인 제한')
    lines.append('- FFplay 누락: 체크박스 기반 오디오 출력 제한')
    lines.append('- 저장 위치 쓰기 실패: 설정 저장, 로그 기록, 분석 캐시 생성 제한')
    return '\n'.join(lines)
