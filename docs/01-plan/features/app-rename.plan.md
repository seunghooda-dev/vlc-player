# Plan: 앱 개명 — MXF QC Player → MasterQC

- 작성일: 2026-07-15
- 배경: MXF 외 포맷(MP4/MOV 등)까지 QC 대상이 되어 포맷 종속 이름을 폐기.
  사용자 확정 명칭 **MasterQC** (방송 '마스터' 소재 검수 도구라는 용도 전달).

## 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 제품명 | MasterQC | 사용자 확정 |
| 버전 | 1.0.1.0 → 1.1.0.0 | 사용자 가시 변경(개명) — 차기 태그 v1.1.0 |
| 데이터 폴더 | `%LOCALAPPDATA%\MasterQC` (버전 무접미) | 버전 올려도 데이터 폴더 유지 — 기존 "V.1.0" 접미 관행 폐기 |
| 데이터 이전 | 이전 기본 폴더(`MXF QC Player V.1.0`)에서 settings.json/archive.db **복사**(원본 보존) | migration.py 기존 복사 방식 확장 |
| 이전 가드 | `MXF_QC_USER_DATA_DIR` 오버라이드 시 이전-폴더 마이그레이션 **스킵** | 스모크/CI 격리 폴더가 실사용 DB를 복사해오면 안 됨 |
| 환경변수 | `MXF_QC_USER_DATA_DIR` 유지 | CI·스크립트·문서 호환(내부 배관) |
| 뮤텍스 | `Local\MasterQC_SingleInstance` | 구/신 EXE 1회 동시 실행 가능 — 허용 |
| 아이콘 파일명 | assets/mxf_qc_player.ico 유지 | 내부 경로 — 불필요 churn 방지 |
| GitHub 저장소명 | vlc-player 유지 | 저장소 개명은 사용자 권한 필요 — 별도 안내 |

## 변경 지점

1. 코드: constants(APP_DATA_NAME·docstring·캐시 상태 문구), main(창 제목·상태바·뮤텍스·
   already-running 문구·릴리스 zip glob 신/구 패턴·QC 리포트 스모크 단언), right_panel
   (리포트 제목·앱버전·확인요약 제목), runtime_tools(진단 제목), logging_setup(docstring),
   migration(PREVIOUS_* 소스 추가 + 오버라이드 가드), check_imports(고정 문자열 2곳 + 배너)
2. 패키징: spec 파일명/name, version_info 4필드+버전, .gitignore 예외,
   ci.yml(spec·dist·zip·release 제목), bat 6종(APP_NAME/버전/바로가기 + 구 바로가기 정리)
3. 테스트: tests/test_migration.py 신설(이전 우선순위·오버라이드 가드·기존 파일 보존)

## 검증

- 게이트: check_imports + pytest(신규 마이그레이션 테스트 포함)
- E2E 격리 마이그레이션: LOCALAPPDATA를 임시 폴더로 재지정 + 구명칭 폴더에 가짜
  settings/db 시드 → env 오버라이드 없이 실행 → `MasterQC` 폴더에 복사 확인(실데이터 무접촉)
- 실기 GUI 스모크(MXF) + 로컬 spec 빌드 → push 후 CI build-exe 그린 → v1.1.0 태그 릴리스
