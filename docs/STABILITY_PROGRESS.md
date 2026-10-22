# Netcheck Center 안정성 개선 진행 기록

## 작업 기준과 승인 범위

- 대상 저장소: `yejin0414/auto_network`만 사용한다.
- 시작 기준 `main` Commit: `bc413434f76068ee443d620a65ba0d622d867cc2`.
- 기준 Tree: `d9ef5138473bbcd09d5e43469e8eeae7b5250f7b`.
- 계획 승인: 2026-10-22 대화에서 사용자 승인. S-01부터 한 번에 한 작업씩 수행한다.
- 작업 브랜치: `stability/s01-credential-startup`. 미병합 변경을 같은 브랜치/PR #8에서 작업별 별도 Commit으로 추적한다.
- 계속 진행 승인: 2026-10-22 사용자의 '검증 성공 시 기존 승인 범위 안에서 다음 단계로 계속 진행' 지시에 따라, 실제 검증 성공 후 승인된 다음 작업을 한 번에 하나씩 수행한다. S-04의 별도 방침 승인 보류는 유지한다.
- S-04의 비정상 수치를 '확인 불가'로 처리하는 방침은 별도 승인 전까지 보류한다.
- 기존 기능, 장비 명령, 판정 기준, UI/API/보고서 형식, 인증/DB/스케줄 호환성을 보존한다.
- 운영 장비와 실제 운영 계정/DB는 사용하지 않는다. Mock, Fixture, Demo, 폐기 가능한 Windows CI만 사용한다.
- `main` 직접 수정, 원본 저장소 접근/동기화, PR 병합, 릴리스 생성, 자동 배포는 하지 않는다.

## 진행률 산정

전체 진행률 = 검증까지 완료된 작업 가중치 합계 / 확정된 전체 가중치 합계 × 100.

- 전체 작업: 9개, 가중치 합계: 100%.
- 현재 완료: 6개, 진행 중: 1개, 대기: 1개, 보류: 1개, 실패: 0개.
- 현재 진행률: **75.0%** ((S-01 15 + S-02 20 + S-03 15 + S-05 10 + S-06 10 + S-07 5) / 100). S-07 완료 증가: **+5.0%p**.
- 진행률: `[███████████████░░░░░] 75.0%` (한 칸 5%p).
- 로컬 재현 및 테스트 통과만으로 완료 처리하지 않는다. 변경 코드에 대한 실제 GitHub Actions 성공 근거가 필요하다.
- 미검증, 진행 중, 보류 작업은 완료 가중치에 포함하지 않는다.
- 이 기록을 새 세션에서 읽을 때 실제 Commit, PR, Actions 상태를 대조한다. 완료 작업을 중복 계산하거나 진행률을 임의로 초기화하지 않는다.
- 100%는 이 계획의 검증 완료를 뜻하며 결함이 전혀 없음을 보장하지 않는다.

## 전체 작업 현황

| ID | 개선 대상 | 위험 등급 | 가중치 | 상태 | 검증 |
|---|---|---|---:|---|---|
| S-01 | 시작 시 인증 조회 실패 후 기존 계정 덮어쓰기 방지 | High | 15% | 완료 | Actions 39786408187 및 39788528305 전체 성공, 330개 테스트 및 EXE 검증 통과 |
| S-02 | 장비 시간 초과 후 대기 작업 정체 및 늦은 진행 상태 갱신 방지 | High | 20% | 완료 | Actions 39793991393 전체 성공, 345개 테스트 및 EXE 검증 통과 |
| S-03 | 이력 정리와 조회/보고서 생성 간 일관성 보장 | Medium | 15% | 완료 | Actions 39801880979 전체 성공, 363개 테스트 OK(미지원 WAL 하위 사례 4개 skip), EXE 검증 통과 |
| S-04 | 비정상 숫자 파싱 오류 격리 | High | 15% | 보류 | 별도 처리 방침 승인 필요 |
| S-05 | SSH 진단 응답 한도와 연결 자원 정리 | Medium | 10% | 완료 | Actions 39806415444 전체 성공, 381개 테스트 OK(기존 WAL 하위 사례 4개 skip), EXE 검증 통과 |
| S-06 | UI 이력 응답 역전 및 일시 조회 실패 복구 | Medium | 10% | 완료 | Actions 39810972763 전체 성공, Node UI15개/기존 설정/Python381개/EXE 검증 통과 |
| S-07 | Excel 제목/부제의 제어 문자 방어 | Medium | 5% | 완료 | Actions 39814068606 전체 성공, 신규 Excel6개/Python387개/EXE 검증 통과 |
| S-08 | 비정상 보고서 ID/토큰 예외 처리 | Low | 5% | 진행 중 | 신규11개/기존26개 로컬 PASS, 변경 코드 Actions 미실행 |
| S-09 | 최종 기능 보존 및 Windows 실행 검증 | Low | 5% | 대기 | 미실행 |

가중치 변경 내역: 없음. 기존 이전/개선 작업은 이 계획의 완료 가중치로 다시 계산하지 않는다.

## 기존에 해결된 문제와 기준 검증

기존 이력은 [MIGRATION_ANALYSIS.md](MIGRATION_ANALYSIS.md)의 F01–F34와 다음 PR에서 확인했다.

- [PR #2](https://github.com/yejin0414/auto_network/pull/2): Windows 짧은 경로 별칭 검증.
- [PR #3](https://github.com/yejin0414/auto_network/pull/3): VRRP 이력과 과거 보고서 기준 보존.
- [PR #4](https://github.com/yejin0414/auto_network/pull/4): 클러스터 대체 수집, 실행 세대 취소, Windows 작업 동기화.
- [PR #5](https://github.com/yejin0414/auto_network/pull/5): 계정/설정 저장 보상 복구와 선택 명령 파싱.
- [PR #6](https://github.com/yejin0414/auto_network/pull/6): 기준값 수명, SQLite 원자 저장, 백업/복원.
- [PR #7](https://github.com/yejin0414/auto_network/pull/7): 대용량 DB, 온라인 백업, 외부 패키지 복원.

기준 Commit의 [Actions 39776407167](https://github.com/yejin0414/auto_network/actions/runs/39776407167)은 실제 로그와 Job 결과를 확인했다. Windows Python 3.12.10 / SQLite 3.49.1에서 단위/통합 테스트 327개, 합성 1GiB DB 검증, EXE 빌드 및 실행 검사가 성공했다. 이는 수정 전 기준 근거이며 새 변경의 성공 근거로 대체하지 않는다.

최초 분석과 S-01 착수 전 확인에서 열린 개선 PR 및 기존 `STABILITY_PROGRESS.md` 이력은 없었다. 기존 Issue #1은 과거 접근 권한 요청이며 이번 결함의 중복 Issue가 아니다.

## 작업별 계획 및 완료 조건

### S-01 — 시작 시 인증 조회 실패 후 계정 덮어쓰기 방지

- 근거: `load_saved()`가 Keyring 조회 예외를 계정 부재로 처리해 우선순위가 낮은 legacy 계정을 가져오고, 정상 저장된 shared 계정을 덮어쓴다. 첫 조회만 실패하는 Mock으로 재현했다.
- 영향 파일: `nc/credentials.py`, `tests/test_settings_transaction.py`, 이 진행 기록. `tests/test_account.py`는 수정 없이 기존 테스트를 재사용한다.
- 변경 전후: 읽기 실패 후 legacy 이전/삭제가 일어남 → 해당 호출의 탐색을 중단해 저장된 원문과 메모리 상태를 보존한다.
- 방법: `get_password()` 예외 분기만 조정한다. 실제 부재일 때의 기존 shared → backbone → aruba 순서, 저장 형식, `apply()` 보상 복구는 유지한다.
- 기능 변경 위험: Low. 저장소 읽기 실패 경로만 바뀌며 정상 계정 로드와 이전 동작은 동일하다.
- `storage_uncertain`의 기존 값은 유지한다. 현재 UI가 이 플래그로 계정 삭제 후 재저장을 안내하므로, 쓰지 않은 조회 오류를 이유로 새 삭제 안내를 유발하지 않는다.
- 테스트: shared 및 backbone의 일시 조회 실패, 저장 원문 불변, set/delete 0회, 메모리 미주입, 불확실성 플래그 보존, 같은 객체/재시작의 정상 로드, 정상 우선순위, backbone/aruba 이전, Demo 격리, 설정 저장/복구.
- 완료 조건: 위 회귀가 통과하고 변경 Commit의 Windows Actions 전체 성공 및 기존 EXE 계정 저장/재시작 검증을 확인한다.
- 가중치: 15%.

### S-02 — 장비 시간 초과 후 대기 작업 정체 및 늦은 상태 갱신 방지

- 근거: `engine.py`의 일반 수집은 작업자 진입 후에만 시작 시각을 기록한다. 병렬도 1에서 첫 작업자가 멈추면 큐의 다음 작업은 시간 초과 대상에도 들어가지 못해 실행이 끝나지 않는다. 늦게 복귀한 작업자가 같은 실행의 '응답 없음'을 '완료'로 덮어쓰는 현상도 Mock으로 재현했다.
- 영향 파일: `nc/engine.py`, `tests/test_engine_timeouts.py`, 이 진행 기록.
- 변경 전후: 대기 작업 정체/만료된 진행 상태 갱신 → 제한된 시간과 자원 내에서 실행을 마무리하고 만료된 작업의 갱신을 무시한다.
- 방법: 일반 수집 worker와 해당 연결 종료 helper의 실제 수명을 Engine에서 회차를 넘어 추적한다. 실제로 종료된 뒤에만 병렬 슬롯을 반환하며, 장비 ID와 접속 identity가 모두 같은 작업의 중복 실행을 차단한다. 개별 취소와 진행 상태 발행에 같은 lock을 사용한다. 정상 대기 장비는 슬롯이 비면 기존 제한 시간 전체를 받는다.
- 기능 변경 위험: Low–Medium. 정상 명령/병렬도/장비별 제한 시간과 기존 강제 종료 유예시간, 판정기, 보고서/API 형식은 보존한다. 수정 전에 비정상 경로의 다음 차이를 대화에서 보고했다.
- 비정상 경로의 차이: 모든 사용 가능한 슬롯이 취소 후에도 실제 종료되지 않은 작업으로 막힌 경우, 기존 `device_grace`(기본 45초, 최소 supervisor poll 1초)를 추가 정리 대기 한도로 사용한다. 이 한도는 작업 최초 취소 시 한 번만 설정하며 루프/다음 회차에서 연장하지 않는다. 그 안에 연결이 정리되면 대기 장비 수집을 계속한다. 끝내 슬롯을 확보하지 못한 장비는 접속 미시도 사유를 기록하고 기존 수집 실패 판정인 '확인 불가'로 저장한다. 장비를 '장애'로 판정하거나 성공한 것처럼 기록하지 않는다.
- 자원 상한: 일반 수집 작업은 이전 회차의 잔존 작업을 포함해 설정 병렬도에 따라 새 작업을 허용하며, 각 작업은 연결 종료 helper를 최대 1개 만든다. 병렬도를 낮춘 경우 이미 실행 중인 작업이 종료될 때까지 새 작업을 제한한다. 별도로 검증된 cluster fallback의 동작/수명 정책은 이번 범위에서 변경하지 않는다.
- 테스트: Mock driver가 잠든 상태에서 대기 작업, 취소, 늦은 반환, 세대 변경, 저장 횟수, 재실행, 기존 cluster fallback 회귀.
- 완료 조건: 실제 운영 장비 없이 정체가 해소되고, 실행 종료 후 상태/저장 중복이 없으며 Windows CI가 통과한다.
- 가중치: 20%.

### S-03 — 이력 정리와 조회/보고서 생성 간 일관성 보장

- 근거: `get_run()`의 부모/장비/명령 조회 사이에 `prune()`이 완료되면 요약은 존재하지만 장비 목록이 비어 있는 이력이 반환된다. 임시 SQLite와 Event로 재현했다. 보고서의 이후 raw 조회에도 동일 수명의 위험이 있다.
- 영향 파일: `nc/store.py`, 필요 최소한의 보고서 조회 경로, DB/보고서 관련 테스트, 이 진행 기록.
- 변경 전후: 삭제 시점에 따라 부분 이력/빈 원문 반환 → 필요한 단일 이력과 원문을 일관된 시점으로 확보하거나 기존 미존재 응답을 반환한다.
- 방법: 기존 DB 스키마/보존 기간/보고서 형식을 유지한 읽기 일관성 확보. 대용량 직렬화 전체를 잠가 기존 응답성을 훼손하지 않는다.
- 기능 변경 위험: Low–Medium. 정상 데이터 내용과 반환 형식은 보존한다.
- 테스트: 같은 Store 및 별도 연결의 동시 prune, 상세 이력/Excel 원문, 기존 백업/대용량 조회 회귀.
- 완료 조건: 부분 결과가 재현되지 않고 보고서 원문과 장비 결과가 같은 이력을 가리키며 CI가 통과한다.
- 가중치: 15%.

### S-04 — 비정상 숫자 파싱 오류 격리 (별도 승인 전 보류)

- 근거: 매우 긴 uptime 숫자에서 `int()` 예외가 전파돼 현재 전체 실행 결과가 저장되지 않는 현상을 Demo로 재현했다. 일부 수치의 비정상 범위는 음수/비유한 값도 만들 수 있다.
- 영향 파일: `nc/parsers.py`, 필요한 `nc/evaluate.py`/격리 경계, 관련 Fixture/테스트, 이 진행 기록.
- 변경 전후: 비정상 한 항목이 전체 실행 실패 또는 잘못된 수치를 만듦 → 해당 항목을 격리하고 승인된 비정상 값 처리 결과를 반환한다.
- 방법: 입력/변환을 좁게 방어한다. 예외를 포괄적으로 숨기거나 정상 임계값을 변경하지 않는다.
- 기능 변경 위험: Medium. 현재 uptime의 단순 `None` 반환은 '정상'이 될 수 있어 임의 적용하지 않는다. 비정상 수치를 '확인 불가'로 처리하는 방침을 별도로 승인받는다.
- 테스트: 긴 숫자, 비유한/범위 밖 수치, 잘린 출력, 정상 전체 Fixture와 판정 비교, 한 장비 오류 시 다른 장비 결과 보존.
- 완료 조건: 처리 방침 승인, 정상 결과 동일, 부분 오류 격리 및 Windows CI 통과.
- 가중치: 15%.

### S-05 — SSH 진단 응답 한도와 연결 자원 정리

- 근거: 배너 이전 완결된 줄이 누적될 때 전체 길이/전체 시간 제한이 없다. Mock에서 1,000줄, 1,023,000문자가 쌓였다. 인증 후 `open_session()` 예외에서는 Transport의 명시적 close가 호출되지 않았다. 실제 운영 OS의 누수량은 미측정이다.
- 영향 파일: `nc/diagnose.py`, 관련 진단 테스트, 이 진행 기록.
- 변경 전후: 응답 누적/예외 경로 자원 정리 누락 → 기존 한도를 전체 읽기에 적용하고 획득한 자원을 모든 종료 경로에서 정리한다.
- 방법: 기존 timeout/길이 한도 활용, monotonic 시간 측정, 좁은 try/finally 정리. 기존 진단 응답 형식/재시도 정책 유지.
- 기능 변경 위험: Low. 정상 SSH 교환/명령/결과는 보존한다.
- 테스트: 완료된 줄의 지속 수신, 조각 응답, EOF, KEX 부분 응답, 인증/채널 예외의 close 횟수, 오류 원인 보존.
- 완료 조건: 응답 누적이 제한되고 Mock 자원 소유권 정리가 검증되며 CI가 통과한다.
- 가중치: 10%.

### S-06 — UI 이력 응답 역전 및 일시 조회 실패 복구

- 근거: 최근 선택한 이력보다 이전 요청이 늦게 오면 과거 선택으로 화면이 되돌아간다. 최신 ID를 성공 전 확정하므로 일시 fetch 실패 뒤 같은 최신 이력을 다시 조회하지 않는다. 실제 JS 함수의 순서 제어 Mock으로 재현했다.
- 영향 파일: `web/app.js`, `tests/test_settings_ui.cjs` 또는 같은 검증 경로, 이 진행 기록.
- 변경 전후: 응답 도착 순서에 따른 오표시/복구 정체 → 최신 선택에 해당하는 성공 응답만 표시하고 일시 실패 후 재시도한다.
- 방법: 요청 소유권과 성공 확정 시점을 최소 수정한다. HTML/CSS, 버튼, 메뉴, API를 바꾸지 않는다.
- 기능 변경 위험: Low. 정상 화면/사용 흐름을 보존한다.
- 테스트: 역순 Promise 완료, 실패 후 같은 최신 ID 복구, 이력 선택 유지, 기존 설정 저장 흐름.
- 완료 조건: 선택과 표시가 일치하고 재시도가 회복하며 UI/Windows CI가 통과한다.
- 가중치: 10%.

### S-07 — Excel 제목/부제의 제어 문자 방어

- 근거: 설정에서 허용된 site_name의 제어 문자가 제목/부제 셀에 그대로 들어가 `IllegalCharacterError`로 보고서 전체 생성이 실패한다. Mock 설정/보고서로 재현했다.
- 영향 파일: `nc/excel.py`, Excel 관련 테스트, 이 진행 기록.
- 변경 전후: 출력 불가능한 제목 문자 하나로 생성 실패 → 기존 셀 정리 정책 중 금지 제어 문자 제거만 제목/부제에도 적용해 생성한다.
- 방법: 출력 경계의 두 셀 대입만 방어하고 원본 설정/DB는 변경하지 않는다. 기존 `_clean()`의 32,000자 제한까지 적용하면 정상 제목의 기존 32,767자 처리와 달라지므로, 같은 `ILLEGAL` 정규식만 사용해 정상 길이 처리를 보존한다.
- 기능 변경 위험: Low. 정상 문자열과 시트 구성, 형식, 수식 주입 방어를 유지한다.
- 테스트: 제어 문자 제목/부제, 정상 현재/과거 보고서, 기존 시트/서식/타입과 Windows Excel 저장.
- 완료 조건: 문제 입력으로 생성 가능하고 정상 보고서 회귀 및 CI가 통과한다.
- 가중치: 5%.

### S-08 — 비정상 보고서 ID/토큰 예외 처리

- 근거: 보고서 ID의 숫자 변환 실패와 비 ASCII 토큰 비교에서 처리되지 않은 ValueError/TypeError가 발생한다. 소켓 없는 실제 handler Mock에서 재현했다. 같은 보고서 ID 경계의 SQLite 정수 범위 초과 OverflowError도 임시 Store에서 추가 재현했다. 프로그램 전체 종료로 확대 해석하지 않는다.
- 영향 파일: `nc/server.py`, HTTP 관련 테스트, 이 진행 기록.
- 변경 전후: 잘못된 요청에서 응답 전 예외 → 기존 오류 응답 정책에 따라 처리한다.
- 방법: 변환/토큰 비교 경계만 방어한다. 기존 API의 입력 오류 400 정책을 보고서 ID에도 적용하고, 보고서의 403/404/503 및 `/api/bye`의 잘못된 종료 신호 무시/204 정책을 보존한다. SQLite 범위 초과는 보고서 조회 호출만 감싸 OverflowError를 처리한다. 렌더러나 다른 DB 오류를 400으로 재분류하지 않는다.
- 기능 변경 위험: Low. 정상 API/파일 형식과 종료 기능은 동일하다.
- 테스트: 잘못된 ID, 비 ASCII/누락/잘못된 토큰, 정상 다운로드, 종료 콜백 부작용 없음, DB 오류 응답.
- 완료 조건: 예외가 밖으로 나오지 않고 정상 API 회귀 및 CI가 통과한다.
- 가중치: 5%.

### S-09 — 최종 기능 보존 및 Windows 실행 검증

- 근거: 여러 안정성 변경이 누적된 최종 코드에 대한 검증이 필요하다. 새 기능 작업이 아니다.
- 영향 파일: 필요한 최소 검증 테스트 및 이 진행 기록. 검증 근거 없이 workflow/패키지를 바꾸지 않는다.
- 변경 전후: 개별 작업 검증 → 최종 합계 코드와 시작 기준의 기능 보존 근거를 정리한다.
- 기능 변경 위험: Low. 검증/기록 작업이다.
- 테스트: 아래 기능 보존 표, 전체 Windows Actions, EXE/계정/DB/예약 작업/창 테스트. 실제 장비는 사용하지 않는다.
- 완료 조건: 승인된 선행 변경이 모두 검증되고 최종 CI, PR/Commit, 미검증 범위를 기록한다. S-04가 보류인 동안 전체 완료를 선언하지 않는다.
- 가중치: 5%.

## 기능 보존 체크리스트

| 기존 기능 | 누적 확인 방법 | S-07 코드 Actions 누적 확인 상태 |
|---|---|---|
| BB/MM/WLC 명령과 결과 | 명령/collector/evaluate 변경 없음, 기존 전체 CI | CI Mock/Fixture 검증 통과 |
| CPU/메모리 및 임계값 | parser/evaluate 변경 없음, Fixture 테스트 | CI 통과 |
| VRRP/OSPF/LACP/인터페이스 | 기존 판정/이력 테스트 | CI 통과 |
| WLC 클러스터/Client 분배 | 기존 cluster 회귀 | CI 통과 |
| 정상/주의/장애/확인 불가 표시 | 판정/표시 문구 보존, 기존 회귀 | CI 통과 |
| 이력/기준값/DB 호환성 | 스키마 보존, 이력 조회 snapshot 및 DB/대용량/복원 회귀 | CI 통과, 실제 사용 DELETE 동시 정리 검증 통과 |
| Excel/HTML 보고서 | 생성 모듈/형식 보존, 원본 snapshot·과거 context 회귀 | 신규/기존 테스트 및 EXE Excel 저장/내려받기 통과 |
| 자동 점검/Windows 작업 스케줄러 | 기존 Windows 작업 검사 | CI 통과, 장시간 운영/절전 복귀 미검증 |
| 인증 정보/기존 저장 형식 | Mock 조회 오류/정상 이전/저장 보상 복구 | CI 및 EXE 저장/재시작 검증 통과 |
| 웹 UI/좁은 화면 | HTML/CSS 보존, 실제 JS 요청 경합 및 기존 UI/창 검사 | 신규 Node15개/기존 설정/창 CI 통과, 별도 모바일 기기/좁은 화면 수동 검증 미실행 |
| Windows EXE 실행 | 기존 빌드/계정 재시작/중복 실행/창/작업 검사 | CI 통과 |

기준 앱은 loopback에 바인딩된다. 외부 모바일 장비의 네트워크 접속을 새 기능으로 추가하지 않는다. 실장비 통신, 실제 PC의 장시간 예약 실행/절전 복귀, 사용자 화면에서 실제 토스트 알림 확인은 미검증이며 CI의 Mock/폐기 가능한 환경 성공과 구분한다.

S-02의 기능 보존 확인: 정상 직렬 순서/병렬 상한/실제 시작 시점의 제한 시간, MM 명령과 CPU·메모리/정상 판정, 기존 클러스터 fallback, 기준값·이력 원자 저장, 과거 보고서와 VRRP, 스케줄러 반복/폐기 후 재실행 회귀가 로컬 및 Windows Actions에서 통과했다. `commands.py`, `collector.py`, `parsers.py`, `evaluate.py`, Store/DB 스키마, 자격 증명 저장 코드, UI/API/보고서 모듈, workflow/패키지는 S-01 완료 코드에서 바꾸지 않았다. 해당 단계의 검증 근거는 [S-02 코드 Actions 39793991393](https://github.com/yejin0414/auto_network/actions/runs/39793991393)다.

현재 위 표는 [S-07 코드 Actions 39814068606](https://github.com/yejin0414/auto_network/actions/runs/39814068606)의 전체 테스트 및 Windows EXE 누적 검증 결과로 갱신했다. S-07은 Excel 제목/부제의 금지 문자 제거 두 줄만 보강했고, 기존 길이/서식/수식 문자열/저장 context와 DB 불변을 신규6개에서 검증했다. S-06은 화면 구성/HTML/CSS/API를 유지하면서 JS 응답 적용과 최신 재시도만 보강했고 실제 함수 회귀15개와 기존 설정 검증이 통과했다. S-05의 정상 진단 단계/명령/결과 보존은 신규 Mock 회귀와 실제 SDK/가짜 SSH 서버 통합에서 통과했다. S-03은 Store 읽기와 Excel 호출부만 보강했고, 명령·판정·DB 스키마·UI·보고서 생성 형식·workflow·패키지는 보존했다. Windows SQLite 3.49.1의 기존 정책에 따라 WAL 하위 사례 4개는 skip이며 실제 사용 모드 DELETE 검증은 통과했다. WAL 경합은 로컬 SQLite 3.53.1에서 통과한 별도 근거로 구분한다. 실제 운영 장비·장시간 사용·모바일 기기·토스트 수동 확인은 계속 미검증이다.

## S-01 실행 기록

1. 기준 Commit/열린 PR/브랜치/진행 문서 이력을 다시 확인했다. 기준은 변경되지 않았다.
2. 별도 브랜치 `stability/s01-credential-startup`을 기준 SHA에서 생성했다.
3. 코드 수정 전 기존 계정/설정 테스트 19개가 로컬에서 통과했다.
4. 먼저 추가한 회귀 테스트를 기존 코드에 적용했다. shared/backbone 각각에 대해 기존 불확실성 상태 False/True의 4개 하위 사례가 모두 실패하며 저장 계정 변경을 재현했다. 합성 계정과 메모리 Keyring만 사용했다.
5. 조회 예외에서 즉시 중단하도록 제품 코드 1개 분기만 수정했다.
6. `python -m unittest tests.test_account tests.test_settings_transaction tests.test_app_regressions -v`: 로컬 Python 3.12에서 43개 통과. 신규 테스트 3개와 기존 legacy 이전의 aruba 하위 사례를 포함한다.
7. 코드 Commit: `dea5d326cb12e2f8ee008ffdbd1cc63f65ef3133`. [PR #8](https://github.com/yejin0414/auto_network/pull/8)은 Draft이며 병합하지 않았다.
8. [Windows Actions 39786408187](https://github.com/yejin0414/auto_network/actions/runs/39786408187): `head_sha`가 위 코드 Commit과 일치하며 `completed/success`이다. Job `119850680453`의 전체 단계 성공 및 실제 로그를 확인했다. 실행 시작 2026-10-22 13:23:31 UTC, 완료 상태 갱신 13:36:01 UTC.
9. 해당 로그: Windows Python 3.12.10 / SQLite 3.49.1, `Ran 330 tests in 177.187s`, `OK`. 새 `test_startup_*` 3개와 legacy 이전 회귀가 모두 `ok`다.
10. 소스 스냅샷 114개 파일 점검, 설정 UI 검증, 합성 1GiB DB 조회/원자 저장/백업/외부 전송/원본 없는 복원/정리 보존 단계가 모두 성공했다.
11. EXE 빌드, Demo 1회 실행, 계정 저장/설정 저장 실패 후 보상 복구/재시작 Mock SSH, 중복 실행/포트 독점, 창/Excel 저장, Windows 예약 작업 검증이 모두 성공했다.
12. 로그의 `NOT_RUN: 사용자 화면에 토스트가 실제 표시되었는지 수동 확인`은 미검증으로 유지한다. 실제 장비/장시간 운영 검증으로 확대 해석하지 않는다.
13. 코드/테스트 독립 검토에서 차단할 문제가 없었다. 최종 기록 갱신은 문서만 변경하며 제품 코드와 테스트는 위 검증 Commit과 동일하다. 이후 문서 갱신으로 추가 실행된 CI의 상태는 [PR #8의 checks](https://github.com/yejin0414/auto_network/pull/8/checks)에서 대조한다.
14. S-01 기록 Commit `0db74253439c83b2d924fa7d6aa07fd73e2793bb`의 [Actions 39788528305](https://github.com/yejin0414/auto_network/actions/runs/39788528305)도 전체 `completed/success`임을 확인했다. Job `119858017305`, `Ran 330 tests in 147.551s`, `OK`; EXE/대용량 DB/Windows 단계 모두 성공했다. S-02 착수 시 이 Commit을 작업 기준으로 재확인했다.

S-01 완료 시점의 판정: 위 실제 Actions 성공을 근거로 S-01을 완료 처리했다. 당시 S-01의 15%만 반영한 진행률은 15.0%였다. PR 병합이나 운영 배포 완료를 의미하지 않는다.

로컬 테스트는 Windows CI 성공의 대체 근거가 아니다. GitHub Tree 비교로 제품 코드/테스트 2개 및 이 문서만 변경했으며 나머지 111개 추적 파일은 기준과 동일함을 확인했다.

## S-02 실행 기록

- 승인: S-01 완료 보고 후 2026-10-22 사용자의 '승인'에 따라 S-02만 착수했다.
- 이번 작업 기준: S-01 완료 `0db74253439c83b2d924fa7d6aa07fd73e2793bb`, Tree `29fa3e4ba7f761b58a00f391877d7bead19c0c40`. `main`은 최초 기준 `bc413434f76068ee443d620a65ba0d622d867cc2`와 동일했다.
- 코드 Commit: [`44a8e91a729c5a3e90d404a95e67aaee5f16818e`](https://github.com/yejin0414/auto_network/commit/44a8e91a729c5a3e90d404a95e67aaee5f16818e).
- 추적: 기존 [Draft PR #8](https://github.com/yejin0414/auto_network/pull/8)에 S-02를 별도 Commit으로 추가했다. 중복 PR/Issue, 병합, 릴리스, 배포는 하지 않았다.
- 변경 파일: `nc/engine.py`, 신규 `tests/test_engine_timeouts.py`, 이 문서. S-01 제품 코드/테스트는 그대로 유지한다.

### 수정 전 재현

동일한 신규 테스트를 수정 전 S-01 코드에 적용해 다음 3개 실패를 확인했다. Mock의 gate는 테스트 실패 후에도 해제/join했으며 실제 장비를 사용하지 않았다.

1. `test_blocked_worker_does_not_strand_queued_device_or_publish_late_results`: 첫 worker가 반환하지 않으면 다음 장비가 큐에 남아 회차 종료 확인에 실패했다.
2. `test_late_open_is_closed_without_commands_or_state_changes`: open 정체에서도 대기 장비 때문에 회차 종료 확인에 실패했다.
3. `test_repeated_runs_do_not_duplicate_busy_identity_or_abort_helpers`: 같은 장비의 이전 worker가 살아 있어도 새 회차마다 다시 열어 기대 1회 대신 4회 접속 시도를 기록했다.

별도 같은 회차 비교에서는 저장 결과가 `unknown`인 상태에서 늦은 worker 반환 후 진행 상태가 '응답 없음' → '완료'로 바뀌었다. 수정 후에는 '응답 없음'을 유지하고, DB 결과/기준값/저장 횟수도 변하지 않았다.

### 수정과 범위

- 일반 수집의 실제 worker/abort helper 수명을 회차를 넘어 추적하고, 종료된 슬롯만 다시 사용한다. 장비 ID와 접속 identity가 모두 같은 작업의 중복 연결을 방지하며 표시 이름 변경은 새로운 장비로 취급하지 않는다. 같은 ID라도 주소가 바뀌면 여유 슬롯에서 새 장비를 점검하는 기존 재설정 흐름을 보존한다.
- 개별 취소 이벤트로 늦은 명령·진행 상태·결과 발행을 차단한다. 취소와 진행 상태 갱신은 같은 lock에서 확인한다.
- 기존 장비별 제한 시간/강제 종료 유예시간을 보존하고 supervisor 경과 시간은 monotonic clock으로 측정한다. 대기 시간은 다음 장비의 수집 예산을 소모하지 않는다.
- 모든 슬롯이 정체된 경우 최초 취소 시 정한 한정된 정리 대기 후 접속 미시도 사유와 기존 '확인 불가' 판정으로 마무리한다. 정상적으로 연결이 종료되면 나머지 장비를 계속 점검한다.
- 독립 검토에서 abort helper의 `Thread.start()` 실패가 timeout 저장을 중단하는 경로를 추가 재현했다. 이 `RuntimeError`를 경고로 기록하고 취소/슬롯/기한을 유지해 다른 작업의 취소와 회차 완료를 계속한다. 일반 collection worker 시작 실패는 기존 전체 회차 미저장/오류 계약을 유지하고 다음 실행의 회복을 검증했다.
- 일반 수집 worker는 daemon으로 실행한다. 종료할 수 없는 Python 스레드 자체를 강제 제거한다고 주장하지 않는다. 실제로 끝나지 않은 일반 작업은 슬롯에 계속 포함된다. cluster fallback은 변경하지 않았다.

### 로컬 검증

- 신규 `tests/test_engine_timeouts.py`: 15개 PASS. 실제 collector/evaluate/임시 SQLite를 이용하며 open/run/close/abort를 Mock gate로 제어한다. 대기/늦은 반환/정상 결과/병렬도/회차 변경/stop/identity 교체/고정 정리 기한/시작 실패를 포함한다.
- 별도 자식 Python 프로세스에서 수집과 abort를 모두 반환하지 않게 만든 뒤 timeout 결과가 저장되고 인터프리터가 종료 코드 0으로 끝나는 것을 확인했다. daemon 속성만으로 종료를 주장하지 않았다.
- 최종 수정 코드에서 다음 명령으로 **94개, 41.590초, OK, 종료 코드 0**을 확인했다.

```text
python -m unittest tests.test_engine_timeouts tests.test_timeouts tests.test_cluster_fallback tests.test_collection_regressions tests.test_baseline_lifecycle tests.test_schedule.Scheduler tests.test_scheduler_refresh tests.test_report_snapshots tests.test_report_capture tests.test_vrrp_stability -v
```

- 두 Python 변경 파일의 문법 검사 PASS. 로컬 비교에서 변경 2개(Engine/진행 기록), 추가 1개(회귀 테스트), 삭제 0개를 확인했다.
- 최초 테스트 초안의 일반 worker 시작 실패 기대값은 기존 코드 계약과 달라 1개 실패했다. 제품의 기존 미저장 동작을 보존하고 테스트 기대를 수정한 뒤 위 최종 94개가 통과했다. 독립 검토에서 발견한 abort helper 시작 실패 경로도 보완 및 전용 테스트를 통과했다.
- 로컬 검증 시점에는 Actions 성공 전이었으므로 S-02를 진행 중, 전체 15.0%로 유지했다. 이후 아래 실제 Windows Actions 성공을 확인했다.

### GitHub Actions 검증 및 완료 판정

1. [Actions 39793991393](https://github.com/yejin0414/auto_network/actions/runs/39793991393)은 `head_sha=44a8e91a729c5a3e90d404a95e67aaee5f16818e`, 최종 `completed/success`다. 시작 2026-10-22 14:14:34 UTC, 완료 상태 갱신 14:35:49 UTC를 확인했다.
2. [Job 119876674023](https://github.com/yejin0414/auto_network/actions/runs/39793991393/job/119876674023)의 모든 단계가 `completed/success`이며 실제 로그를 읽었다. Windows Python 3.12.10 / SQLite 3.49.1에서 **`Ran 345 tests in 191.822s`, `OK`**다. 신규 timeout 회귀 15개와 기존 테스트가 모두 통과했다.
3. 새 자식 Python 종료 테스트도 Windows에서 실제 통과했다. 수집/abort가 반환하지 않는 Mock 상황에서 timeout 회차 저장 후 정상 종료를 검증했다.
4. 공개 소스 스냅샷 115개 파일 점검과 Node 설정 UI 검증이 통과했다. 합성 1GiB DB의 원자 저장, 온라인 백업, 외부 패키지 전송, 원본 없이 복원, 논리 fingerprint/해시 일치, 복원 DB 조회 및 보존 정리가 모두 PASS다.
5. EXE 빌드, Demo 1회 점검, 계정 저장·저장 실패 보상 복구·재시작 Mock SSH, 중복 실행/포트 독점, Edge 앱 창·종료·Excel 저장/내려받기, Windows 예약 작업 검증이 모두 통과했다. 기존 workflow의 artifact 묶기/업로드도 성공했으며 릴리스·배포·병합은 수행하지 않았다.
6. `NOT_RUN: 사용자 화면에 토스트가 실제 표시되었는지 수동 확인`은 미검증으로 유지한다. 실제 장비 통신, 실제 PC 장시간 실행/절전 복귀, 모바일 기기 수동 검증도 미실행이다.
7. GitHub Tree 비교에서 S-01 기준 114개 → 115개 파일, Engine/이 기록 변경 및 새 회귀 테스트 추가만 확인했다. 삭제 0개이며 S-01 제품 코드/테스트와 나머지 파일은 동일하다. 독립 코드/테스트/기록 검토에서도 추가 차단 결함은 발견하지 못했다.

**S-02 완료 판정:** 코드 Commit의 실제 Windows Actions 전체 성공에 근거해 20%를 반영한다. 누적 완료는 S-01/S-02, **35.0%**, 이전 대비 **+20.0%p**다. 남은 7개 작업의 가중치는 65%이며 S-04 보류를 포함한다.

검증 결과를 정리하는 후속 Commit은 이 문서만 변경한다. Engine blob `ff8543e4a3824aad4fa0fdf4ee7c65187c85fda7`과 회귀 테스트 blob `ca3e28f760aca2e22e3983fa7655537df5681c72`는 위 검증 코드와 동일하게 유지한다. 문서 Commit의 추가 CI 상태는 [PR #8 checks](https://github.com/yejin0414/auto_network/pull/8/checks)에서 별도로 확인하며, 그 실행까지 성공했다고 앞서 주장하지 않는다.

## 남은 위험과 다음 작업

- S-01의 수정/검증은 완료했다. PR #8은 검토용 Draft이며 병합/릴리스/배포는 수행하지 않았다.
- S-02의 수정 및 Windows Actions 검증을 완료했다. 종료에 응답하지 않는 실제 일반 worker/helper는 강제 제거하지 않고 슬롯을 계속 점유한다. 이 경우 후속 미시도 장비는 기존 '확인 불가'로 기록하며, 실행 슬롯이 실제 해제되면 다음 점검에서 복구한다. 기존 클러스터 fallback은 변경하지 않았다.
- S-03의 이력/보고서 읽기 일관성 수정과 Windows Actions 검증을 완료했다. Excel용 단일 회차의 압축 원문은 보고서 처리 동안 메모리에 유지되며, 일반 조회에는 추가하지 않는다. S-05의 진단 수신 한도/자원 정리와 S-06의 UI 응답 경합도 Windows Actions 검증을 완료했다. S-07의 Excel 제목/부제 문자 방어도 Windows Actions 검증을 완료했다. S-08의 보고서 ID/토큰 입력 경계는 수정·검증 중이다.
- S-04는 잘못된 수치를 어떤 상태로 표시할지 별도 승인 전까지 수정하지 않는다.
- 현재 승인 작업은 S-08(가중치 5%, Low), 비정상 보고서 ID/토큰 예외 처리다. 검증 성공 후 S-09로 진행한다. S-04 보류를 유지하며 한 번에 하나씩 진행한다. 각 작업 전 실제 기준과 중복 변경 여부를 확인하고 Commit/PR/검증 근거를 이 문서에 이어 기록한다.

## S-03 실행 기록

- 승인: 검증 성공 후 기존 승인 범위에서 순차 진행하라는 2026-10-22 사용자 지시.
- 작업 기준: S-02 기록 Commit `90c3bed4cef554f410fd891c48ab9628e9017576`, Tree `984886d21305c4602d5103fd484e5b5109c1f7e6`. `main`은 최초 기준과 동일하며 PR #8은 Draft/미병합임을 재확인했다.
- 이전 기록 Commit의 추가 [Actions 39797497734](https://github.com/yejin0414/auto_network/actions/runs/39797497734)도 `head_sha=90c3bed4cef554f410fd891c48ab9628e9017576`, `completed/success`로 확인했다(2026-10-22 14:52:56 UTC 갱신). Job `119888494782`의 모든 단계 성공, `Ran 345 tests in 189.214s`, `OK` 및 대용량 DB/EXE/Windows 검증 성공을 실제 로그에서 확인했다. 이 확인은 S-02 중복 가중치로 계산하지 않는다.
- 수정 전 재현: 합성 임시 SQLite 3.53.1에서 WAL/DELETE × 같은 Store/별도 Store 연결의 네 조합 모두 부모 조회 후 prune을 완료시키면 요약의 장비 수는 남지만 장비 목록이 비었다. 장비 행 조회 후 정리하면 명령 목록이 비었고, 실제 Excel의 첫 원문 조회 후 정리하면 이후 원문 셀이 빈칸으로 성공 저장됐다. Event로 순서를 제어했으며 실제 장비나 운영 DB를 사용하지 않았다.
- 사전 위험 보고: DELETE 모드에서는 짧은 행 캡처 동안 쓰기 commit이 대기할 수 있다. JSON 변환/압축 해제/Excel 직렬화/파일 저장 전 읽기 트랜잭션과 Store 잠금을 해제한다. 원본 BLOB은 Excel용 단일 이력 snapshot에만 확보하며 일반 이력/HTML에는 추가하지 않는다.
- 수정: Store의 기존 연결/잠금과 읽기 savepoint로 부모·장비·명령 행을 한 시점에 확보한다. 기존 get_run/get_raw 반환 형식을 유지하고 Excel용 내부 snapshot callback은 같은 시점의 압축 원문만 지연 해제한다. Excel 저장/열기, 다운로드, 자동 저장의 세 진입점에서 이를 사용한다. HTML/일반 이력에는 metadata만 조회한다.
- 기존 동작 보존: 명령 순서/내용, 판정, DB 스키마·보존 정책, 과거 보고서 context, Excel/HTML 형식과 생성 함수 시그니처를 유지한다. 자동 Excel 오류는 기존 오류 기록 경계 안에서 처리하고 완료 알림은 계속한다. 처음 이력 조회 후 이미 정리된 경우 Excel만 생략한다.
- 코드 Commit: [`b45da0308279266a825e716de49ca5f61348937e`](https://github.com/yejin0414/auto_network/commit/b45da0308279266a825e716de49ca5f61348937e), Tree `9a3fe4234709c5ec28858005fe846d7513f23842`. 기존 Draft PR #8에서 별도 Commit으로 추적한다.
- 진행 상태: 아래 실제 Windows Actions 성공에 따라 S-03을 완료하고 가중치 15%를 반영한다. 누적 50.0%다.

### S-03 로컬 재현 및 검증

- 수정 전 S-02 코드에 새 보고서 테스트 중 3개를 그대로 실행했다. 명시/최신 다운로드, 저장/열기, 자동 저장의 5개 하위 사례가 모두 원본 셀 `None`으로 실패했다. 테스트 준비 오류는 없었으며 실제 workbook을 읽어 누락을 확인했다.
- 수정 후 신규 보고서 경합 테스트 9개 및 기존 저장소 API/수집 회귀를 합한 34개가 PASS(0.380초)다. 같은 command ID를 가진 두 장비의 원문 구분, 당시 임계값·사업장명·판정·시트 보존, 없는 이력 404, 원문 손상/읽기 실패 후 알림 계속, 일반 이력/HTML/알림 전용 경로의 원문 미조회도 확인했다.
- 기존 과거 보고서/DB 확장성/저장 원자성/백업·복원/SQLite 장애 테스트 59개가 PASS(2.253초)다.
- 기존 `tests/db_scale_check.py --runs 100 --devices 20 --raw-bytes 1536`의 축소 합성 검증이 모든 단계 PASS다. 저장·조회·원자 쓰기·온라인 백업·외부 전송·원본 없이 복원·fingerprint·정리 보존을 검증했다. 이 소규모 검증을 1GiB Windows 검증으로 표시하지 않는다.
- 세 제품 변경 파일의 문법 검사와 독립 diff 리뷰에서 차단 결함을 발견하지 못했다. 기존 caller transaction이 있으면 내부 savepoint만 해제하며 그 바깥 transaction은 호출자가 관리한다. SQLite 자체 장애로 이미 취소된 바깥 transaction을 복원한다는 보장은 하지 않는다.
- 신규 Store 회귀 9개도 PASS(0.784초)다. 같은 Store/별도 연결 × WAL/DELETE 경합, 원본의 지연 해제 및 DB 종료 후 lookup, 단일 회차 범위, 일반 조회의 output 컬럼 미접근, SQL/RELEASE 오류 후 재사용과 최초 오류 보존, 외부 transaction의 미커밋 변경 보존, 최신/미존재 계약을 검증했다. 그중 2개를 수정 전 코드에 적용하면 네 모드/연결 하위 사례 모두 부분 이력으로 FAIL했다.
- 최종 변경 코드에서 아래 관련 회귀를 함께 실행해 **133개, 13.642초, OK, 종료 코드 0**을 확인했다. 신규 테스트는 두 파일의 18개이며, 기존 테스트 두 곳에는 새 내부 accessor의 Mock 계약만 각 1줄 추가했다.

```text
python -m unittest tests.test_read_snapshots tests.test_report_read_snapshots tests.test_report_snapshots tests.test_report_capture tests.test_report_window tests.test_optional_reports tests.test_cluster_source_reports tests.test_store_scaling tests.test_store_recovery tests.test_sqlite_faults tests.test_storage_api tests.test_collection_regressions tests.test_engine_timeouts -v
```

- 로컬 Python 3.12.14 / SQLite 3.53.1에서는 WAL/DELETE를 모두 실행했다. 기존 정책상 WAL을 지원하지 않는 SQLite에서는 WAL 하위 사례를 명시적으로 skip하며, 운영 journal 선택을 바꾸거나 미지원 모드를 강제하지 않는다. 해당 환경의 실제 사용 모드인 DELETE 사례는 계속 실행한다.
- 변경 파일: `nc/store.py`, `nc/server.py`, `nc/engine.py`, `tests/test_storage_api.py`, `tests/test_collection_regressions.py`, 신규 `tests/test_read_snapshots.py`, 신규 `tests/test_report_read_snapshots.py`, 이 문서. 제품 3개/기존 테스트 2개/기록 1개 변경, 테스트 2개 추가, 삭제 0개다. 이전 S-01/S-02 수정과 장비 명령·판정·UI·보고서 생성 모듈·스키마·workflow·패키지는 유지한다.

### S-03 GitHub Actions 검증 및 완료 판정

1. [Actions 39801880979](https://github.com/yejin0414/auto_network/actions/runs/39801880979)은 `head_sha=b45da0308279266a825e716de49ca5f61348937e`, 최종 `completed/success`다. 시작 2026-10-22 15:07:47 UTC, 완료 상태 갱신 15:18:47 UTC를 확인했다.
2. [Job 119904501174](https://github.com/yejin0414/auto_network/actions/runs/39801880979/job/119904501174)의 모든 단계가 `completed/success`이고 실제 로그를 읽었다. Windows Python 3.12.10 / SQLite 3.49.1에서 **`Ran 363 tests in 177.744s`, `OK (skipped=4)`**다.
3. skip 4개는 기존 안전 정책상 해당 SQLite에서 사용하지 않는 WAL 경합 하위 사례다. 같은/별도 연결의 이력 조회 및 보고서에 대해 실제 사용 DELETE 사례와 신규 오류 복구/기존 transaction/원문 callback/반환 계약 검증은 성공했다. WAL은 로컬 3.53.1에서 별도로 검증했으며 Windows WAL까지 통과했다고 주장하지 않는다.
4. 신규 보고서 테스트는 다운로드/저장·열기/자동 저장 중 정리 후에도 원문과 저장 당시 context를 유지했다. 정상 시트·셀·판정, 없는 이력 404, 원문 손상·조회 실패 후 알림 처리도 통과했다. 실패를 주입한 테스트의 경고 로그는 기대한 오류 처리이며 테스트 실패가 아니다.
5. 소스 스냅샷/UI 검사, 합성 1GiB DB 검증의 29개 단계(원자 저장·온라인 백업·외부 전송·원본 없는 복원·fingerprint·정리 보존)가 모두 PASS다.
6. EXE 빌드/Demo, 계정 저장·보상 복구·재시작 Mock SSH, 중복 실행/포트 독점, 창 열기·완전 종료·Excel 저장/내려받기, Windows 예약 작업, artifact/검증 로그 보관 단계가 모두 성공했다.
7. 실제 화면의 toast는 로그의 `NOT_RUN` 그대로 미검증이다. 실장비, 장시간 운영/절전 복귀, 모바일 기기 수동 확인도 미실행이다.
8. 원격 GitHub Tree에서 S-02 115개 → S-03 117개 추적 파일, 예정한 8개 경로의 변경/추가 및 삭제 0개를 확인했다. 업로드된 blob SHA가 로컬 검증 코드와 모두 일치한다. 독립 구현/테스트/실제 CI 검토에서 추가 차단 결함을 발견하지 못했다.

**S-03 완료 판정:** 실제 코드 Commit의 전체 Actions 성공을 근거로 15%를 반영했다. 완료 3개(S-01/S-02/S-03), **50.0%**, 이전 대비 **+15.0%p**, 잔여 6개/50%다. S-04는 보류이며 다음 승인 작업은 S-05다. 가중치는 변경하지 않았다.

이 완료 기록의 후속 Commit은 문서만 변경한다. 제품/테스트 7개 blob은 위 검증 코드와 동일하게 유지한다. 문서 갱신으로 자동 실행되는 추가 CI는 별도 상태로 관리하며 아직 성공했다고 주장하지 않는다.

## S-05 실행 기록

- 승인: 검증 성공 후 기존 승인 범위 안에서 순차 진행하라는 사용자 지시에 따라 S-03 완료 후 착수했다. S-04는 계속 보류한다.
- 작업 기준: S-03 완료 기록 `e6a60bce3d2fa9b772c4af77f51a608ce0ede216`, Tree `1a6e7b341504a48a671caa5147ee276f040eb7fd`. GitHub ref와 Tree를 확인했고 제품/테스트는 검증된 S-03 코드와 동일했다. `main`은 최초 기준과 동일하다.
- 수정 전 Mock 재현: 1,024바이트 완결 pre-line 80개 후 정상 KEX를 보내면 81,840문자/80줄을 저장하고 성공했다. timeout 1초에서 0.3초씩 여섯 조각을 보내면 전체 1.8초 후 성공했다. 초기 settimeout 실패에서는 socket close가 0회였다.
- 자원 재현: 두 Transport 생성자/협상, 비밀번호 인증 일반 예외, 채널 생성/PTY/shell/화면 읽기 예외에서 획득한 객체의 명시적 close 누락을 확인했다. recv의 최초 오류와 close 오류를 함께 주입하면 close 오류가 최초 원인을 가렸다. Mock 재현이며 실제 OS 핸들 누수량을 측정했다고 주장하지 않는다.
- 사전 위험 보고: TCP connect와 sendall의 기존 timeout 예산은 유지한다. sendall 성공 뒤 배너·KEX 수신이 하나의 monotonic deadline을 공유하도록 변경한다. 짧은 조각으로 수신 제한을 계속 연장하던 비정상 응답은 종료되며, 정상적으로 느린 TCP 연결이 수신 예산을 소모하도록 바꾸지 않는다.
- 길이 경계: 배너 LF까지의 원시 바이트 누적에 기존 65,536바이트 한도를 적용한다. 배너 뒤 coalesced KEX는 이 누적에서 제외하고 기존 KEX `plen <= 65536` 한도와 구조 검사를 유지한다. 빈 줄/CRLF도 실제 바이트로 계산한다.
- 자원 정리: raw socket, Transport, channel을 획득 직후 각각 독립된 정리 범위로 관리한다. 최초 작업 오류가 있으면 정리 오류로 가리지 않고, 정상 본문의 close 오류는 기존 실패 경로로 전달한다. 인증 거부는 정리 후 기존 로그인 실패 결과로 즉시 반환하고 Netmiko 진단을 새로 시도하지 않는다.
- 기존 동작 보존: 두 SSH 연결의 목적·순서, TCP 10초, 역할별 connect_timeout, auth_password fallback, PTY vt100/200×50, 화면 읽기 6초/빈 화면 CRLF 후 4초, 표시 범위, BB `display version`/MM·WLC `show version` 및 명령 30초를 유지한다. 화면 읽기 경과 시간만 monotonic으로 바꾼다. Netmiko의 기존 finally 정리와 API/UI/보고서 형식은 변경하지 않는다.
- 범위: 제품 `nc/diagnose.py`, 별도 진단 회귀 테스트, 이 문서. 패키지/workflow 변경 없음. 로컬에 netmiko/paramiko가 없어 실제 SDK 통합은 미실행이며, 새 Mock 테스트와 기존 Windows CI의 실제 SDK/가짜 SSH 서버 검증을 구분한다.
- 기존 기록 추가 CI: S-03 완료 기록 Commit의 [Actions 39804115107](https://github.com/yejin0414/auto_network/actions/runs/39804115107)도 `head_sha=e6a60bce3d2fa9b772c4af77f51a608ce0ede216`, `completed/success`를 확인했다. Job `119912618836`의 22개 단계 모두 성공이며 실제 로그는 `Ran 363 tests in 185.051s`, `OK (skipped=4)`다. 대용량 DB 29단계/EXE/Windows 검증도 PASS다. 기존 WAL 하위 사례 4개와 화면 toast 미검증은 그대로이며 가중치를 중복 계산하지 않는다.

### S-05 로컬 재현 및 검증

- 신규 테스트는 `tests/test_diagnose_limits.py` 9개와 `tests/test_diagnose_resources.py` 9개다. Socket/Transport/Channel/Netmiko를 Mock으로 대체하고 가상 시간으로 지연을 제어한다. 가짜 Transport도 정상 close 시 자신이 받은 소켓을 닫으므로 정상 기준 코드를 Mock 결함으로 누수 판정하지 않는다.
- 수신 한도 테스트 중 3개를 수정 전 S-03 코드에 적용해 5개 하위 사례 FAIL, 준비 오류 0개를 확인했다. 완결 일반/빈/UTF-8 줄의 누적 한도, 수신 총 시간, 초기 settimeout 실패 후 정리 누락이 재현됐다.
- 자원 테스트 중 생성자/협상·인증/채널 오류 3개 메서드를 수정 전 코드에 적용해 24개 하위 사례 FAIL, 준비 오류 0개를 확인했다. 같은 테스트 파일의 정상 SSH/Telnet/기존 분기/Netmiko 오류 계약 4개 메서드는 수정 전에도 모두 PASS다.
- 수정 후 다음 명령으로 **32개, 0.624초, OK, 종료 코드 0**을 확인했다. 신규 18개와 기존 수집·판정·명령 정책·SSH EOF/잘린 패킷 테스트 14개를 포함한다.

```text
python -m unittest tests.test_diagnose_limits tests.test_diagnose_resources tests.test_collection_regressions -v
```

- 정확한 배너 65,536/65,537바이트, 원시 UTF-8/CRLF/빈 줄, 1바이트 조각, coalesced 최대 KEX, deadline 이후 최종 recv, connect/send의 별도 예산, wall-clock 변경 시 기존 6초/4초 화면 읽기를 검증했다.
- 자원 테스트 9개 메서드의 48개 하위 조건에서 정상 BB/MM/WLC·Telnet·계정 없음, 각 생성/협상/인증/채널 오류, 인증 거부 조기 반환, 최초 오류 보존, 정상 본문 close 실패 보고, logger 복구와 결과 필드/명령/시간/화면 형식을 확인했다.
- 제품 수정은 `nc/diagnose.py` 하나이며, 새 테스트 2개와 이 기록만 추가 변경한다. 삭제 0개이고 collector/판정/DB/UI/workflow/의존성은 유지한다. 문법과 독립 제품 diff 검토에서 차단 결함은 발견하지 못했다.
- 로컬 SDK 통합은 패키지 부재로 미실행이다. 변경 Commit의 실제 Windows Actions에서 기존 SDK/가짜 SSH 서버 통합 및 전체 EXE 검증을 확인하기 전까지 S-05는 진행 중, 전체 **50.0%**로 유지한다.


### S-05 GitHub Actions 검증 및 완료 판정

1. 코드 Commit [`2027ef60d6e6c4be1f122ada32e8434fc87b2b14`](https://github.com/yejin0414/auto_network/commit/2027ef60d6e6c4be1f122ada32e8434fc87b2b14), Tree `011f3de7c65bdce09a10c69c080b4257e9850344`를 기존 Draft PR #8에 추가했다. 원격 Tree의 119개 추적 파일 중 예정한 제품 1개/새 테스트 2개/진행 기록만 변경됐고 로컬 blob SHA와 모두 일치한다. 삭제는 없다.
2. [Actions 39806415444](https://github.com/yejin0414/auto_network/actions/runs/39806415444)의 head_sha가 위 코드와 일치하며 최종 `completed/success`다. 시작 2026-10-22 15:36:25 UTC, 완료 상태 갱신 15:47:44 UTC다. [Job 119920719443](https://github.com/yejin0414/auto_network/actions/runs/39806415444/job/119920719443)의 22개 단계도 모두 성공이다.
3. 실제 로그는 **`Ran 381 tests in 186.334s`, `OK (skipped=4)`**다. 신규 진단 18개 모두 `ok`이며 기존 실제 SDK/가짜 SSH 서버의 정상 로그인 화면/잘못된 비밀번호 조기 반환과 SSH 종단 테스트도 통과했다. 기존 SQLite 3.49.1 정책의 WAL 하위 사례 4개 skip은 S-03과 같으며 S-05 테스트 skip은 없다.
4. 소스 119개 파일 및 설정 UI, 합성 1GiB DB 검증 29단계, EXE 빌드/Demo/계정 저장·보상 복구·재시작 MockSSH/중복 실행·포트 독점/창·완전 종료·Excel/Windows 예약 작업/검증 로그 및 artifact 보관이 모두 성공했다.
5. 독립 제품 diff 및 테스트 타당성 검토에서 추가 차단 결함을 발견하지 못했다. 정상 SSH/Telnet 결과, 역할별 명령·시간, 보고서/API/UI, 인증 정책은 유지한다. connect/send 이후의 수신만 단일 예산으로 제한하며 전체 함수의 DNS/connect/close까지 한 timeout으로 강제 종료한다고 주장하지 않는다.
6. 실제 toast 육안 표시는 `NOT_RUN`이며 실장비 통신·장시간 운영/절전 복귀·물리 모바일 기기는 계속 미검증이다. Mock close 검증을 실제 OS 핸들 누수량 측정으로 확대 해석하지 않는다.

**S-05 완료 판정:** 실제 변경 Commit의 전체 Windows Actions 성공에 따라 10%를 반영한다. 완료 4개(S-01/S-02/S-03/S-05), **60.0%**, 이전 대비 **+10.0%p**, 잔여 5개/40%다. S-04는 별도 방침 승인 전 보류하고 다음 승인 작업 S-06으로 계속한다. 가중치 변경은 없다.

후속 완료 기록 Commit은 이 문서만 변경한다. 진단 제품 blob `0002240a1b92b58de9537cfb5dab1ead68663e4d`와 신규 테스트 blob `d0598a16ec9f70f96bad97b43ea439001aadf52b`, `3e3e170873e15c32a9ede3ac63664c5983a490e1`은 위 검증 코드와 동일하게 유지한다. 문서 변경의 추가 CI는 별도로 확인하며 완료 전 성공을 주장하지 않는다.


## S-06 실행 기록

- 승인: 검증 성공 후 기존 승인 범위에서 순차 진행하라는 사용자 지시에 따라 S-05 완료 후 착수했다. S-04는 계속 보류한다.
- 작업 기준: S-05 완료 기록 `79d97db0c095a864426a752a59b362629263a8c4`, Tree `1acd86addda291d3dff879b3d4911b38aa6120b3`. 원격 ref/Tree와 제품·테스트 동일성을 확인했다. `main`은 최초 기준과 동일하다.
- 실제 JavaScript 함수와 제어 가능한 Promise로 수정 전 결함을 재현했다. 이력 10→11 선택에 11→10 응답이 오면 화면이 10으로 되돌아갔다. 최신12 조회의 첫 실패 후 같은ID poll은 /api/run을 다시 요청하지 않았다. 상태 응답 역전은 latestId=10/run.id=11 불일치와 알림 2회를 만들었다.
- 같은 S-06의 요청 경합을 추가 확인했다. 사용자 이력4 요청 대기 중 자동 최신10 요청이 나중에 시작돼 선택을 덮었다. 이전 trends/events/vrrp 응답도 새 회차11 자료를10으로 덮고 추가 알림을 발생시켰다. 실제 네트워크 없이 원본 함수를 실행한 재현이며 별도 작업/가중치를 추가하지 않는다.
- 사전 위험 및 정상 계약: S.latestId는 현재 표시한 이력이 아니라 관측한 최신 회차이므로 그 의미를 바꾸지 않는다. 별도 성공 결과/대기 여부로 같은ID 재시도를 판단한다. 과거 이력 선택, 첫 표시 알림 생략, 새 회차 알림1회, 기존 strict 상태 조회 실패 전파와 설정 저장 후 재확인을 보존한다. 정상 화면/버튼/메뉴/HTML/CSS/API는 변경하지 않는다.
- 최소 수정: loadRun의 현재 요청만 결과·선택·원문 캐시·렌더링·pending 상태를 갱신한다. refresh 시작 이후의 사용자 선택과 진행 중 이력 요청을 자동 조회가 덮지 않는다. state는 더 최신 요청의 성공 응답이 이미 적용된 경우만 오래된 응답을 무시해, 새 배경 poll이 대기 중이라는 이유로 strict 성공을 버리지 않는다.
- 보조 자료는 각 loader의 요청 순서로 적용을 보호한다. 새 latest ID를 관측한 갱신의 별도 소유권을 유지해 같은ID 후속 poll 때문에 완료 알림이 누락되지 않으며, 오래된 갱신은 최신 알림을 중복 발행하지 않는다. 숫자 ID의 크기로 비교하지 않아 복원 후 ID 변경을 거부하지 않는다.
- 제품 변경은 web/app.js의 데이터 갱신 경계다. 회귀를 기존 tests/test_settings_ui.cjs 실행 경로에 연결하며 workflow/의존성을 변경하지 않는다. 새 tests/test_history_ui.cjs는 실제 S 초기화와 함수 본문을 사용하고 API만 Mock으로 대체한다.
- 현재 기존 Node 설정 저장 테스트 및 JS 구문은 PASS다. 신규 경합 회귀/독립 리뷰가 진행 중이며 변경 코드 Actions는 미실행이다. 전체 진행률은 **60.0%**로 유지한다.


### S-06 독립 재현·검토

- 실제 S 초기화와 함수 본문을 수정 전/후에 동일하게 적용한 다섯 비교에서, 이력 역전·동일 최신ID 재시도 누락·state 역전·pending 사용자 선택 덮어쓰기·보조 자료 역전이 모두 수정 후 해소됐다. 정상 과거 이력 유지/최신 복귀, 초기 알림0회·새 회차1회, 일반/strict 조회 실패 계약도 동일했다. 이는 로컬 VM 결과이며 Actions 성공을 대체하지 않는다.
- 독립 검토에서 초안의 VRRP 최신 시작 요청만 허용하는 guard가 초기 null 화면의 기존 재조회와 결합해 요청을 반복하는 회귀를 재현했다. VRRP만 마지막 성공적으로 적용한 요청과 비교하도록 좁혀 먼저 완료한 사용 가능한 응답으로 초기 화면을 채우고, 최신 응답 적용 뒤의 이전 값은 거부한다. 수정 후 old-first/new-first 모두 요청 2회에서 증가하지 않고 최종 new 값을 유지했다.
- 같은ID 후속 poll의 결과가 보조 자료보다 먼저 렌더된 경우 보조 자료 완료 후 화면만 과거 값으로 남는 초안 경합도 재현했다. 새 회차 자료의 소유권이 유효하고 최신 보기·요청 대기 없음 조건에서 현재 선택을 바꾸지 않는 renderAll을 적용한다. 과거 이력과 pending 사용자 선택은 그대로 보존한다.
- S-05 완료 기록 Commit의 추가 [Actions 39808354634](https://github.com/yejin0414/auto_network/actions/runs/39808354634)도 head_sha=79d97db0c095a864426a752a59b362629263a8c4, completed/success다. Job119927540055의 모든 단계 및 실제 로그에서 381개 테스트188.029초, OK(skipped=4), 합성DB29단계/EXE/Windows 성공을 확인했다. 완료 상태 갱신은 2026-10-22 16:00:49 UTC다. 기존 WAL/실제toast 미검증은 유지하고 추가 가중치로 계산하지 않는다.


### S-06 최종 로컬 검증

- `node tests/test_settings_ui.cjs`: **신규 이력/응답 경합 15개 PASS 및 기존 설정 저장 검증 PASS**, 종료 코드0. 기존 workflow가 이 명령을 그대로 실행하므로 새로운 테스트는 기존 CI gate에 포함된다. Python 제품/테스트나 workflow 변경은 없다.
- 동일 테스트 중 이력 응답 역전·이전 실패·최신 재시도·pending 선택·state 역전·보조 자료 역전의 6개를 S-05 app.js에 적용해 **6개 모두 assertion FAIL**로 원래 결함을 재현했다. harness 오류/timeout은 없었다. 정상 이력 선택·알림·일반/strict 오류 계약 3개는 기준 코드에서도 PASS다.
- 15개는 실제 S 초기화와 refresh/load/notify, 상태·저장 경고 표시 함수, VRRP 초기 빈 화면 재조회 분기를 사용한다. 요청 응답은 합성 Promise로 제어하고 case별 3초 watchdog으로 미완료 Promise만 남아 Node가 성공 종료하는 것을 방지한다. 정상 테스트에는 실제 sleep/네트워크가 없다.
- 두 초안 회귀(초기 VRRP 반복 요청, 동일ID의 결과가 보조 자료보다 먼저 표시된 후 화면 미갱신)를 보완한 최종 코드에서 해당 회귀도 PASS다. 독립 최종 diff 및 일회성 재현 재검토에서 추가 차단 결함을 발견하지 못했다.
- 변경 경로: `web/app.js`, `tests/test_settings_ui.cjs`, 신규 `tests/test_history_ui.cjs`, 이 문서. 기존 settings fixture에는 실제 제품과 같은 state 요청 카운터 초기값을 넣고 신규 suite 호출1줄을 추가했다. HTML/CSS/버튼/문구/API/명령/판정/DB/보고서/패키지는 유지한다.
- 로컬 검증만으로 완료 처리하지 않는다. 실제 변경 Commit의 Windows Actions 전체 성공을 확인하기 전까지 S-06은 진행 중이며 누적 **60.0%**다.


### S-06 GitHub Actions 검증 및 완료 판정

1. 코드 Commit [`7e981420ede6d0465f0f854d1a2689885f9cea00`](https://github.com/yejin0414/auto_network/commit/7e981420ede6d0465f0f854d1a2689885f9cea00), Tree `7ce3016bb16356dd781f5dca295c1017c6778035`를 기존 Draft PR #8에 추가했다. 원격 Tree 120개 파일에서 예정한 web/app.js, 기존 UI gate, 새 회귀, 진행 기록 네 경로만 변경됐고 로컬 blob SHA와 일치했다. 삭제는 없다.
2. [Actions 39810972763](https://github.com/yejin0414/auto_network/actions/runs/39810972763)의 head_sha가 위 코드와 일치하며 최종 completed/success다. 시작 2026-10-22 16:05:43 UTC, 완료 상태 갱신16:16:42 UTC다. [Job119936790114](https://github.com/yejin0414/auto_network/actions/runs/39810972763/job/119936790114)의22개 단계도 모두 성공이다.
3. 실제 로그에서 **PASS: history UI 15 cases**와 기존 설정 UI PASS를 확인했다. Node 검증은 Python 테스트 수와 별도로 센다. Python은 **Ran 381 tests in 187.368s, OK (skipped=4)**이며 skip은 기존 SQLite3.49.1 정책의 WAL 하위 조건4개다.
4. 소스120개 파일/합성1GiB DB29단계/EXE 빌드·Demo·계정 저장·보상 복구·재시작 MockSSH·중복 실행·포트 독점·창 종료·Excel·Windows 예약 작업·artifact 및 로그 보관이 모두 성공했다. 실제 화면 toast는 NOT_RUN, 실장비·장시간 운영/절전 복귀·물리 모바일 기기는 계속 미검증이다.
5. 로컬 재현/독립 diff 검토와 실제 CI를 합쳐 정상 알림, 이력 선택과 보고서 대상, 최신 복귀, 상태/저장 경고 및 strict 설정 갱신 계약을 보존한 것으로 판단한다. 신규 API/버튼/설정/기능을 추가하지 않았다.

**S-06 완료 판정:** 실제 코드 Commit의 전체 Actions 성공으로10%를 반영한다. 완료5개, **70.0%**, 이전 대비 **+10.0%p**, 잔여4개/30%다. S-04 보류를 유지하며 다음 승인 작업S-07로 계속한다. 가중치 변경은 없다.

완료 기록 후속 Commit은 문서만 변경한다. 제품 및 테스트 blob `328a78388bb346c97d51a4c321872e152d8d38d4`, `80a33908c28bee2a58db9ad87eaed1667de5940b`, `1fb78980b02ce19a6193e8ad9319561a4046eba4`는 검증 코드와 동일하다. 문서 변경으로 자동 실행되는 추가 CI는 별도로 확인한다.


## S-07 실행 기록

- 승인: 실제 S-06 Actions 성공 후 기존 승인 범위 안에서 순차 착수했다. 기준은 완료 기록 Commit `fdb501ac596190d0ea768d0d94efa3b65c99c9d7`, Tree `8ce5d26fed2eb46190eb2e44aa8210002b5c5ff3`이며 `main`은 최초 SHA와 동일하다.
- 수정 전 재현: `validate()`와 `capture_context()`가 그대로 보존한 제어 문자 포함 사업장명이 요약 A1에서 `IllegalCharacterError`를 발생시켰다. 정상 제목과 금지 제어 문자 부제목 조합도 A2에서 같은 예외를 냈다. 합성 설정/메모리 workbook을 사용했다.
- 사전 위험 보고 및 최소화: 기존 `_clean()`은 제어 문자 제거 외에 32,000자 제한을 적용한다. 기존 제목/부제목은 정상 32,767자도 저장·재열기가 가능하므로 이 함수를 그대로 쓰면 이미 가능한 결과가 짧아진다. 이 차이를 실제 확인하고 사용자에게 먼저 보고했다. 승인된 결함 범위 안에서 기존 `ILLEGAL.sub()`만 재사용하는 두 줄로 방법을 좁혔다. 작업/가중치 추가는 없다.
- 제품 변경: `Sheet.__init__()`의 A1/A2 대입에서 금지 ASCII 제어 문자만 제거한다. 기존 `data_type="s"`, 제목/부제목 글꼴과 위치, 본문 정리의 32,000자 제한, 원본 설정/DB, 역사적 보고서 문맥, 시트 구성·파일명·HTML·명령·판정·패키지는 그대로다.
- 테스트 범위: 실제 workbook 저장·재열기로 제목과 부제목을 각각 확인하고 현재/저장 당시 사업장명, 허용 TAB/LF/CR, 수식 모양 문자열의 literal 타입, 정상 긴 제목과 서식 보존을 검증한다. 독립 diff 검토 및 변경 코드 Actions 성공 전까지 완료 가중치는 반영하지 않는다. 현재 **70.0%**다.


### S-07 로컬 검증

- 신규 `tests/test_excel_text_safety.py`: **6개, 0.467초, OK**. 금지 문자 전체의 제목/부제, 현재·역사적 사업장명, 원본 run/설정/임시 SQLite 불변, 허용 문자, 기존 서식/시트, 제어 문자 제거 뒤 수식 모양 문자열의 literal 타입, 32,001·32,767·32,772자 경계를 실제 저장·재열기로 검증했다. 본문 32,000자 정책과 제목/부제 32,767자 처리는 각각 보존한다.
- 동일 새 테스트의 결함 경로3개 메서드를 S-06 기준 제품에 적용해 **4개 `IllegalCharacterError` 사례**를 실제 재현했다(제목/부제 각각, context 없는 이력, 저장 당시 context). 정상 서식 계약1개는 기준 코드에서도 PASS다. 예상된 기준 결함 재현이며 수정 후 실패로 집계하지 않는다.
- 기존 ExcelDataIntegrity, ReportSnapshotExports, ReportSettingsCapture, ExcelReport, ClusterSourceReports: **16개, 10.684초, OK**. 직접 생성·다운로드·저장/열기·자동 저장, 과거 문맥·상태, 점검 중 설정 변경, 클러스터 출처와 기존 Excel/HTML 결과를 검증했다.
- 제품 diff는 `nc/excel.py` 두 줄뿐이다. 신규 테스트와 이 문서를 포함한 세 경로만 Commit에 포함한다. 기존 workflow의 unittest discover가 새 파일을 실행하므로 workflow/패키지는 변경하지 않는다.
- 변경 코드 GitHub Actions는 아직 미실행이다. 로컬 PASS만으로 완료 처리하지 않으며 진행률은 **70.0%**를 유지한다.


### S-07 GitHub Actions 검증 및 완료 판정

1. 코드 Commit [`b114b28d14b3eb343932376c6037ed87eae77990`](https://github.com/yejin0414/auto_network/commit/b114b28d14b3eb343932376c6037ed87eae77990), Tree `8b8725dbaf24bb7fb7cab1eb8ec9658c57d8091c`를 기존 Draft PR #8에 추가했다. 원격 121개 파일 중 예정한 세 경로만 변경됐고 로컬 blob SHA와 일치했다. 삭제는 없다.
2. [Actions 39814068606](https://github.com/yejin0414/auto_network/actions/runs/39814068606)의 head_sha가 위 코드와 일치하며 최종 **completed/success**다. 시작2026-10-22 16:26:19 UTC, 최종 상태 갱신16:44:46 UTC다. [Job119947769225](https://github.com/yejin0414/auto_network/actions/runs/39814068606/job/119947769225)도 completed/success이며22개 단계가 모두 성공이다. 중간 조회에서 일부 단계/상위 상태 반영이 늦었으므로 실제 로그와 최종 Run/Job 상태를 모두 대조한 뒤 완료 처리했다.
3. 실제 로그: **Ran 387 tests in 209.586s, OK (skipped=4)**. 신규 Excel6개 각각 ok, Node history UI15개 및 기존 설정 UI PASS, 소스121개 파일 검증 PASS다. skip4는 기존 Windows SQLite3.49.1 정책의 미지원 WAL 하위 사례이며 실제 DELETE 검증은 통과했다.
4. 합성1GiB DB의29개 단계, EXE 빌드·Demo·계정 저장/보상 복구/MockSSH·재시작·중복 실행/포트 독점·창/종료/Excel 저장과 내려받기·Windows 예약 작업·artifact/로그 보관 모두 성공이다. 실제 화면 toast는 NOT_RUN, 실장비·장시간 운영/절전 복귀·물리 모바일 기기는 미검증이다.
5. 독립 제품/테스트 검토에서도 차단 결함이나 정상 동작 변경을 발견하지 못했다. 정상 허용 문자·장문·literal 타입·시트/서식/판정과 원본 설정/이력/DB 보존을 로컬 및 Windows에서 확인했다.

**S-07 완료 판정:** 실제 변경 Commit의 전체 Actions 성공으로5%를 반영한다. 완료6개, **75.0%**, 이전 대비 **+5.0%p**, 잔여3개/25%다. S-04 보류를 유지하며 다음 승인 작업S-08로 계속한다. 작업/가중치 변경은 없다.

후속 완료 기록 Commit은 이 문서만 변경한다. 제품 blob `7d9e3e648d2c0b3d28e44d979ec2ed36df2970ac`, 신규 회귀 blob `fd8a887b2e089965595ecb9439ce116696c36f7f`는 검증 코드와 동일하게 유지한다. 추가 문서 CI는 별도로 확인하며 미실행/진행 중 상태를 성공으로 간주하지 않는다.


## S-08 실행 기록

- 승인: S-07의 실제 Actions 성공 후 기존 승인 범위에서 순차 착수했다. 기준 완료 기록 Commit `5321ddbe2f9430c5eca8103453f5d3b0f522f4d6`, Tree `211ce8607f92554fcb1c335578e64b9c0343ace6`이며 원격 ref와 server 원본 blob `8eff7afe7663ca8d291a600b26c6e4b238f76a2a`를 대조했다.
- 수정 전 실제 handler Mock 재현: 양쪽 보고서 경로의 비숫자·긴 숫자 ID는 ValueError, 보고서 query/API header/bye의 비 ASCII 토큰은 TypeError로 응답 전에 빠졌다. 이 결과는 요청 처리 예외이며 프로그램 전체 종료로 확대 해석하지 않는다.
- 같은 ID 경계의 추가 재현: 실제 임시 Store에서 `2**63` 및 `-(2**63)-1`은 SQLite bind OverflowError, 범위 안 양 끝은404였다. 사용자에게 근거와 변경 위험을 먼저 보고하고 같은 S-08의 보고서 조회 경계 안에 포함했다. 작업/가중치를 추가하지 않았다.
- 정상 계약 확인: ID의 생략·빈 값·부호·공백·Unicode 십진숫자·underscore는 기존 int 처리를 유지한다. 0은 기존 Store의 최신 회차 선택 의미를 유지한다. 인증 검사가 ID 해석보다 먼저이며, 정상 보고서 MIME/첨부 헤더와403/404/503, 잘못된 bye의204·콜백 없음, 정상 quit의0.3초 Timer와focus/bye 호출 계약을 보존한다.
- 최소 제품 변경: `make_handler()` 내부의 작은 비교 함수가 기존 compare_digest의 TypeError만 불일치로 처리해 세 토큰 경계를 보호한다. 변환·정규화·공백 제거·일반 문자열 비교는 도입하지 않는다. `_token_ok(self)` 호출 계약도 유지한다.
- ID 변환의 KeyError/ValueError는 기존 API와 같은400 형식으로 처리한다. 실제 보고서 조회 호출만 별도 OverflowError→400 경계로 감싸고 기존 외곽 DB/파일 오류503을 유지한다. renderer/workbook 오류나 Store의 다른 ValueError는 새400 범위 밖이다. 일반 API의 숫자 처리 정책·장비 판정·DB 스키마·UI·보고서 형식·패키지/workflow는 변경하지 않는다.
- 독립 제품 diff 검토에서 차단 결함이나 정상 기능 변경을 발견하지 못했다. 기존 HTTP 입력/저장 API/읽기 snapshot/역사적 보고서 회귀 **26개,0.722초,OK**다. 신규 회귀 및 변경 코드 Actions 검증 전이므로 현재 **75.0%**를 유지한다.
- 범위 밖 확인된 잔여 위험: 일반 `/api/run`에 SQLite 정수 범위 밖 ID를 직접 보내는 경우도 OverflowError가 재현된다. 이번 승인 작업은 보고서 ID와 토큰 경계이므로 일반 API 숫자 정책으로 확대하지 않았다. 정상 UI가 DB에서 받은 회차 ID를 사용하는 경로와 구분하며, 별도 후속 범위 결정 대상으로 남긴다. 이 위험은 완료 가중치에 포함하지 않는다.


### S-08 로컬 검증

- 신규 `tests/test_http_input_safety.py`: **11개,0.123초,OK**. 실제 Handler 메서드를 소켓 없이 호출해 비정상 ID/토큰, 정상 int 변환 형태, HTML/XLSX 실제 출력과 MIME/첨부 헤더,403/404/503 구분,bye204·부작용 없음,정상 heartbeat/quit Timer 계약을 확인했다. 임시 실제 SQLite에서64비트 경계·실패 후 트랜잭션 해제·0의 최신 이력 선택·DB 불변도 확인했다.
- 같은 신규 suite 중 결함 경로6개 메서드를 기준 S-07 제품에 적용해 **처리되지 않은 예외32개**를 재현했다(ValueError/TypeError/OverflowError). assertion 실패나 harness 오류가 아니며, 정상 계약5개 메서드는 같은 기준 코드에서도 **0.062초,OK**였다.
- 내부 Store ValueError와 renderer의 ValueError/OverflowError가 새 입력 오류400으로 잘못 바뀌지 않는 검증도 PASS다. 기존 입력 경계를 넓혀 내부 오류를 숨기지 않았다.
- 기존 관련26개 테스트0.722초와 함께 수정 후 총37개 메서드가 로컬 PASS다. 테스트들은 합성 데이터·Mock·폐기 가능한 임시 SQLite만 사용했다. 실제 장비·운영 계정·운영 DB나 종료 callback을 실행하지 않았다.
- Python의 정수 문자열 자릿수 제한이 비활성화된 환경에서만 해당 회귀는 명시적 skip한다. 현재 로컬 Python3.12의 제한4300에서 실제4301자리 입력을 실행해 통과했으며 skip은 없었다. Windows CI의 실제 실행 결과는 별도로 기록한다.
- 제품 변경은 `nc/server.py`의 입력 경계이고 새 회귀1개와 이 진행 기록까지 세 경로를 Commit에 포함한다. 실제 변경 Commit의 Actions 전체 성공 전까지 S-08은 진행 중, 누적 **75.0%**다.
