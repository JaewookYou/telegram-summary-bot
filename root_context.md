META: { project: "telegram-summary-bot", version: "0.1", mode: "TOOL_DEV", created: "2025-08-20T00:00:00Z" }
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
FINDINGS:
- [F-001] SimHash(64-bit) 기반 근사 중복 제거를 구현(app/dedup.py)
- [F-002] Telethon(NewMessage 이벤트, 채널 필터 지원)로 수집(app/telegram_client.py)
- [F-003] LLM(OpenAI) JSON 구조화 분석(요약/중요도/카테고리/태그)(app/llm.py)
- [F-004] 개인 채널 전송용 HTML 포맷(원문 링크 포함)(app/formatter.py)
- [F-005] SQLite 저장 및 중복/분석 메타 유지(app/storage.py)
HYPOTHESES:
- [H-001] 해밍거리 ≤ 9, 최근 6시간 윈도우에서 SimHash로 실사용 중복을 충분히 필터링 가능
EXPERIMENTS:
- [E-001] venv 생성 및 의존성 설치 → `pip install -r requirements.txt` 성공 시 OK
- [E-002] 최초 실행 시 Telethon 로그인(OTP) 완료되면 세션 파일 생성됨
ATTACK/DEFENSE_PLAN:
- LLM 호출량 증가 시 임계값/전처리로 비용 제어, 필요 시 배치 다이제스트로 전송 횟수 축소
DECISIONS:
- [D-001] 1차 버전에서는 임베딩 없이 SimHash 사용(간단/저비용). 필요 시 Upstage 임베딩 확장
- [D-002] Userbot(Telethon) 방식 채택(원본 링크·개인 채널 전송 용이)
TODO:
- [T-001] Upstage.ai 임베딩 연동 옵션(군집/중복 고도화)
- [T-002] 중요도 가중치·전처리 규칙 튜닝(스팸/광고 억제)
OPEN_QUESTIONS:
- [Q-001] 수집 소스 채널 확정(SOURCE_CHANNELS)
- [Q-002] 개인 전용 전송 채널(AGGREGATOR_CHANNEL) 결정 및 권한 확인
APPENDIX: []
AUDIT_LOG:
- 2025-08-20T00:00:00Z: 프로젝트 스캐폴딩 및 핵심 모듈 생성(app/*, requirements.txt)


