# MasterQC (구 MXF QC Player)

방송용 MXF/MP4/MOV QC 데스크톱 플레이어 — Python/PyQt6 + VLC(재생) + FFmpeg(분석·오디오 믹스).
GitHub `seunghooda-dev/vlc-player` (origin/main 직push, v* 태그 → Release 자동 생성).

## 게이트 (커밋 전 필수)

- `QT_QPA_PLATFORM=offscreen MXF_QC_USER_DATA_DIR=<임시폴더> python check_imports.py` (exit 0)
- `MXF_QC_USER_DATA_DIR=<임시폴더> python -m pytest` (tests/, 95개+)
- 실기 스모크: `python main.py --mxf-smoke-test "C:/Users/seung/Desktop/black_4sec_test_hd_20s.mxf" --play-seconds 5`
  (데스크톱에 HD/UHD 16ch 샘플 상주. 비직접 경로는 .mov로 `--media-smoke-test` — .mp4는 DIRECT_VLC라 안 탐)
- 스모크류는 MXF_QC_USER_DATA_DIR 격리 필수 — 미지정 시 실사용 데이터(%LOCALAPPDATA%\MasterQC)를 건드림.
  단 cleanup-smoke는 자체 격리 폴더를 요구하므로 env 없이 실행.

## 아키텍처 규칙

- God 모듈 분할 패턴: 새 모듈이 소유 + 원래 모듈이 파사드 재노출(소비자 import 무수정).
  순환 회피: leaf는 훅 주입, 경로 의존 모듈은 `import constants as _c` 지연 속성 참조(from-import 금지).
  constants를 경유하지 않고 분리 모듈(diagnostics 등)을 단독 import하면 부분초기화 에러 — 테스트는 constants 선import.
- `XxxCoordinator(panel)` 역참조 패턴(loudness/transcode): 클러스터 상태는 조정자 소유,
  외부 호출부는 패널 위임 메서드/읽기 프로퍼티로 보존. 이동 검증은 pre-image 기계 diff.
- check_imports.py는 소스 문자열 마커 검사 — 코드 이동 시 마커 재타겟 필수(FILES 등록 포함).
  실호출로 검증 가능한 마커는 pytest로 이관하는 것이 방침.
- CUE 완료 선언은 소스가 실제 player에 올라온 뒤에만(`_complete_transcode_cue_load`) — load_file 조기 선언 금지.
- **투명(WA_TranslucentBackground) 위젯 + VLC 네이티브 HWND 형제 금지** — 화면 합성이 낡은 프레임에
  고착됨(grab은 정상, 화면만 낡음). 불투명 배경 사용. 진단: `--meter-dump`.

## 버전·배포

- 릴리스는 `python bump_version.py X.Y.Z` 한 명령으로 두 버전 소스(constants.APP_VERSION,
  version_info.txt)를 갱신 → 커밋 → `git tag vX.Y.Z && git push origin vX.Y.Z`.
  두 소스가 어긋나면 tests/test_version_sync.py가 게이트를 빨갛게 만든다.
  APP_VERSION은 창 제목·리포트·바로가기 이름의 단일 소스.
- 바탕화면 배포: `update_desktop_release.bat` (빌드→검증→릴리스 폴더 교체→바로가기 자동 갱신).
  실행 중 앱이 있으면 릴리스 폴더 잠김 — 먼저 종료. bat 간 호출은 `%~dp0` 절대 경로 유지.
- 단일 인스턴스 뮤텍스 `Local\MasterQC_SingleInstance` — 앱 실행 중엔 GUI 스모크 전부 차단.

## 16채널 (UHD 마스터)

- 레벨 미터 좌 홀수/우 짝수 8행(행 17px, 우레일은 라우드니스 미터와 적응 클램프),
  출력 선택 체크박스 1~16. probe의 channels는 스트림 합계라 16모노/1×16ch/8×스테레오 전부 커버.
