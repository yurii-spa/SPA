# SPA React Dashboard — M5

## Быстрый старт

### 1. Запустить API сервер
```bash
cd spa_core
pip install fastapi uvicorn pydantic
uvicorn api.server:app --reload --port 8000
```

### 2. Запустить React frontend
```bash
cd spa_frontend
npm install
npm run dev
# → http://localhost:5173
```

## Структура

```
src/
├── api.ts                  # API client (fetch wrapper)
├── types.ts                # TypeScript types
├── App.tsx                 # Главный компонент + роутинг табов
├── App.css                 # Стили
├── main.tsx                # Entry point
└── components/
    ├── Portfolio.tsx       # Метрики капитала + Risk + Clock
    ├── Positions.tsx       # Таблица открытых позиций
    ├── Protocols.tsx       # Таблица протоколов + APY
    ├── BusStats.tsx        # Статистика Message Bus
    ├── APYChart.tsx        # Графики PnL и deployed %
    └── RunButton.tsx       # Кнопка запуска оркестратора
```

## Сборка для GitHub Pages

```bash
npm run build
# Результат в dist/ — загрузить на GitHub Pages
```
