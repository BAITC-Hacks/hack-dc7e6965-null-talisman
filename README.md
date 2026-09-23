# hack-dc7e6965-null-talisman
Hackathon team repository for Null talisman

План работ на хакатон: [docs/PLAN.md](docs/PLAN.md)

## Проверка интеграционной ветки

Ветка `codex/nikita-core` соединяет загрузчик и графики движка с UI команды.
Используются реальные модули расчёта из `main`; первоначальная заглушка заменена.
Инструкции интерфейса: [app/README.md](app/README.md).

Проверено в локальном Python 3.12 с зависимостями из `requirements.txt`.
Команды PowerShell из корня репозитория:

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest -q
```

UTF-8 нужен для существующего UI-теста чтения журнала утверждений на Windows.
Приёмочные тесты создают свежие данные во временном каталоге; содержимое
локального `data/demo/` не влияет на них. Генератор и исходные материалы
заказчика в этой интеграции не перезаписываются.

История проверок: [TDD evidence](docs/tdd/nikita-first-checkpoint.tdd.md).
