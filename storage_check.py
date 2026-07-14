# 실행 파일/사용자 데이터 저장 위치 읽기·쓰기 가능 여부 점검
import os
from datetime import datetime
from pathlib import Path

import constants as _c

def runtime_storage_policy():
    items = [
        {
            'name': '앱 실행 파일 폴더',
            'path': str(_c.APP_DIR),
            'role': '프로그램 파일, tools, README, 라이선스 파일',
            'status': '실행 파일 전용, 기존 데이터 파일은 보존',
        },
        {
            'name': '사용자 데이터 폴더',
            'path': str(_c.USER_DATA_DIR),
            'role': 'settings.json, archive.db, logs, tmp, backups, reports',
            'status': '현재 설정/DB/log/tmp/backups/reports 저장 위치',
        },
    ]
    if _c.LEGACY_DATA_DIR != _c.APP_DIR:
        items.append({
            'name': '기존 데이터 원본',
            'path': str(_c.LEGACY_DATA_DIR),
            'role': '개발 실행 시 release 폴더의 기존 settings.json, archive.db',
            'status': '새 사용자 데이터 폴더로 최초 복사할 원본',
        })
    return items

def _check_write_location(name, path, role, required=True):
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_name = f'.mxf_qc_write_probe_{os.getpid()}_{datetime.now().strftime("%H%M%S%f")}.tmp'
        probe = path / probe_name
        probe.write_text('ok', encoding='utf-8')
        try:
            probe.unlink(missing_ok=True)
        except Exception:
            pass
        return {
            'name': name,
            'ok': True,
            'path': str(path),
            'message': '쓰기 가능',
            'role': role,
            'required': required,
            'hint': '',
        }
    except Exception as e:
        return {
            'name': name,
            'ok': False,
            'path': str(path),
            'message': str(e),
            'role': role,
            'required': required,
            'hint': '앱 폴더를 쓰기 가능한 위치에 두세요. Program Files처럼 권한이 막힌 위치는 피하는 것이 좋습니다.',
        }

def _check_read_location(name, path, role, required=True):
    path = Path(path)
    try:
        ok = path.exists() and path.is_dir()
        return {
            'name': name,
            'ok': ok,
            'path': str(path),
            'message': '읽기 가능' if ok else '폴더를 찾을 수 없습니다',
            'role': role,
            'required': required,
            'hint': '' if ok else '앱 실행 파일 폴더가 이동/삭제됐는지 확인하세요.',
        }
    except Exception as e:
        return {
            'name': name,
            'ok': False,
            'path': str(path),
            'message': str(e),
            'role': role,
            'required': required,
            'hint': '앱 실행 파일 폴더 접근 권한을 확인하세요.',
        }

def check_runtime_storage():
    return [
        _check_read_location('앱 실행 파일 폴더', _c.BASE_DIR, '프로그램 파일, tools, README 보관 위치'),
        _check_write_location('사용자 데이터 폴더', _c.USER_DATA_DIR, 'settings.json, archive.db, logs, tmp, backups, reports 저장 위치'),
        _check_write_location('로그 폴더', _c.LOG_DIR, 'logs/player.log 기록'),
        _check_write_location('임시 폴더', _c.TMP_DIR, '분석 캐시와 임시 작업 파일 생성'),
        _check_write_location('백업 폴더', _c.BACKUP_DIR, 'settings.json, archive.db 자동 백업', required=False),
        _check_write_location('리포트 폴더', _c.REPORT_DIR, '진단 리포트 zip 저장', required=False),
    ]
