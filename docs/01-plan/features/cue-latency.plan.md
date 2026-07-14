# Plan: cue-latency — CUE 첫 화면 표시 지연 단축

- 작성일: 2026-07-14
- 상태: Plan 확정 (사용자 지시로 Design 단계 생략, 곧바로 구현)
- 대상: MXF QC Player V.1.0 (`video_panel.py`)

## 1. 배경 / 문제

파일을 CUE하면 플레이어에 첫 화면이 뜨기까지 눈에 띄는 지연이 있다(운영자 체감 보고).

실측 근거(player.log, 2026-07-14 20:02, newswide.mxf 9GB):

- `total_before_cue=0.069s` — 파일 확인·상태 리셋·VLC 소스 설정까지는 69ms에 불과.
- 지연의 본체는 그 뒤 preroll 단계의 **하드코딩된 고정 대기**다.

코드 근거:

- `video_panel.py` `_prepare_vlc_cue._poll` — `ready = elapsed >= 0.45 and has_duration_hint`,
  `fallback_ready = elapsed >= 0.90`. VLC가 먼저 준비돼도 최소 450ms(힌트 없으면 900ms)를 채운다.
- `VlcPlayerAdapter.show_first_frame` — play() 후 120/260/520/860ms 고정 타이머로 4회
  블라인드 freeze(set_time+set_pause). VLC 준비 상태를 조회하지 않는다.
- 체인 전체의 설계상 최소 지연: 50ms(preroll 예약) + 450ms(poll 바닥) + 70ms + 80ms(settle)
  ≈ **650ms** + VLC 실제 오픈 시간.
- 고정 대기를 둔 이유는 코드 주석에 있다 — "MXF는 preroll 전에는 get_length()가 0으로 남는
  경우가 많다". 즉 준비 완료를 알 방법이 없어 시간을 채우는 보수적 설계.

## 2. 목표

CUE 시 VLC의 실제 준비 상태를 조회해, 준비되는 즉시 첫 프레임을 표시한다.
로컬 HD/UHD MXF 기준 체감 300~500ms 단축을 노린다.

## 3. 접근 방식

libvlc `MediaPlayer.has_vout()`(비디오 출력 개수, 첫 프레임 렌더 후 ≥1)를 **폴링**으로 조회한다.
이벤트(event_manager) 방식이 아닌 폴링을 택하는 이유는 libvlc 이벤트가 VLC 스레드에서
발화되어 Qt 마샬링 복잡성이 생기기 때문 — has_vout()은 메인 스레드에서 동기 호출 가능해
기존 QTimer 폴링 구조에 그대로 얹힌다.

변경점 2곳:

1. `VlcPlayerAdapter`에 `has_video_output()` 추가 (`self._player.has_vout() > 0`, 실패 시 False).
2. `_prepare_vlc_cue._poll`의 readiness 조건 확장:
   `ready = (has_vout and elapsed >= 0.15) or (elapsed >= 0.45 and has_duration_hint)`
   - vout 확인 시 150ms 바닥(첫 freeze 타이머 120ms 직후)만 지나면 즉시 완료.
   - **기존 450/900ms 경로는 삭제하지 않고 fallback으로 유지** — vout 신호가 안 오는
     비정상 파일에서도 현재와 동일하게 동작.
3. `show_first_frame`의 블라인드 freeze 타이머(120/260/520/860ms)는 그대로 둔다 —
   vout 이전의 freeze 시도는 무해하고(no-op에 가깝고), 조기 완료 시 시퀀스 가드
   (`_is_current_op`)가 이후 타이머를 무효화한다.

## 4. 성공 기준 (검증 방법)

1. `check_imports.py` 게이트 그린 + pytest 55개 전부 통과 (회귀 없음).
2. 실 MXF 스모크(`--mxf-smoke-test`, 데스크톱 샘플) 통과.
3. **before/after 실측**: `record_state_event('cue', 'cue readiness reached', elapsed=...)` 로그로
   같은 로컬 MXF 샘플의 elapsed가 개선 전(≥0.45s) 대비 유의미하게 감소(목표 ≤0.30s).
4. duration 힌트가 없거나 vout이 늦는 경우에도 기존 fallback 타이밍으로 완료(동작 저하 없음).

## 5. 범위 제외

- libvlc event_manager 기반 이벤트 구동(스레드 마샬링 리스크 대비 이득 낮음).
- `_finish_cue`의 70/80ms settle 지연 제거(포지션 안정화 목적, 유지).
- 트랜스코드 프리뷰 경로(비 DIRECT_VLC_EXTS)의 로딩 최적화.

## 6. 리스크

| 리스크 | 완화 |
|---|---|
| has_vout()이 일부 코덱에서 조기/지연 보고 | 150ms 바닥 + freeze 타이머 병행 + 기존 fallback 유지 |
| check_imports의 소스 문자열 마커 검사와 충돌 | 게이트 실행으로 확인, 필요 시 마커 갱신 |
| 스모크만으로 놓치는 시각적 회귀 | before/after 로그 타이밍 비교 + 실 MXF 재생 확인 |

## 7. 구현 결과 — 근본 원인 수정 (Do 단계 기록, 2026-07-14)

구현 중 계측으로 **계획 시점의 가설이 뒤집혔다**. 450ms 고정 대기가 병목이 아니라,
그보다 깊은 문제가 있었다.

- 실측 1(독립 프로브): 앱의 preroll 시퀀스(play 후 120ms pause + 반복 seek)를 재현하면
  첫 프레임(vout)이 **1.22s**에 생성. pause/seek를 하지 않으면 **0.86s**.
- 실측 2(앱 내부 계측): 기존 앱은 0.45s에 "준비 완료"를 표시하지만 그 시점 화면은
  블랙이고, 실제 프레임은 ~1.2s에 나타났다. 조기 pause(블라인드 freeze 4회)와
  완료 경로의 pause+seek(_force_cue_position)가 VLC preroll을 반복 방해한 것.

최종 구현은 계획 3절을 다음과 같이 수정 적용했다.

1. `show_first_frame`: 블라인드 freeze 타이머(120/260/520/860ms) 제거 →
   40ms 폴링으로 vout 감지 즉시 1회 freeze(+140ms settle). 1.4s 최후 음소거 가드.
2. `_prepare_vlc_cue._poll`: `ready = has_vout and elapsed >= 0.15`.
   0.45s duration-hint 조기 완료 경로 제거(프레임 전 pause를 유발하던 주범).
   0.90s 타이머 fallback은 유지.

결과(HD MXF, 동일 파일·머신):

| 지표 | 개선 전 | 개선 후 |
|---|---|---|
| 첫 프레임 표시 | ~1.22s | **0.83s** (-32%) |
| CUE 완료 표시 | 0.45s(화면은 블랙) | 0.91s(실제 프레임과 정렬) |

vout 생성 자체(~0.85s)는 이 머신의 VLC/D3D 고정 비용으로 확인(MP4도 0.89s,
file-caching=100 무효). 게이트: check_imports 그린, pytest 55개 통과,
실 MXF 스모크 통과(오디오 자식 프로세스 정상).

## 8. 후속 실험 — 시작 시 vout 워밍업 (2026-07-15, 실측 후 no-ship 결정)

7절에서 "vout ~0.85s는 고정 비용"이라 적었으나, 그 고정 비용이 **프로세스 최초 vout 1회에만**
드는지(즉 이후 CUE는 싼지) 확인되지 않았다. 이를 실측해 시작 시 더미 워밍업의 가치를 판단했다.

프로브(앱의 VlcPlayerAdapter 시퀀스를 그대로 모사 — 단일 vlc.Instance + 단일 media_player,
오프스크린 hidden hwnd, stop→set_media→muted play→has_vout() 메인스레드 폴링):

- 실측 A(한 프로세스, 실파일 4개 연속): UHD 첫 vout **0.457s** → 이후 HD 0.155s·0.194s →
  동일 UHD 재생 **0.184s**. 즉 **2번째 이후 CUE는 자연히 warm**(0.15~0.19s)이다.
- 실측 B(cold vs 합성 블랙 워밍업, 각 별도 프로세스 다수 시행):
  - cold(워밍업 없음): UHD 0.31~0.45s.
  - 1080p 블랙 워밍업 후: UHD 0.27~0.28s(중앙값), 단 0.39s 이상치 1회.
  - 2160p 블랙 워밍업 후: UHD 0.24~0.29s, 안정적이나 여전히 ~0.28s 바닥.
  - 워밍업은 D3D 디바이스·H.264 DXVA 디코더 초기화(변동분 ~0.05~0.15s)만 회수하고,
    실측 A의 동일 스트림 warm(0.18s)에는 못 미친다 — 나머지 ~0.28s는 스트림별
    스왑체인 할당·첫 프레임 디코드로, 실제 그 파일을 재생해야만 사라진다.

**결정: 합성 vout 워밍업을 넣지 않는다.**

1. 원래 성공 기준("2번째 CUE가 싸지면 추가 작업 불필요")이 실측 A로 충족됐다.
   운영 중 대부분의 CUE는 이미 warm이다.
2. 첫 CUE에 대한 합성 워밍업 이득은 ~0.05~0.15s로 한계가 뚜렷하고, 시작 경로에
   재생 부작용(취소 가드 필요)·생성 자산(ffmpeg 블랙 클립) 의존을 더한다.
3. 단일 인스턴스 뮤텍스로 현재 GUI 스모크가 막혀 있어, 타이밍 민감한 시작 경로 변경을
   실기 검증할 수 없다. 방송 QC 도구에 검증 불가한 변경을 ~0.1s 이득으로 넣지 않는다
   (CLAUDE.md 단순함 우선·추측성 코드 금지).
4. `VlcPlayerAdapter`는 이미 `VideoPanel.__init__`(video_panel.py:404)에서 eager 생성 —
   DLL 로드·vlc.Instance 비용은 이미 시작 시 지불된다. lazy-init 회수 여지도 없다.

남은 여지(별건, 범위 밖): 앱 실측 첫 CUE ~0.83s 중 순수 vout(~0.33~0.45s)를 뺀 ~0.4s는
CUE 주변 앱 작업(메타데이터 probe·오디오 믹스 자식 spawn·UI). 첫 CUE 추가 단축은 이 앱측
경로 계측이 필요하며 GUI 실행이 가능할 때 별도로 다룬다.
