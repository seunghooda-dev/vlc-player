# 릴리스 버전 범프 — constants.APP_VERSION과 version_info.txt를 한 번에 갱신
"""사용법: python bump_version.py 1.1.4

두 버전 소스(constants.APP_VERSION, version_info.txt)를 원자적으로 갱신한다.
이후 절차는 출력되는 명령대로 커밋 + 태그 push — 빌드/릴리스/바로가기는 전부 자동.
"""
import io
import re
import sys


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r'\d+\.\d+\.\d+', sys.argv[1]):
        print('사용법: python bump_version.py X.Y.Z  (예: 1.1.4)')
        return 1
    new = sys.argv[1]
    x, y, z = new.split('.')

    c = io.open('constants.py', encoding='utf-8', newline='').read()
    m = re.search(r'APP_VERSION = "(\d+\.\d+\.\d+)"', c)
    if not m:
        print('constants.py에서 APP_VERSION을 찾지 못했습니다')
        return 1
    old = m.group(1)
    if old == new:
        print(f'이미 {new} 입니다')
        return 1
    c = c.replace(f'APP_VERSION = "{old}"', f'APP_VERSION = "{new}"', 1)

    v = io.open('version_info.txt', encoding='utf-8', newline='').read()
    ox, oy, oz = old.split('.')
    pairs = [
        (f'filevers=({ox}, {oy}, {oz}, 0)', f'filevers=({x}, {y}, {z}, 0)'),
        (f'prodvers=({ox}, {oy}, {oz}, 0)', f'prodvers=({x}, {y}, {z}, 0)'),
        (f"'FileVersion', '{old}.0'", f"'FileVersion', '{new}.0'"),
        (f"'ProductVersion', '{old}.0'", f"'ProductVersion', '{new}.0'"),
    ]
    for o, n in pairs:
        if v.count(o) != 1:
            print(f'version_info.txt 불일치: {o!r} — 수동 확인 필요')
            return 1
        v = v.replace(o, n)

    io.open('constants.py', 'w', encoding='utf-8', newline='').write(c)
    io.open('version_info.txt', 'w', encoding='utf-8', newline='').write(v)
    print(f'{old} -> {new} 갱신 완료 (constants.py + version_info.txt)')
    print('다음 절차:')
    print(f'  git add constants.py version_info.txt')
    print(f'  git commit -m "chore: 버전 {new}"')
    print(f'  git push origin main && git tag v{new} && git push origin v{new}')
    print('→ CI가 빌드·릴리스 zip 첨부, 바탕화면은 update_desktop_release.bat 실행(바로가기 이름 자동).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
