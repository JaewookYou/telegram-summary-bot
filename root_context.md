META: { project: "telegram-summary-bot", version: "0.2", mode: "TOOL_DEV", created: "2025-08-20T00:00:00Z", updated: "2025-08-21T01:45:00Z" }
ARTIFACTS:
- file: app/run.py
- file: app/telegram_client.py
- file: app/formatter.py
- file: app/dedup.py
- file: app/llm.py
- file: app/storage.py
- file: app/config.py
- file: requirements.txt
- file: README.md
- file: migrate_db.py
- file: data/db.sqlite3.backup
FINDINGS:
- [F-001] SimHash(64-bit) 기반 근사 중복 제거를 구현(app/dedup.py)
- [F-002] Telethon(NewMessage 이벤트, 채널 필터 지원)로 수집(app/telegram_client.py)
- [F-003] LLM(OpenAI) JSON 구조화 분석(요약/중요도/카테고리/태그)(app/llm.py)
- [F-004] 개인 채널 전송용 HTML 포맷(원문 링크 포함)(app/formatter.py)
- [F-005] SQLite 저장 및 중복/분석 메타 유지(app/storage.py)
- [F-006] Telegram 메시지 ID 오버플로우 발생 (SQLite INTEGER 범위 초과)
- [F-007] 중요도 필터링으로 인한 메시지 누락 (important_threshold=medium)
- [F-008] Forward 메시지 처리 로직 미구현 (원본 메시지와 중복 처리 가능성)
HYPOTHESES:
- [H-001] 해밍거리 ≤ 9, 최근 6시간 윈도우에서 SimHash로 실사용 중복을 충분히 필터링 가능
- [H-002] BIGINT 스키마로 Telegram 메시지 ID 오버플로우 해결 가능
- [H-003] important_threshold=low로 설정 시 더 많은 메시지 전달 가능
- [H-004] Forward 메시지의 원본 정보 추출로 중복 제거 및 링크 정확성 향상 가능
EXPERIMENTS:
- [E-001] venv 생성 및 의존성 설치 → `pip install -r requirements.txt` 성공 시 OK
- [E-002] 최초 실행 시 Telethon 로그인(OTP) 완료되면 세션 파일 생성됨
- [E-003] SQLite 마이그레이션 실행 → BIGINT 스키마 적용 성공
- [E-004] 중요도 임계값 "low"로 변경 → 더 많은 메시지 전달 예상
- [E-005] Forward 메시지 감지 함수 구현 → 원본 정보 추출 성공
ATTACK/DEFENSE_PLAN:
- LLM 호출량 증가 시 임계값/전처리로 비용 제어, 필요 시 배치 다이제스트로 전송 횟수 축소
- 메시지 스팸 방지를 위한 키워드 기반 필터링 추가 고려
DECISIONS:
- [D-001] 1차 버전에서는 임베딩 없이 SimHash 사용(간단/저비용). 필요 시 Upstage 임베딩 확장
- [D-002] Userbot(Telethon) 방식 채택(원본 링크·개인 채널 전송 용이)
- [D-003] SQLite 스키마를 BIGINT로 변경하여 오버플로우 해결
- [D-004] 기본 중요도 임계값을 "low"로 설정하여 메시지 누락 최소화
- [D-005] Forward 메시지 처리 시 원본 정보를 기준으로 중복 체크 및 링크 생성
TODO:
- [T-001] Upstage.ai 임베딩 연동 옵션(군집/중복 고도화)
- [T-002] 중요도 가중치·전처리 규칙 튜닝(스팸/광고 억제)
- [T-003] 메시지 ID 범위 검증 로직 추가
- [T-004] Forward 메시지 전용 설정 옵션 추가
- [T-005] 원본 채널 정보 캐싱 최적화
OPEN_QUESTIONS:
- [Q-001] 수집 소스 채널 확정(SOURCE_CHANNELS)
- [Q-002] 개인 전용 전송 채널(AGGREGATOR_CHANNEL) 결정 및 권한 확인
- [Q-003] 스팸 메시지 필터링 기준 최적화
- [Q-004] Forward 메시지 처리 우선순위 (원본 vs 현재 채널)
APPENDIX: []
AUDIT_LOG:
- 2025-08-20T00:00:00Z: 프로젝트 스캐폴딩 및 핵심 모듈 생성(app/*, requirements.txt)
- 2025-08-21T01:45:00Z: SQLite BIGINT 마이그레이션 완료, 중요도 임계값 "low"로 변경
- 2025-08-21T02:00:00Z: Forward 메시지 처리 로직 구현 완료 (원본 정보 추출, 중복 체크, 링크 생성)
- 2025-08-21T02:15:00Z: README.md 업데이트 완료 (v0.2 기능 반영, 트러블슈팅 확장)


