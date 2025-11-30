#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

class DuplicateChecker:
    def __init__(self):
        self.source_pruned: dict[str, set[str]] = {}
        self.rule_sources: dict[str, list[str]] = {}
        self.lock = threading.Lock()

    def normalize(self, line: str) -> str:
        """只接受 ||domain.com^ 格式"""
        line = line.strip().lower()
        if not (line.startswith('||') and line.endswith('^') and '$' not in line):
            return ""
        
        domain = line[2:-1]  # 移除 || 和 ^
        if not re.fullmatch(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$', domain):
            return ""
        return line

    def prune_subdomain(self, rules: set[str]) -> set[str]:
        """父域子剪：父域存在则删除子域规则"""
        if not rules:
            return rules

        domains = {rule[2:-1] for rule in rules}
        kept = set()

        for rule in rules:
            domain = rule[2:-1]
            parts = domain.split('.')
            # 判断是否为任何父域的子域名
            if any('.'.join(parts[i:]) in domains for i in range(1, len(parts))):
                continue
            kept.add(rule)

        return kept

    def download(self, url: str) -> str:
        try:
            resp = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
            resp.raise_for_status()
            return resp.text
        except:
            return ""

    def process_source(self, url: str):
        """独立处理单个源：下载 → 提取 → 剪枝"""
        content = self.download(url)
        raw = self.extract_rules(content)
        pruned = self.prune_subdomain(raw)

        with self.lock:
            self.source_pruned[url] = pruned
        print(f"[✅] {url}  {len(raw)} → {len(pruned)} 条")

    def extract_rules(self, content: str) -> set[str]:
        return {self.normalize(line) for line in content.splitlines() if self.normalize(line)}

    def load_sources(self, file: str = 'sources.txt') -> list[str]:
        for enc in ('utf-8-sig', 'utf-8', 'gbk'):
            try:
                with open(file, 'r', encoding=enc) as f:
                    return [line.split('#')[0].strip() for line in f
                           if line.strip() and not line.startswith('#')]
            except:
                continue
        return []

    def run(self, sources_file: str = 'sources.txt'):
        sources = self.load_sources(sources_file)
        
        print("\n" + "="*70)
        print("阶段1: 各源独立剪枝")
        print("="*70 + "\n")
        
        with ThreadPoolExecutor(max_workers=8) as exe:
            list(exe.map(self.process_source, sources))

        print("\n" + "="*70)
        print("阶段2: 剪枝后重复统计")
        print("="*70 + "\n")
        
        # 全局映射：规则 → 来源列表
        for src, rules in self.source_pruned.items():
            for rule in rules:
                self.rule_sources.setdefault(rule, []).append(src)
        
        # 生成报告
        report = {'sources': {}}
        for src, rules in self.source_pruned.items():
            duplicate = sum(1 for r in rules if len(self.rule_sources[r]) > 1)
            report['sources'][src] = {
                'total': len(rules),
                'duplicate': duplicate,
                'distinct': len(rules) - duplicate,
                'duplicate_rate': duplicate / max(len(rules), 1)
            }

        self.print_report(report)
        
        # 保存 JSON 文件
        with open('duplicate_report.json', 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def print_report(self, report: dict):
        """简洁版：一眼看出该删谁"""
        
        # 1. 头部摘要
        print("\n" + "="*100)
        print("🎯 规则源优选报告")
        print("="*100 + "\n")
        print("删除建议:  🔴 立即删除  |  🟡 考虑删除  |  🟢 保留\n")
        
        # 2. 按评分排序（独立规则占比）
        sorted_sources = sorted(
            report['sources'].items(),
            key=lambda x: x[1]['distinct'] / max(x[1]['total'], 1),
            reverse=True
        )
        
        # 3. 分组显示
        print(f"{' 保留源（高质量）  ':^90}\n")
        print(f"{'源名称':<50} {'独立':<8} {'重复':<8} {'总分':<8} {'重复率':<10}")
        print("-"*90)
        
        keep_count = 0
        for src, d in sorted_sources:
            if d['distinct'] / max(d['total'], 1) >= 0.5:  # 独立规则≥50%
                name = src.split('/')[-1][:45]
                total, dup, distinct = d['total'], d['duplicate'], d['distinct']
                rate = d['duplicate_rate'] * 100
                print(f"🟢 {name:<48} {distinct:<8} {dup:<8} {total:<8} {rate:>6.1f}%")
                keep_count += 1
        
        print(f"\n{' 删除源（低价值）  ':^90}\n")
        print(f"{'源名称':<50} {'独立':<8} {'重复':<8} {'总分':<8} {'重复率':<10}")
        print("-"*90)
        
        remove_count = 0
        for src, d in sorted_sources:
            if d['distinct'] / max(d['total'], 1) < 0.5:  # 独立规则<50%
                name = src.split('/')[-1][:45]
                total, dup, distinct = d['total'], d['duplicate'], d['distinct']
                rate = d['duplicate_rate'] * 100
                icon = "🔴" if rate >= 70 else "🟡"
                print(f"{icon} {name:<48} {distinct:<8} {dup:<8} {total:<8} {rate:>6.1f}%")
                remove_count += 1
        
        print("\n" + "="*100)
        print(f"统计: 保留 {keep_count} 个源  |  删除 {remove_count} 个源")
        print("="*100 + "\n")

if __name__ == '__main__':
    DuplicateChecker().run()