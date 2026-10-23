# Netcheck Center 안정성 개선 진행 기록

> **현재 상태 — 안정성 작업 10개 검증 완료, 100.0%:** S-10 코드 `0101825b9042ce4751caa0b97118cd5c889c7af3`의 Windows Actions 39873264462 / Job 120152585949가22단계 전체 성공했다. Python425개(기존 WAL 하위4개 skip), HTTP16개, DB29단계, EXE·Windows 결과를 실제 로그로 확인해 S-10의5%를 반영했다. 사용자의 최종 버전 지시에 따라 직전1.5.1의 다음 패치인 **1.5.2 / v1.5.2**를 준비한다. 이 후속 변경은 실행 버전1줄과 완료 기록이며, 새 버전 CI·PR 병합·릴리스 게시 완료를 아직 주장하지 않는다. 100%는 확정된 안정성 작업의 검증 완료이며 전달 단계나 무결함 보증과 구분한다.

## 작업 기준과 승인 범위

- 대상 저장소: `yejin0414/auto_network`만 사용한다.
- 시작 기준 `main` Commit: `bc413434f76068ee443d620a65ba0d622d867cc2`.
- 기준 Tree: `d9ef5138473bbcd09d5e43469e8eeae7b5250f7b`.
- 계획 승인: 2026-10-22 대화에서 사용자 승인. S-01부터 한 번에 한 작업씩 수행한다.
- 작업 브랜치: `stability/s01-credential-startup`. 미병합 변경을 같은 브랜치/PR #8에서 작업별 별도 Commit으로 추적한다.
- 계속 진행 승인: 2026-10-22 사용자의 '검증 성공 시 기존 승인 범위 안에서 다음 단계로 계속 진행' 지시에 따라, 실제 검증 성공 후 승인된 다음 작업을 한 번에 하나씩 수행한다. S-04는 별도 방침 승인을 받은 다음 재개했다.
- S-04 추가 승인: 2026-10-23(한국시간) 사용자가 비정상 수치를 해당 지표의 '확인 불가'로 격리하고 다른 정상 지표·장비 결과의 저장을 유지하는 방침을 승인했다. 이 승인 범위에서 S-04를 재개한다.
- 기존 기능, 장비 명령, 판정 기준, UI/API/보고서 형식, 인증/DB/스케줄 호환성을 보존한다.
- 운영 장비와 실제 운영 계정/DB는 사용하지 않는다. Mock, Fixture, Demo, 폐기 가능한 Windows CI만 사용한다.
- S-10 및 전달 승인: 2026-10-23(한국시간) 사용자가 남은 작업 진행을 승인했다. 앞서 '추가를 해야 될 작업 없으면 ... PR 병합이 릴리즈도 같이 진행해줘'라고 요청한 병합·릴리스는 S-10 검증 후 수행한다. 운영 환경 자동 배포는 승인 범위에 추가하지 않는다.
- 최종 버전 승인: 사용자가 누적 변경에 대한 버전업을 요청한 뒤 '전 버전 확인하고 그 직전 버전 다음 버전 ... 너무 한번에 ... 올리지 말고'라고 구체화했다. 원격 `app.py`의 직전1.5.1을 다시 확인해 **1.5.2**, 릴리스 태그 **v1.5.2**로 확정한다. 앞서 제안한1.6.0은 적용하지 않았다.
- `main` 직접 수정, 원본 저장소 접근/동기화, 운영 장비 접속은 하지 않는다. 승인된 PR 병합은 정확한 검증 head와 실제 GitHub 상태를 확인해 수행한다.

## 진행률 산정

전체 진행률 = 검증까지 완료된 작업 가중치 합계 / 확정된 전체 가중치 합계 × 100.

- 전체 작업: 10개, 가중치 합계: 100%.
- 현재 완료: 10개, 진행 중: 0개, 대기: 0개, 보류: 0개, 실패: 0개. 과거 실패 및 성공 이력은 그대로 보존한다. 버전 변경·병합·릴리스는 별도 전달 단계다.
- 현재 진행률: **100.0%** ((14.25 + 19.00 + 14.25 + 14.25 + 9.50 + 9.50 + 4.75 + 4.75 + 4.75 + 5.00) / 100 × 100). 직전95.0% 대비 **+5.0%p**는 실제 전체 CI를 통과한 S-10의 가중치다. 범위 확장 당시100.0%→95.0% 및 과거9개 계획은 이력으로 보존한다. 완료 작업을 중복 집계하지 않는다.
- 진행률: `[████████████████████] 100.0%` (한 칸 5%p).
- 로컬 재현 및 테스트 통과만으로 완료 처리하지 않는다. 변경 코드에 대한 실제 GitHub Actions 성공 근거가 필요하다.
- 미검증, 진행 중, 보류, 실패 작업은 완료 가중치에 포함하지 않는다.
- 이 기록을 새 세션에서 읽을 때 실제 Commit, PR, Actions 상태를 대조한다. 완료 작업을 중복 계산하거나 진행률을 임의로 초기화하지 않는다.
- 100%는 이 계획의 검증 완료를 뜻하며 결함이 전혀 없음을 보장하지 않는다.

## 전체 작업 현황

| ID | 개선 대상 | 위험 등급 | 가중치 | 상태 | 검증 |
|---|---|---|---:|---|---|
| S-01 | 시작 시 인증 조회 실패 후 기존 계정 덮어쓰기 방지 | High | 14.25% | 완료 | Actions 39786408187 및 39788528305 전체 성공, 330개 테스트 및 EXE 검증 통과 |
| S-02 | 장비 시간 초과 후 대기 작업 정체 및 늦은 진행 상태 갱신 방지 | High | 19.00% | 완료 | Actions 39793991393 전체 성공, 345개 테스트 및 EXE 검증 통과 |
| S-03 | 이력 정리와 조회/보고서 생성 간 일관성 보장 | Medium | 14.25% | 완료 | Actions 39801880979 전체 성공, 363개 테스트 OK(미지원 WAL 하위 사례 4개 skip), EXE 검증 통과 |
| S-04 | 비정상 숫자 파싱 오류 격리 | High | 14.25% | 완료 | Actions 39860763613 전체 성공, 신규 숫자 회귀 22개/Python 420개/EXE 검증 통과 |
| S-05 | SSH 진단 응답 한도와 연결 자원 정리 | Medium | 9.50% | 완료 | Actions 39806415444 전체 성공, 381개 테스트 OK(기존 WAL 하위 사례 4개 skip), EXE 검증 통과 |
| S-06 | UI 이력 응답 역전 및 일시 조회 실패 복구 | Medium | 9.50% | 완료 | Actions 39810972763 전체 성공, Node UI15개/기존 설정/Python381개/EXE 검증 통과 |
| S-07 | Excel 제목/부제의 제어 문자 방어 | Medium | 4.75% | 완료 | Actions 39814068606 전체 성공, 신규 Excel6개/Python387개/EXE 검증 통과 |
| S-08 | 비정상 보고서 ID/토큰 예외 처리 | Low | 4.75% | 완료 | Actions 39818540896 전체 성공, 신규 HTTP11개/Python398개/EXE 검증 통과 |
| S-09 | 최종 기능 보존 및 Windows 실행 검증 | Low | 4.75% | 완료 | Actions 39867775538 및 39869381349 전체 성공; Python 420개/DB29·EXE·Windows 검증 통과 |
| S-10 | 일반 회차 API의 SQLite 범위 밖 ID 예외 처리 | Low | 5.00% | 완료 | Actions 39873264462 전체 성공; Python425개/HTTP16개/DB29·EXE·Windows 검증 통과 |

가중치 변경 내역(2026-10-23 한국시간): 기존 순서별 `[15, 20, 15, 15, 10, 10, 5, 5, 5]`에 0.95를 곱해 `[14.25, 19.00, 14.25, 14.25, 9.50, 9.50, 4.75, 4.75, 4.75]`로 조정하고 승인된 S-10에 5.00%를 배정했다. 이전 계획·실행 기록에 적힌 당시 가중치/진행률은 이력으로 보존하고, 현재 집계에는 이 표를 사용한다. 기존 F01–F34나 완료된 작업의 재검증을 새 작업으로 중복 계산하지 않는다. PR 병합·릴리스는 전달 단계이며 안정성 가중치를 별도 중복 부여하지 않는다.

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

### S-04 — 비정상 숫자 파싱 오류 격리 (2026-10-23 방침 승인 후 재개)

- 근거: 매우 긴 uptime 숫자에서 `int()` 예외가 전파돼 현재 전체 실행 결과가 저장되지 않는 현상을 Demo로 재현했다. 일부 수치의 비정상 범위는 음수/비유한 값도 만들 수 있다.
- 영향 파일: `nc/parsers.py`, 필요한 `nc/evaluate.py`/격리 경계, 관련 Fixture/테스트, 이 진행 기록.
- 변경 전후: 비정상 한 항목이 전체 실행 실패 또는 잘못된 수치를 만듦 → 해당 항목을 격리하고 승인된 비정상 값 처리 결과를 반환한다.
- 방법: 입력/변환을 좁게 방어한다. 예외를 포괄적으로 숨기거나 정상 임계값을 변경하지 않는다.
- 기능 변경 위험: Medium. 현재 uptime의 단순 `None` 반환은 '정상'이 될 수 있어 임의 적용하지 않고 보류했으며, 2026-10-23 사용자가 비정상 수치를 해당 지표의 '확인 불가'로 처리하고 다른 정상 결과를 보존하는 방침을 승인했다. 정상 입력의 판정 기준은 변경하지 않는다.
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
- 완료 조건: 대상 비정상 보고서 ID/토큰 예외가 요청 처리 밖으로 나오지 않고 정상 API 회귀 및 CI가 통과한다.
- 가중치: 5%.

### S-09 — 최종 기능 보존 및 Windows 실행 검증

- 근거: 여러 안정성 변경이 누적된 최종 코드에 대한 검증이 필요하다. 새 기능 작업이 아니다.
- 영향 파일: 필요한 최소 검증 테스트 및 이 진행 기록. 검증 근거 없이 workflow/패키지를 바꾸지 않는다.
- 변경 전후: 개별 작업 검증 → 최종 합계 코드와 시작 기준의 기능 보존 근거를 정리한다.
- 기능 변경 위험: Low. 검증/기록 작업이다.
- 테스트: 아래 기능 보존 표, 전체 Windows Actions, EXE/계정/DB/예약 작업/창 테스트. 실제 장비는 사용하지 않는다.
- 완료 조건: 승인된 선행 변경이 모두 검증되고 최종 CI, PR/Commit, 미검증 범위를 기록한다. S-04가 보류인 동안 전체 완료를 선언하지 않는다.
- 가중치: 5%.

### S-10 — 일반 회차 API의 SQLite 범위 밖 ID 예외 처리

- 근거: 유효한 토큰으로 `/api/run?id=9223372036854775808` 또는 `-9223372036854775809`를 요청하면 `int()` 변환 뒤 SQLite 바인딩에서 `OverflowError`가 발생하고 HTTP 응답이 전송되지 않는다. S-08의 보고서 경계와 다른 일반 API 경로이며 기존 기록의 후속 후보를 이번 승인으로 확정했다.
- 영향 파일: `nc/server.py`, `tests/test_http_input_safety.py`, 이 진행 기록.
- 위험 등급: Low. 인증된 로컬 비정상 요청의 응답 실패이며 재현에서 DB 손상이나 전체 프로세스 종료는 확인되지 않았다.
- 변경 전후: 범위 밖 ID에 응답 없이 예외 발생 → 기존 `요청 값 오류: ...` 형식의 HTTP 400 응답. 정상 조회/인증/존재하지 않는 이력/저장소 장애는 기존 200/403/404/503을 유지한다.
- 방법: `/api/run`의 기존 정수 해석 직후 SQLite signed 64-bit 범위를 확인하고 기존 `ValueError` 응답 경로를 재사용한다. 전체 API에 포괄적 `OverflowError` 처리를 추가하지 않는다.
- 기능 변경 위험: Low. 범위 밖 입력의 실패 응답만 의도적으로 바뀐다. ID 생략/빈 값/0의 최신 조회, 부호·공백·Unicode 숫자 등 기존 `int()` 호환 형식, DB 스키마/내용, 보고서/UI/명령/판정 기준은 보존한다. 수정 전에 이 차이를 사용자에게 보고했다.
- 테스트: 임시 실제 SQLite의 양 경계와 범위 초과값, 오류 뒤 정상 조회/DB 불변/열린 트랜잭션 없음, 인증 선행, 기존 정상 ID 해석/400/404/503, 정상 ID에서 발생한 내부 OverflowError 미은폐, 기존 HTTP·저장소·보고서 회귀 및 전체 Windows CI.
- 완료 조건: 수정 전 결함 재현, 최소 Diff 검토, 정상 기능 회귀 보존, 변경 Commit의 실제 GitHub Actions 전체 성공, Windows EXE/DB/예약 작업 검증 및 Commit/PR 근거 기록.
- 가중치: 5.00%.

## 기능 보존 체크리스트

| 기존 기능 | 누적 확인 방법 | S-04 반영 후 누적 검증 상태 |
|---|---|---|
| BB/MM/WLC 명령과 결과 | 명령/collector 보존, 정상 평가 회귀와 S-04의 승인된 비정상 uptime 격리 | CI Mock/Fixture 및 14대 Demo 저장/복구 통과 |
| CPU/메모리 및 임계값 | 정상 Fixture 반환값·임계값 보존, 비정상 수치 입력 경계와 지표별 격리 | 기존 회귀 및 신규 숫자 22개 CI 통과 |
| VRRP/OSPF/LACP/인터페이스 | 기존 판정/이력 테스트 | CI 통과 |
| WLC 클러스터/Client 분배 | 기존 cluster 회귀 | CI 통과 |
| 정상/주의/장애/확인 불가 표시 | 표시 명칭·상태 우선순위·정상 판정 보존; 해석 실패 uptime만 승인에 따라 확인 불가 | CI 통과, 기존 주의·장애를 unknown으로 낮추지 않음 |
| 이력/기준값/DB 호환성 | 스키마 보존, 이력 조회 snapshot 및 DB/대용량/복원 회귀 | CI 통과, 실제 사용 DELETE 동시 정리 검증 통과 |
| Excel/HTML 보고서 | 정상 생성 결과/형식 보존, 원본 snapshot·과거 context 회귀 | 신규/기존 테스트 및 EXE Excel 저장/내려받기 통과 |
| 자동 점검/Windows 작업 스케줄러 | 기존 Windows 작업 검사 | CI 통과, 장시간 운영/절전 복귀 미검증 |
| 인증 정보/기존 저장 형식 | Mock 조회 오류/정상 이전/저장 보상 복구 | CI 및 EXE 저장/재시작 검증 통과 |
| 웹 UI/좁은 화면 | HTML/CSS 보존, 실제 JS 요청 경합 및 기존 UI/창 검사 | 신규 Node15개/기존 설정/창 CI 통과, 별도 모바일 기기/좁은 화면 수동 검증 미실행 |
| Windows EXE 실행 | 기존 빌드/계정 재시작/중복 실행/창/작업 검사 | CI 통과 |

기준 앱은 loopback에 바인딩된다. 외부 모바일 장비의 네트워크 접속을 새 기능으로 추가하지 않는다. 실장비 통신, 실제 PC의 장시간 예약 실행/절전 복귀, 사용자 화면에서 실제 토스트 알림 확인은 미검증이며 CI의 Mock/폐기 가능한 환경 성공과 구분한다.

S-02의 기능 보존 확인: 정상 직렬 순서/병렬 상한/실제 시작 시점의 제한 시간, MM 명령과 CPU·메모리/정상 판정, 기존 클러스터 fallback, 기준값·이력 원자 저장, 과거 보고서와 VRRP, 스케줄러 반복/폐기 후 재실행 회귀가 로컬 및 Windows Actions에서 통과했다. `commands.py`, `collector.py`, `parsers.py`, `evaluate.py`, Store/DB 스키마, 자격 증명 저장 코드, UI/API/보고서 모듈, workflow/패키지는 S-01 완료 코드에서 바꾸지 않았다. 해당 단계의 검증 근거는 [S-02 코드 Actions 39793991393](https://github.com/yejin0414/auto_network/actions/runs/39793991393)다.

현재 위 표는 [S-04 코드 Actions 39860763613](https://github.com/yejin0414/auto_network/actions/runs/39860763613)의 전체 테스트 및 Windows EXE 누적 검증 결과로 갱신했다. 실제 Python 420개/202.583초/OK(skipped=4), 신규 숫자 회귀 22개, Node UI 15개/설정, 합성 1GiB DB 29단계 및 EXE/Windows 검증을 확인했다. S-04는 정상 수치·임계값·상태 우선순위를 보존하고 승인된 비정상 지표 격리만 적용했다. S-08 신규 HTTP11개는 정상 토큰/ID 해석/보고서 출력/종료 계약과 입력 오류 응답을 검증했다. S-07은 Excel 제목/부제의 금지 문자 제거 두 줄만 보강했고, 기존 길이/서식/수식 문자열/저장 context와 DB 불변을 신규6개에서 검증했다. S-06은 화면 구성/HTML/CSS/API를 유지하면서 JS 응답 적용과 최신 재시도만 보강했고 실제 함수 회귀15개와 기존 설정 검증이 통과했다. S-05의 정상 진단 단계/명령/결과 보존은 신규 Mock 회귀와 실제 SDK/가짜 SSH 서버 통합에서 통과했다. S-03은 Store 읽기와 Excel 호출부만 보강했고, 명령·판정·DB 스키마·UI·보고서 생성 형식·workflow·패키지는 보존했다. 이번 Windows SQLite 3.49.1 로그에서도 기존 WAL 하위 사례 4개 skip을 확인했고 실제 사용 모드 DELETE 검증은 통과했다. 로컬 WAL 검증과 구분한다. 실제 운영 장비·장시간 사용·모바일 기기·토스트 수동 확인은 계속 미검증이다.

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
- S-03의 이력/보고서 읽기 일관성 수정과 Windows Actions 검증을 완료했다. Excel용 단일 회차의 압축 원문은 보고서 처리 동안 메모리에 유지되며, 일반 조회에는 추가하지 않는다. S-05의 진단 수신 한도/자원 정리와 S-06의 UI 응답 경합도 Windows Actions 검증을 완료했다. S-07의 Excel 제목/부제 문자 방어와 S-08의 보고서 ID/토큰 입력 경계도 Windows Actions 검증을 완료했다.
- S-04는 2026-10-23 추가 승인 후 수정과 실제 Actions 39860763613 검증을 완료했다. 비정상 수치만 해당 지표의 확인 불가로 격리하고 정상 지표·다른 장비·기존 저장 경로를 보존한다. 완료 가중치 15%를 반영하여 전체 100.0%다.
- S-09는 앞선 코드의 누적 기능 보존/Windows 검증을 완료한 기록이다. S-04 변경 이후 전체 Windows CI를 다시 확인했으며 S-09의 5%를 중복 가산하지 않았다. 확정 계획 안의 남은 작업은 없다. PR #8은 검토용 Draft이며 병합/릴리스/배포는 별도 승인이 필요한 후속 결정이다.
- 승인 범위 밖 잔여 위험: 일반 `/api/run`에 SQLite 정수 범위 밖 ID를 직접 보내면 OverflowError가 남는다. S-08의 보고서 ID/토큰 경계 밖이므로 별도 후속 범위 결정 대상으로 기록하며 이번9개 작업/100% 가중치에 임의로 추가하지 않는다.

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

### S-08 GitHub Actions 검증 및 완료 판정

1. 코드 Commit [`170f50f54761cfc601641cb04edec283f8bf28d4`](https://github.com/yejin0414/auto_network/commit/170f50f54761cfc601641cb04edec283f8bf28d4), Tree `24cc991fab23dbc448be1802cd6b977b3a80b5f9`의 [Actions 39818540896](https://github.com/yejin0414/auto_network/actions/runs/39818540896)와 [Job 119963319434](https://github.com/yejin0414/auto_network/actions/runs/39818540896/job/119963319434)를 플러그인으로 조회했다. `head_sha` 일치, Run/Job 모두 `completed/success`,22개 단계 전부 성공이며 Run 최종 갱신은2026-10-22 17:09:19 UTC다.
2. 실제 전체 로그: **Python398개,188.864초,OK(skipped=4)**. 신규 `tests/test_http_input_safety.py`의11개 메서드가 모두 개별 `ok`다. 정수 문자열 길이 제한 회귀도 skip 없이 실행됐으며 런타임 활성 한도보다 한 자리 긴 입력을 검증했다. CI 로그에 한도 숫자가 출력되지는 않으므로 로컬4300과 혼동하지 않는다.
3. source122개,Node history UI15개와 기존 settings UI,합성1GiB DB29개 phase,EXE 빌드·Demo·계정 저장/보상 복구/MockSSH·재시작·중복 실행/포트 독점·창/완전 종료/Excel 저장 및 다운로드·Windows 예약 작업·artifact/로그 보관 모두 성공이다. 기존 Windows SQLite3.49.1 정책상 WAL 하위 사례4개만 skip이며 실제 DELETE 모드는 통과했다.
4. 실제 화면 toast 표시는 `NOT_RUN`이다. 운영 장비·장시간 예약/절전 복귀·물리 모바일 기기 검증도 미실행으로 유지한다. 입력 예외 재현을 서버 전체 종료나 실장비 장애로 확대 해석하지 않는다.
5. 제품 diff와 신규11개 회귀의 독립 검토에서 차단 결함이나 정상 기능 변경을 발견하지 못했다. 인증 우선순위,기존403/404/503,bye204,정상 int/ID0,보고서 형식·헤더,내부 오류 구분 및 임시SQLite 트랜잭션 해제를 확인했다.
6. 코드 Commit의 세 경로와 원격 blob을 대조했다. server blob `a8f25cff06f630acd2122ca9c16ca433f6491ee9`,신규 HTTP 회귀 blob `f34a1f554336fda69d6e9ad8d26ef049289e78c0`가 로컬 검토 대상과 일치한다. main은 시작 SHA를 유지하며 PR #8은 Draft/미병합이다.

**S-08 완료 판정:** 실제 변경 Commit의 전체 Windows Actions 성공으로5%를 반영한다. 완료7개, **80.0%**, 이전 대비 **+5.0%p**, 잔여2개/20%다. S-04는 별도 방침 승인 전 보류하며 다음 승인 작업S-09로 계속한다. 작업/가중치 변경은 없다.

후속 완료 기록 Commit은 이 문서만 변경한다. 제품/테스트는 위 코드 Commit의 blob과 동일하게 유지하며 문서 Commit의 추가 CI 성공을 확인 없이 주장하지 않는다. 일반 `/api/run`의 범위 밖 정수 ID 예외는 승인 범위 밖 후속 위험으로 남긴다.

## S-09 실행 기록 — S-04 재개 전의 최종 기능 보존 및 Windows 검증

이 절은 S-04 추가 승인 전의 완료 이력이다. 당시 코드/파일 수/검증 수치/85.0%를 그대로 보존하며 최신 누적 상태는 문서 상단과 이후 S-04 실행 기록을 기준으로 한다.

### 기준, 범위와 코드 동일성

- S-08의 실제 Actions 성공과 완료 기록 이후, 계속 진행 승인 범위에서 한 작업으로 착수했다. 시작 Commit `29c52d79b6429046838791de79baf8a84be995d5`, Tree `37efdc0a3a3ee2d61008cb54a9c4c4b252d75303`다. 원격 PR #8은 `open`, `draft=true`, `merged=false`였으며 base/main은 최초 `bc413434f76068ee443d620a65ba0d622d867cc2`를 유지했다.
- 최종 제품 코드 Commit은 `170f50f54761cfc601641cb04edec283f8bf28d4`, Tree `24cc991fab23dbc448be1802cd6b977b3a80b5f9`다. 이 코드와 S-08 완료 기록의 원격 전체 Tree를 비교해122개 blob 중 진행 문서1개만 변경되고 나머지121개가 동일함을 확인했다. 코드·테스트·Fixture·workflow·의존성 선언은 실제 CI 검증 대상 그대로다.
- 이번 S-09 변경 파일은 `docs/STABILITY_PROGRESS.md` 하나다. 제품 코드나 테스트를 새로 바꾸지 않았으므로 동일 코드의 검증을 반복 실행하지 않았다. 실제 최종 코드 CI의 성공과 전체 blob 동일성을 사용한 검증이며 새 실행을 했다고 주장하지 않는다. 이 절의 문서 Commit은 [PR #8의 Commit 이력](https://github.com/yejin0414/auto_network/pull/8/commits)에서 추적한다.
- 최초 main의 원격113개 파일에서 최종122개 파일로 늘었다. 수정11개(제품7개,기존 테스트4개),추가9개(새 테스트8개,진행 문서1개),삭제0개,기존 파일 mode 변경0개다. 기존102개 blob은 바이트 단위로 동일하다. 로컬 텍스트 사본도 원격 Git blob과 대조했다. 로컬에 내려받지 않은 아이콘2개는 원격 blob 동일성으로 확인했으며 로컬 검증으로 표현하지 않는다.
- 제품 변경7개는 `nc/credentials.py`, `nc/engine.py`, `nc/store.py`, `nc/diagnose.py`, `web/app.js`, `nc/excel.py`, `nc/server.py`다. 모두 앞선 작업의 재현 근거/최소 수정/회귀 검증으로 추적되며 S-09에서 변경 범위를 늘리지 않았다.

### 누적 기능 보존 대조

| 확인 대상 | 시작 기준 대비 보존 근거 | 실제 최종 CI 검증 근거 |
|---|---|---|
| BB/MM/WLC 명령·SSH/Telnet·정상 수집 | `commands.py`, `collector.py` 전체 blob 동일; 정상 수집 명령/호출 유지 | `test_e2e_ssh`, `test_backbone_access`, 정상 순서/명령/결과를 포함한 `test_engine_timeouts` |
| CPU/메모리·VRRP/OSPF/LACP/인터페이스·상태 판정 | `parsers.py`, `evaluate.py`, 설정 파일 및 기존26개 Fixture 동일 | `test_parsers`, `test_optional_command_accuracy`, `test_vrrp_accuracy`, `test_vrrp_stability`, 기존 collection 판정 회귀 |
| WLC 클러스터·Client 분배 | 관련 명령/파서/판정 동일, Engine cluster 함수 AST 동일 | `test_cluster_fallback`, `test_cluster_source_reports` |
| 이력·기준값·기존 DB | Store SCHEMA 문자열1934bytes 동일; 초기화·저장·commit·기준값·VRRP·prune 메서드 AST 동일 | `test_baseline_lifecycle`, `test_sqlite_faults`, `test_read_snapshots`, `test_store_recovery`, 합성1GiB DB·복원29단계 |
| Excel/HTML 및 과거 기준 | HTML/report_context 모듈 동일; Excel 제목/부제 금지 문자 처리 두 줄과 일관된 원문 snapshot만 변경 | `test_report_snapshots`, `test_report_capture`, `test_report_read_snapshots`, `test_excel_text_safety`, 실제 EXE 저장/내려받기 |
| 인증 정보·저장 형식 | 조회 실패 분기 외 기존 shared/legacy 우선순위·형식·apply 보상 복구 유지 | `test_account`, `test_settings_transaction`, Windows 계정 저장/가짜 SSH/재시작 검증 |
| 자동 점검·Windows 예약 작업 | 일정 계산 함수와 `schedule_sync.py`, `wintask.py` 동일 | `test_schedule`, `test_scheduler_refresh`, `test_schedule_sync`, `windows_task_check.py`의 등록/주기 변경/닫힌 창 상태 `schtasks /Run` |
| 정상 API·보고서 다운로드·종료 | 기존 경로 문자열29개 집합 동일; 정상 ID/토큰/헤더와403/404/503/bye204 보존 | 신규 `test_http_input_safety`11개와 기존 API/저장/보고서 회귀 |
| 웹 UI·상태 문구·설정 흐름 | HTML/CSS·렌더 함수·상태 문구·기존 poll 간격 보존; JS 응답 적용 경계만 보강 | Node history UI15개, 기존 settings UI, Windows 창 검사 |
| Windows EXE·빌드·백업/복원 | `app.py`, 창/instance/notify, DB 유지보수/전송/파일 발행, workflow/requirements/tools 동일 | EXE 빌드·Demo·계정/보상 복구·백업/복원·중복 실행/포트 독점·창/종료·Excel·예약 작업 |

Store SCHEMA의 동일 SHA-256은 `3822940824c7d49dba08b02d77a5d50aff92bed3d3c45299586372ccabe00b2a`다. 의존성 선언과 기존 설치 절차를 보존했다는 의미이며, 서로 다른 실행 시점에 설치된 모든 패키지의 실제 버전이 같았다고 확대하지 않는다.

### 실제 CI와 보관 근거

- [최종 코드 Actions 39818540896](https://github.com/yejin0414/auto_network/actions/runs/39818540896), [Job119963319434](https://github.com/yejin0414/auto_network/actions/runs/39818540896/job/119963319434): 정확한 코드 SHA, Run/Job `completed/success`,22개 단계 모두 성공을 다시 확인했다. Python3.12.10/SQLite3.49.1의 **398개,188.864초,OK(skipped=4)**, 신규 HTTP11개 개별ok,Node UI15개/기존 설정 PASS,합성1GiB DB29개 phase PASS다.
- 단계4의 공개 소스122개 검사, 단계6의 실제 Node UI, 단계8의 전체 Python/MockSSH, 단계9의 DB, 단계10–15의 EXE/Windows 실행과 단계16–18의 ZIP 검증/artifact/로그 보관을 확인했다. Mock/Fixture/Demo/폐기 가능한 Windows 환경만 사용했다.
- [Windows-validation-logs](https://github.com/yejin0414/auto_network/actions/runs/39818540896/artifacts/12444580909): artifact ID12444580909,18229bytes. [NetcheckCenter_windows](https://github.com/yejin0414/auto_network/actions/runs/39818540896/artifacts/12443598669): ID12443598669,21616027bytes. 두 artifact의 코드 SHA가 최종 검증 코드와 같고 조회 당시 미만료이며 보존 만료일은2026-11-05다. 핵심 검증 수치·Commit·제한은 만료되는 artifact와 별도로 이 Git 문서에 남긴다.
- S-08 완료 문서 Commit의 별도 [Actions39846598182](https://github.com/yejin0414/auto_network/actions/runs/39846598182)는 기록 시 `in_progress`,conclusion=null이었다. 이 추가 실행이나 이후 S-09 문서 Commit의 CI를 성공으로 계산하지 않았다. 완료 근거는 이미 최종 성공한 제품 코드 CI와 문서 외 모든 blob의 동일성이다.
- 독립 검토는 누적 제품 diff/기능 보존, CI/Windows 근거, 진행률/Commit 기록을 나누어 읽기 전용으로 수행했다. 새 차단 결함이나 승인 범위 밖 정상 기능 변경은 발견하지 못했다. 문서의 Excel 설명을 '정상 생성 결과/형식 보존'으로 명확히 하고 S-08 완료 조건을 대상 ID/토큰 예외로 한정해 내부 오류 은폐로 오해하지 않게 했다.

### 완료 근거 연결

| 작업 | 코드 Commit | 실제 성공한 Actions | 당시 전체 Python 테스트 |
|---|---|---|---:|
| S-01 | `dea5d326cb12e2f8ee008ffdbd1cc63f65ef3133` | [39786408187](https://github.com/yejin0414/auto_network/actions/runs/39786408187) | 330 |
| S-02 | `44a8e91a729c5a3e90d404a95e67aaee5f16818e` | [39793991393](https://github.com/yejin0414/auto_network/actions/runs/39793991393) | 345 |
| S-03 | `b45da0308279266a825e716de49ca5f61348937e` | [39801880979](https://github.com/yejin0414/auto_network/actions/runs/39801880979) | 363 |
| S-05 | `2027ef60d6e6c4be1f122ada32e8434fc87b2b14` | [39806415444](https://github.com/yejin0414/auto_network/actions/runs/39806415444) | 381 |
| S-06 | `7e981420ede6d0465f0f854d1a2689885f9cea00` | [39810972763](https://github.com/yejin0414/auto_network/actions/runs/39810972763) | 381 + 별도 Node15 |
| S-07 | `b114b28d14b3eb343932376c6037ed87eae77990` | [39814068606](https://github.com/yejin0414/auto_network/actions/runs/39814068606) | 387 |
| S-08 / S-09 최종 코드 | `170f50f54761cfc601641cb04edec283f8bf28d4` | [39818540896](https://github.com/yejin0414/auto_network/actions/runs/39818540896) | 398 + 별도 Node15 |

S-09는 위 검증을 새 테스트 실행으로 중복 보고하지 않고 누적 코드/기능 보존·원격 동일성·기록 대조의 승인된5%만 반영한다. 기존 F01–F34,PR #2–#7,후속 문서 Commit의 추가 CI도 완료 가중치에 중복 반영하지 않는다.

### S-09 완료 시점의 남은 위험과 재개 조건

다음은 S-04 추가 승인 전의 이력이다. 현재 상태는 문서 상단과 이후 S-04 실행 기록을 기준으로 한다.

- **S-04 보류/15%:** 매우 긴 uptime 수치 변환 예외가 전체 실행 결과 저장을 막을 수 있다. 해당 지표만 '확인 불가'로 격리하는 방침은 기존 판정 결과에 영향을 줄 수 있어 별도 승인 전 적용하지 않는다. 승인 뒤 정상 Fixture/임계값/다른 지표·장비 결과 보존 및 누적 Windows CI를 검증해야 한다.
- 일반 `/api/run`의 SQLite 정수 범위 밖 직접 ID 요청 예외는 이번 확정 계획 밖 잔여 위험이다. 새 작업과 가중치는 승인 없이 추가하지 않는다.
- 종료되지 않는 일반 worker/helper를 강제 제거하지 않는 제한과 단일 Excel 회차의 압축 원문 메모리 보유는 앞선 작업 기록대로 유지한다. 성공한 Mock 검증을 모든 OS/장비의 자원 회수 보장으로 확대하지 않는다.
- Windows에서 WAL 하위 조건4개는 기존 SQLite 정책상 skip이고 실제 DELETE 검증은 PASS다. 로컬 WAL 성공을 Windows WAL 성공으로 표시하지 않는다. 실제 화면 toast는 NOT_RUN이며 운영 장비·장시간 예약/절전 복귀·물리 모바일 기기/좁은 화면 수동 검증은 미실행이다.
- main 직접 수정,원본 저장소 접근/동기화,운영 장비 접속,PR 병합,릴리스 생성,배포는 수행하지 않았다. PR #8은 검토용 Draft다.

**S-09 완료 판정:** 실제 최종 코드의 전체 Windows Actions 성공, 기능 보존 대조, 제품/테스트 동일성, Commit/PR/미검증 기록 조건을 충족했다. 완료8개·보류1개·진행 중0개·대기0개·실패0개, **85.0%**, 이전 대비 **+5.0%p**다. 잔여1개/15%는S-04이며 작업과 가중치 변경은 없다. 이번 승인 범위에서 추가로 진행 가능한 대기 작업은 없고 전체 계획 완료나 무결함을 선언하지 않는다.

## S-04 실행 기록 — 비정상 수치 격리 승인 후 재개

### 승인과 시작 기준

- 2026-10-23(한국시간) 사용자가 '비정상 수치를 해당 지표의 확인 불가로 격리하고 다른 정상 지표·장비 결과의 저장을 유지'하는 방침을 승인했다. 기존 9개 작업 중 보류한 S-04만 재개하며 가중치 15%, 전체 100%는 변경하지 않는다.
- 시작 Commit `96fe17aa5beaee3394e857aa22742beb44fb7cff`, Tree `6fd87c6e3594b54cf5f68e3f414a51bac42b96de`. 원격 main은 최초 `bc413434f76068ee443d620a65ba0d622d867cc2`, PR #8은 open/Draft/미병합이며 작업 브랜치는 기존 `stability/s01-credential-startup`이다. 원격 Tree와 로컬 텍스트 120개 blob을 대조했고 아이콘 2개는 원격 불변으로 확인했다.
- 직전 완료 문서의 추가 [Actions 39847419474](https://github.com/yejin0414/auto_network/actions/runs/39847419474), Job 120064255974도 정확한 head와 Run/Job `completed/success`, 22단계 전체 성공을 확인했다. 실제 로그는 Python **398개, 199.357초, OK(skipped=4)**, Node UI 15개/기존 설정, 합성 1GiB DB 29단계, EXE/Windows 전체 PASS다. 기존 WAL 하위 사례 4개 skip과 화면 toast NOT_RUN은 유지하며 추가 가중치로 계산하지 않는다.

### 수정 전 실제 재현과 기존 해결 범위

- 실제 Engine·DemoWorld(speed=0)·합성 장비 14대·임시 SQLite에서 정상 1회는 ID 1로 저장됐다. 다음 회차의 bb1 version 응답에서 uptime만 5,000자리로 바꾸면 14대 수집은 모두 완료되지만 `run_blocking()`은 None을 반환했다. ValueError로 새 회차가 저장되지 않아 회차 수/최신 ID가 1로 남았다. 보고서·알림·영구 인증 저장은 비활성화했고 운영 장비는 접속하지 않았다.
- uptime의 음수/소수/지수 토큰에서 뒷부분 숫자만 읽는 오해석도 재현했다. Aruba CPU의 범위 밖 idle 200%는 CPU -100%/정상, 400자리 idle은 -inf%/정상으로 평가됐고 strict JSON 직렬화도 실패했다. Comware CPU의 음수도 양수로 해석됐다.
- Aruba 메모리의 긴 정수는 ValueError 또는 비율 계산의 OverflowError를 냈으며 used/free가 total보다 큰 수치도 정상 비율 계산에 들어갔다. Comware의 Total/Used fallback과 VRRP의 긴 총계/숫자 키도 ValueError를 일으켰다. `to_int()`의 `isdigit()` 검사는 문자 '²'에서 int 변환 예외를 막지 못했다.
- 기존 DB에서 읽은 400자리 uptime과 float 시각은 정상 현재 값의 재부팅 비교에서도 OverflowError를 일으켰다. 과거 샘플과의 비교만 격리하고 현재 수치와 기존 DB 원문을 보존하도록 범위를 좁혔다.
- 이미 해결된 Comware 메모리의 '잘못된 슬롯을 제외하고 정상 슬롯을 유지'하는 계약은 보존한다. LACP/선택 명령 총계/Client 분배의 기존 `to_int()` 방어와 부분 출력 정책도 보존한다. CPU 합계 100%, 메모리 used+free=total 등식이나 VLAN/VRID 운영 범위 제한은 추가하지 않는다.

### 수정 범위와 사전 위험 보고

- 제품 수정은 `nc/parsers.py`와 `nc/evaluate.py`의 공통 uptime 분기로 한정한다. 수치 변환 불가·비유한·퍼센트/메모리 정의역 밖 값을 기존 실패 반환으로 격리하고 정상 형식과 슬롯 선택·fallback을 유지한다. Engine/Store/명령/UI/API/보고서 형식/DB 스키마/패키지/workflow는 변경하지 않는다.
- 기존 uptime None의 '정상/가동 -' 표시는 승인한 방침에 따라 해당 지표의 '확인 불가'로 변경한다. 같은 version 출력의 model/version 정보와 이후 CPU/메모리 평가를 보존한다. 정상 재부팅 감지의 600초 비교, 최근 재부팅 1시간 조건, 상태 우선순위와 issues 계산을 유지한다.
- 과거의 거대/비유한 숫자는 재부팅 비교에서만 제외한다. 정상 현재 uptime을 버리거나 DB를 삭제·변경하지 않는다. 장비 전체나 전체 실행에서 예외를 포괄적으로 숨기지 않고 각 숫자 입력 경계에서 처리한다.
- 신규 회귀는 `tests/test_numeric_safety.py`로 기존 discover에 포함한다. 정상 Fixture 반환값 대조, 지표별 격리·상태 우선순위·원문/기준값 보존·실제 Demo 저장/회복을 검증한다. 변경 코드의 Actions 전체 성공 전까지 S-04는 진행 중이며 누적 85.0%를 유지한다.

### 구현과 정상 동작 보존

- 정수 변환은 기존 18자리 제한이 있는 `to_int()`를 재사용한다. `isdigit()` 대신 `isdecimal()`로 실제 int 변환이 가능한 Unicode 십진숫자만 허용하여 '²' 예외를 막는다.
- uptime은 단위 앞의 전체 숫자 토큰을 검증한다. 음수·소수·지수 표기의 뒷부분만 양수로 읽지 않으며, 기존 정상 단위 조합·공백/쉼표·붙여 쓴 단위·양수 + 부호는 보존한다.
- CPU는 유한한 0–100%만 허용한다. Comware의 표/상세 형식, 다중 슬롯 최대값, 일부 시간 구간만 있는 상세 출력, 쉼표로 연결한 문장과 기존 label/괄호/+ 처리 결과를 유지한다. `1,000%`를 `0%`로 읽던 숫자 내부 쉼표도 방어한다. 원래 +를 해석하지 않던 colon 상세 필드는 예전처럼 건너뛰고 다른 기간 값은 보존한다. Aruba에서 idle 필드 자체가 없을 때의 기존 계산 fallback과 반올림을 유지하고, 명시적으로 잘못된 idle은 해석 실패로 분리한다.
- Aruba 메모리는 정수 변환과 total/used/free 범위를 검증한다. Comware의 Total/Used fallback도 긴 정수와 소수·지수 등의 잘못된 마지막 토큰을 차단한다. 표의 잘못된 명시적 Used/FreeRatio를 계산값으로 대신하지 않으며 다른 정상 슬롯은 유지한다.
- VRRP snapshot의 총계/그룹 숫자와 로그 행의 숫자를 검증한다. 잘못된 로그 행 옆의 정상 로그는 유지한다. 기존 DB 그룹 키는 숫자를 문자별로 정규화해 무제한 크기의 정수 변환 없이 기존 Unicode/leading-zero 문자열 계약을 보존한다.
- 공통 평가기는 잘못된 uptime만 `unknown`으로 기록한다. model/version 및 다른 지표를 보존하고 기존 상태 우선순위(`ok < unknown < warn < crit`)와 정상 임계값/재부팅 조건을 그대로 사용한다. 과거의 비정상 uptime/시각은 해당 비교에서만 제외한다.

### 로컬 재현과 검증

- 신규 테스트의 최종 파일을 S-04 수정 전 코드로 실행했다. 정상 계약 6개 메서드는 모두 PASS, 결함을 검증하는 16개 메서드는 모두 실패를 재현했다(하위 사례의 assertion failure 69개 + 변환/산술 error 32개, skip 0). 이는 수정 전 재현 근거다.
- 신규 `tests.test_numeric_safety` 22개는 정수/uptime/CPU/메모리/VRRP 경계, 정상 계약, 지표별 unknown, 기존 주의·장애의 우선순위, 과거 비정상 샘플, 실제 Demo 저장/복구를 검증한다.
- 최종 파일을 고정한 뒤 신규 22개와 기존 관련 132개를 함께 실행해 **154개, 11.130초, OK**, skip 0을 확인했다. 기존 묶음은 `tests.test_parsers`, `test_collection_regressions`, `test_vrrp_accuracy`, `test_optional_command_accuracy`, `test_optional_reports`, `test_cluster_source_reports`, `test_baseline_lifecycle`, `test_report_snapshots`, `test_vrrp_stability`, `test_cluster_fallback`이다. 출력된 의도적 보고서/DB 실패 로그는 Mock 장애 주입 검증에 해당한다.
- 기존 정상 Fixture 26개의 유효 parser 호출 39개를 수정 전후 비교했고 전체 반환 객체와 strict JSON이 동일했다. 같은 포맷으로 직렬화한 10,565 bytes의 SHA-256은 양쪽 모두 `1d701462114f24acd2fb1f8f933235b68bcb78235a4dd338166eb48921d7e59f`다. 별도의 26 Fixture × 공개 parser 24개 교차 검토에서도 차이가 없었다.
- 실제 14대 Demo 테스트는 정상 control과 bad-uptime 회차의 다른 13대 상태/지표/점검 항목, 문제 장비의 다른 지표, 기준값, 수집 원문, strict JSON을 대조한다. 오류 회차의 정상 저장, 이후 정상 회차 저장, 이전 이력 불변까지 확인하며 socket 연결을 금지하는 Mock을 사용한다.
- 독립 평가기 검토에서 정상 72조합의 전체 metrics/checks가 기준과 동일하고 비정상 과거 샘플 14조합이 현재 정상 지표를 보존했다. 초기 테스트의 잘못된 전체 상태 참조는 실제 반환 구조인 `summary.overall`로 바로잡았으며 제품 API를 변경하지 않았다. 초안 검토에서 발견한 정상 CPU 쉼표/label 형식 회귀도 원격 게시 전에 보완했다.
- 최종 독립 검토에서 정상/기존 부분 CPU 반환 12개가 기준과 동일했다. 숫자 내부 쉼표의 17개 비정상 변형은 None으로 격리했으며, 원래 +를 해석하지 않는 colon 형식의 부분 결과는 유지했다. 제품/신규 테스트 blob은 각각 parser `d538d0434ffe8f6baacba6618473e155031e1a68`, evaluate `4196129f6d263608b9d20096728f304308556f00`, test `823590b8b43a74cdba94294b3dc795927d68ea08`로 고정했다.
- 로컬 환경은 Python 3.12.14/SQLite 3.53.1이다. 이 로컬 검증 단계에서는 Windows/실제 SDK/EXE 성공을 주장하지 않았고 완료 가중치 **0%p**, 누적 **85.0%**를 유지했다. 이후 실제 Windows Actions 검증 결과는 다음에 기록한다.

### S-04 GitHub Actions 검증 및 완료 판정

1. 코드 Commit [d854dae82e3e7cfb0a9e3e6075920afe847d1ff1](https://github.com/yejin0414/auto_network/commit/d854dae82e3e7cfb0a9e3e6075920afe847d1ff1), Tree `a35e271e4ccdcd0cf6d9d7c3446cdb90b8ac5217`, 기존 [Draft PR #8](https://github.com/yejin0414/auto_network/pull/8)로 추적한다. 게시 직전 main과 브랜치 기준을 확인하고 expected SHA를 사용해 작업 브랜치만 갱신했다.
2. [Actions 39860763613](https://github.com/yejin0414/auto_network/actions/runs/39860763613), [Job 120110557794](https://github.com/yejin0414/auto_network/actions/runs/39860763613/job/120110557794)의 head SHA가 위 코드와 일치하며 Run/Job 모두 `completed/success`, **22개 단계 모두 success**임을 확인했다. 최종 Run 갱신 시각은 `2026-10-22T22:03:40Z`다.
3. 실제 전체 로그 164,617자에서 Windows Python **3.12.10**, SQLite **3.49.1**, **`Ran 420 tests in 202.583s`, `OK (skipped=4)`**를 확인했다. 신규 `test_numeric_safety` 22개도 각각 `ok`이며 14대 Demo 저장/복구 테스트가 포함된다. 기존 테스트 수에 산술적으로 더한 추정치로 성공을 대신하지 않았다.
4. skip 4개는 기존 SQLite 3.49.1 정책이 DELETE를 사용하는 환경에서 지원하지 않는 WAL 하위 사례다. 같은 Store/별도 연결의 읽기 일관성과 보고서 snapshot 테스트에 표시된 정확한 skip 사유를 확인했다. 실제 DELETE 모드 및 Windows EXE 복원 DB 검증은 통과했다.
5. 공개 소스 **123개 파일** 검사, Node history UI **15개**와 기존 설정 저장/복구 검증이 PASS다. 합성 **1GiB DB 29개 phase**의 PASS 로그를 확인했다. 원자 저장, 온라인 백업, 외부 전송·패키지 검증, 원본 없이 복원, SHA-256/논리 fingerprint, 복원 후 조회·보존 정리까지 포함한다.
6. EXE 빌드와 Demo 1회 저장, 계정 저장·설정 실패 보상 복구·가짜 SSH·재시작 계정 유지, 중복 실행/버전 교체/포트 독점, Edge 앱 창·완전 종료·Excel 자동 저장/내려받기, Windows 예약 작업 등록/주기 변경/창이 닫힌 상태의 점검/작업 삭제가 모두 통과했다. 로그의 `NOT_RUN: 사용자 화면에 토스트가 실제 표시되었는지 수동 확인`은 그대로 미검증으로 남긴다.
7. 기존 workflow의 ZIP 내용 검사와 artifact/로그 보관도 성공했다. [Windows-validation-logs](https://github.com/yejin0414/auto_network/actions/runs/39860763613/artifacts/12461589560)는 ID 12461589560, 18,754 bytes이며 [NetcheckCenter_windows](https://github.com/yejin0414/auto_network/actions/runs/39860763613/artifacts/12461478499)는 ID 12461478499, 21,617,255 bytes다. 두 artifact의 head SHA가 검증 코드와 같고 조회 당시 미만료, 만료일은 2026-11-05다. 핵심 결과와 제한은 만료되는 artifact와 별도로 이 Git 문서에 영구 기록한다.
8. S-04 게시 Tree는 직전 Commit 대비 제품 2개/문서 수정과 테스트 1개 추가만 있다. 나머지 **119개 blob**은 동일하다. 최초 main과 누적 비교하면 **113 → 123개 파일**, 변경 경로 **23개(제품 9 + 기존 테스트 4 + 신규 테스트 9 + 문서 1)**, 기존 blob **100개 동일**, 삭제와 파일 mode 변경은 0개다. 장비 명령/collector, 설정 형식, DB 스키마, HTML/CSS, schedule_sync/wintask, 앱/창/instance/notify, DB 유지보수, requirements/workflow/tools를 보존했다.

### 최종 상태와 검증 한계

- **기능 변경 판단:** 정상 입력의 기능·임계값·판정·출력 형식을 보존했다. 사용자가 별도 승인한 예외 처리에 따라, 해석 실패 uptime의 기존 '정상/가동 -'가 해당 지표의 '확인 불가'로 바뀐다. 다른 지표·장비와 이미 확인된 주의/장애는 유지한다. 신규 기능이나 UI/API/보고서 형식 변경은 없다.
- 기존 DB를 수정하거나 과거 손상 데이터를 일괄 복구한 작업은 아니다. 사용할 수 없는 과거 uptime/시각을 현재 재부팅 비교에서만 제외한다. 이미 저장된 임의의 손상 보고서 전체를 복구했다고 주장하지 않는다.
- 일반 `/api/run`의 SQLite 정수 범위 밖 ID 예외는 이번 확정 계획 밖 잔여 위험이다. 별도 범위 결정 전 새 작업/가중치로 추가하지 않는다. 종료되지 않는 worker/helper의 강제 제거 제한과 단일 Excel 회차의 압축 원문 메모리 보유도 앞선 기록대로 유지한다.
- 운영 장비 통신, 실제 PC의 장시간 예약/절전 복귀, 물리 모바일 기기/좁은 화면, 실제 화면 toast는 미검증 또는 미실행이다. Mock/Fixture/Demo/폐기 가능한 Windows CI 성공을 실운영 전반의 보장으로 확대하지 않는다.
- 최종 검증 결과를 기록하는 후속 Commit은 이 문서만 바꾼다. 제품/테스트를 포함한 나머지 **122개 blob**을 성공한 코드 Commit과 동일하게 유지한다. 후속 문서 Commit의 추가 CI 상태는 [PR #8 checks](https://github.com/yejin0414/auto_network/pull/8/checks)에서 별도로 확인하며, 확인 없이 그 추가 실행까지 성공했다고 주장하지 않는다.

**S-04 완료 당시 판정(추가 Actions 종료 전 이력):** 사용자 처리 방침 승인, 최소 범위 수정, 정상 결과 보존 및 비정상 지표 격리, 실제 전체 Windows Actions 성공, Commit/PR/검증 근거 기록 조건을 충족했다. 완료 **9개**, 진행 중·대기·보류·실패 **0개**, 전체 **100.0%**, 이전 대비 **+15.0%p**다. 작업 목록과 가중치 변경은 없으며 기존 S-09의 5%도 중복 계산하지 않았다.

**S-04 완료 당시 다음 작업 안내(과거 이력):** 당시 확정된 9개 계획 안에는 남은 작업이 없다고 판단했다. PR #8은 검토용 Draft로 유지한다. main 직접 수정, 원본 저장소 접근/동기화, 운영 장비 접속, PR 병합, 릴리스 생성, 배포는 수행하지 않았다. **100.0%는 승인된 계획의 검증 완료이며 무결함, 실운영 검증 또는 병합/배포 완료를 의미하지 않는다.**

## S-09 재검증 기록 — 완료 문서의 추가 CI 실패 확인

### 확인 시점과 실제 원격 상태

- 2026-10-22 22:12:50 UTC(한국시간 2026-10-23 07:12:50)에 [Actions 39862467484](https://github.com/yejin0414/auto_network/actions/runs/39862467484)가 `completed/failure`로 종료됐다. 사용자의 후속 질문에 따라 최신 상태를 다시 조회하고 [Job 120116326446](https://github.com/yejin0414/auto_network/actions/runs/39862467484/job/120116326446)의 전체 실제 로그 123,634자를 확인했다.
- 실패한 정확한 head는 완료 기록 Commit `af9a643ccde9935b9ad3acc8ef94a0d619fb44c9`이다. 직전 [성공한 제품 코드 Actions 39860763613](https://github.com/yejin0414/auto_network/actions/runs/39860763613)의 head `d854dae82e3e7cfb0a9e3e6075920afe847d1ff1`와 비교해 진행 문서만 달라졌으며 제품/테스트를 포함한 나머지 122개 blob은 동일하다.
- `main`은 최초 `bc413434f76068ee443d620a65ba0d622d867cc2` 그대로이며 PR #8은 open/Draft/미병합이다. 기존 성공 결과를 취소하거나 삭제하지 않고 최신 실패를 추가 근거로 기록한다.

### 실패 결과와 아직 확정되지 않은 원인

실제 결과는 다음과 같다.

```text
FAIL: test_runs_repeatedly (tests.test_schedule.Scheduler.test_runs_repeatedly)
File "tests/test_schedule.py", line 50
self.assertGreaterEqual(len(runs), 3)
AssertionError: 2 not greater than or equal to 3
Ran 420 tests in 286.067s
FAILED (failures=1, skipped=4)
```

- 소스 검사와 Node UI 검증은 success다. 신규 S-04 숫자 회귀 22개도 각각 ok였다. Python 테스트 단계의 실패로 이후 대용량 DB, EXE 빌드/실행, Windows 계정/창/예약 작업 검증 및 패키징은 이번 실행에서 skipped다. 이 단계들을 이번 실행의 PASS로 표시하지 않는다.
- 테스트는 `next_slot`을 최초 +1초/이후 +2초로 바꾼 뒤 실제 Demo Engine에 `sleep(8)`, `stop()`, 저장 회차 수 >=3을 요구한다(`tests/test_schedule.py:41–50`). 실제 Engine은 기존 점검이 진행 중이면 다음 예정 점검을 건너뛰고, stop은 취소 Event를 설정하며 저장 직전 취소된 회차는 저장하지 않는다.
- 따라서 고정 8초 내 완료 처리량 가정이나 종료 시점 경합으로 실패할 가능성이 있다. 그러나 이번 실행에서 회차 시작/저장/종료 시각과 종료 직전 상태를 기록하지 않았으므로 **일시적인 테스트 실패, 호스트 부하, 제품 결함 중 어느 하나로 원인을 확정하지 않는다**.
- 직전 성공 202.583초와 이번 286.067초의 전체 테스트 시간 차이는 확인된 사실이지만 그 차이만으로 원인을 증명하지 않는다. 코드 동일성도 실행 환경이나 스케줄링 시점 동일성을 보장하지 않는다.
- 이번 확인에서는 제품 코드, 테스트, workflow, 패키지를 수정하지 않았고 재실행을 요청하지 않았다. 해당 스케줄러 실패의 로컬 재현이나 수정 성공을 주장하지 않는다.

### 남아 있는 별도 결함과 미검증 범위

- 기존에 기록한 일반 `/api/run` 범위 밖 ID 예외를 현재 코드의 실제 Handler와 임시 SQLite로 다시 재현했다. `2**63`과 `-(2**63)-1`에 `OverflowError: Python int too large to convert to SQLite INTEGER`가 전파되고 응답 전송 호출은 0회였다. signed 64-bit 양 끝의 범위 내 ID는 기존 404였고 보고서 두 경로의 범위 밖 ID는 기존 400이었다.
- 해당 재현 뒤 DB 내용/회차 수/total_changes와 후속 정상 조회가 유지됐으며 열린 읽기 트랜잭션도 없었다. 영향은 해당 요청의 오류 응답 누락으로 확인됐고 전체 프로세스 종료나 DB 손상으로 확대 해석하지 않는다.
- 후속 후보 S-10은 아직 확정 계획에 추가하지 않는다. 일반 회차 조회의 입력 경계만 기존 400 형식으로 방어하는 최소 수정과 정상 200/403/404/503 및 ID 해석 계약 보존을 계획 후보로 제시한다. 새 작업/가중치는 별도 범위 승인 전 부여하지 않는다.
- 실제 화면 toast, 장시간 예약/절전 복귀, 물리 모바일 기기/좁은 화면 수동 검증은 계속 미검증이다. 운영 장비는 접속하지 않는다.

### 현재 진행률과 다음 작업

- **S-09 상태:** 실패 — 최신 누적 검증 재확인 필요. 가중치 5%는 재검증 완료 전 완료 합계에서 제외한다.
- **현재 진행률:** 완료 8개/95%, 실패 1개/5%, 전체 **95.0%**, 직전 대비 **-5.0%p**. 작업 9개와 합계 100%는 그대로이며 새 작업 추가, 완료 이력 삭제, 임의 초기화는 없다.
- **다음 작업:** 기존 S-09 범위에서 성공/실패 로그와 환경을 비교하고 반복 스케줄 테스트의 예정/시작/저장/종료 시점 및 stop 직전 상태를 제한적으로 관찰해 원인을 구분한다. 시간 가정이 원인으로 확인되면 제품의 스케줄/중복 방지 정책을 유지하는 검증 보강을 검토한다. 반복 재실행 중 한 번의 성공만으로 원인 해결을 선언하지 않는다.
- **재완료 조건:** 실패 원인과 대응 근거, 기존 자동 점검 기능 보존, 실제 최종 코드의 전체 Windows Actions 성공 및 Commit/PR/미검증 기록을 확인한다. 제품 동작 변경이 필요하면 변경 전 위험과 승인 범위를 다시 확인한다.
- 이 정정 Commit은 진행 문서만 변경한다. PR #8 설명도 현재 95.0%/재검증 필요 상태로 맞춘다. 이 문서 Commit이 촉발하는 별도 CI는 상태를 확인하기 전 PASS로 주장하지 않으며 단순 재실행 통과가 위 원인 확인을 대신하지 않는다.

## S-09 재검증 실행 — 반복 점검 완료 조건과 테스트 자원 정리

### 승인·기준 및 변경 범위

- 사용자가 '검증 성공 시 기존 승인 범위 안에서 다음 단계로 계속 진행'을 재확인하여 S-09 재검증을 이어간다. 작업 수 9개, S-09 가중치 5%, 전체 가중치 100%는 변경하지 않는다. 일반 `/api/run` S-10 후보는 이번 수정에 포함하지 않는다.
- 시작 head는 `4d79335df8e43a85b2a8ecc7f9a05cd25227e059`, Tree `3b86ed6447cacce828da1080795fc00651056352`이다. PR #8 open/Draft/미병합과 main `bc413434f76068ee443d620a65ba0d622d867cc2`를 재확인했다.
- 원격 123개 중 로컬 텍스트 121개의 Git blob을 모두 대조했다. 아이콘 2개는 원격에서 보존한다. 작업용 snapshot의 제품/테스트는 시작 head와 동일하며 별도 작업 경로에서 수정한다.
- 이번 수정 파일은 `tests/test_schedule.py`와 이 진행 기록뿐이다. **제품 코드, 장비 명령, 스케줄/중복 방지 정책, 판정, UI/API/보고서, DB 스키마, 패키지 및 workflow는 변경하지 않는다.**

### 실제 로그 비교와 재현된 메커니즘

- 성공 Run 39860763613과 실패 Run 39862467484의 차이는 진행 문서 한 파일이다. 실패 로그는 반복 스케줄의 회차 수 assertion 1건뿐이며 신규 숫자 회귀 22개는 양쪽 모두 ok였다. 인접 테스트의 중단/SSH 배너/worker 시작 실패 로그는 성공 실행에도 있는 의도된 장애 주입이다.
- Python 3.12.10, SQLite 3.49.1과 설치된 Python 패키지 29개의 버전은 같았다. Runner 이미지 버전은 성공 20261021.278.1 / 실패 20261018.275.1, Node는 v22.23.4 / v22.23.3으로 달랐다. 전체 suite 시간이 202.583초에서 286.067초로 늘었으나 이것만으로 호스트 부하를 원인으로 확정하지 않는다.
- Linux/Python 3.12.14에서 실제 원래 테스트와 임시 Demo Engine을 사용하고 소켓 연결을 금지한 3개 제어 실험을 수행했다.
  1. 원래 테스트는 1.063/3.055/5.051/7.050초에 저장하고 8.009초 stop, 총 4회로 PASS였다.
  2. 세 번째 Demo 회차만 Event로 보류하자 5.020초에 실행 중이 됐다. 7.019초 예약 시도는 기존 중복 방지 계약에 따라 건너뛰었고, 원래 테스트의 8.011초 stop이 진행 중 회차를 취소했다. 저장 2회와 정확히 `2 not greater than or equal to 3` assertion을 재현했다.
  3. 같은 보류를 stop 없이 8.001초에 해제하면 8.040초에 세 번째 회차가 정상 저장됐다.
- 세 실험의 제품 ERROR 로그와 last_error는 없었으며 취소 실험에서만 기존 _Abandoned 경고가 있었다. **제품 오류 없이 고정 8초 종료가 동일 실패를 만들 수 있는 메커니즘을 입증했다. 실제 Windows 실패 당시의 구체적인 지연 지점/원인까지 확정한 것은 아니다.**
- 제품/테스트가 같은 상태 정정 head의 후속 Run 39864325921도 전체 success로 종료됐다. 재실행 1회 통과만으로 S-09를 복구하지 않고 아래 검증 보강과 해당 Commit의 전체 CI를 별도로 요구한다.

### 최소 보강과 기능 보존

- 실제 `start_scheduler()`, Demo 수집, 평가, SQLite 저장과 최초 1초/이후 2초의 테스트용 예약은 그대로 실행한다. 실행/저장을 가짜 성공값으로 대체하지 않는다.
- 고정 `sleep(8)` 뒤 중단하는 대신, **최대 30초의 monotonic deadline 안에서 실제 DB에 3개 이상 저장되고 현재 점검이 끝났는지** 확인한다. 조건이 충족되면 즉시 종료하고 실제 오류가 있으면 빨리 실패한다. assertion을 2개로 낮추거나 점검을 테스트에서 직접 3회 호출하지 않는다.
- 서로 다른 회차 ID 3개 이상, 모든 trigger가 auto, 각 회차의 전체 활성 장비 ID 보존, last_error 없음과 실행 종료를 검증한다.
- 실제 Thread 생성자를 그대로 호출하면서 생성된 스레드 참조만 기록한다. 성공/실패 모두 finally에서 stop하고 공통 10초 종료 기한으로 join한다. 스레드가 남으면 명시 assertion으로 실패하며 모든 작업 종료 뒤 DB 연결을 닫는다.
- Windows에서 정리 실패가 원래 진단을 덮지 않도록 기존 `TemporaryDirectory(ignore_cleanup_errors=True)`는 유지한다. 작업 생존 여부 검증과 정상 경로의 명시 DB close를 별도로 수행한다.
- 실패 시 중단 전 경과 시간, running/last_error/progress, 마지막 예약 시도/다음 예정 시각, 저장 회차와 종료 후 생존 스레드를 남긴다. 따라서 단순 회차 수 부족보다 실패 원인을 구분할 근거가 늘어난다.
- 변경은 테스트 및 기록뿐이므로 제품 기능 변경 위험은 없다. 30초는 점검 주기나 제품 타임아웃 변경이 아니라 테스트의 완료 대기 상한이다.

### 로컬 검증과 독립 검토

- 관련 `test_schedule.Scheduler`, `TaskXml`, `test_scheduler_refresh`, `test_schedule_sync`, `test_engine_timeouts` **45개 / 30.325초 / OK**를 확인했다.
- 일회성 양성 검증: 보강한 테스트에서 세 번째 회차를 8초 이후까지 보류했다. 8.050초 해제 시 stop=false였고 8.096초에 세 번째 저장 후 완료 확인, 8.147초에 stop하여 PASS였다.
- 일회성 음성 검증: 세 번째 commit_run에 sqlite3.OperationalError를 주입하자 저장 2회와 last_error를 보존하고 기대대로 assertion FAIL(1 failure, 0 errors)이 발생했다. 실제 저장 오류를 성공으로 숨기지 않았다. 두 실험 모두 DB 닫힘, 임시 디렉터리 삭제, 관찰한 스케줄러/실행 스레드 종료를 확인했다.
- 독립 검토의 Windows cleanup 진단 보완을 반영했다. 최종 테스트 blob은 `a525031a501a05e3349e3e27fb55c1e940ca8700`이다. 마지막 보완 후 해당 실제 반복 테스트를 다시 실행해 **1개 / 6.017초 / OK**를 확인했고 최종 독립 review도 PASS였다.
- 위 45개·양성/음성 관찰은 cleanup 옵션 보완 전 테스트 blob `8107c4581ed58ed9e50dab30a5feceea626df95a`에서 수행했다. 마지막 차이는 실패 경로의 임시 경로 정리 예외 보존 옵션 한 줄이며 최종 blob의 단일 테스트 및 전체 Windows CI와 구분한다.
- 로컬 검증만으로 완료 처리하지 않는다. **현재 S-09 진행 중, 완료 8개, 전체 95.0%, 증가 +0.0%p**다. 실제 변경 Commit의 전체 GitHub Actions가 성공한 뒤 완료 조건과 기능 보존을 대조한다.


## S-09 재검증 실행 — 보고서 Demo fixture의 실행 시각 의존성

### 실제 추가 CI와 실패 범위

- 반복 스케줄 테스트 보강 Commit [4ad89eddef849e4054a4ef980f99a166c8551a53](https://github.com/yejin0414/auto_network/commit/4ad89eddef849e4054a4ef980f99a166c8551a53), Tree `0a8fd7f42858b3c6e4bed4322ab9a19204086563`의 [Actions 39866316716](https://github.com/yejin0414/auto_network/actions/runs/39866316716) / [Job 120129280641](https://github.com/yejin0414/auto_network/actions/runs/39866316716/job/120129280641)은 `completed/failure`다. 실제 전체 로그 123,677자와 정확한 head를 확인했다.
- 결과는 **420개 / 184.397초 / FAILED(failures=1, skipped=4)**다. 유일한 실패는 `tests.test_report_window.ExcelReport.test_two_clusters_separate`의 기존 OUT Client warn 부재 assertion이며 `AssertionError: True is not false`가 발생했다.
- 보강한 `test_runs_repeatedly`는 개별 **ok**였고 숫자 회귀 22개/HTTP 입력 11개도 모두 개별 ok였다. 공개 소스 123개, Node history 15개/기존 settings는 PASS다. 선행 Python 실패로 DB 규모/EXE/Windows 단계는 미실행이며 전체 성공으로 집계하지 않는다.
- Windows Python 3.12.10/SQLite 3.49.1, Node v22.23.3, runner 이미지 20261007.264.1이다. 29개 Python 패키지 버전은 앞선 성공과 같다. 실패 로그에는 당시 OUT의 실제 Active 값이 없으므로 실행 환경 차이나 난수만으로 해당 원인을 단정하지 않는다.
- [Windows-validation-logs](https://github.com/yejin0414/auto_network/actions/runs/39866316716/artifacts/12464381789)만 생성됐으며 배포 ZIP은 생성되지 않았다. PR #8은 open/Draft/미병합, main은 최초 기준 그대로임을 다시 확인했다.

### 재현 근거와 최소 수정

- 기존 fixture는 실제 시각의 Demo로 27회 점검한 뒤 OUT에서 Client warn이 전혀 없기를 요구했다. Demo의 야간 factor는 0.12이므로 OUT Active는 `int(160 * 0.12 + randint(-15, 15))`, 즉 4~34명이다. 기존 기준은 클러스터 총 50명 이상일 때 같은 클러스터 다른 장비 중앙값의 25% 미만을 warn으로 표시한다.
- 임시 SQLite와 실제 Demo/Engine/평가를 사용하고 소켓 연결을 금지한 두 조건, 총 54회 저장 실험을 수행했다. 야간 조건에서 제품이 허용하는 난수 결과를 제어해 OUT **[4, 34, 34, 34]**를 생성했다. 합계 106명, 다른 OUT 중앙값 34명의 25%인 8.5명보다 4명이 작아 기존 판정대로 warn이 발생했고 **동일한 기존 OUT assertion 실패**를 재현했다. 27회 모두 저장됐고 last_error는 비어 있었다.
- 낮 조건의 마지막 OUT은 **[164, 150, 155, 151]**, 모두 ok였으며 IN wlc3는 **32명/다른 IN 중앙값 399명**으로 warn이었다. 27회 모두 저장되고 테스트가 통과했다. 두 조건의 동일 입력을 수정 전과 현재 평가 함수에 각각 적용한 54개 반환 결과도 모두 같았다.
- 이는 제품 판정 오류 없이 테스트 전제가 깨지는 메커니즘을 입증한다. **실제 Windows 실패 당시의 난수 순서/정확한 분배값을 복원한 것은 아니다.** 제품의 정상 주의 표시를 제거하거나 임계값을 완화하지 않는다.
- 수정 파일은 `tests/test_report_window.py`와 이 기록뿐이다. 기존 `Engine.run_blocking(now=...)` 인자에 **실행 당일의 로컬 13:00부터 1분 간격** 시각을 주입한다. 27회 실제 수집/평가/DB 저장/보고서 생성 및 BB3 장애 시나리오는 그대로다.
- 절대 과거 날짜를 고정하면 실제 시각 기준의 이력 보관 정리로 미래 CI에서 fixture가 삭제될 수 있으므로 실행 당일을 사용한다. 전역 시계나 제품 timeout/보존 정책을 바꾸지 않는다.
- 13:00~13:26의 factor는 0.9958428249693113~1.0이며, 가능한 모든 OUT Active는 144~175명이다. 최소 144가 다른 OUT의 최대 중앙값 175의 25%(43.75)보다 크므로 허용 난수 순서와 무관하게 OUT 정상 조건이 유지된다. 마지막 4회 IN의 정상 peer는 최소 393, wlc3는 최대 33이므로 기존 저분배 경고도 유지된다.
- 기존 OUT 정상/클러스터 연결/요약/합계/보고서 assertions를 모두 보존하고 IN wlc3의 clients=warn assertion을 추가했다. 모든 Client 경고를 없애는 잘못된 수정은 통과할 수 없다. 기본 25%와 현재 fixture만으로 모든 클러스터 혼합 오류를 검출한다고 주장하지는 않는다.

### 변경 후 검증과 현재 상태

- `python -m unittest tests.test_report_window tests.test_excel_text_safety tests.test_report_snapshots -v`: **32개 / 8.386초 / OK**. Python 3.12.14 로컬에서 기존 보고서 시트/셀/형식, 완료 알림 문구, 창 종료 판단, Excel 제어 문자, 과거 보고서 context/DB 호환성을 확인했다.
- 최종 테스트 blob은 `7df95a72693cfab5c3fa3fce0a1496ddfcc7f25b`이며 독립 Diff review PASS다. 변경은 datetime import, 당일 낮 시간 주입, 실제 IN warn assertion의 3개 hunk다.
- 진행 문서 수정 전 로컬 121개 text blob을 기준 head와 대조해 보고서 테스트 하나만 달라지고 120개가 같음을 확인했다. 원격 아이콘 2개를 포함한 나머지 blob은 base tree에서 보존한다. 제품/장비 명령/판정/임계값/UI/API/보고서 형식/설정/DB/스케줄/workflow/패키지는 이번 보강에서 변경하지 않는다.
- **S-09 진행 중, 완료 8개, 전체 95.0%, 증가 +0.0%p**를 유지한다. 기존 스케줄 테스트 보강을 포함한 실제 새 Commit의 전체 Windows Actions 성공과 최종 기록 대조 후에만 S-09의 5%를 복구한다.
- 작업 수 9개와 가중치 100%는 그대로이며 새 작업을 추가하지 않았다. 일반 `/api/run` 범위 밖 ID 예외는 승인 범위 밖 후속 후보로 남긴다.


## S-09 재완료 — 두 검증 보강 후 최종 Windows Actions 성공

### 확정 코드와 실제 성공 근거

- 반복 스케줄 테스트 변경은 [4ad89eddef849e4054a4ef980f99a166c8551a53](https://github.com/yejin0414/auto_network/commit/4ad89eddef849e4054a4ef980f99a166c8551a53), 보고서 Demo fixture 변경은 [3daca0f035013982f98293db06608cb8680158fa](https://github.com/yejin0414/auto_network/commit/3daca0f035013982f98293db06608cb8680158fa)이며 기존 [Draft PR #8](https://github.com/yejin0414/auto_network/pull/8)로 추적한다.
- 최종 검증 코드 head는 `3daca0f035013982f98293db06608cb8680158fa`, Tree `985ceeae2081ca6d67396d0d542cd8243fb41f15`다. 원격에 게시한 테스트와 문서를 다시 읽어 로컬 원문 및 blob이 정확히 같은지 확인했다.
- [Actions 39867775538](https://github.com/yejin0414/auto_network/actions/runs/39867775538) / [Job 120134212774](https://github.com/yejin0414/auto_network/actions/runs/39867775538/job/120134212774)의 정확한 head를 대조했다. Run/Job 모두 **completed/success**, **22개 단계 전체 success**이며 최종 Run 갱신 시각은 **2026-10-22T23:01:17Z**다. 전체 실제 로그 **164,751자**를 확인했고 독립 검토에서도 같은 결과를 확인했다.

| 검증 항목 | 실제 최종 결과 |
|---|---|
| Windows Python 3.12.10 / SQLite 3.49.1 | **Ran 420 tests in 179.686s / OK (skipped=4)** |
| 보강한 반복 자동 점검 테스트 | `test_runs_repeatedly` 개별 **ok** |
| 보강한 두 클러스터 보고서 테스트 | `test_two_clusters_separate` 개별 **ok** |
| 신규 숫자 안전성 / HTTP 입력 회귀 | **22개 / 11개 모두 개별 ok** |
| 공개 소스 및 UI | **123개 파일 PASS**, history **15개 PASS**, 기존 settings PASS |
| 합성 1GiB DB·백업·외부 복원 | **서로 다른 29개 phase 모두 PASS** |
| Windows EXE | 빌드, Demo 저장, 계정/설정 실패 보상, Mock SSH, 재시작 유지 모두 성공 |
| Windows 실행·창·보고서 | 중복 실행/버전 교체/포트 독점, Edge 앱 창, 완전 종료, Excel 자동 저장/내려받기 모두 성공 |
| Windows 작업 스케줄러 | 등록, 주기 변경, 켜진 앱 중복 방지, 창이 닫힌 상태 점검, `schtasks /Run` 점검, 설정 해제/종료 후 작업 부재 확인 모두 성공 |
| 패키지·증거 보관 | 기존 ZIP 내용 검사, EXE artifact와 검증 로그 보관 성공 |

- skip 4건은 SQLite 3.49.1의 기존 DELETE 정책으로 지원하지 않는 **WAL 하위 fixture**다. 같은 Store/별도 연결의 읽기 및 보고서 snapshot 하위 조건이라는 실제 skip 사유를 확인했다. 보강한 두 테스트나 신규 숫자/HTTP 테스트가 skip된 것이 아니다. Windows EXE/복원 DB의 실제 journal mode=delete 검증은 통과했다.
- 토스트는 표시 요청까지 성공했지만 실제 사용자 화면 표시 확인은 로그의 **NOT_RUN** 그대로 미검증이다. Windows CI 성공을 운영 PC의 장시간 실행·절전 복귀 또는 물리 모바일 검증으로 확대하지 않는다.
- 검증 로그 artifact는 [Windows-validation-logs / 12465636691](https://github.com/yejin0414/auto_network/actions/runs/39867775538/artifacts/12465636691), **18,755 bytes**다. EXE artifact는 [NetcheckCenter_windows / 12465741259](https://github.com/yejin0414/auto_network/actions/runs/39867775538/artifacts/12465741259), **21,618,162 bytes**다. 둘 다 같은 head SHA이고 조회 당시 미만료, 만료일은 2026-11-05다. 핵심 결과는 artifact 만료와 별도로 이 문서에 남긴다.

### 기능 보존과 최종 변경 범위

- S-09 재작업에서는 제품 코드 수정 없이 **기존 테스트 2개와 진행 문서**만 보강했다. 일정·중복 방지·실제 수집/평가/저장/보고서 경로를 그대로 사용하며, 시간과 난수에 좌우되던 테스트의 가정과 완료/정리 조건을 명확히 했다.
- 최종 코드 Tree는 직전 head 대비 보고서 테스트와 진행 문서 2개만 다르고 다른 **121개 blob**은 같다. 최초 main과 누적 비교 결과는 **113 → 123개 파일**, 변경 경로 **25개(제품 9 + 기존 테스트 6 + 신규 테스트 9 + 문서 1)**, 기존 **98개 blob 동일**, 삭제/mode 변경 0개다.
- 장비 명령/collector, 설정 형식, DB 스키마, HTML/CSS, schedule_sync/wintask, app/창/instance/notify, DB 유지보수, requirements/workflow/tools는 시작 기준과 동일하다. 일반 기능·임계값·판정·UI/API/보고서 형식은 보존한다.
- S-04의 사용자 승인 사항은 유지한다. 해석할 수 없는 uptime만 기존 정상 표시에서 해당 지표의 '확인 불가'로 격리하며 다른 정상 결과 및 기존 주의/장애는 보존한다. 과거 DB나 임의의 손상 보고서를 일괄 변경하지 않는다.
- 이 완료 기록 Commit은 **이 문서만 변경**하며 성공한 코드와 제품/테스트 등 **나머지 122개 blob을 동일하게 유지**한다. 이 추가 Commit의 자동 CI는 [PR #8 checks](https://github.com/yejin0414/auto_network/pull/8/checks)에서 다시 확인하고 실제 결과를 PR 설명에 기록한다. 확인 전 그 실행까지 성공했다고 주장하지 않는다.

### 진행률·잔여 범위·다음 작업

- **S-09 완료.** 두 실패 메커니즘의 제어 재현, 검증 보강, 기존 기능 보존 대조, 정확한 최종 코드의 전체 Windows Actions 성공, Commit/PR/실제 결과 기록 조건을 충족했다.
- 전체 **9개 완료**, 진행 중/대기/보류/실패 **0개**, 가중치 합계 **100%**, 진행률 **100.0%**, 직전 대비 **+5.0%p**다. 재검증으로 제외했던 S-09의 기존 5%만 복구하며 중복 집계나 작업/가중치 변경은 없다.
- **기존 승인 계획 안에서 다음으로 진행할 대기 작업은 없다.** 일반 `/api/run`의 SQLite 정수 범위 밖 ID 예외는 별도 후속 후보 S-10이다. 승인된 계획 범위 안에서만 계속한다는 사용자 조건에 따라 새 작업/가중치나 제품 수정으로 자동 확장하지 않는다.
- 남은 한계는 기존 worker/helper의 강제 종료 불가, 단일 Excel 회차 압축 원문의 처리 중 메모리 보유, 실제 토스트/장시간 실행·절전 복귀/물리 모바일 미검증이다. 운영 장비와 실제 계정/DB는 사용하지 않았다.
- PR #8은 Draft/미병합으로 유지한다. main 직접 수정, 원본 저장소 접근/동기화, PR 병합, 릴리스 생성 또는 배포를 수행하지 않는다. **100.0%는 승인된 계획의 검증 완료이며 소프트웨어 전체의 무결함 보증이 아니다.**

## S-10 실행 기록 — 일반 회차 조회의 정수 범위 방어

### 승인, 기준과 기존 완료 상태

- 2026-10-23(한국시간) 사용자의 '남은 작업 진행해 줘'를 이미 구체적으로 제시한 S-10에 대한 승인으로 기록한다. 제품 수정 전 범위 밖 ID만 요청 실패에서 기존 형식의 HTTP 400으로 바뀌는 차이를 보고했다.
- 시작 head는 `f2e254dfa379bd00db2f6479de754c1c8174d902`, Tree `75fd4e82d3bccc2d8e5947b4edd09e6d28ae554b`이며 기존 브랜치 `stability/s01-credential-startup`과 [PR #8](https://github.com/yejin0414/auto_network/pull/8)을 계속 사용한다. `main`은 최초 기준 `bc413434f76068ee443d620a65ba0d622d867cc2` 그대로다.
- S-09 완료 문서 head의 별도 [Actions 39869381349](https://github.com/yejin0414/auto_network/actions/runs/39869381349) / [Job 120139646501](https://github.com/yejin0414/auto_network/actions/runs/39869381349/job/120139646501)도 **completed/success**, 22단계 전체 성공이다. 실제 로그에서 Python **420개 / 178.380초 / OK(skipped=4)**, Node UI15개/설정, 소스123개, DB29단계, Windows EXE/계정/창/예약 작업/패키지 성공을 확인했다. 이 성공은 이전 완료 이력을 유지하는 근거이며 S-10의 새 변경 검증을 대신하지 않는다.
- 로컬 사본의 텍스트/소스 **121개** Git blob을 위 원격 Tree와 대조해 모두 동일함을 확인했다. 내려받지 않은 아이콘2개는 기존 base Tree를 보존한다. 새 작업 폴더에서 제품·테스트·진행 문서 세 경로만 수정한다.
- 기존 9개는 완료 상태를 유지하며 합계95%로 비례 조정했다. S-10에5%를 추가한 현재10개 계획의 진행률은 **95.0%**다. 과거100% 기록은 당시9개 범위의 사실로 보존한다.

### 수정 전 재현과 최소 변경

- 테스트를 먼저 추가한 뒤 수정 전 제품에서 `tests.test_http_input_safety`를 실행했다. **16개 / 0.622초 / FAILED(failures=4, errors=4)**. 범위 밖 ID 4개를 Mock Store가 그대로 받는 결함과 실제 임시 SQLite에서 같은4개가 `OverflowError`로 HTTP 응답 없이 빠져나오는 결함을 구분해 확인했다.
- 실제 재현 입력은 `-9223372036854775809`, `9223372036854775808`, `-(10**100)`, `10**100`이다. 정확한 signed64 양 끝값은 기존404이며, 기존11개 및 새 정상 계약3개 메서드가 수정 전에도 통과했다.
- `nc/server.py`의 `/api/run`에서 기존 `int()` 해석 직후 범위 검사2줄만 추가했다. 범위를 벗어나면 기존 SQLite 예외 문구를 가진 `ValueError`를 발생시켜 기존 HTTP 입력 오류 처리로 전달한다. 정상 ID에 대한 Store 내부 `OverflowError`까지 포괄적으로 잡지 않는다.
- `tests/test_http_input_safety.py`에는 기존11개를 유지하고5개 메서드를 추가했다. API 정상 ID 호환성, 범위 밖 입력의 Store 호출 방지/인증 선행,404/503, 내부 오류 미은폐, 실제 SQLite의 데이터 불변과 다음 정상 조회를 확인한다. 실제 소켓/운영 장비/계정은 사용하지 않는다.

### 로컬 검증과 기능 보존

- 수정 후 `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_http_input_safety -v`: **16개 / 0.230초 / OK**. 독립 검토에서 제품2줄의 범위/None/0 동작과 최소 Diff를 확인했다.
- `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_storage_api tests.test_read_snapshots tests.test_report_read_snapshots tests.test_report_snapshots tests.test_report_capture tests.test_excel_text_safety -v`: **50개 / 1.713초 / OK**. 출력된 synthetic snapshot/압축 오류는 주입한 실패 경로의 예상 로그이며 테스트는 통과했다.
- 합계66개 로컬 검증에서 정상200 payload, 인증403, 존재하지 않는 이력404, DB/파일 읽기 장애503, 기존400 형식을 보존했다. 생략/빈 ID/0 최신 조회, 부호/공백/Unicode/밑줄/앞자리0 등 기존 `int()` 해석도 보존했다.
- 범위 밖 ID는 DB에 전달하지 않는다. 실제 SQLite의 전체 `iterdump()`와 `total_changes`가 동일하고 열린 트랜잭션이 없으며 바로 다음 정상 ID/최신 이력 조회가200으로 성공한다.
- 장비 명령/수집/판정/임계값, 인증 저장 형식, DB 스키마, UI/보고서 형식, 스케줄러/Windows 코드, app.py의 실행 버전1.5.1, dependencies/workflow/tools는 이번 S-10에서 변경하지 않는다.
- 제품 Git blob: `3a601159d20de8c8855d705d49b175e6f60f59b2`; 테스트 Git blob: `45aef144c30fb2beec21d8121268fbc042fc40bc`. 새 Commit/Actions 근거는 이 기록을 갱신해 확정하며 [PR #8 Commit 이력](https://github.com/yejin0414/auto_network/pull/8/commits)과 대조한다.
- **현재 S-10 진행 중, 완료9개/10개,95.0%**. 로컬 성공을 GitHub Actions 성공으로 계산하지 않으며 변경 Commit의 전체 Windows 검증은 아직 미실행이다.

### 검증 후 전달 단계

- 사용자 요청에 따라 S-10 검증 후 PR #8을 정확한 검증 head 조건과 merge commit 방식으로 병합하여 작업별 Commit을 보존한다. 보호/리뷰/검증 조건을 우회하지 않는다.
- 최초 릴리스 준비 조회에서 이 대상 저장소의 기존 tags/releases는 모두0개였고 실제 실행 버전은 `app.py`의1.5.1이었다. 당시 후보는v1.5.1이었으나 이후 사용자의 버전업·최소 증가 지시에 따라 **v1.5.2**로 변경했다. 현재 기준은 아래 전달 단계 기록이다.
- 기존 main push workflow의 실제 전체 성공 후 그 병합 Commit에서 생성한 `NetcheckCenter_windows.zip` 및 `.sha256`을 배포 후보로 사용한다. Actions artifact의14일 보관과 GitHub Release의 게시를 구분한다.
- 현재 GitHub 플러그인에는 Draft 해제/PR 병합/artifact 다운로드가 있으나 Release 생성/태그 생성/asset 업로드 도구가 노출되지 않았다. 게시 수단을 확보하기 전 릴리스 완료를 주장하지 않으며, 이를 우회하려고 권한이 다른 workflow나 자동 배포 기능을 추가하지 않는다.
- 실제 운영 장비, 장시간 운영/절전 복귀, 물리 모바일, 사용자 화면의 토스트 표시는 계속 미검증이다. 이 제한은 S-10 수정으로 새로 생긴 결함이 아니며 기존 기록과 함께 유지한다.

## S-10 완료 — 실제 전체 Windows Actions 성공

- 코드 Commit: [0101825b9042ce4751caa0b97118cd5c889c7af3](https://github.com/yejin0414/auto_network/commit/0101825b9042ce4751caa0b97118cd5c889c7af3), Tree `54b6bb640af8c29f7b0d53f2480815ea198afda7`. 예정된3개 경로만 변경했고 원격 원문과 로컬 blob이 모두 일치한다. 나머지120개 blob은 동일하며 삭제/파일 mode 변경은 없다.
- [Actions 39873264462](https://github.com/yejin0414/auto_network/actions/runs/39873264462) / [Job 120152585949](https://github.com/yejin0414/auto_network/actions/runs/39873264462/job/120152585949)의 `head_sha`가 코드 Commit과 정확히 같다. Run/Job 모두 **completed/success**, **22단계 전체 success**, Run 최종 갱신은 **2026-10-22T23:52:12Z**다.
- 실제 전체 로그165,154자를 확인했다. Windows Python3.12.10 / SQLite3.49.1에서 **Ran425 tests in187.916s / OK(skipped=4)**다. S-10 신규5개 포함 HTTP16개, 숫자 안전성22개, S-09의 반복 스케줄·두 클러스터 보고서 테스트가 모두 개별ok다.
- 공개 소스123개, Node history15개/기존 settings, 합성1GiB DB의 서로 다른29개 phase가 모두PASS다. DB의 원자 저장·온라인 백업·외부 byte 전송·SHA256·원본 없는 복원·정리 후 원본 불변도 포함한다.
- EXE 빌드/데모/계정 저장·설정 실패 보상/Mock SSH/재시작 유지, 중복 실행·버전 교체·포트 독점, Edge 창·Excel 저장/내려받기·완전 종료, Windows 예약 작업 등록/주기 변경/켜진 앱 중복 방지/닫힌 앱 점검/설정 해제/종료 후 작업 부재 확인이 모두 성공했다. 실제 `schtasks /Run` 결과는 **점검됨**이다.
- skip4개는 기존 DELETE 정책의 미지원WAL 하위 fixture다. 신규5개를 포함한 HTTP16개는 skip되지 않았다. 토스트 표시 요청은 성공했지만 실제 사용자 화면 표시 확인은 **NOT_RUN**이다.
- 같은 head의 [EXE artifact12467548065](https://github.com/yejin0414/auto_network/actions/runs/39873264462/artifacts/12467548065)는21,618,215bytes, [검증 로그 artifact12467289585](https://github.com/yejin0414/auto_network/actions/runs/39873264462/artifacts/12467289585)는18,865bytes다. 조회 시 미만료, 만료일2026-11-05다. 이 EXE는 버전업 전1.5.1 검증 자료이며 최종1.5.2 릴리스 패키지로 혼용하지 않는다.
- 기존 정상200/403/404/503, int 호환 ID,0/생략 최신 조회, 보고서/토큰/종료, DB 불변/복구 계약을 실제 회귀로 확인했다. 승인된 오류 입력 이외의 기능 변경을 발견하지 못했다.
- **S-10 완료.** 수정 전 재현, 최소2줄 수정, 독립 Diff/테스트 검토, 정상 기능 보존, 실제 전체 Windows CI 및 Commit/PR 기록 조건을 충족했다. 전체10개 완료, 진행 중·대기·보류·실패0개, **100.0%**, 직전95.0% 대비 **+5.0%p**다. 현재 승인된 안정성 계획 안의 잔여 작업은0개다.

## 전달 단계 — 사용자 요청에 따른 버전 1.5.2

- 사용자가 누적 변경에 대한 버전업을 요청한 뒤 직전 버전의 바로 다음 버전으로 최소 증가하도록 지시했다. 현재 원격 `app.py`의 `VERSION = "1.5.1"`과 blob `bb34e5b3fa4e7c8e1a017cce7796cfd060b4b794`를 다시 확인했다. 대상 저장소의 tag/release는 조회 당시 모두0개였다.
- **변경:1.5.1→1.5.2, 릴리스 태그:v1.5.2, 제목:Netcheck Center v1.5.2 — 안정성 개선.** 앞서 제안한1.6.0은 파일/Commit/태그/릴리스에 적용하지 않았다.
- 이번 후속 Commit은 `app.py`의 VERSION1줄과 이 진행 기록만 변경한다. S-10 제품 및 테스트를 포함한 다른121개 blob은 성공한 코드 Commit과 동일하게 유지한다. 안정성 작업에 새 가중치를 추가하거나 기존 완료를 중복 계산하지 않는다.
- 실행 코드의 버전 상수는 한 곳이며 동일 값이 App, `/api/version`, 상태/UI, 실행 로그와 인스턴스 기록에 전달된다. 버전 비교/인증/종료 동작은 변경하지 않는다. 다른 버전과의 기존 인증된 교체 경로가1.5.2에서도 작동하는지 실제 Windows 테스트로 확인한다.
- 로컬 AST 파싱과 원문 대조에서 app.py의 정확히1줄만 바뀜을 확인했다. 새 앱 blob은 `8742830c14ec5a8460f962ee2fd0b56dcfa363c6`이다. 기존 Windows 인스턴스 검사는 EXE에서 버전을 동적으로 읽으므로 테스트를 바꾸지 않는다. 역사 문서의 과거 버전/도입 시점은 보존한다.
- 새 버전의 전체 Windows CI는 이 기록 작성 시 **미실행**이다. 통과 여부와 실제 `v1.5.2`/이전 버전 교체 로그를 [PR #8 checks](https://github.com/yejin0414/auto_network/pull/8/checks)에서 확인하고 PR 설명에 영구 기록한다. 기록만 추가하기 위한 반복 CI를 만들지 않으며 실제 새 버전 실패가 발생하면 전달을 중단하고 근거를 기록한다.
- 정확한 최종 head의 CI 성공 후 승인된 merge commit 병합을 진행한다. main push CI도 확인해 병합 Commit의 ZIP/체크섬을 릴리스 후보로 준비한다. main 직접 편집, 원본 접근/동기화, 보호 규칙 우회, 운영 장비/자동 배포는 수행하지 않는다.
- GitHub 플러그인의 Release 생성/태그 생성/asset 업로드 도구 부재는 아직 해결되지 않았다. 코드/검증/병합/배포 파일 준비를 가능한 범위까지 마친 다음 게시 수단을 확정한다. 실제 Release가 생성되지 않았다면 게시 완료라고 기록하지 않는다.

**현재 구분:** 안정성10개 검증100.0%; 버전1.5.2 소스 반영/최종 CI 대기; PR 병합 미실행; 릴리스 게시 미실행. 최신 실제 전달 결과는 [PR #8](https://github.com/yejin0414/auto_network/pull/8)의 최종 head, 병합 상태, Actions 근거 및 전달 기록과 함께 대조한다.
