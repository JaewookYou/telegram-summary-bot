# 이 파일은 더 이상 사용되지 않습니다.
# SimHash 기반 중복 제거에서 Upstage.ai 임베딩 기반으로 변경되었습니다.
# 
# 기존 함수들:
# - normalize_text: 텍스트 정규화 (이제 단순 strip() 사용)
# - tokenize: 토크나이징 (더 이상 사용되지 않음)
# - compute_simhash: SimHash 계산 (임베딩 기반으로 대체)

def normalize_text(text: str) -> str:
    """텍스트 정규화 (하위 호환성을 위해 유지)"""
    return text.strip()

def tokenize(text: str) -> list[str]:
    """토크나이징 (더 이상 사용되지 않음)"""
    return []

def compute_simhash(text: str) -> int:
    """SimHash 계산 (더 이상 사용되지 않음)"""
    return 0


