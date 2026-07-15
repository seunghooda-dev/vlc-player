# Plan: 오디오 출력 선택 체크박스 16채널 확장

- 작성일: 2026-07-15
- 요구: 레벨 미터 16채널(완료)에 이어, 출력 선택 체크박스도 1~16으로 확장해
  UHD 마스터의 상위 채널(9~16)을 모니터링 출력으로 선택 가능하게.

## 변경 지점 (8→16 캡 해제)

1. video_panel: 체크박스 생성 range(8)→16(레이아웃은 기존 ch_bar 스트레치 내 수용),
   `_audio_channel_control_count`·`_audio_channel_display_text`·provisional 활성화
   (MXF 힌트 없음 기본 8→16)·`_next` 페어·`_audio_channel_label` 필터.
2. settings: `_settings_audio_channels` 1..8 → 1..16 (저장/복원).
3. vlc_player: AudioMixPlayer `set_channels`/`_max_output_channel`(layout 미상 시 16)/
   `effective_channels`/`_source_for_channel`/`_build_filter` 클램프,
   VlcPlayerAdapter `set_audio_channel` 클램프.
   — 믹스 필터는 스트림(0:a:N)/채널(cN) 인덱스 기반이라 캡 해제만으로 16채널 동작.
4. check_imports: 8 고정 프로브 갱신(설정 정규화 9·16 허용, control_count 16,
   display 텍스트, AudioMix 클램프 기대값).
5. tests: settings/vlc_adapter의 8 캡 단언 갱신 + 16채널 케이스 추가.

## 불변

- 기본 선택 [1,2] (방송 QC 기본 모니터링), 새 파일 열기 시 1/2 리셋 동작,
  단일 스트림·스테레오 파일에서의 소스 상한 로직(source_max).

## 검증

- 게이트: pytest(케이스 추가) + check_imports(프로브 갱신 후 그린)
- 실기: UHD 16ch 파일 스모크 + 실행 창 캡처로 체크박스 16개 표시·활성 확인,
  9번 이상 채널 선택 시 오디오 믹스 기동 확인(로그 channels=[9,10] 등)
