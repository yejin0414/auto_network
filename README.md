# 무선망 통합 점검 센터 (Netcheck Center)

## 소스 및 Windows 검증

이 저장소는 [yejin0414/auto_network](https://github.com/yejin0414/auto_network)입니다.
[소스 ZIP 다운로드](https://github.com/yejin0414/auto_network/archive/refs/heads/main.zip) ·
[Windows 빌드와 검증 결과](https://github.com/yejin0414/auto_network/actions/workflows/build-exe.yml) ·
[릴리스 목록](https://github.com/yejin0414/auto_network/releases)

**최초 이전에서는 Release를 게시하지 않습니다.** 성공한 Actions 실행의 `NetcheckCenter_windows`
아티팩트에 EXE ZIP과 SHA-256이 있습니다(GitHub 로그인 필요). 공개 배포는 별도 검토 후 진행합니다.
압축은 쓰기 가능한 새 폴더에 풀고 `NetcheckCenter.exe`를 실행하세요.
장비 없이 확인하려면 `데모_실행.bat`, 일반 브라우저를 사용하려면 `웹_버전_실행.bat`을 실행합니다.

**새 설정의 자동 점검과 Windows 백그라운드 예약작업은 기본 꺼짐입니다.**
장비·계정을 확인한 후 필요한 기능만 설정에서 켜세요. 자격 증명 서비스·실행 상태는 `AutoNetwork.NetcheckCenter`, 예약작업은
`AutoNetwork NetcheckCenter AutoCheck`로 분리됩니다. 원본의 저장 계정·예약작업·실행 상태를
자동으로 가져오지 않으며, 대상 기본 화면 주소는 `http://127.0.0.1:8875/`입니다.

분석·재현 방법·검증 범위는 [이전 분석 보고서](docs/MIGRATION_ANALYSIS.md),
원본 출처는 [UPSTREAM.md](UPSTREAM.md)를 참고하세요.

---

백본(HPE Comware) · Mobility Master · WLC 클러스터(ArubaOS 8)를 **한 번에** 점검하고,
**CPU·메모리**와 상세 항목을 확인하며, **사용자가 활성화한 주기(기본 간격 1시간)마다 자동 점검**하는 Windows 프로그램입니다.
주소창·탭 없는 독립된 프로그램 창으로 실행됩니다(Windows에 기본으로 있는 Microsoft Edge의 앱 모드 사용, 추가 설치 없음).

기존 두 도구를 하나로 합쳤습니다.

| 기존 | 통합 후 |
|---|---|
| Aruba MM/WLC 대시보드: `show switches`, `lc-cluster` 2개 명령만 확인 | + CPU(`show cpuload`), 메모리(`show memory`), 가동시간·재부팅 감지, 구성 동기화 상태 |
| 백본 상태 추적기: 별도 실행, 작업 전/후 수동 비교 | 같은 화면에서 자동 점검, 첫 점검을 기준값으로 저장해 이후 변화 자동 감지 |
| 프로그램을 따로 열어야 함 | 한 화면, 한 번의 ‘지금 점검’으로 BB·MM·WLC 동시 점검(병렬 SSH) |

## 화면 구성

- **종합 상태 + 구성도**: 백본 → MM → WLC 클러스터를 그림으로 보여 주고 장비마다 상태색, CPU·메모리를 표시
- **장비 현황**: 장비별 CPU·메모리 막대(주의/장애 기준선 포함), 가동시간, 확인할 내용, 24시간 추이
- **상세(장비 클릭)**: 점검 항목별 판단 근거 / **원본 출력**(실제 장비 응답 그대로, 검색·복사) / CPU·메모리 24시간·7일 그래프
- **WLC 클러스터**: MM 보고 상태, CONNECTED 여부, Leader, Connection-Type, Active/Standby Client 분배
- **VRRP 이력**: 백본 VRRP Master/Backup 변화와 장비 로그를 표시합니다. 같은 인터페이스·VRID·이전/새 역할이 일치하고 점검 사이에 유일한 전환 로그가 있을 때만 점검 변화에 장비 로그 시각을 연결합니다. 그 외에는 점검 시각 범위와 로그를 별도로 남깁니다. 확인 후 **‘확인 · 초기화’**를 누르면 그 백본의 VRRP 기준값만 다시 잡고 바로 다시 점검합니다(다른 점검 항목 기준값은 그대로).
- **이력**: 최근 48회 점검 상태 격자(칸을 누르면 그 회차로 이동), 상태 변화 기록, **HTML 보고서 저장**
- **직접 확인**: 원하는 장비에 `show` / `display` 조회 명령을 바로 실행(설정 변경·재부팅·삭제 명령은 차단)
- **설정**: 계정, 장비 목록, 자동 점검 주기, 판단 기준, 원본 보관용 추가 명령

## 점검 항목

| 구분 | 명령 | 판단 |
|---|---|---|
| 공통 | `display version` / `show version` | 가동시간, 이전 점검 대비 재부팅 감지 |
| 백본 | `show cpu summary` (거부되면 `display cpu-usage summary` → `display cpu-usage`) | Last 5 sec / 1 min / 5 min, 슬롯별. 판단은 Last 1 min 최대값: 주의 50% · 장애 70% |
| 백본 | `show memory summary` (거부되면 `display memory summary` → `display memory`) | 슬롯별 Total / Used / Free / FreeRatio. 사용률(100% - FreeRatio) 주의 60% · 장애 70% |
| 백본 | `show logbuffer reverse` | 최근 로그 100건(엑셀 ‘백본 로그’ 시트), 오류급 이상 건수 표시 |
| 컨트롤러 | `show cpu` (거부되면 `show cpuload`) | user / system / idle. 판단은 100% - idle |
| 컨트롤러 | `show memory` | Total / Used / Free, Used % |
| 백본 | `display device` | 슬롯/IRF 멤버 Fault, 기준 대비 사라진 멤버 |
| 백본 | `display power`, `display fan` | Fault/Abnormal, 기준 Normal이던 모듈 미장착 |
| 백본 | `display interface brief` | **기준 대비 UP → DOWN 된 포트** (ADM은 제외) |
| 백본 | `display link-aggregation summary` | Selected 감소 = 장애, Unselected 존재 = 주의 |
| 백본 | `display ospf peer` | Full/2-Way 아님, 기준 대비 사라진 인접 |
| 백본 | `display vrrp` (거부되면 `show vrrp`) | Initialize = 장애, Master↔Backup 변화 = 주의 |
| MM | `show switches` | 등록 WLC가 Down이면 해당 WLC 장애, 구성 동기화 실패는 주의 |
| WLC | `show lc-cluster group-membership` | CONNECTED 아님 = 장애, Connection-Type 변화 = 주의 |
| WLC | 클러스터별(IN/OUT 등) 대표 WLC에서 실행 | 모델이 다른 컨트롤러(예: IN 7240XM, OUT 7210)는 클러스터를 따로 두고, Client 분배도 같은 클러스터 안에서만 비교 |
| WLC | `show lc-cluster load distribution client` | 다른 WLC 중앙값의 25% 미만이면 주의(전체 사용량이 낮을 땐 판단 안 함) |

클러스터 멤버십과 Client 분배 중 일부만 수집되면, 성공한 결과를 보존하면서 같은 클러스터의
다른 접속 가능한 WLC에서 부족한 항목만 다시 수집합니다. 항목별 출처는 화면·원본 출력·보고서에
표시합니다. 모든 클러스터의 대체 수집은 합쳐서 기본 5분의 예산을 사용하며, 제한을 넘긴 항목은
확인 불가로 남깁니다. 중단된 점검의 늦은 응답은 새 회차에 반영하지 않습니다.

상태는 **정상 / 주의 / 장애 / 확인 불가** 네 단계입니다. SSH 접속 실패·명령 거부·해석 실패는
장비 장애로 단정하지 않고 **확인 불가**로 구분합니다(기존 Aruba 도구의 원칙 유지). 단, MM이 해당 WLC를
명시적으로 Down으로 보고하면 장애입니다.

**기준값**: 백본의 UP 포트·LACP Selected 수·OSPF 인접·VRRP 역할·전원/팬 상태, WLC Connection-Type은
첫 점검 때 저장됩니다. 계획된 작업으로 구성이 바뀌었다면 설정 탭에서 **기준값 다시 잡기**를 누르세요.

VRRP 기준에 있던 그룹이 사라지면 장애로 표시하며 기준값은 자동으로 지우지 않습니다.
명령 실패나 해석할 수 없는 출력은 확인 불가로 구분합니다.

**과거 보고서**: 새 점검부터 당시 사업장명과 판단 임계값을 회차에 함께 저장합니다.
이후 설정을 바꿔도 HTML·Excel 보고서는 해당 회차의 기준을 사용합니다.
기존 DB는 자동으로 호환 형식으로 확장됩니다. 당시 기준이 없는 과거 회차는 저장된 판정을 유지하고
‘당시 판단 기준 없음’을 표시합니다. 이 경우 Excel 슬롯 상태는 저장된 장비 단위 CPU·메모리 판정이며,
사업장명은 현재 설정의 참고값입니다.

## 실행

### 프로그램(EXE)으로 실행 — 권장

1. 성공한 Windows Actions 실행에서 아티팩트를 받아 EXE ZIP을 새 폴더에 풉니다.
2. `NetcheckCenter.exe` 를 실행하면 점검 프로그램 창이 열립니다.
3. **설정 → 접속 계정**에 아이디·비밀번호를 입력합니다(백본·MM·WLC 공통 계정 하나, enable 비밀번호 없음).
   ‘Windows 자격 증명 관리자에 저장’을 켜면 계정을 다시 사용할 수 있습니다. 자동 점검은 설정에서 활성화해야 하며, 창 밖의 점검은 백그라운드 점검 활성화와 Windows 로그인 세션이 필요합니다.
4. **설정 → 점검 장비**에서 IP를 실제 값으로 바꾸고 대표 WLC를 고른 뒤 **설정 저장**.
   기본 목록은 백본 4대 · MM 2대 · WLC 8대(IN 4대 · OUT 4대)입니다. WLC는 **클러스터** 칸에 IN / OUT을 넣고, 클러스터마다 **대표 WLC**를 하나씩 고르세요. 여러 대는 **여러 대 한 번에 추가**에
   `구분 이름 IP` 를 한 줄에 한 대씩(엑셀에서 세 칸 복사해 붙여 넣기 가능) 넣으면 됩니다.
5. **지금 점검**으로 첫 결과(=기준값)를 확인합니다. 자동 점검을 켜면 설정한 주기에 따라 점검합니다.

- 새 장애·주의가 생기면 프로그램 창이 맨 앞으로 올라오고 제목 표시줄에 `(장애 1)` 처럼 표시됩니다.
- 점검이 끝날 때마다 **화면 오른쪽 아래에 Windows 알림**이 뜨고, **엑셀 보고서가 `보고서` 폴더에 자동 저장**됩니다.
- 상단 **엑셀 보고서** 버튼은 가장 최근 결과를 엑셀로 만들어 바로 엽니다.
- **창을 닫으면 프로그램은 완전히 종료**됩니다. 설정에서 자동 점검과 **창을 닫아도 자동 점검**을 모두 켠 경우에만 Windows **작업 스케줄러**에
  `AutoNetwork NetcheckCenter AutoCheck` 작업을 등록해, 창이 닫혀 있으면 정해진 시간마다 창 없이 점검 → 엑셀 저장 → 완료 알림을 합니다.
  창이 켜져 있으면 프로그램 안에서 점검하므로 두 번 점검하지 않습니다. 관리자 권한은 필요 없습니다.
  - 끄기: 설정 → 자동 점검 → ‘창을 닫아도 자동 점검’ 해제(작업이 지워짐)
  - PC를 끄거나 로그아웃하면 멈추고, 절전에서 깨어나면 놓친 점검을 바로 합니다.
  - 프로그램 폴더를 옮겼으면 프로그램을 한 번 실행하면 작업이 새 위치로 다시 맞춰집니다.
- 주기를 연속 저장하거나 자동 점검을 끄면 마지막으로 저장한 설정을 Windows 작업에 반영합니다.
  반영 중·실패·재시도 상태를 화면에 표시하며, 종료할 때도 마지막 설정 반영을 기다립니다.
  Windows가 적용을 거부하거나 제한 시간 내 응답하지 않으면 로그에 실패를 남깁니다.
- **점검이 ‘점검 중’에서 멈추지 않습니다**: 장비 한 대가 ‘접속 대기×2 + 명령 대기×3’(최소 5분)을 넘기면 그 장비만 ‘응답 없음’으로 중단하고 점검을 끝냅니다.
  그래도 점검 전체가 40분 넘게 끝나지 않으면 멈춘 것으로 보고 다음 자동 점검을 진행합니다.
- 로그인할 때 자동으로(최소화 상태로) 켜려면 프로그램 폴더에서:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

### 새 버전으로 바꿀 때

새 ZIP을 받아 압축을 풀고 `NetcheckCenter.exe` 를 실행하면 됩니다. 이전 버전이 켜져 있으면
“이전 버전을 종료하고 새 버전으로 실행할까요?”라고 묻고, **예**를 누르면 자동으로 바꿉니다(v1.3.3부터).
지금 실행 중인 버전은 화면 왼쪽 위 제목 옆(`v1.3.3` 등)과 창 제목에 표시됩니다.

### Python으로 실행

Python 3.10 이상(현재 자동 검증 기준: Python 3.12).

```powershell
python -m pip install -r requirements.txt
python app.py              # 프로그램 창으로 실행
python app.py --demo       # 장비 없이 데모 데이터로 실행(지난 24시간 데모 이력 포함)
python app.py --browser    # 프로그램 창 대신 웹 브라우저로 열기
```

`실행.bat` / `데모_실행.bat` 을 더블클릭해도 됩니다. Edge가 없는 PC에서는 기본 웹 브라우저로 엽니다.

### EXE 직접 만들기

Actions는 테스트와 패키징만 수행하며 Release는 게시하지 않습니다. Windows PC에서 직접 만들 때는:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_exe.ps1
```

## 접속이 안 될 때

장비를 누르면 ‘SSH 접속’ 항목에 원인이 표시됩니다.
**SecureCRT는 되는데 여기서만 안 되면** 장비 상세의 **접속 진단** 탭에서 ‘접속 진단 실행’을 누르세요.
TCP 연결 → SSH 배너 → 암호 방식 → 인증 방식 → 로그인 → 로그인 직후 화면 → 실제 명령 순서로 시험해 막힌 단계를 보여 줍니다.
‘결과 복사’는 IP 가운데 자리를 가린 텍스트를 복사합니다.

기존 **백본 상태 추적기**에서 잘 되던 장비라면 **설정 → 점검 장비 → 기존 백본 도구 설정 가져오기**로
그 도구의 `config\devices.yaml` 을 고르세요. IP·포트·장비 종류(device_type, 예: `hp_comware_telnet`)를 그대로 가져옵니다.
백본은 기존 도구와 같은 방식(시간 기준 명령 실행)으로 접속합니다.

**설정 → 접속 대기 시간**에서 **백본**과 **컨트롤러(MM·WLC)** 대기 시간을 따로 정합니다.

| | 접속 대기 (기본) | 명령 응답 대기 (기본) | 범위 |
|---|---|---|---|
| 백본 | 2분 | 2분 | 30초 ~ 10분 |
| 컨트롤러(MM·WLC) | 1분 | 1분 | 30초 ~ 10분 |

‘응답 없음’이나 ‘시간 초과’가 나오는 쪽만 늘리세요. 재시도 횟수는 공통입니다.

| 표시 | 뜻 | 조치 |
|---|---|---|
| 접속 계정이 입력되지 않았습니다 | 프로그램에 계정이 없음 | 설정 → 접속 계정 입력 후 저장 |
| 로그인 실패 | 아이디/비밀번호 불일치 | 백본·MM·WLC 모두 설정 → 접속 계정 하나를 씁니다 |
| SSH 암호 방식이 맞지 않습니다 | 장비가 오래된 SHA-1 SSH 방식만 지원 | 최신 버전으로 업데이트(v1.2.0부터 지원) 또는 접속 방식을 Telnet으로 |
| 연결 거부 | 장비에서 SSH(또는 Telnet)가 꺼져 있거나 포트가 다름 | 설정 → 점검 장비에서 접속 방식(SSH/Telnet)·포트 확인 |
| 응답 없음 | 관리망 경로, 방화벽/ACL, 장비의 접속 허용 IP | 이 PC에서 장비로 접속이 허용돼 있는지 확인 |

백본(Comware)은 **설정 → 점검 장비 → 접속 방식**에서 SSH/Telnet을 고를 수 있습니다(Telnet 기본 포트 23).
기존 백본 상태 추적기에서 Telnet(`hp_comware_telnet`)으로 접속했다면 여기서도 Telnet을 선택하세요.

## 엑셀 보고서

Demo 보고서는 `보고서-demo`에 분리됩니다. 점검이 끝날 때마다 `보고서\무선망점검_날짜_시각_run회차.xlsx` 로 저장합니다(설정 → 보고서·알림에서 끄거나 폴더 변경).

| 시트 | 내용 |
|---|---|
| 요약 | 장비별 상태, CPU, 메모리 사용, 가동시간, 확인할 내용 |
| 백본 CPU·메모리 | 슬롯별 **Last 5 sec / Last 1 min / Last 5 min**, Memory Total / Used / **Free** / FreeRatio |
| 컨트롤러 CPU·메모리 | MM·WLC별 CPU **user / system** / idle, Memory Total / **Used** / Free / Used % |
| 백본 로그 | `show logbuffer reverse` 최근 100건(오류급 이상 붉게 표시) |
| 백본 VRRP | 그룹별 현재 역할, 장비 로그의 VRRP 상태 변경 시각 |
| 점검 항목 | 모든 판단 근거 |
| 원본 출력 | 장비가 보낸 실제 응답(값 확인용) |

## 저장 위치와 보안

| 항목 | 위치 |
|---|---|
| 장비 설정(비밀번호 없음) | `config\config.json` |
| 점검 이력·원본 출력(압축)·기준값 | `data\netcheck.sqlite3` (기본 30일 보관) |
| 실행 로그 | `data\netcheck.log` |
| 비밀번호 | 프로그램 메모리, 선택 시 Windows 자격 증명 관리자 |

- 프로그램 화면은 PC 내부 주소(`127.0.0.1`)로만 통신하며 다른 PC에서 접속할 수 없습니다. 민감한 API와 보고서 요청에 실행 시 생성되는 토큰을 확인합니다. 초기 화면·정적 리소스·앱 식별 정보는 토큰 없이 로컬에 제공됩니다.
- 장비에는 `show` / `display` 조회 명령만 보냅니다(세션 준비용 `screen-length disable`, `no paging` 제외).
- 인증 실패는 계정 잠금 방지를 위해 재시도하지 않습니다.
- 데모와 테스트 데이터는 문서용 예약 주소(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24)와 로컬 테스트용 루프백만 사용합니다. OSPF Area ID와 버전 번호는 IP 주소가 아닙니다.

## 테스트

```powershell
python -m unittest discover -s tests -t . -v
```

- `tests/test_parsers.py`: 기존 Aruba 도구 fixture + Comware/ArubaOS 8 실제 형식 출력 해석
- `tests/test_backbone_access.py`: 오래된 SHA-1 SSH만 쓰는 백본, Telnet 백본, 연결 거부·비SSH 포트 원인 안내
- `tests/test_diagnose.py`: 접속 진단 단계별 결과, 기존 백본 도구 devices.yaml 가져오기
- `tests/test_report_window.py`: Excel 생성·알림 문구·WindowWatch 창 종료 판단
- `tests/test_e2e_ssh.py`: 가짜 SSH 장비(`<BB-3>`, `(ArubaMM) [mynode] #`, `(WLC-01) #` 프롬프트)에 **실제 netmiko로 접속**해
  수집 → 판단 → 저장 → 2회차 변화 감지 → 직접 확인 차단까지 검증, 조회 외 명령이 전송되지 않는지 확인

> 자동 검증은 가짜 장비 기준입니다. 실제 장비 출력 형식이 다르면(펌웨어 버전 차이 등) 해당 항목은 ‘확인 불가’로
> 표시되고 원본 출력 탭에서 실제 응답을 볼 수 있습니다. 그 출력을 `tests/fixtures`에 추가하면 파서를 맞출 수 있습니다.

## 구조

```
app.py               실행 진입점
nc/commands.py       역할별 점검 명령, 직접 확인 안전 검사
nc/collector.py      netmiko SSH 수집(병렬, 대체 명령, 오류 분류)
nc/parsers.py        명령 출력 파서
nc/evaluate.py       판단 로직(임계값, 기준값 비교, MM↔WLC 상관분석)
nc/engine.py         점검 실행, 자동 주기 스케줄러, 이벤트 기록
nc/store.py          SQLite 이력
nc/server.py         로컬 웹 서버/API
nc/report.py         HTML 보고서
nc/diagnose.py       접속 진단, 기존 백본 도구 설정 가져오기
nc/appwindow.py      프로그램 창(Edge 앱 모드), 창이 닫히면 전체 종료
nc/excel.py          엑셀 보고서
nc/notify.py         Windows 완료 알림(화면 오른쪽 아래)
nc/instance.py       중복 실행 방지·이전 버전 교체
nc/demo.py           데모 장비
web/                 화면(HTML/CSS/JS, 외부 라이브러리·웹폰트 없음 → 사내망 오프라인 동작), 아이콘
.github/workflows/   Windows EXE 빌드·테스트·검증용 아티팩트 (자동 Release 없음)
```
