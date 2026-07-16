# RNGN Reels Selector Bot

Telegram-бот принимает идеи для рилзов и записывает их в нужную вкладку Google Sheets.

## Формат сообщения

```text
МК | Майкл Джексон выполняет трюки без страховки | 9 | https://...
```

Подключённые категории:

- `Ф1` — Весь Спорт Формула-1
- `Футбол` — Весь Спорт Футбол
- `НБА` — Баскетбол «Взял Мяч»
- `ММА` — Весь Спорт ММА
- `МК` — Music Core
- `СК` — Sport Core

`Теннис` и `НХЛ` будут добавлены после получения ссылок на соответствующие вкладки.

## Что записывает бот

| Колонка | Значение |
|---|---|
| A | Название события |
| B | Ссылка |
| C | Оценка мощности от 1 до 10 |
| D | Пусто |
| E | `нет` |
| F | Дата добавления в формате `ДД.ММ.ГГГГ` |

После добавления диапазон `A:F` сортируется по колонке C от большей оценки к меньшей. Колонка G и всё правее не затрагиваются.

Бот проверяет дубли ссылок внутри выбранной вкладки. Для Instagram, TikTok, X/Twitter и ряда других соцсетей параметры отслеживания в конце ссылки не учитываются.

## Переменные окружения Vercel

```text
TELEGRAM_BOT_TOKEN=токен от BotFather
TELEGRAM_WEBHOOK_SECRET=случайная секретная строка
GOOGLE_SERVICE_ACCOUNT_JSON={...содержимое JSON-ключа одной строкой...}
ALLOWED_TELEGRAM_USER_IDS=52203584
TIMEZONE=Europe/Moscow
```

`SPREADSHEET_ID` можно не задавать: текущий документ уже указан в коде. При необходимости его можно переопределить переменной окружения.

Никогда не добавляйте токены и JSON-ключ Google в GitHub.

## Настройка Google

1. Создайте проект в Google Cloud.
2. Включите **Google Sheets API**.
3. Создайте Service Account.
4. Создайте для него JSON-ключ.
5. Найдите в JSON поле `client_email`.
6. Откройте Google-таблицу и выдайте этому адресу права редактора.
7. Скопируйте весь JSON одной строкой в `GOOGLE_SERVICE_ACCOUNT_JSON` в Vercel.

## Деплой

1. Импортируйте этот GitHub-репозиторий в Vercel.
2. Framework Preset: `Other`.
3. Добавьте переменные окружения.
4. Выполните Production Deployment.
5. Проверьте адрес:

```text
https://ВАШ-ПРОЕКТ.vercel.app/api/webhook
```

GET-запрос должен вернуть статус `ok`.

## Подключение webhook Telegram

PowerShell:

```powershell
$token = "ТОКЕН_ОТ_BOTFATHER"
$secret = "ТОТ_ЖЕ_TELEGRAM_WEBHOOK_SECRET_ИЗ_VERCEL"
$url = "https://ВАШ-ПРОЕКТ.vercel.app/api/webhook"

$body = @{
  url = $url
  secret_token = $secret
  allowed_updates = @("message")
  drop_pending_updates = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://api.telegram.org/bot$token/setWebhook" `
  -ContentType "application/json" `
  -Body $body
```

Проверка webhook:

```powershell
Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getWebhookInfo"
```

## Команды

- `/start` — инструкция и формат сообщения
- `/help` — инструкция
- `/categories` — подключённые категории

## Локальная проверка парсера

```bash
python -m unittest discover -s tests
```
