# 밤샘 소크 테스트 러너 — 릴리스 EXE로 CUE→재생→검증→정리 사이클을 반복하며 메모리 추이 기록
r"""사용법: python soak_test.py [--hours 8] [--play-seconds 570] [--sample <MXF>] [--exe <EXE>]

- 사이클마다 `--mxf-stability-test`(실재생·드리프트·오디오·자식정리 검증)를 실행하고
  경과·종료코드·피크 메모리(WorkingSet)를 soak 로그에 남긴다.
- 반복되는 로드/해제 사이클은 단일 장시간 재생보다 누수·핸들 고갈을 잘 드러낸다.
- 중지: tmp\soak\STOP 파일을 만들면 현재 사이클 종료 후 안전 정지.
- 데이터 격리: MXF_QC_USER_DATA_DIR=tmp\soak\user_data (실사용 DB/설정 무오염).
"""
import argparse
import datetime
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOAK_DIR = ROOT / 'tmp' / 'soak'
STOP_FILE = SOAK_DIR / 'STOP'


def now():
    return datetime.datetime.now().strftime('%H:%M:%S')


def peak_memory_sampler(proc_name, stop_evt, out):
    # tasklist로 30초마다 WorkingSet(KB) 샘플 — 외부 패키지 불필요
    while not stop_evt.is_set():
        try:
            r = subprocess.run(
                ['tasklist', '/FI', f'IMAGENAME eq {proc_name}', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, timeout=20,
            )
            for line in r.stdout.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 5 and proc_name.lower() in parts[0].lower():
                    kb = int(parts[4].replace(',', '').replace(' K', '').replace('K', '').strip() or 0)
                    out['peak'] = max(out.get('peak', 0), kb)
        except Exception:
            pass
        stop_evt.wait(30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=float, default=8.0)
    # 기본 540s — 10분 소재 기준 EOF 60초 마진(경계 조건은 앱 가드가 처리하지만 사이클을 깔끔하게)
    ap.add_argument('--play-seconds', type=int, default=540)
    ap.add_argument('--sample', default=r'C:\Users\seung\Desktop\uhd_colorbar_59p94_16ch_10min.mxf')
    ap.add_argument('--exe', default=str(ROOT / 'release' / 'MasterQC V.1.1' / 'MasterQC.exe'))
    args = ap.parse_args()

    SOAK_DIR.mkdir(parents=True, exist_ok=True)
    if STOP_FILE.exists():
        STOP_FILE.unlink()
    log_path = SOAK_DIR / f"soak_{datetime.datetime.now():%Y%m%d_%H%M}.log"

    def log(msg):
        line = f'[{now()}] {msg}'
        print(line, flush=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')

    exe = Path(args.exe)
    sample = Path(args.sample)
    if not exe.exists() or not sample.exists():
        log(f'FAIL 사전조건: exe={exe.exists()} sample={sample.exists()}')
        return 2

    env = dict(os.environ)
    env['MXF_QC_USER_DATA_DIR'] = str(SOAK_DIR / 'user_data')

    deadline = time.monotonic() + args.hours * 3600
    cycle_timeout = args.play_seconds + 240
    results = []
    log(f'soak 시작: {args.hours}h, cycle={args.play_seconds}s, sample={sample.name}')
    log(f'중지하려면 이 파일을 만드세요: {STOP_FILE}')

    cycle = 0
    while time.monotonic() < deadline:
        if STOP_FILE.exists():
            log('STOP 파일 감지 — 안전 정지')
            break
        cycle += 1
        t0 = time.monotonic()
        mem = {}
        stop_evt = threading.Event()
        sampler = threading.Thread(target=peak_memory_sampler, args=(exe.name, stop_evt, mem), daemon=True)
        sampler.start()
        try:
            r = subprocess.run(
                [str(exe), '--mxf-stability-test', str(sample),
                 '--play-seconds', str(args.play_seconds), '--check-interval', '30'],
                cwd=str(exe.parent), env=env, timeout=cycle_timeout,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            code = r.returncode
        except subprocess.TimeoutExpired:
            code = -1
        stop_evt.set()
        sampler.join(timeout=5)
        elapsed = time.monotonic() - t0
        peak_mb = mem.get('peak', 0) / 1024
        results.append((cycle, code, elapsed, peak_mb))
        log(f'cycle {cycle}: exit={code} elapsed={elapsed:.0f}s peak_mem={peak_mb:.0f}MB')
        if code != 0:
            log(f'FAIL cycle {cycle} — 소크 중단 (로그: %LOCALAPPDATA% 아님, {SOAK_DIR}\\user_data\\logs)')
            break
        time.sleep(5)

    ok = [r for r in results if r[1] == 0]
    log('=' * 50)
    log(f'soak 종료: 총 {len(results)}사이클, 성공 {len(ok)}, 실패 {len(results) - len(ok)}')
    if len(ok) >= 2:
        first, last = ok[0][3], ok[-1][3]
        max_peak = max(r[3] for r in ok)
        drift = last - first
        log(f'메모리: 첫 사이클 피크 {first:.0f}MB → 마지막 {last:.0f}MB (변화 {drift:+.0f}MB), 전체 최대 {max_peak:.0f}MB')
        log('메모리 추이 판정: ' + ('안정 (누수 징후 없음)' if drift < 150 else '증가 추세 — 누수 의심, 로그 검토 필요'))
    return 0 if results and all(r[1] == 0 for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
