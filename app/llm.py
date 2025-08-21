from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class AnalysisResult:
    importance: str
    categories: List[str]
    tags: List[str]
    summary: str
    money_making_info: str
    action_guide: str


SYSTEM_PROMPT = (
    "당신은 크립토/블록체인 뉴스/알파/신호 선별 어시스턴트입니다. "
    "입력 메시지를 분석하여 다음 정보를 JSON으로만 출력하세요:\n"
    "- importance: low/medium/high 중 하나\n"
    "- categories: ['alpha','news','airdrop','trading','security','regulation','narrative','ecosystem'] 중 1~3개\n"
    "- tags: 3~7개의 키워드(예: 'Solana','ETF','Bridge Exploit')\n"
    "- summary: 2~4문장 요약, 한국어\n"
    "- money_making_info: 돈을 버는데 활용할 수 있는 정보인가? (예: '에어드랍 정보', '거래 기회', '투자 정보', '없음')\n"
    "- action_guide: 구체적인 행동 가이드 (예: '지갑 생성 후 참여', '모니터링 필요', '즉시 매수 고려', '추가 정보 대기')\n"
    "출력은 반드시 JSON 하나만, 키: importance,categories,tags,summary,money_making_info,action_guide"
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
        importance = str(data.get("importance", "low")).lower()
        categories = [str(c) for c in data.get("categories", [])][:3]
        tags = [str(t) for t in data.get("tags", [])][:7]
        summary = str(data.get("summary", "")).strip()
        money_making_info = str(data.get("money_making_info", "없음")).strip()
        action_guide = str(data.get("action_guide", "추가 정보 대기")).strip()
        return AnalysisResult(
            importance=importance, 
            categories=categories, 
            tags=tags, 
            summary=summary,
            money_making_info=money_making_info,
            action_guide=action_guide
        )


