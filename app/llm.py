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


SYSTEM_PROMPT = (
    "당신은 크립토/블록체인 뉴스/알파/신호 선별 어시스턴트입니다. "
    "입력 메시지를 요약하고, 중요도와 카테고리, 태그를 JSON으로만 출력하세요. "
    "중요도는 low/medium/high 중 하나. 카테고리는 ['alpha','news','airdrop','trading','security','regulation','narrative','ecosystem'] 중 1~3개. "
    "태그는 3~7개의 키워드(예: 'Solana','ETF','Bridge Exploit'). "
    "출력은 반드시 JSON 하나만, 키: importance,categories,tags,summary"
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
        return AnalysisResult(
            importance=importance, categories=categories, tags=tags, summary=summary
        )


