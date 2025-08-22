# telegram-summary-bot

## 채널
- 중요도 높음·이벤트/에어드랍 알림: [@arang_summary_important](https://t.me/arang_summary_important)
- 모든 메시지 스트림: [@arang_summary](https://t.me/arang_summary)

여러 텔레그램 코인 채널의 메시지를 수집해 중복 제거, 중요도 분류, 태그 부여, 요약 후 개인 전용 채널로 가독성 좋게 재전송합니다. 각 메시지에는 원문으로 이동 가능한 링크가 포함됩니다.

**🚀 최신 업데이트**: 최초/재시작 시 각 채널의 최신 메시지 ID 스냅샷 후 그 이후만 분석(백필 없음), SOURCE_CHANNELS 동적 반영 시 @username → 숫자 peer id 정규화, channel_last_message_ids datatype mismatch 해결, Bot API 권한 기반 순수 방송 채널만 모니터링, 제거된 채널 중복 로딩 방지, 메시지 작성시간 포함

## 주요 기능
- **LLM 분석**: 요약/중요도(low/medium/high)/카테고리/태그/돈버는 정보 분석(JSON 응답)
- **중복 제거**: Upstage.ai 임베딩 벡터 + 코사인 유사도 기준, 최근 N분 윈도우 내 의미적 중복 드랍
- **Forward 메시지 처리(강화)**: Telegram 스펙 기반(`fwd_from` 우선, `from_id/saved_from_peer/channel_post`)으로 원본 메시지 정보 추출 → 정확한 중복 체크/원문 링크 생성
- **안정적인 메시지 수신**: 폴링 방식으로 실시간 이벤트 핸들러 제한 우회, 30초 간격으로 모든 채널 메시지 확인
- **정확한 채널 필터링**: Bot API 권한 기반으로 순수 방송 채널만 모니터링, 채팅 기능이 있는 채널/그룹 자동 제거
- **댓글/토픽 스레드 무시**: 채널 본문만 처리, 댓글/연동 대화방/토픽 메시지는 무시
- **원문 일부 동봉**: 재전송 시 요약 + 원문 400자 스니펫 동봉, 원문 링크 버튼 포함
- **포함된 링크 표시**: 메시지에 포함된 모든 링크를 요약 전송 시 함께 표시
- **저장소**: SQLite BIGINT 스키마(대용량 메시지/채널 ID 안전)
- **상세 로깅**: 콘솔 + 회전 파일 로그 `logs/app.log`, 메시지 전용 `logs/messages.log`, 에러 전용 `logs/error.log`
- **룰 기반 중요도 부스팅**: 이벤트/추첨/에어드랍 등 키워드 포함 시 중요도 상향
- **이미지 OCR**: 메시지에 포함된 이미지에서 텍스트 추출 (안정성 강화)
- **링크 콘텐츠 분석**: Playwright 기반 브라우저 렌더링으로 403 우회 및 JavaScript 실행 지원
- **돈버는 정보 별도 저장**: 돈버는 정보가 포함된 메시지를 별도 테이블에 저장하여 후속 처리 가능
- **중요 채널 중복 전송**: high 중요도 메시지를 별도 중요 채널로 중복 전송
- **봇 개인 DM 알림**: 모든 전송된 메시지에 대해 개인 DM으로 즉시 알림
- **중요 봇 분리 전송**: medium 이상 + 돈버는 정보 메시지를 별도 봇으로 분리 전송
- **메시지 중복 처리 방지**: 폴링 방식만 사용하여 메시지 중복 처리 해결
- **이벤트 상품 정보 표시**: 이벤트/에어드랍/프로모션 메시지에서 상품/보상 정보 자동 추출 및 표시
- **포워딩 메시지 중복 제거 강화**: 텍스트 해시 기반 정확한 중복 제거, 2단계 중복 제거 시스템
- **프로그램 재시작 시 중복 처리 방지**: 데이터베이스 기반 메시지 처리 상태 추적, 효율적인 폴링 방식
- **포워딩 메시지 원본 채널 자동 추가**: 포워딩된 메시지의 원본 채널을 자동으로 모니터링 대상에 추가
- **SOURCE_CHANNELS 동적 최신화**: polling할 때마다 SOURCE_CHANNELS 최신화, 실시간 채널 관리
- **Bot API 권한 기반 채널 필터링**: `can_send_messages`, `join_to_send_messages` 권한으로 정확한 채팅 기능 판단
- **순수 방송 채널만 모니터링**: 채팅 기능이 있는 채널/그룹은 자동으로 .env에서 제거
- **제거된 채널 중복 로딩 방지**: 메모리에 제거된 채널 목록 유지하여 중복 처리 방지
- **@username 형태 chat_id 처리**: @username 형태의 chat_id를 정확한 숫자 ID로 변환하여 처리
- **메시지 작성시간 정보 포함**: 원본/포워드 작성시간을 전송 메시지에 포함
- **초기 오프셋(최신 기준)**: DB 비어있거나 재시작 시 각 채널의 현재 최신 메시지 ID를 기록하고 그 이후만 처리(백필 없음)

## 프로젝트 구조
```
telegram-summary-bot/
├── app/                    # 메인 애플리케이션 코드
│   ├── __main__.py        # 실행 진입점
│   ├── run.py             # 메인 런루프 (폴링 방식 메시지 수신, 정확한 채널 필터링)
│   ├── telegram_client.py # Telegram 클라이언트 (Bot API 권한 기반 채널 타입 판별)
│   ├── llm.py             # OpenAI LLM 분석
│   ├── dedup.py           # 중복 제거 (SimHash)
│   ├── formatter.py       # HTML 메시지 포맷(원문 스니펫/링크/포함된 링크)
│   ├── storage.py         # SQLite 저장소 (money_messages 테이블 포함)
│   ├── config.py          # 설정 관리 (remove_source_channel 함수 포함)
│   ├── logging_utils.py   # 로깅 설정
│   ├── rules.py           # 중요도 부스팅 룰
│   ├── image_processor.py # 이미지 OCR 처리 (안정성 강화)
│   ├── link_processor.py  # Playwright 기반 링크 웹 스크래핑
│   ├── bot_notifier.py    # 봇 개인 DM 알림 시스템
│   └── money_message_processor.py # 돈버는 정보 메시지 처리 유틸리티
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
├── root_context.md       # 프로젝트 상태 및 의사결정 기록
└── .env                  # 환경 변수 (git 제외)
```

## 구성 요소(핵심)
- **수집**: 폴링(30s), 순수 방송 채널만 모니터링, 동적 채널 추가 시 최신 ID 스냅샷
- **중복 제거**: 텍스트 해시 + 임베딩 유사도(Upstage.ai)
- **분석/전송**: OpenAI 분석 → 요약/분류 후 개인 채널로 전송(원문 링크 포함)
- **채널 관리**: `app/config.py`(remove_source_channel 함수로 .env 파일 자동 수정)

## 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

# Playwright 브라우저 설치
playwright install
```

## 환경 변수(.env)
필수 항목만 예시합니다.
```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_SESSION=telegram_session

# 순수 방송 채널만 지원 (@username 또는 -100...)
# 채팅 기능이 있는 채널/그룹은 자동으로 제거됨
SOURCE_CHANNELS=@coinfeed,@defi_alpha,-1001234567890

# 개인 채널 또는 'me' (Saved Messages)
AGGREGATOR_CHANNEL=@my_private_feed

# 봇 토큰 (Bot API 권한 확인용)
BOT_TOKEN=your_bot_token_here

# 중요 채널 (high 중요도 메시지 중복 전송)
IMPORTANT_CHANNEL=@arang_summary_important

# 봇 설정 (개인 DM 알림용)
PERSONAL_CHAT_ID=your_personal_chat_id_here

# 중요 봇 설정 (중요 메시지 분리 전송용)
IMPORTANT_BOT_TOKEN=your_important_bot_token_here

OPENAI_API_KEY=sk-...
UPSTAGE_API_KEY=your_upstage_api_key_here
OPENAI_MODEL=gpt-4o-mini

# Upstage.ai 임베딩 API
UPSTAGE_API_KEY=up_...

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

## 봇 설정
### Bot API 권한 확인용 봇 설정
1. **봇 생성**: @BotFather에서 봇 생성 후 토큰 획득
2. **환경변수 설정**: `.env`에 `BOT_TOKEN` 설정
3. **기능**: 채널의 `can_send_messages`, `join_to_send_messages` 권한을 확인하여 정확한 채팅 기능 판단

### 개인 DM 알림 설정
1. **개인 chat_id 확보**: 
   ```bash
   python3 app/bot_notifier.py
   ```
   봇에게 `/start` 메시지를 보내고 Enter를 누르면 개인 chat_id가 출력됩니다.
2. **환경변수 설정**: `.env`에 `PERSONAL_CHAT_ID` 설정

### 중요 봇 설정 (선택사항)
1. **중요 봇 생성**: @BotFather에서 별도 봇 생성 후 토큰 획득
2. **환경변수 설정**: `.env`에 `IMPORTANT_BOT_TOKEN` 설정
3. **기능**: medium 이상 + 돈버는 정보 메시지를 별도 봇으로 분리 전송

## 핵심 동작(간결)
- **폴링 수집**: 30초 간격으로 모니터링 채널 점검(안정적 수신)
- **채널 정규화**: SOURCE_CHANNELS의 @username을 숫자 peer id로 변환하여 내부 일관성 유지
- **초기 오프셋**: 최초/재시작 시 최신 메시지 ID를 스냅샷하고 그 이후만 처리(백필 없음)
- **댓글/토픽 무시**: 채널 본문만 처리를 보장
- **동적 채널 추가**: 실행 중 추가된 채널도 즉시 최신 ID로 초기화 후 모니터링 시작

## 중복 제거 시스템
1. **1단계: 정확한 중복 제거**
   - 원본 텍스트의 MD5 해시값 사용
   - 포워딩된 곳이 달라도 원문이 동일하면 중복으로 처리

2. **2단계: 유사도 중복 제거**
   - 임베딩 기반 코사인 유사도 사용
   - 유사하지만 완전히 동일하지 않은 메시지 처리

3. **재시작 시 중복 처리 방지**
   - 데이터베이스에서 마지막 처리된 메시지 ID 추적
   - 프로그램 재시작 시 해당 ID 이후부터 처리

## 동적 채널 관리 시스템
1. **포워딩 메시지 원본 채널 자동 추가**
   - 포워딩된 메시지의 원본 채널이 모니터링 대상에 없으면 자동 추가
   - .env 파일의 SOURCE_CHANNELS에 자동으로 채널 ID 추가

2. **SOURCE_CHANNELS 동적 최신화**
   - polling할 때마다 SOURCE_CHANNELS 파일에서 최신 목록 로드
   - 새로운 채널 추가 시 마지막 메시지 ID 자동 초기화

3. **실시간 채널 관리**
   - 메모리 캐시 실시간 업데이트
   - 새로운 채널 즉시 모니터링 시작

## 돈버는 정보 메시지 관리
```bash
# 돈버는 정보 메시지 목록 조회
python3 app/money_message_processor.py --list

# 상세 정보와 함께 조회
python3 app/money_message_processor.py --list --details

# JSON 형식으로 내보내기
python3 app/money_message_processor.py --export money_messages.json

# CSV 형식으로 내보내기
python3 app/money_message_processor.py --export money_messages.csv --format csv

# 통계 조회
python3 app/money_message_processor.py --stats
```

## 동작 흐름(요약)
1) **폴링 방식 메시지 수신**: 30초 간격으로 모든 모니터링 채널 확인
2) **정확한 채널 필터링**: Bot API 권한 기반으로 순수 방송 채널만 처리
3) **@username 형태 chat_id 처리**: @username을 정확한 숫자 ID로 변환
4) **Forward 감지/원본 정보 추출**: 원문 링크/중복 기준 확정
5) **텍스트 임베딩**: Upstage.ai 임베딩 벡터 → 의미적 중복 드랍
6) **OpenAI 분석**: 요약/중요도/카테고리/태그
7) **룰 부스팅**: 임계값 미만은 저장만, 이상은 전송
8) **전송**: 요약 + 원문 일부(400자) + 링크 + 포함된 링크 + 이벤트 상품 정보 + 포워드 정보
9) **중요 채널 중복 전송**: high 중요도 메시지를 중요 채널로 중복 전송
10) **봇 개인 DM 알림**: 모든 전송된 메시지에 대해 개인 DM으로 알림
11) **중요 봇 분리 전송**: medium 이상 + 돈버는 정보 메시지를 별도 봇으로 전송
12) **포워딩 원본 채널 자동 추가**: 원본 채널이 모니터링 대상에 없으면 자동 추가
13) **결과 저장**: SQLite (일반 메시지 + 돈버는 정보 메시지 별도 저장)

## 로깅 팁
```bash
# 오늘 로그 빠르게 보기
tail -f logs/$(date +%Y-%m-%d)/app.log | grep -E "폴링|초기화|최신 메시지 ID|전송|중복|🔍|✅|⏭️"

# 전송된 메시지
tail -f logs/$(date +%Y-%m-%d)/sent_messages.log

# 에러만
tail -f logs/$(date +%Y-%m-%d)/error.log
```

## 해결된 문제들(요약)
- **메시지 수신 문제**: Telethon 실시간 이벤트 핸들러 제한을 폴링 방식으로 해결
- **채널 접근 권한**: 모든 모니터링 채널의 접근 권한과 메시지 읽기 권한 확인
- **메시지 처리 오류**: EventWrapper 클래스로 메시지 객체를 이벤트 객체로 래핑하여 해결
- **중요도 임계값 버그**: `low` 중요도 메시지도 정상 전송되도록 수정
- **상세 로깅**: 메시지 버림 이유와 처리 과정을 상세히 로깅
- **UnboundLocalError**: formatter.py에서 변수 정의 순서 수정
- **403 Forbidden 에러**: Playwright 브라우저 렌더링으로 우회
- **None 텍스트 처리**: 안전한 텍스트 처리 로직 추가
- **이미지 처리 에러**: 이미지 로드 및 검증 로직 강화
- **링크 포함 전송**: 메시지에 포함된 모든 링크를 요약 전송 시 표시
- **돈버는 정보 별도 저장**: 전용 테이블과 처리 유틸리티 구현
- **중요 채널 중복 전송**: 돈버는 정보 또는 high 중요도 메시지 중복 전송
- **봇 개인 DM 알림**: Telegram Bot API를 통한 개인 알림 시스템
- **변수 정의 에러**: date_ts → now_ts 변수명 통일
- **원문 열기 링크 오류**: 포함된 링크와 원문 링크 구분 문제 해결
- **중요 봇 분리 전송**: medium 이상 + 돈버는 정보 메시지를 별도 봇으로 분리
- **메시지 중복 처리**: 폴링 방식만 사용하여 중복 처리 방지
- **이벤트 상품 정보 표시**: 이벤트/에어드랍/프로모션 메시지에서 상품 정보 자동 추출
- **포워딩 메시지 중복 제거 강화**: 텍스트 해시 기반 정확한 중복 제거, 2단계 중복 제거 시스템
- **프로그램 재시작 시 중복 처리 방지**: 데이터베이스 기반 메시지 처리 상태 추적
- **포워딩 메시지 원본 채널 자동 추가**: 포워딩된 메시지의 원본 채널을 자동으로 모니터링 대상에 추가
- **SOURCE_CHANNELS 동적 최신화**: polling할 때마다 SOURCE_CHANNELS 최신화, 실시간 채널 관리
- **정확한 채널 필터링**: Bot API 권한 기반으로 순수 방송 채널만 모니터링, 채팅 기능이 있는 채널/그룹 자동 제거
- **제거된 채널 중복 로딩 방지**: 메모리에 `removed_channels` set으로 제거된 채널 목록 유지
- **@username 형태 chat_id 처리**: @username 형태의 chat_id를 `utils.get_peer_id(entity)`로 정확한 숫자 ID 변환
- **정확한 채널 타입 구분**: channel/group/supergroup 정확한 구분 및 linked_chat_id 정보 활용
- **채널 댓글 스레드 감지**: message_thread_id 기반 정확한 채널 댓글 스레드 감지 및 제거
- **연결된 채널/그룹 정보 활용**: linked_chat_id 정보 로깅 및 활용
- **포워딩 메시지 원본 채널 자동 추가**: 포워딩된 메시지의 원본 채널을 자동으로 모니터링 대상에 추가
- **SOURCE_CHANNELS 동적 최신화**: polling할 때마다 SOURCE_CHANNELS 최신화, 실시간 채널 관리
- **이벤트 상품 정보 표시**: 이벤트/에어드랍/프로모션 메시지에서 상품/보상 정보 자동 추출 및 표시
- **포워딩 메시지 중복 제거 강화**: 텍스트 해시 기반 정확한 중복 제거, 2단계 중복 제거 시스템
- **프로그램 재시작 시 중복 처리 방지**: 최초/재시작 시 최신 ID 스냅샷 후 그 이후만 처리(백필 없음)
- **중요 봇 분리 전송**: medium 이상 + 돈버는 정보 메시지를 별도 봇으로 분리 전송
- **메시지 중복 처리 해결**: 폴링 방식만 사용하여 메시지 중복 처리 방지
- **원문 열기 링크 오류 수정**: 포함된 링크와 원문 링크 구분 문제 해결
- **중요 채널 조건 변경**: high 중요도 메시지만 중요 채널로 중복 전송
- **봇 개인 DM 알림 개선**: 채널과 동일한 포매팅 적용, 전체 요약 전송
- **내용 없는 요약 필터링**: 무의미한 요약 메시지 전송 방지
- **이미지 처리 안정성 강화**: 대용량 이미지 리사이즈, 검증 로직 개선
- **링크 추출 및 표시 개선**: 포괄적인 URL 패턴, 클릭 가능한 링크 표시
- **메시지 작성시간 정보 포함**: 원본 메시지와 포워딩 메시지의 작성시간을 내 채널 포스팅에 포함
- **이전 메시지들 고려한 초기화**: 새로 발견된 채널에서 최신 메시지가 아닌 이전 메시지들도 고려하여 초기화

## 알려진 이슈
- **이미지 처리 지연**: 대용량 이미지 처리 시 시간 소요 (개선됨)
- **일부 웹사이트 접근 제한**: 매우 엄격한 봇 차단 정책을 가진 사이트는 여전히 접근 불가 (극소수)
- **Bot API 호출 증가**: 채널 권한 확인을 위한 API 호출 증가 (정확성 향상을 위한 필요 비용)
- **초기화 시 API 호출 증가**: 새로 발견된 채널에서 이전 메시지들도 고려하여 초기화 시 API 호출 증가 (메시지 누락 방지를 위한 필요 비용)

## 최근 업데이트
- **v2.6**: 최초/재시작 시 최신 ID 스냅샷(백필 없음), @username → 숫자 peer id 정규화, channel_last_message_ids datatype mismatch 해결
- **v1.8**: 메시지 작성시간 정보 포함, 이전 메시지들 고려한 초기화
- **v1.7**: @username 형태 채널 추가 (Telegram API를 통한 자동 변환)
- **v1.6**: LLM 기반 정보 가치 판단 (의미있는 정보만 필터링)
- **v1.5**: LLM 기반 코인 관련성 판단 (SYSTEM_PROMPT 통합)
- **v1.4**: 정확한 채널 필터링, 제거된 채널 중복 로딩 방지, @username 형태 chat_id 처리

## 라이선스
- 개인 사용 목적 예제. 상업/배포 시 각 API 약관/요금/정책을 준수하세요.