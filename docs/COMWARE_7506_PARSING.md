# 7500/7506 계열 출력 형식 호환성 — v1.5.3

7506 백본의 `display device`, `display power`, `display ospf peer` 응답은
수신되지만 점검 결과가 “출력을 해석하지 못했습니다.”로 표시되는 문제가 보고됐다.
실제 운영 출력은 제공받지 않았다. 아래 변경은 제조사 공식 문서에 있는 형식으로
기존 파서의 해석 실패를 재현한 뒤 보강한 것이며, 사용자 장비의 원인 확정이나
실장비 검증 완료를 뜻하지 않는다.

## 변경 내용

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
