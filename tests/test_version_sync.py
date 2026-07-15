# 버전 소스 동기화 가드 — constants.APP_VERSION과 version_info.txt가 어긋나면 게이트 실패
"""릴리스 절차(bump_version.py)가 두 소스를 함께 올리는지 강제한다.
한쪽만 올리면 이 테스트가 빨개져 커밋 전에 잡힌다.
"""
import re
from pathlib import Path

import constants


def test_app_version_matches_exe_version_resource():
    text = (Path(constants.APP_DIR) / 'version_info.txt').read_text(encoding='utf-8')
    m = re.search(r"StringStruct\('ProductVersion', '(\d+\.\d+\.\d+)\.0'\)", text)
    assert m, 'version_info.txt에서 ProductVersion을 찾지 못함'
    assert m.group(1) == constants.APP_VERSION, (
        f'버전 불일치: constants.APP_VERSION={constants.APP_VERSION} '
        f'vs version_info.txt={m.group(1)} — python bump_version.py로 함께 올리세요'
    )
    m2 = re.search(r'filevers=\((\d+), (\d+), (\d+), 0\)', text)
    assert m2 and '.'.join(m2.groups()) == constants.APP_VERSION
