# -*- coding: utf-8 -*-
from typing import Dict, Any
from pathlib import Path

class DirectiveApplicator:
    """
    Opus から返された軌道修正指示 (Directive) を Flash 用のプロンプトファイルにマージする。
    """
    def __init__(self, prompt_file_path: Path):
        self.prompt_file_path = Path(prompt_file_path)

    def apply(self, directive: Dict[str, Any]) -> bool:
        """
        プロンプトファイルにディレクティブ情報をマージする。
        """
        if not self.prompt_file_path.exists():
            return False

        try:
            file_content = self.prompt_file_path.read_text(encoding="utf-8")
        except OSError:
            return False

        start_tag = "<!-- OPUS_DIRECTIVE_START -->"
        end_tag = "<!-- OPUS_DIRECTIVE_END -->"

        if start_tag not in file_content or end_tag not in file_content:
            return False

        formatted_directive_markdown = self._format_directive_to_markdown(directive)

        try:
            new_content = self._replace_directive_in_content(
                file_content, formatted_directive_markdown, start_tag, end_tag
            )
            self.prompt_file_path.write_text(new_content, encoding="utf-8")
            return True
        except OSError:
            return False

    def _format_directive_to_markdown(self, directive: Dict[str, Any]) -> str:
        """
        ディレクティブ情報をMarkdown形式の文字列に変換する。
        """
        markdown_lines = []
        priorities = directive.get("priorities", [])
        if priorities:
            markdown_lines.append("- Priorities:")
            for priority in priorities:
                markdown_lines.append(f"  - {priority}")
        
        strategy = directive.get("strategy")
        if strategy:
            markdown_lines.append(f"- Strategy: {strategy}")

        return "\n".join(markdown_lines)

    def _replace_directive_in_content(
        self, file_content: str, formatted_markdown: str, start_tag: str, end_tag: str
    ) -> str:
        """
        ファイルコンテンツ内の directive タグに囲まれた範囲を formatted_markdown で置換する。
        """
        start_idx = file_content.find(start_tag)
        end_idx = file_content.find(end_tag) + len(end_tag)
        
        return (
            file_content[:start_idx]
            + start_tag
            + "\n"
            + formatted_markdown
            + "\n"
            + end_tag
            + file_content[end_idx:]
        )
