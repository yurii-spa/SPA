# Analyst Sources

Сюда конвертируются аналитические материалы (PDF/DOCX/XLSX/YouTube) в Markdown
для дальнейшей обработки агентами и NotebookLM.

## Как добавить материал

```bash
# Один файл
python3 scripts/convert_analyst_sources.py ~/Downloads/defi_report.pdf

# YouTube видео
python3 scripts/convert_analyst_sources.py https://youtube.com/watch?v=VIDEO_ID

# Целая папка
python3 scripts/convert_analyst_sources.py --dir ~/Downloads/reports/
```

## Структура

- `*.md` — сконвертированные материалы (frontmatter: source, converted, chars)
- `_conversion_log.json` — лог всех конвертаций

## Требование

```bash
pip install 'markitdown[all]'
```
