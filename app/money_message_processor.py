#!/usr/bin/env python3
"""
돈버는 정보 메시지 처리 유틸리티
저장된 돈버는 정보 메시지들을 조회하고 분석/처리할 수 있는 도구
"""

import json
import os
import sys
from datetime import datetime
from typing import List, Optional
import argparse

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.storage import SQLiteStore, MoneyMessageRecord

# settings 대신 직접 DB 경로 설정
DB_PATH = "data/messages.db"


class MoneyMessageProcessor:
    def __init__(self):
        self.store = SQLiteStore(DB_PATH)
    
    def list_money_messages(self, limit: int = 50, show_details: bool = False) -> None:
        """저장된 돈버는 정보 메시지들을 조회하여 출력"""
        messages = self.store.get_money_messages(limit=limit)
        
        if not messages:
            print("💰 저장된 돈버는 정보 메시지가 없습니다.")
            return
        
        print(f"💰 저장된 돈버는 정보 메시지 ({len(messages)}개):")
        print("=" * 80)
        
        for i, msg in enumerate(messages, 1):
            print(f"\n{i}. [ID: {msg.id}] {datetime.fromtimestamp(msg.date_ts)}")
            print(f"   채널: {msg.chat_id} | 메시지: {msg.message_id}")
            print(f"   중요도: {msg.importance} | 카테고리: {msg.categories}")
            print(f"   돈버는 정보: {msg.money_making_info}")
            print(f"   행동 가이드: {msg.action_guide}")
            
            if show_details:
                print(f"   원문: {msg.original_text[:200]}...")
                if msg.forward_text:
                    print(f"   포워딩: {msg.forward_text[:200]}...")
                if msg.image_paths != '[]':
                    try:
                        images = json.loads(msg.image_paths)
                        print(f"   이미지: {len(images)}개")
                    except:
                        print(f"   이미지: {msg.image_paths}")
                if msg.forward_info != '{}':
                    print(f"   포워딩 정보: {msg.forward_info}")
                print(f"   링크: {msg.original_link}")
                print(f"   요약: {msg.summary[:200]}...")
            
            print("-" * 40)
    
    def export_money_messages(self, output_file: str, format: str = 'json') -> None:
        """돈버는 정보 메시지들을 파일로 내보내기"""
        messages = self.store.get_money_messages(limit=1000)  # 최대 1000개
        
        if not messages:
            print("💰 내보낼 돈버는 정보 메시지가 없습니다.")
            return
        
        if format == 'json':
            # JSON 형태로 내보내기
            export_data = []
            for msg in messages:
                export_data.append({
                    'id': msg.id,
                    'chat_id': msg.chat_id,
                    'message_id': msg.message_id,
                    'date': datetime.fromtimestamp(msg.date_ts).isoformat(),
                    'author': msg.author,
                    'original_text': msg.original_text,
                    'forward_text': msg.forward_text,
                    'money_making_info': msg.money_making_info,
                    'action_guide': msg.action_guide,
                    'image_paths': json.loads(msg.image_paths) if msg.image_paths != '[]' else [],
                    'forward_info': json.loads(msg.forward_info) if msg.forward_info != '{}' else {},
                    'original_link': msg.original_link,
                    'importance': msg.importance,
                    'categories': msg.categories,
                    'tags': msg.tags,
                    'summary': msg.summary,
                })
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            print(f"💰 {len(export_data)}개의 돈버는 정보 메시지를 {output_file}에 JSON 형태로 내보냈습니다.")
        
        elif format == 'csv':
            # CSV 형태로 내보내기
            import csv
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'ID', 'Chat ID', 'Message ID', 'Date', 'Author', 'Money Making Info',
                    'Action Guide', 'Importance', 'Categories', 'Tags', 'Original Link',
                    'Original Text', 'Forward Text', 'Summary'
                ])
                
                for msg in messages:
                    writer.writerow([
                        msg.id, msg.chat_id, msg.message_id,
                        datetime.fromtimestamp(msg.date_ts).isoformat(),
                        msg.author, msg.money_making_info, msg.action_guide,
                        msg.importance, msg.categories, msg.tags, msg.original_link,
                        msg.original_text[:500], msg.forward_text[:500], msg.summary[:500]
                    ])
            
            print(f"💰 {len(messages)}개의 돈버는 정보 메시지를 {output_file}에 CSV 형태로 내보냈습니다.")
    
    def get_money_stats(self) -> None:
        """돈버는 정보 메시지 통계 출력"""
        messages = self.store.get_money_messages(limit=1000)
        
        if not messages:
            print("💰 통계를 계산할 돈버는 정보 메시지가 없습니다.")
            return
        
        # 중요도별 통계
        importance_stats = {}
        category_stats = {}
        tag_stats = {}
        
        for msg in messages:
            # 중요도 통계
            importance_stats[msg.importance] = importance_stats.get(msg.importance, 0) + 1
            
            # 카테고리 통계
            categories = msg.categories.split(',') if msg.categories else []
            for cat in categories:
                cat = cat.strip()
                if cat:
                    category_stats[cat] = category_stats.get(cat, 0) + 1
            
            # 태그 통계
            tags = msg.tags.split(',') if msg.tags else []
            for tag in tags:
                tag = tag.strip()
                if tag:
                    tag_stats[tag] = tag_stats.get(tag, 0) + 1
        
        print(f"💰 돈버는 정보 메시지 통계 (총 {len(messages)}개):")
        print("=" * 50)
        
        print("\n📊 중요도별 분포:")
        for importance, count in sorted(importance_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"   {importance}: {count}개")
        
        print("\n📊 카테고리별 분포:")
        for category, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"   {category}: {count}개")
        
        print("\n📊 태그별 분포 (상위 10개):")
        for tag, count in sorted(tag_stats.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"   {tag}: {count}개")


def main():
    parser = argparse.ArgumentParser(description="돈버는 정보 메시지 처리 유틸리티")
    parser.add_argument('action', choices=['list', 'export', 'stats'], help='실행할 작업')
    parser.add_argument('--limit', type=int, default=50, help='조회할 메시지 개수 (기본값: 50)')
    parser.add_argument('--details', action='store_true', help='상세 정보 출력 (list 명령어와 함께 사용)')
    parser.add_argument('--output', type=str, help='출력 파일 경로 (export 명령어와 함께 사용)')
    parser.add_argument('--format', choices=['json', 'csv'], default='json', help='내보내기 형식 (기본값: json)')
    
    args = parser.parse_args()
    
    processor = MoneyMessageProcessor()
    
    if args.action == 'list':
        processor.list_money_messages(limit=args.limit, show_details=args.details)
    
    elif args.action == 'export':
        if not args.output:
            print("❌ export 명령어는 --output 옵션이 필요합니다.")
            sys.exit(1)
        processor.export_money_messages(args.output, args.format)
    
    elif args.action == 'stats':
        processor.get_money_stats()


if __name__ == "__main__":
    main()
