# Changelog

All notable changes to this project will be documented in this file.

## [3.0.3] - 2026-09-10

### Added
- **Grok 계정 상태** — `list`에 Grok 섹션을 추가하고, 403의 사유가 주간 한도 소진(`spending-limit`)인지 인증 실패(401)인지 구분해 표시한다. 재로그인이 소용없는 한도 소진을 인증 문제로 오진하지 않는다.

### Changed
- **라이브 전용 데이터** — 일반 실행은 `LIVE` 사용량만 표시하고, 읽지 못한 공급자는 예시로 보강하지 않고 가용하지 않음으로 표시한다. `DEMO` 예시는 `--demo-only` 캡처 모드에서만 쓴다.
- **공급자 화면 정리** — 공급자별 레이아웃과 원본 공식 아이콘을 정리했다.

### Fixed
- **Codex 계정 목록 크래시** — `/backend-api/codex/usage`가 `additional_rate_limits`·`rate_limit`을 `null`로 돌려주는 계정(예: Plus)에서 `account` 목록이 `TypeError: 'NoneType' object is not iterable`로 죽었다. 누락 키와 `null` 값을 모두 방어한다.
- **Codex 인증 스냅샷 드리프트** — Codex CLI가 `~/.codex/auth.json`을 갱신할 때 회전하는 refresh token이 저장 스냅샷에 반영되지 않아, 다른 계정으로 로그인하면 이전 계정이 만료 토큰에 묶여 `codex login`을 다시 요구했다. 목록·전환 진입 시 활성 auth를 소유 계정 스냅샷에 되쓰고, 더 최신 스냅샷의 downgrade와 심볼릭 링크 스냅샷은 거부한다.
- **Codex 첫 등록 게이트** — 계정 인덱스가 없는 새 머신에서 등록 메뉴 자체가 뜨지 않아 첫 Codex 계정을 저장할 수 없던 닭-달걀 구조를 열었다.
- **macOS 릴리스 빌드 실패 보존** — 빌드 실패가 파이프라인에서 삼켜지지 않도록 종료 코드를 보존한다.

### Documentation
- `README.md`와 `README.ko.md`에 Codex 인증 스냅샷 동기화 계약(회전 토큰 보존·downgrade 거부·심볼릭 링크 거부)을 기록하고, 라이브 전용 데이터 정책과 공급자 아이콘·상표 고지를 반영했다.

## [3.0.2] - 2026-08-17

### Changed
- **전체 화면 UX 정리** — 공급자 요약 카드를 누르면 해당 상세 탭으로 이동하고, 계정이 하나뿐인 공급자의 중복 계정 칩과 LIVE-only 상태의 `DEMO 0개` 문구를 숨긴다. 다중 계정 전환 칩과 실제 DEMO fallback 표시는 유지한다.

### Fixed
- **GitHub macOS 앱 빌드 호환성** — Swift 패키지 도구 버전을 `macos-14` 릴리스 러너의 Swift 5.10에 맞추고 정적 회귀 테스트로 고정해, 검증된 `Switchboard-macos.zip`이 Release 생성 전에 반드시 빌드되도록 한다.

### Documentation
- `README.md`와 `README.ko.md`에 GitHub 릴리스의 Swift 5.10 빌드 호환성 검증을 기록했다.

## [3.0.1] - 2026-08-17

### Changed
- **메뉴바 UI 단일화** — 배포 앱에서 프로토타입용 A/B/C 비교 컨트롤을 제거하고 공급자 집중 화면을 기본으로 사용한다. 왼쪽 `전체` 항목에서 Claude·Codex·Grok·Gemini 상태를 한 번에 확인한 뒤 공급자별 상세 화면으로 이동할 수 있다.

### Fixed
- **Python 3.8 릴리스 호환성** — Codex 사용량 테스트의 context 구문을 Python 3.8 호환 `ExitStack`으로 바꾸고, 로컬 릴리스 게이트도 지원 최소 버전의 전체 테스트를 강제해 CI와 동일한 실패를 태그 전에 차단한다.

### Documentation
- `README.md`, `README.ko.md`, `prototype/switchboard-menubar/README.md`에 단일 사이드바 UI와 Python 3.8 릴리스 검증을 기록하고, 개인정보 없는 최신 `전체` 화면 캡처를 반영했다.

## [3.0.0] - 2026-08-17

### Added
- **Switchboard macOS 메뉴바 앱** — Claude, Codex, Grok, Antigravity(`agy`)의 LIVE 사용량·초기화 시각·크레딧을 한 화면에서 비교하고 남은 한도로 계정을 추천한다. 개인정보 없는 데모 화면, 무광 앱 아이콘, 로컬 설치기와 `Switchboard-macos.zip` 릴리스 산출물을 포함한다.
- **검증 가능한 공급자 전환** — Claude와 Codex는 저장 credential의 실소유자와 전환 후 readback을 확인하고, Grok은 계정별 `GROK_HOME`으로 기존 세션을 건드리지 않는 새 Terminal 세션을 연다.

### Changed
- **AGY를 Gemini 단일 진실 소스로 사용** — 레거시 Gemini CLI 계정 파일을 버리고 `agy --print /usage`와 `/credits`의 읽기 전용 결과만 표시한다. AGY에 공식 계정 전환 명령이 없어 가짜 즉시 전환은 제공하지 않는다.
- **Switchboard 브랜드와 릴리스 계약 통일** — 프로젝트·문서·앱 표면을 Switchboard로 정리하고, 태그가 현재 `main`과 일치하며 기존 버전보다 높고 전체 테스트와 앱 서명을 통과한 경우에만 GitHub Release를 생성한다.

### Fixed
- **회전형 OAuth credential 보존 강화** — Claude/Codex 전환과 토큰 갱신을 원자 저장·소유권 검증·compare-and-swap rollback으로 보호해 동시 refresh/login의 최신 one-time refresh token을 덮어쓰지 않는다.
- **앱 설치 복구** — 새 앱 복사나 서명이 실패하면 불완전한 번들을 제거하고 기존 설치가 있으면 자동 복구한다.

### Documentation
- `README.md`와 `README.ko.md`에 Switchboard 설치법, 공급자별 LIVE/전환 범위, 개인정보 없는 앱 캡처, Grok 프로필과 AGY 제한을 추가했다.

## [2.5.10] - 2026-07-19

### Changed
- **Codex 계정 레이아웃을 Claude와 통일** — 이메일을 계정 헤더 아래의 별도 DIM 줄로 이동하고, reset suffix를 양수일 때만 CYAN 시계 아이콘과 총시간 `Hh Mm` 형식으로 표시한다.

## [2.5.9] - 2026-07-19

### Changed
- **Codex 사용량 의미를 Claude와 통일** — API의 `used_percent`를 그대로 12칸 막대와 `N%`로 표시하고 `남음` 문구를 제거한다. 사용량에 따른 색상 기준도 Claude 행과 동일하게 적용한다.

## [2.5.8] - 2026-07-19

### Changed
- **Codex 사용량 표시 간소화** — 사용량 막대를 Claude와 같은 12칸으로 맞추고, 별도 Spark 주간 한도 행은 숨긴다. 다른 추가 모델 한도는 기존대로 표시한다.

## [2.5.7] - 2026-07-19

### Fixed
- **`account`의 Codex 사용량·만료 표시 불일치 수정** — 현재 계정은 저장 당시 auth 사본 대신 Codex CLI가 갱신한 live `~/.codex/auth.json`을 사용한다. 이로써 사용량 행이 누락되고 정상 토큰이 `-Nd Nh 후 만료`로 표시되던 문제를 함께 해결한다.
- **Codex `/status`와 한도 의미 통일** — API의 사용률을 남은 비율로 변환하고, 5시간·일간·주간·월간·연간 윈도우를 공식 허용 범위로 판별하며, 남은 비율과 진행 막대 색을 일치시킨다.

### Added
- live/stale auth 분리, 음수 만료 방지, 한도 윈도우·남은 비율·막대 색을 검증하는 오프라인 회귀 테스트.

## [2.5.6] - 2026-07-10

### Fixed
- **shell rc 소유권 분리** — SessionStart가 `~/.zshrc`/`~/.bashrc`를 읽거나 수정하지 않고 plugin-owned runtime fragment만 atomic/idempotent하게 보장한다. installer는 exact source block을 먼저 확인하고 symlink, Git tracked rc, 불확실한 Git 환경에서는 기존 파일을 보존한 채 fail-closed한다.
- **릴리스 무결성 강화** — Python 3.8 호환성과 세 version metadata 정합성을 CI에 고정하고, single-branch marketplace clone에서도 explicit refspec, clean/equality gate, exact release SHA, no-ff main merge와 tag 순서를 검증한다.

### Added
- 실제 symlink/tracked rc/alternate Git index, fragment replace 실패, single-branch Git checkout partial failure를 재현하는 회귀 테스트.

## [2.5.5] - 2026-07-08

### Fixed
- **`CLAUDE_CONFIG_DIR`이 설정된 세션에서 hook/alias가 엉뚱한 Keychain을 참조하던 문제** — 이 플러그인의 계정 저장소(`~/.claude/accounts`)는 `CLAUDE_CONFIG_DIR`과 무관하게 항상 고정 경로인데(`config.py`), `keychain.py`의 Keychain 조회는 `CLAUDE_CONFIG_DIR`을 반영해 서비스명이 갈린다. 커스텀 config-dir로 실행되는 세션(예: 플러그인 로드를 줄이려는 프로필 전환 스크립트)에서 SessionStart/PromptSubmit hook이 돌면, 공유 저장소에 그 프로필 전용(별도) Keychain의 토큰이 쓰여 계정이 뒤섞이는 원인이 됐다.
  - `hooks-handlers/session-start.sh` / `prompt-submit.sh`: `account_manager.py` 호출 전 `CLAUDE_CONFIG_DIR`을 명시적으로 unset
  - 터미널 alias(`_account_mgr_run`, `account`/`account-switch`/`account-list`) 생성 블록도 동일하게 unset 하도록 갱신, 마커 버전 v2 → v3 (기존 v1/v2 설치는 세션 시작 시 자동 마이그레이션, 사용자 설정 앞뒤 내용 보존)
  - `tests/test_hooks_shell.sh` 추가 — hook의 unset 동작 + v2→v3 자동 교체 + idempotency 회귀 테스트 (bash, 12케이스)

## [2.5.4] - 2026-07-08

### Fixed
- **credential 교차 오염 수정** — switch나 `/login` 직후 `~/.claude.json`(oauthAccount)과 Keychain이 잠깐 어긋나는 desync 윈도우에, hook이 Keychain의 새 계정 토큰을 이전 계정 슬롯에 저장하던 문제 (2026-07-08 실사고: gmail 토큰이 soop 슬롯에 저장되어 두 계정이 동일 사용량으로 표시됨)
  - `owner.py` 신설: `/api/oauth/profile`로 토큰 실소유 계정(uuid/email/org)을 확인, 토큰 해시 키로 캐시 (신규 토큰당 API 1회)
  - Keychain credential을 슬롯 파일에 쓰는 5개 경로 전부에 소유자 검증 가드 추가: `cmd_refresh_all`(현재 계정 저장), `cmd_refresh_expiring`(Keychain→파일 동기화), `_auto_migrate`(credential 복구), `cmd_add`(토큰만 갱신 + 신규 저장), `cmd_auto_add`
  - 소유자 불일치 또는 확인 불가 시 저장을 스킵하고 로그/메시지 출력 (fail-closed — 다음 hook에서 자동 재시도)
  - 동일 이메일이 여러 org에 속한 경우 org uuid까지 비교하여 org 단위 슬롯 구분 유지
- **Max20 계정이 `Max5`로 표시되던 문제** — `_fetch_usage_from_api`의 planName 계산이 `subscriptionType: "max"`(숫자 없음)일 때 rateLimitTier를 무시하고 무조건 Max5로 표기. `detect_plan_from_credential`과 동일하게 rateLimitTier로 세분화
- **계정 삭제 감사 로그 부재** — `account remove`가 실행돼도 누가/언제/어떤 상태의 계정을 지웠는지 기록이 없어 사후 추적이 불가능했음 (2026-07-08: `dlwlgns1240_soop` 계정 항목이 원인 불명으로 두 차례 삭제됨). 삭제 확정 직후 계정 식별자·이메일·조직·credential 실존 여부·actor 컨텍스트(대화형 여부, 부모 프로세스 id, 세션 id)를 `token-refresh.log`에 WARN으로 기록 (Claude/Codex 삭제 경로 모두)

### Added
- `tests/test_owner_guard.py` — 소유자 검증 단위 테스트 + 교차 오염 시나리오 회귀 테스트 (오프라인, 전부 mock)
- `tests/test_remove_audit.py` — 계정 삭제 감사 로깅 회귀 테스트 (반쪽 상태 삭제 시나리오 포함)
- cc-fleet single-owner refresh (`_cc_fleet_accounts`) — 이전 릴리즈 이후 설치 캐시에만 존재하던 핫패치를 git 이력에 포팅 (컨테이너가 refresh owner로 lease 중인 계정은 mac 쪽 자동 토큰 회전을 skip해 회전 충돌 방지)

## [2.5.3] - 2026-05-31

### Fixed
- **Codex 사용량(`남은 %`) 미표시 수정** — `fetch_codex_usage`의 `/backend-api/codex/usage` 호출이 `403 Forbidden`으로 차단되어 `list` / `switch` UI에 사용량이 안 뜨던 문제. OpenAI WAF가 `originator` 헤더 없는 요청을 봇으로 간주해 차단함이 원인. codex CLI와 동일하게 `originator: codex_cli_rs` 헤더를 추가해 통과.

## [2.5.2] - 2026-05-31

### Fixed
- **Codex 토큰 만료 오표시 수정** — `account switch` / `list` UI에서 정상 작동하는 Codex 계정이 `⚠만료`로 잘못 표시되던 문제. `get_codex_token_status`가 저장된 사본(`accounts/auth_{id}.json`)의 오래된 `last_refresh` + 240h 고정 윈도우를 기준으로 판정해, Codex CLI가 실제로는 토큰을 갱신했는데도 만료로 표시되던 괴리.
  - 현재 활성 계정이면 `~/.codex/auth.json`(Codex CLI가 자동 갱신)을 기준으로 판정
  - 임의의 240h 윈도우 대신 access_token JWT의 실제 `exp`를 사용 (exp 없으면 기존 `last_refresh + 240h`로 폴백)

## [2.5.1] - 2026-05-13

### Removed
- **v2.5.0의 Long-lived OAuth token 지원 전면 revert** — `claude setup-token`이 발급하는 토큰은 `user:inference` scope만 가지고 `user:sessions:claude_code` scope가 없어 **인터랙티브 Claude Code 세션을 시작할 수 없음** (Anthropic 정책상 제한). 등록·switch는 가능하지만 활성화 시 "Not logged in" 표시되어 실용성 없음.
- 제거된 항목:
  - `/account:add`의 Long-lived 분기, `cmd_add_long_lived` 함수
  - `/account:export-token` 명령
  - `/account:switch --shell-export` 플래그, `build_shell_export_lines` 함수
  - `list` / `switch` UI의 `[CI]` 배지 + D-day 표시
  - SessionStart hook의 long-lived 만료 임박 경고
  - `refresh-all` / `refresh-expiring` / `check`의 long-lived skip 분기
  - zsh wrapper v4 → v2 (Codex 시점 기본)
  - `claude_account_manager/long_lived.py`, `commands/export_token_cmd.py`, 관련 테스트 5개

### Note
CI/스크립트 환경에서 `claude -p "..."` 같은 비인터랙티브 호출이 필요하면 그대로 `CLAUDE_CODE_OAUTH_TOKEN` 환경변수를 export하여 사용 가능 (이 플러그인 외부에서 직접 관리).

## [2.5.0] - 2026-05-13

### Added
- **Long-lived OAuth token 지원** — `claude setup-token`이 발급하는 1년 유효 토큰을 일반 계정과 동일하게 등록·전환·관리
  - `/account:add` 진입 시 `[2] Long-lived 토큰 등록` 선택지 추가
  - `/account:export-token <id>` 명령 신설 — `export CLAUDE_CODE_OAUTH_TOKEN='...'` stdout 출력
  - `/account:switch --shell-export` 플래그 — long-lived 활성화 시 env 라인 자동 emit, 일반 OAuth로 복귀 시 `unset` 라인 emit
  - `list` / `switch` UI에 `[CI]` 배지 + D-day 만료 표시 (inference-only scope라 usage API skip)
  - SessionStart hook이 D-7 이내 만료 임박 long-lived 토큰 stderr 경고
  - `refresh-all` / `refresh-expiring` / `check`가 `tokenType=="long-lived"` 계정 자동 skip
- zsh wrapper v4 — `account switch <id>` 와 `account-switch <id>` 둘 다 `CLAUDE_CODE_OAUTH_TOKEN` env 자동 동기화 (분기 로직을 `_account_mgr_run` 한 곳으로 통합)

### Fixed
- `switch --shell-export`가 동일 계정 재선택 시에도 env 라인 출력 (새 셸 첫 활성화 시 env 동기화 보장)
- `switch` 대화형 선택 UI가 long-lived 토큰으로 `/api/oauth/usage` 호출하여 INVALID 표시되던 회귀

### Documentation
- README.md / README.ko.md에 "Long-lived OAuth Token (CI/Scripts)" 섹션 추가
- `docs/superpowers/specs/` 및 `docs/superpowers/plans/` 에 설계·구현 문서 보관
- `scripts/poc_long_lived.sh` POC 검증 스크립트

## [0.1.0] - 2026-02-01

### What's changed

**Added**
- UserPromptSubmit hook으로 만료 임박(1시간 이내) 토큰 자동 갱신
- 세션 중간에 토큰 만료 방지 기능

**Fixed**
- README Mermaid 다이어그램 렌더링 오류 수정

**Improved**
- Claude 세션 내 설치 방법 안내 추가
- CLAUDE.md에 OAuth 상세 정보 추가

### Commits

```
03676cf fix: Mermaid syntax error and add session install guide
```

### Full Changelog

https://github.com/lee-ji-hoon/claude-multi-account-manager/compare/v0.0.1...v0.1.0

---

## [0.0.1] - 2026-02-01

### What's changed

**Added**
- Initial release of Claude Code multi-account manager plugin
- Multiple account management without logout (`/account:add`, `/account:switch`, `/account:remove`)
- Real-time usage monitoring with visual progress bars
- Automatic token refresh for all accounts on session start
- Plan auto-detection (Free / Pro / Team / Max5 / Max20)
- SessionStart hook for automatic account registration
- macOS Keychain integration for secure token storage

**Technical Details**
- OAuth token refresh via `platform.claude.com/v1/oauth/token`
- Refresh token rotation (single-use tokens)
- Token validity: 8 hours (28800 seconds)

### Commits

```
b360843 feat: Initial release - Claude Code multi-account manager plugin
deef16d fix: Correct SessionStart hook configuration format
6121cff docs: Update installation to plugin-based approach
eb40c43 docs: Add marketplace installation method
404c682 refactor: Simplify command structure and add marketplace support
03c0a04 feat: Always refresh all account tokens on session start
efad03b fix: Use correct OAuth endpoint for token refresh
e8dd30c docs: Add architecture documentation with diagrams
092bb67 docs: Add both dialog and terminal installation methods
2c4c8a4 docs: Update README with new command structure
b96b08b docs: Simplify README with Mermaid diagram
```

### Full Changelog

https://github.com/lee-ji-hoon/claude-multi-account-manager/commits/main
