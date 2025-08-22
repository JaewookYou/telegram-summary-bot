from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class AnalysisResult:
    is_coin_related: bool
    has_valuable_info: bool
    importance: str
    categories: List[str]
    tags: List[str]
    summary: str
    money_making_info: str
    action_guide: str
    event_products: str
    relevance_reason: str
    info_value_reason: str


SYSTEM_PROMPT = (
    "당신은 크립토/블록체인 뉴스/알파/신호 선별 어시스턴트입니다. "
    "입력 메시지를 분석하여 다음 정보를 JSON으로만 출력하세요:\n"
    "- is_coin_related: true/false (크립토/블록체인/암호화폐/DeFi/NFT/Web3/이벤트/프로모션과 관련이 있는지)\n"
    "- has_valuable_info: true/false (실질적인 정보나 가치가 있는 내용인지, 단순한 감정표현이나 반복적인 내용이 아닌지)\n"
    "- importance: low/medium/high 중 하나 (is_coin_related가 false면 'low')\n"
    "- categories: ['alpha','news','airdrop','trading','security','regulation','narrative','ecosystem','event','promotion','macro'] 중 1~3개\n"
    "- tags: 3~7개의 키워드(예: 'Solana','ETF','Bridge Exploit')\n"
    "- summary: 2~4문장 요약, 한국어\n"
    "- money_making_info: 돈을 버는데 활용할 수 있는 정보인가? (예: '에어드랍 정보', '거래 기회', '투자 정보', '이벤트 보상', '없음')\n"
    "- action_guide: 구체적인 행동 가이드 (예: '지갑 생성 후 참여', '모니터링 필요', '즉시 매수 고려', '이벤트 참여', '추가 정보 대기')\n"
    "- event_products: 이벤트/에어드랍/프로모션인 경우 상품/보상 정보 (예: '신세계상품권 10만원', '스타벅스 커피 30잔', '없음')\n"
    "- relevance_reason: 코인 관련성 판단 근거 (한국어, 1-2문장)\n"
    "- info_value_reason: 정보 가치 판단 근거 (한국어, 1-2문장)\n\n"
    "관련성 판단 기준 (is_coin_related=true):\n"
    "- 암호화폐/토큰/코인 관련 정보\n"
    "- 블록체인 기술/프로젝트/플랫폼\n"
    "- DeFi/DeFi 프로토콜/스왑/유동성\n"
    "- NFT/메타버스/게임\n"
    "- Web3/탈중앙화/스마트 컨트랙트\n"
    "- 거래소/지갑/보안\n"
    "- 규제/정책/시장 동향\n"
    "- 에어드랍/토큰 발행/ICO/IDO\n"
    "- 크립토 관련 이벤트/프로모션/컨퍼런스\n"
    "- 코인에 간접적으로 영향을 주는 거시경제 요소:\n"
    "  * 미국 경제/정책 (금리, 인플레이션, GDP, 고용지표)\n"
    "- 정치적 이벤트 (대선, 정책 발표, 규제 논의)\n"
    "  * 달러 강세/약세, 환율 변동\n"
    "  * 글로벌 금융시장 동향 (주식시장, 채권시장)\n"
    "  * 트럼프/바이든 등 정치인 발언 (코인 정책 관련)\n"
    "  * 중앙은행 정책 (Fed, ECB, BOJ 등)\n"
    "  * 경제 지표 (CPI, PPI, 실업률 등)\n"
    "  * 금융 규제 정책 (SEC, CFTC 등)\n\n"
    "정보 가치 판단 기준 (has_valuable_info=true):\n"
    "- 새로운 정보나 뉴스 제공\n"
    "- 구체적인 분석이나 인사이트\n"
    "- 실용적인 가이드나 팁\n"
    "- 시장 동향이나 예측\n"
    "- 프로젝트 업데이트나 발표\n"
    "- 거래 기회나 투자 정보\n"
    "- 이벤트나 프로모션 정보\n"
    "- 기술적 분석이나 차트\n"
    "- 거시경제 분석이나 정책 영향 예측\n\n"
    "정보 가치가 없는 경우 (has_valuable_info=false):\n"
    "- 단순한 감정표현 (좋아요, 싫어요, 대박, 망했다 등)\n"
    "- 반복적인 내용이나 스팸\n"
    "- 의미없는 이모티콘만\n"
    "- 단순한 인사나 대화\n"
    "- 광고성 내용만\n\n"
    "출력은 반드시 JSON 하나만, 키: is_coin_related,has_valuable_info,importance,categories,tags,summary,money_making_info,action_guide,event_products,relevance_reason,info_value_reason"
)


def _build_user_prompt(text: str) -> str:
    return (
        "다음 원문을 분석하세요. 요약은 2~4문장, 한국어. 중복·광고는 낮은 중요도.\n\n"
        f"원문:\n{text.strip()}"
    )


class OpenAILLM:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    def analyze(self, text: str) -> AnalysisResult:
        prompt = _build_user_prompt(text)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        is_coin_related = bool(data.get("is_coin_related", True))  # 기본값은 True (안전성)
        has_valuable_info = bool(data.get("has_valuable_info", True))  # 기본값은 True (안전성)
        importance = str(data.get("importance", "low")).lower()
        categories = [str(c) for c in data.get("categories", [])][:3]
        tags = [str(t) for t in data.get("tags", [])][:7]
        summary = str(data.get("summary", "")).strip()
        money_making_info = str(data.get("money_making_info", "없음")).strip()
        action_guide = str(data.get("action_guide", "추가 정보 대기")).strip()
        event_products = str(data.get("event_products", "없음")).strip()
        relevance_reason = str(data.get("relevance_reason", "판단 근거 없음")).strip()
        info_value_reason = str(data.get("info_value_reason", "판단 근거 없음")).strip()
        return AnalysisResult(
            is_coin_related=is_coin_related,
            has_valuable_info=has_valuable_info,
            importance=importance, 
            categories=categories, 
            tags=tags, 
            summary=summary,
            money_making_info=money_making_info,
            action_guide=action_guide,
            event_products=event_products,
            relevance_reason=relevance_reason,
            info_value_reason=info_value_reason
        )


