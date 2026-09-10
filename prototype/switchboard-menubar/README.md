# Switchboard 메뉴바 앱

> 로컬 로그인 메타데이터와 Claude/Codex 사용량 API를 읽되, 토큰 값은 UI나 스냅샷에 노출·저장하지 않습니다.

macOS 메뉴바에서 네 AI CLI 계정의 상태를 보고, 지원되는 계정은 안전하게 전환하는 앱입니다.

질문: **네 공급자와 여러 계정을 메뉴바의 작은 공간에서 어떻게 가장 빠르고 정확하게 파악하고 전환해야 하는가?**

세 가지 구조를 앱 안의 `A / B / C` 선택기로 바꿔 볼 수 있습니다.

- A — 전체 현황: 네 공급자를 한 화면에서 비교
- B — 공급자 집중: 한 공급자의 사용량과 계정에 집중
- C — 빠른 전환: 상태보다 계정 전환 속도를 우선

## 결정

2026-08-17 사용자 검토에서 **B — 공급자 집중**을 실제 앱의 기본 정보 구조로 선택했습니다. 공급자별 사용량, 인증 상태, 계정 전환 가능 여부를 작은 메뉴바 팝오버 안에서 가장 명확하게 설명하기 때문입니다. A와 C는 비교 근거로만 남깁니다.

B 화면은 공급자마다 같은 구조를 유지합니다.

- 두 개의 한도 슬롯: 공급자가 한도 하나만 주면 두 번째 슬롯은 `공급자 미제공`으로 표시
- 추천 계정: 인증이 정상인 계정 중 일간/주간 한도를 가중 비교하고, 곧 만료되는 크레딧을 보조 신호로 사용
- 계정별 추가 혜택: 공급자가 실제로 반환한 Codex 리셋 크레딧 개수와 AGY 크레딧 잔액
- Claude/Codex 전환: `정상`인 저장 계정만 전환하고, provider-switch CLI 결과 뒤 fresh live snapshot readback까지 일치할 때만 성공 표시
- Grok: `GROK_HOME` 프로필이 실제로 설정돼 있을 때만 기존 세션을 건드리지 않는 `새 Grok 세션 열기` 동선을 표시
- AGY/Gemini: 즉시 전환은 지원하지 않으며, 사용량 새로고침 및 CLI 재인증 안내만 표시

앱 번들의 `live_snapshot.py`가 allowlist JSON을 통해 Claude/Codex usage API, Grok 로컬 `/usage`, Antigravity의 `/usage`·`/credits`를 읽습니다. 레거시 Gemini CLI 계정 파일은 읽지 않습니다. 자격 증명 값은 Swift 앱이나 스냅샷에 포함하지 않습니다. 일반 실행은 LIVE 데이터만 사용하므로 사용량을 읽을 수 없는 공급자는 가용하지 않음으로 표시하며, 비교용 DEMO 계정을 섞지 않습니다. 익명 예시 데이터는 명시적인 `--demo-only`에서만 사용합니다.

공급자가 반환한 단위와 이름은 그대로 보존하고, 응답에 없는 한도·크레딧은 추정하지 않습니다. 이전 성공값은 재사용하지 않으므로 조회가 실패하면 해당 LIVE 사용량을 가용하지 않은 상태로 표시합니다.

## 실행

```bash
cd prototype/switchboard-menubar
./run.sh
```

`run.sh`는 빌드 후 GPT Image로 제작한 무광 Switchboard 아이콘을 포함한 `.build/Switchboard.app`을 만들고 실행합니다. 앱 종료는 팝오버 하단의 `종료`를 누릅니다.

배포 UI는 공급자 집중 화면 하나를 사용합니다. 왼쪽 `전체`에서 네 공급자의
요약을 함께 보고, 공급자 항목을 누르면 계정별 상세·전환 화면으로 이동합니다.
프로토타입 비교용 A/B/C 선택기는 배포 앱에 포함하지 않습니다.

자동 UI 검증이나 큰 화면 미리보기가 필요하면 `./run.sh --preview`로 같은 콘텐츠를 일반 창에도 띄울 수 있습니다. 캡처에는 반드시 아래처럼 `--demo-only`를 함께 사용합니다. 이 모드는 live snapshot 실행 자체를 생략하고 익명 예시 데이터만 표시합니다.

```bash
./run.sh --preview --demo-only
```

상태 읽기는 실제 데이터입니다. Claude/Codex는 `python3 account_manager.py switch-provider <provider> <account-id> --json`을 백그라운드에서 실행하고, 다시 읽은 live snapshot의 활성 ID가 일치할 때만 성공으로 표시합니다. Grok의 웹 UI에 보이는 리셋 가능 여부·만료일은 공식 로컬 API가 확인되기 전까지 `알 수 없음 · 웹에서 확인/적용`으로만 안내합니다. 앱은 리셋을 자동 적용하거나 크레딧을 구매하지 않습니다.

## 설치

```bash
cd prototype/switchboard-menubar
./install.sh
open "$HOME/Applications/Switchboard.app"
```

`install.sh`는 먼저 번들을 빌드하고 `~/Applications/Switchboard.app`에 설치합니다. 기존 앱은 같은 디렉터리에 시간표시 백업으로 이동합니다. 실행 없이 CI 산출물만 만들려면 다음을 사용합니다.

```bash
./run.sh --build-only
ditto -c -k --sequesterRsrc --keepParent .build/Switchboard.app Switchboard-macos.zip
```
