# MasterQC → MasterQC Player 개명 (표시명 + EXE 파일명)

## 배경

2026-07-23 사용자 요청. 표시 이름과 EXE 파일명을 `MasterQC Player`로 바꾸고 버전을 뒤에 붙인다.
데이터 폴더·뮤텍스는 **바꾸지 않는다** — 재마이그레이션 위험 대비 실익이 없다는 판단(사용자 선택).

## 범위

| 층 | 변경 | 결과 |
|---|---|---|
| 표시 문구 | 창 제목, 상단 헤더, 상태바, 리포트 제목, 진단/로그 | `MasterQC Player v1.1.9` |
| EXE 파일명 | spec `name=`, version_info.txt 메타데이터 | `MasterQC Player.exe` |
| 패키지 | bat 4종의 `APP_NAME` → 릴리스 폴더·zip·바로가기 이름 파생 | `MasterQC Player V.1.1`, `MasterQC Player v1.1.9.lnk` |
| 문서 | README_RELEASE, 운영자 안내, UPDATE_POLICY, DEV_WORKFLOW, CLAUDE.md | 명칭·경로 일치 |
| CI | `dist\MasterQC Player\MasterQC Player.exe` 경로 | 빌드/스모크 통과 |

## 바꾸지 않는 것 (보호 토큰)

일괄 치환 시 다음은 그대로 둔다. 바꾸면 깨지거나 의미가 틀어진다.

- `APP_DATA_NAME = "MasterQC"` / `%LOCALAPPDATA%\MasterQC` — 데이터 폴더 유지(범위 밖)
- `MasterQC_SingleInstance` — 뮤텍스. 바꾸면 구버전과 동시 실행 가능해짐
- `MasterQC.spec` — 스펙 파일명(내용의 `name=`만 변경). .gitignore·CI가 참조
- `MasterQC-win64.zip` — CI 아티팩트/릴리스 자산 이름
- `MasterQC*.zip` — main.py의 릴리스 zip 탐색 glob(접두 일치라 신구 모두 잡음)
- `mxf_qc_player.ico`, `MXF_QC_USER_DATA_DIR` — 실제 파일명/환경변수
- `tests/`, `docs/01-plan/` 기존 문서 — 과거 개명 이력 기술이라 보존

## 검증 (성공 기준)

1. `python -m pytest` / `python check_imports.py` 그린 — 문자열 단언(리포트 제목·요약 헤더) 동반 갱신 확인
2. `python main.py --ui-layout-check` 그린 — 헤더 문구가 길어져 최소 창(1240×760)에서 겹치지 않는지
3. 재빌드 후 `dist ↔ release` EXE 해시 일치, ProductVersion 1.1.9, 패키지 스모크 통과
4. 바탕화면 바로가기가 `MasterQC Player v1.1.9.lnk`로 갱신
5. 패키지 문서에 옛 표기(`MasterQC.exe`, `MasterQC V.1.1`) 잔존 0곳
6. 구 릴리스 폴더(`release\MasterQC V.1.1`)는 신 패키지 검증 후 제거

## 위험

- **헤더 라벨 길이** — `MASTER  QC  PLAYER`가 최소 창에서 상단 버튼과 충돌할 수 있다. ui-layout-check로 판정하고, 실패하면 헤더는 원복한다.
- **공백 포함 EXE 이름** — 인용 없는 호출이 있으면 깨진다. bat/ps1/py의 호출부가 모두 따옴표로 감싸져 있는지 확인한다.
