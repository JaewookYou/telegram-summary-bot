# telegram-summary-bot

여러 텔레그램 코인 채널의 메시지를 수집해 중복 제거, 중요도 분류, 태그 부여, 요약 후 개인 전용 채널로 가독성 좋게 재전송합니다. 각 메시지에는 원문으로 이동 가능한 링크가 포함됩니다.

**🚀 최신 업데이트**: 임베딩 기반 중복 제거, 돈 버는 정보 분석, 안정성 대폭 개선

## 주요 기능
- **LLM 분석**: 요약/중요도(low/medium/high)/카테고리/태그(JSON 응답)
- **중복 제거**: Upstage.ai 임베딩 벡터 + 코사인 유사도 기준, 최근 N분 윈도우 내 의미적 중복 드랍
- **Forward 메시지 처리(강화)**: Telegram 스펙 기반(`fwd_from` 우선, `from_id/saved_from_peer/channel_post`)으로 원본 메시지 정보 추출 → 정확한 중복 체크/원문 링크 생성
- **안정적인 메시지 수신**: 폴링 방식으로 실시간 이벤트 핸들러 제한 우회, 30초 간격으로 모든 채널 메시지 확인
- **방송 채널 + 메가그룹 지원**: `broadcast` 채널과 `megagroup` 채널 모두 모니터링
- **댓글/토픽 스레드 무시**: 채널 본문만 처리, 댓글/연동 대화방/토픽 메시지는 무시
- **원문 일부 동봉**: 재전송 시 요약 + 원문 400자 스니펫 동봉, 원문 링크 버튼 포함
- **저장소**: SQLite BIGINT 스키마(대용량 메시지/채널 ID 안전)
- **상세 로깅**: 콘솔 + 회전 파일 로그 `logs/app.log`, 메시지 전용 `logs/messages.log`, 에러 전용 `logs/error.log`
- **룰 기반 중요도 부스팅**: 이벤트/추첨/에어드랍 등 키워드 포함 시 중요도 상향
- **이미지 OCR**: 메시지에 포함된 이미지에서 텍스트 추출
- **링크 콘텐츠 분석**: 메시지 내 링크의 웹페이지 내용 분석

## 프로젝트 구조
```
telegram-summary-bot/
├── app/                    # 메인 애플리케이션 코드
│   ├── __main__.py        # 실행 진입점
│   ├── run.py             # 메인 런루프 (폴링 방식 메시지 수신)
│   ├── telegram_client.py # Telegram 클라이언트 (broadcast/megagroup 판별)
│   ├── llm.py             # OpenAI LLM 분석
│   ├── dedup.py           # 중복 제거 (SimHash)
│   ├── formatter.py       # HTML 메시지 포맷(원문 스니펫/링크)
│   ├── storage.py         # SQLite 저장소
│   ├── config.py          # 설정 관리
│   ├── logging_utils.py   # 로깅 설정
│   ├── rules.py           # 중요도 부스팅 룰
│   ├── image_processor.py # 이미지 OCR 처리
│   └── link_processor.py  # 링크 웹 스크래핑
├── tools/                 # 유틸리티 도구들
├── data/                  # 데이터베이스 및 백업
├── logs/                  # 로그 파일들
│   ├── YYYY-MM-DD/       # 일자별 로그 디렉터리
│   │   ├── app.log       # 메인 애플리케이션 로그
│   │   ├── messages.log  # 메시지 처리 전용 로그
│   │   ├── sent_messages.log # 전송된 메시지 전용 로그
│   │   └── error.log     # 에러 전용 로그
│   └── app.log           # 기존 로그 (하위 호환성)
├── requirements.txt       # Python 의존성
├── README.md             # 프로젝트 문서
└── .env                  # 환경 변수 (git 제외)
```

## 구성 요소
- **수집**: 폴링 방식 메시지 수신 (30초 간격)
  - `chat_filters`에는 방송 채널과 메가그룹의 peer_id 포함
  - 실시간 이벤트 핸들러 제한을 우회하여 안정적인 메시지 수신
- **분석**: `app/llm.py` OpenAI Chat Completions(JSON 강제)
- **중복**: `app/embedding_client.py` Upstage.ai 임베딩 벡터 + 코사인 유사도
- **포맷**: `app/formatter.py` HTML 메시지 빌드(요약+원문 스니펫+원문 링크)
- **저장**: `app/storage.py` SQLite 스키마/CRUD
- **로깅**: `app/logging_utils.py`(콘솔+파일, 회전, 메시지 전용 로그)
- **룰**: `app/rules.py`(이벤트/에어드랍 중요도 부스팅)
- **이미지**: `app/image_processor.py`(OCR 텍스트 추출)
- **링크**: `app/link_processor.py`(웹페이지 콘텐츠 분석)

## 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 환경 변수(.env)
필수 항목만 예시합니다.
```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_SESSION=telegram_session

# 방송 채널과 메가그룹 모두 지원 (@username 또는 -100...)
SOURCE_CHANNELS=@coinfeed,@defi_alpha,-1001234567890

# 개인 채널 또는 'me' (Saved Messages)
AGGREGATOR_CHANNEL=@my_private_feed

# 중요 채널 (돈버는 정보 또는 high 중요도 메시지 중복 전송)
IMPORTANT_CHANNEL=@arang_summary_important

# 봇 설정 (개인 DM 알림용)
BOT_TOKEN=your bot token
PERSONAL_CHAT_ID=your_personal_chat_id_here

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Upstage.ai 임베딩 API
UPSTAGE_API_KEY=up_nkINy3WXUkUKPNbWG0td0i0phGaiL

IMPORTANT_THRESHOLD=low
DEDUP_SIMILARITY_THRESHOLD=0.85
DEDUP_RECENT_MINUTES=360
SQLITE_PATH=data/db.sqlite3
```

## 실행
```bash
python -m app
```
처음 실행 시 Telegram 로그인(OTP) 필요할 수 있습니다.

## 동작 흐름(요약)
1) **폴링 방식 메시지 수신**: 30초 간격으로 모든 모니터링 채널 확인
2) **채널 필터링**: 방송 채널과 메가그룹만 처리
3) **Forward 감지/원본 정보 추출**: 원문 링크/중복 기준 확정
4) **텍스트 임베딩**: Upstage.ai 임베딩 벡터 → 의미적 중복 드랍
5) **OpenAI 분석**: 요약/중요도/카테고리/태그
6) **룰 부스팅**: 임계값 미만은 저장만, 이상은 전송
7) **전송**: 요약 + 원문 일부(400자) + 링크 + 포워드 정보
8) **결과 저장**: SQLite

## 로깅 팁
```bash
# 일자별 로그 확인 (예: 2025-08-21)
tail -f logs/2025-08-21/app.log
tail -f logs/2025-08-21/messages.log
tail -f logs/2025-08-21/sent_messages.log

# 전송된 메시지만 확인
tail -f logs/$(date +%Y-%m-%d)/sent_messages.log

# 폴링 메시지 수신 확인
tail -f logs/$(date +%Y-%m-%d)/app.log | grep -E "폴링|🔍|📨|✅|❌"

# 특정 채널 메시지 확인
tail -f logs/$(date +%Y-%m-%d)/app.log | grep -E "emperorcoin|-1001325732918"

# 전송 성공/실패 확인
tail -f logs/$(date +%Y-%m-%d)/app.log | grep -E "전송 성공|전송 실패"

# 돈 버는 정보가 있는 메시지만 확인
tail -f logs/$(date +%Y-%m-%d)/sent_messages.log | grep "MONEY_INFO"
```

## 해결된 문제들
- **메시지 수신 문제**: Telethon 실시간 이벤트 핸들러 제한을 폴링 방식으로 해결
- **채널 접근 권한**: 모든 모니터링 채널의 접근 권한과 메시지 읽기 권한 확인
- **메시지 처리 오류**: EventWrapper 클래스로 메시지 객체를 이벤트 객체로 래핑하여 해결
- **중요도 임계값 버그**: `low` 중요도 메시지도 정상 전송되도록 수정
- **상세 로깅**: 메시지 버림 이유와 처리 과정을 상세히 로깅

## 최근 업데이트 (v0.4)
- **폴링 방식 메시지 수신**: 실시간 이벤트 핸들러 제한 우회
- **방송 채널 + 메가그룹 지원**: 더 많은 채널 타입 지원
- **상세 로깅 시스템**: 메시지 전용 로그 파일 추가
- **이미지 OCR**: 메시지 이미지에서 텍스트 추출
- **링크 콘텐츠 분석**: 웹페이지 내용 분석
- **메시지 처리 안정성**: EventWrapper 클래스로 안정적인 메시지 처리
- **채널 접근 권한 테스트**: 봇 시작 시 모든 채널 접근 권한 확인

## 알려진 이슈
- **링크 처리 오류**: 일부 웹사이트에서 `Session.get()` 오류 발생 (기능에 영향 없음)
- **이미지 처리 지연**: 대용량 이미지 처리 시 시간 소요

## 라이선스
- 개인 사용 목적 예제. 상업/배포 시 각 API 약관/요금/정책을 준수하세요.