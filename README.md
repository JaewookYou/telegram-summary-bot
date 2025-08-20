# telegram-summary-bot

여러 텔레그램 코인 채널의 메시지를 수집해 중복 제거, 중요도 분류, 태그 부여, 요약 후 개인 전용 채널로 가독성 좋게 재전송합니다. 각 메시지에는 원문으로 이동 가능한 링크가 포함됩니다.

## 주요 기능
- LLM 분석: 요약/중요도(low/medium/high)/카테고리/태그(JSON 응답)
- 중복 제거: SimHash(64-bit) + 해밍거리 기준, 최근 N분 윈도우 내 근사 중복 드랍
- Forward 메시지 처리: 원본 메시지 정보 추출로 정확한 중복 체크 및 링크 생성
- 원문 링크: 공개 `@username` → `https://t.me/<username>/<id>`, 비공개 → `https://t.me/c/<internal_id>/<id>`
- 개인 채널로 재전송: 다른 채널 알림 OFF, 개인 채널만 ON으로 효율적 구독
- 저장소: SQLite BIGINT 스키마로 대용량 메시지 ID 지원
- 로깅: 콘솔 + 회전 파일 로그 `logs/app.log`, 에러 전용 `logs/error.log`
- 룰 기반 중요도 부스팅: 이벤트/추첨/에어드랍/기프티콘/커피 등 키워드 포함 시 중요도 상향(참여 유도까지 있으면 high)

## 구성 요소
- 수집: Telethon(Userbot) `events.NewMessage` + 소스 채널 필터
- 분석: `app/llm.py` OpenAI Chat Completions(JSON 강제)
- 중복: `app/dedup.py` SimHash 토크나이징/정규화
- 포맷: `app/formatter.py` HTML 메시지 빌드(원문 링크 포함, 미리보기 OFF)
- 저장: `app/storage.py` SQLite 스키마/CRUD
- 로깅: `app/logging_utils.py`(콘솔+파일, 회전)
- 룰: `app/rules.py`(이벤트/에어드랍 중요도 부스팅)
- 실행 진입점: `app/__main__.py`, 런루프: `app/run.py`

## 요구사항
- Python 3.9+ (권장 3.10+)
- Telegram API ID / API Hash (my.telegram.org, 사용자 계정 기반 Userbot)
- OpenAI API Key

## 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 환경 변수(.env)
아래 예시를 복사해 `.env`를 생성하세요.

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_SESSION=telegram_session

# 콤마로 구분된 채널 식별자(username 또는 숫자 ID)
SOURCE_CHANNELS=coin_signal,@defi_alpha,-1001234567890

# 개인 채널 또는 'me' (Saved Messages)
AGGREGATOR_CHANNEL=@my_private_feed
# AGGREGATOR_CHANNEL=me

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# 중요도 임계값: low, medium, high (이 값 이상만 전송, 기본값: low)
IMPORTANT_THRESHOLD=low

# 중복 설정
DEDUP_HAMMING_THRESHOLD=9
DEDUP_RECENT_MINUTES=360

# SQLite 경로
SQLITE_PATH=data/db.sqlite3
```

입력 형식 참고:
- `SOURCE_CHANNELS`: `username` 또는 `@username` 모두 가능. 비공개 채널은 `-100xxxxxxxxxx` 형태의 숫자 ID 사용.
- `AGGREGATOR_CHANNEL`: `@username` 또는 `me`(Saved Messages).

## 채널 목록 자동 수집
현재 계정이 가입한 채널/슈퍼그룹 목록을 출력하고, `.env`에 바로 붙여넣을 라인을 생성할 수 있습니다.
```bash
# 표 형태 출력
python -m app.list_channels

# 연결된 공지 채널까지 포함
python -m app.list_channels --include-linked

# .env에 붙여넣을 SOURCE_CHANNELS=... 생성
python -m app.list_channels --env-line
# @username 형식 사용
python -m app.list_channels --env-line --use-at
```

## 실행
```bash
python -m app
```
처음 실행 시 Telegram 로그인 코드(OTP) 입력이 필요할 수 있습니다(1회). 이후 세션 파일로 자동 로그인됩니다.

## 동작 흐름
1) 설정된 `SOURCE_CHANNELS`에서 새 메시지 수신
2) Forward 메시지 감지 및 원본 정보 추출 (원본 채널/메시지 ID)
3) 텍스트 정규화 후 SimHash 계산 → 최근 N분 윈도우 내 해밍거리 ≤ 임계값이면 드랍
4) OpenAI 호출로 요약/중요도/카테고리/태그(JSON)
5) 룰 기반 부스팅 적용(이벤트/에어드랍 등) → 중요도 상향 가능
6) 임계값 미만은 저장만, 임계값 이상은 `AGGREGATOR_CHANNEL`로 HTML 전송(원문 링크 포함)
7) SQLite에 결과/메타데이터 저장 (BIGINT 스키마로 대용량 메시지 ID 지원)

## 로깅
- 콘솔: 시작/소스 채널/수신/중복 드랍/전송/부스팅/에러 등을 INFO/ERROR로 출력
- Forward 메시지: `[FORWARD]` 태그와 원본 정보 로그
- 파일 로그: 회전 로그 `logs/app.log`, 에러 전용 `logs/error.log`
```bash
tail -f logs/app.log
# 에러만
tail -f logs/error.log
# Forward 메시지만 필터링
grep "FORWARD" logs/app.log
```

## 중요도 부스팅(룰)
- 키워드: 이벤트/추첨/경품/기프티콘/커피/스타벅스/나눔/쿠폰/리워드/raffle/giveaway/bounty/에어 드랍/airdrop 등
- 참여 유도(리트윗/팔로우/퀘스트/댓글/공유 등)까지 포함 시 high로 상향, 키워드만 있으면 최소 medium

## 트러블슈팅
- **SQLite INTEGER 오버플로우**: Telegram 메시지 ID가 SQLite INTEGER 범위를 초과하는 경우
  - 자동으로 BIGINT 스키마로 마이그레이션됨
  - 백업 파일 `data/db.sqlite3.backup`에서 복구 가능
- **Forward 메시지 중복**: 원본 메시지와 forward 메시지가 모두 처리되는 경우
  - 자동으로 원본 메시지 정보를 기준으로 중복 체크
  - 로그에서 `[FORWARD]` 태그로 구분 가능
- **메시지 필터링 과다**: 중요도가 높은 메시지도 전송되지 않는 경우
  - `IMPORTANT_THRESHOLD=low`로 설정하여 더 많은 메시지 허용
- Telethon 세션 락(`database is locked`): 동일 세션으로 다중 실행 중일 수 있음
  - 다른 프로세스 종료 또는 세션명 변경 실행
  - 예) `TELEGRAM_SESSION=telegram_session_v2 python -m app`
  - 잔여 `*.session-journal` 제거 후 재시도
- 로그인 실패/OTP 미수신: 네트워크 변경(테더링), API ID/HASH 재발급(반드시 본인 계정), 세션 파일 삭제 후 재로그인
- 링크 접근 불가: 비공개 채널은 가입자만 열람 가능

## Upstage 임베딩(옵션)
- 현재는 SimHash만으로 충분한 경우가 많습니다.
- 한국어 패러프레이즈 중복이 많거나 군집/다이제스트 정밀도를 높이고 싶다면 Upstage.ai 임베딩+FAISS로 확장 가능합니다(요청 시 추가 구현).

## 보안/버전관리
- `.gitignore`에 `.env`, 세션(`*.session`), 로그, 로컬 DB(`data/`) 등 민감/로컬 산출물 제외
- 데이터베이스 백업: `data/db.sqlite3.backup` 파일로 자동 백업 생성

## 최근 업데이트 (v0.2)
- **Forward 메시지 처리**: 원본 메시지 정보 추출로 정확한 중복 체크 및 링크 생성
- **SQLite BIGINT 스키마**: 대용량 Telegram 메시지 ID 지원 (오버플로우 해결)
- **중요도 임계값 조정**: 기본값을 "low"로 변경하여 더 많은 메시지 전달
- **향상된 로깅**: Forward 메시지 감지 및 원본 정보 로그 추가

## 라이선스
- 개인 사용 목적 예제. 상업/배포 시 각 API 약관/요금/정책을 준수하세요.