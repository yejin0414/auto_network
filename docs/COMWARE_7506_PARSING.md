# 7500/7506 계열 출력 형식 호환성

7506 백본의 `display device`, `display power`, `display ospf peer` 응답은
수신되지만 점검 결과가 “출력을 해석하지 못했습니다.”로 표시되는 문제가 보고됐다.
실제 운영 출력은 제공받지 않았다. 아래 변경은 제조사 공식 문서에 있는 형식으로
기존 파서의 해석 실패를 재현한 뒤 보강한 것이며, 사용자 장비의 원인 확정이나
실장비 검증 완료를 뜻하지 않는다.

## v1.5.3 변경 내용

| 명령 | 추가로 해석하는 형식 |
|---|---|
| `display device` | `Slot No. / Brd Type / Brd Status` 표, 정상 대기 보드의 `Slave` 표기, IRF의 `Chassis / Slot` 표 |
| `display power` | `Chassis N:`별 전원 상태, `Input Power` 소비전력 요약이 있는 표, `Faulty` 장애 상태 |
| `display ospf peer` | `Interface → State` 열 순서의 표, 원형 S7500에서 기본 명령이 반환하는 여러 줄 상세 이웃 정보 |

기존 S6800 표 및 `State → Interface` OSPF 표, 기존 슬롯·전원 기준값 형식은
유지한다. IRF 보드는 `섀시/슬롯`으로 구분해 서로 다른 섀시의 같은 슬롯 번호가
충돌하지 않도록 한다. 수집 명령, 접속 방식, 임계값, 설정 및 DB 구조는 바꾸지 않는다.

새 형식에서도 잘린 행, 미지원 상태, 중복 식별자, 모순된 개수, 빈 섀시·OSPF
프로세스 출력은 정상이나 “모두 사라짐”으로 단정하지 않는다. 기준값은 보존하고,
부분 출력 중 완전히 해석한 장애 항목만 별도 근거로 유지한다.

## 출처와 검증 범위

- [H3C S7500E Release 6610 장비 관리 명령](https://www.h3c.com/cn/d_201106/716357_30005_0.htm): 단독/IRF 보드 표와 전원 구역.
- [H3C S7500E 장비 관리 명령(2024)](https://www.h3c.com/en/Support/Resource_Center/EN/Switches/Catalog/S7500E/S7500E/Technical_Documents/Reference_Guides/Command_References/H3C_CR-22188/01/202409/2275338_294551_0.htm): 소비전력 요약, 전원 표와 `Faulty`.
- [H3C S7500E-XS R7178 점검 예시](https://www.h3c.com/cn/Service/Document_Software/Document_Center/Switches/Catalog/S7500E/S7500E-XS/Maintenance/Troubleshooting/H3C_S7500E-XS_TG-R7178-6W100/?CHID=211761): `Input Power`의 괄호 단위 표기.
- [H3C S7500E Release 6100 IPv4 라우팅 명령](https://wwwsg.h3c.com/cn/d_200912/658550_30005_0.htm): OSPF 표의 `Interface → State` 열 순서.
- [H3C S7500 Release 3100 라우팅 명령 §3.1.20](https://www.h3c.com/en/d_200707/207783_294551_0.htm): 기본 `display ospf peer`의 상세 형식.

테스트의 장비명·주소·보드명·수치는 합성 값이다. 파서/판정 회귀와 Mock SSH를
통한 수집 → 해석 → 이력·원문 저장을 검증하며, 실제 7506 접속 및 운영 출력
검증은 수행하지 않는다. Windows 자동 검증 결과는 해당 PR/릴리즈의 정확한
커밋에 연결된 GitHub Actions 실행 결과를 기준으로 확인한다.

## v1.5.4 후속 보완

사용자가 v1.5.3 배포 후 `display device`와 `display ospf peer`에서 같은
해석 실패를 보고했고, 장비 모델은 `7506`이라고 확인했다. 프로그램 표시 버전과
실제 명령 출력은 제공받지 않았으므로 특정 펌웨어의 원인으로 확정하지 않는다.

- 장비 표: `Subslot Num` 외에 `Subslot` 열 제목, 구형 S7500의 모델 설명 줄과
  미장착 슬롯의 `NONE / Absent / Absent / None / None` 행, `1/0`처럼 하나의
  열에 표시하는 IRF 섀시/슬롯 식별자를 지원한다. 알려진 설명 줄은 표 앞에서만
  허용하고, 행의 필드 수·미장착 값의 조합·식별자의 중복 검사는 유지한다.
- OSPF 상세 응답: 영역마다 반복되는 `Neighbors` 제목, GR 상태·MTU·Options,
  `Dead timer due in … sec`, `Neighbor is up for …`, 인증 순서·상태 변경 횟수·BFD
  필드, `DR/BDR: None`, `Mode: Null/Hold`를 해석한다. 식별자·상태·타이머 등
  필수 정보가 빠지거나 알 수 없는 행이 남으면 정상·누락 판정에 사용하지 않는다.
- 수집 중 남은 페이지 대기 표식은 정규화 전에 검사한다. 일부 페이지만 받은
  응답을 정상으로 오인하지 않고 원문을 보존하며 기준값 갱신을 막는다.

구형 S7500은 기본 `display ospf peer`가 상세 응답을 반환하지만, 추가 참고한
S7500E 문서는 상세 예시에 **`display ospf peer verbose`**를 사용한다. 새 상세
fixture는 그 문법의 파서 호환성을 검증할 뿐, 사용자 장비가 기본 명령으로 이
형식을 반환했다는 증거는 아니다. 프로그램이 보내는 점검 명령은 바꾸지 않는다.
저장된 과거 점검 결과는 자동 재해석하지 않으므로 새 버전에서 새 점검을 해야 한다.

추가 공식 출처:

- [S7500 Release 3100 시스템 유지보수 명령](https://www.h3c.com/en/d_200707/207804_294551_0.htm): 모델 설명 줄과 미장착 subslot 표기.
- [S7500 제품·교환 엔진](https://www.h3c.com/en/d_200707/207813_294551_0.htm): S7503/S7506/S7506R 및 Salience III 계열.
- [S7500E R7150 예시](https://www.h3c.com/en/Support/Resource_Center/HK/Switches/H3C_S7500E/S7500E/Technical_Documents/Configure___Deploy/Configuration_Examples/H3C_S7500E_CE-Release7150-6W100/01/201506/873300_294551_0.htm): `Subslot` 열 제목.
- [S7500E-X R7178 장비 관리 명령](https://www.h3c.com/en/d_201601/913424_294551_0.htm): 단일 열의 IRF 슬롯 식별자.
- [S7500E R6300 OSPF 구성](https://www.h3c.com/cn/d_200911/654940_30005_0.htm): 영역별 반복 제목 및 상세 응답의 추가 필드.
- [S7500E R6300 MPLS 구성](https://www.h3c.com/cn/d_200911/654971_30005_0.htm): 상세 응답의 `DR/BDR: None`.
- [S7500E-X R7178 OSPF 명령](https://www.h3c.com/en/d_201601/913471_294551_0.htm): Options 및 BFD를 포함한 상세 응답.

실제 운영 출력·운영 주소·장비 접속은 사용하지 않았으며, 합성 회귀와 Mock SSH
수집·판정·저장 테스트 및 Windows CI를 실장비 검증과 구분한다.
